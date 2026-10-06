"""Application tools bind actual computations to immutable inputs and reviews.

Only these handlers create experiments, reviews, or execution-eligible decisions.
Agent prose is never treated as a computed result or permission to place an order.
"""

import hashlib
import json
from dataclasses import asdict
from datetime import date
from functools import partial
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from researchdesk.agents.registry import ToolContext, ToolError, ToolRegistry
from researchdesk.config import Settings
from researchdesk.errors import DomainError
from researchdesk.quant import (
    BacktestSpec,
    MarketSnapshot,
    QuantError,
    ScenarioSpec,
    StrategySpec,
    WalkForwardSpec,
    compare_binary_rates,
    evaluate_scenarios,
    run_backtest,
    run_walk_forward,
)
from researchdesk.quant.assessment import assessed_result
from researchdesk.sandbox import DockerSandbox
from researchdesk.store import PROTECTED_KINDS

ALL_ROLES = {"coordinator", "researcher", "coder", "reviewer"}
MAX_TOOL_RESULT_CHARS = 24_000
DEFAULT_ARTIFACT_PAGE_CHARS = 12_000
MAX_ARTIFACT_PAGE_CHARS = 16_000


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ArtifactRead(Input):
    artifact_id: str = Field(min_length=1, max_length=200)
    section: Literal["content", "metadata"] = "content"
    offset: int = Field(default=0, ge=0, le=10_000_000, strict=True)
    limit: int = Field(
        default=DEFAULT_ARTIFACT_PAGE_CHARS, ge=1, le=MAX_ARTIFACT_PAGE_CHARS, strict=True
    )


class ArtifactWrite(Input):
    kind: Literal["code", "note"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)
    source_artifact_ids: list[str] = Field(default_factory=list, max_length=30)


class Search(Input):
    query: str = Field(min_length=2, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


class ClinicalSearch(Search):
    query: str = Field(min_length=2, max_length=1000)


class ClinicalTrial(Input):
    nct_id: str = Field(pattern=r"^NCT[0-9]{8}$")


class Fetch(Input):
    url: str = Field(max_length=2000)


class DatasetInput(Input):
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")
    start: date
    end: date


class ExperimentInput(Input):
    dataset_id: str
    mode: Literal["backtest", "walk_forward", "generated_strategy"] = "backtest"
    strategy: StrategySpec = Field(default_factory=StrategySpec)
    spec: BacktestSpec = Field(default_factory=BacktestSpec)
    walk: WalkForwardSpec = Field(default_factory=WalkForwardSpec)
    code_id: str | None = None


class PythonInput(Input):
    code_id: str
    input_artifact_ids: list[str] = Field(default_factory=list, max_length=5)


class ReviewInput(Input):
    artifact_id: str
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    verdict: Literal["accept", "revise", "reject"]
    findings: str = Field(min_length=30, max_length=16000)
    experiment_ids: list[str] = Field(default_factory=list, max_length=20)


class ProposalInput(Input):
    artifact_id: str
    review_id: str
    rationale: str = Field(min_length=30, max_length=12000)
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0, le=1_000_000, strict=True)
    limit_price: str = Field(pattern=r"^[0-9]+(\.[0-9]+)?$")


class BinaryComparison(Input):
    treatment_events: int = Field(ge=0, strict=True)
    treatment_n: int = Field(gt=0, strict=True)
    control_events: int = Field(ge=0, strict=True)
    control_n: int = Field(gt=0, strict=True)


def artifact_ref(artifact: dict) -> dict:
    return {key: artifact[key] for key in ("id", "kind", "title", "sha256")}


def _json_size(value) -> int:
    # Match the registry's conservative default JSON encoding, including escaped
    # Unicode/control characters. A character-page limit alone is not an output bound.
    return len(json.dumps(value, allow_nan=False))


def _fit_json_text(text, budget):
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if _json_size(text[:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def _content_text(content) -> str:
    # This is also the retrieval index's representation, so passage offsets are
    # usable directly with read_artifact. The artifact hash always names the full
    # original JSON value; it is not a hash of a rendered page.
    return (
        content
        if isinstance(content, str)
        else json.dumps(content, sort_keys=True, ensure_ascii=False, allow_nan=False)
    )


def _bounded_view(value, budget=3000):
    if _json_size(value) <= budget:
        return value
    return {
        "omitted": True,
        "reason": "Exceeds the inline response budget; inspect the original with read_artifact.",
    }


def _read_hint(identifier, *, offset=0, limit=DEFAULT_ARTIFACT_PAGE_CHARS, section="content"):
    return {
        "tool": "read_artifact",
        "arguments": {
            "artifact_id": identifier,
            "section": section,
            "offset": offset,
            "limit": limit,
        },
    }


def _provenance(artifact):
    content = artifact["content"]
    if not isinstance(content, dict):
        return {}
    fields = (
        "provenance",
        "url",
        "requested_url",
        "source",
        "retrieved_at",
        "published_at",
        "untrusted_source",
        "price_basis",
        "corporate_actions_checked",
        "synthetic",
    )
    return {key: content[key] for key in fields if key in content}


def _artifact_summary(artifact):
    content = artifact["content"]
    if not isinstance(content, dict):
        return {"content_chars": len(_content_text(content))}
    kind = artifact["kind"]
    if kind == "dataset":
        bars = content.get("bars", [])
        return {
            "symbol": content.get("symbol"),
            "sessions": len(bars),
            "first_session": bars[0].get("session") if bars else None,
            "last_session": bars[-1].get("session") if bars else None,
            "corporate_actions": len(content.get("corporate_actions", [])),
            "synthetic": content.get("synthetic"),
        }
    if kind in {"options_chain", "options_expirations"}:
        rows = content.get("contracts", [])
        return {
            key: value
            for key, value in {
                "underlying": content.get("underlying"),
                "expiration": content.get("expiration"),
                "date_count": len(content["dates"]) if "dates" in content else None,
                "dates": content["dates"][:20] if "dates" in content else None,
                "dates_truncated": len(content.get("dates", [])) > 20,
                "contract_count": len(rows) if kind == "options_chain" else None,
                "flagged_contract_count": sum(bool(row.get("issues")) for row in rows),
                "research_purpose": _fit_json_text(content.get("research_purpose", ""), 1000),
                "provider": content.get("provider"),
                "feed": content.get("feed"),
                "delay_seconds": content.get("delay_seconds"),
                "received_at": content.get("received_at"),
                "acquisition_started_at": content.get("acquisition_started_at"),
                "execution_eligible": False,
                "issues": content.get("issues", []),
                "synthetic": content.get("synthetic", False),
            }.items()
            if value is not None
        }
    if kind == "instrument_comparison":
        rows = content.get("candidates", [])
        return {
            "underlying": content.get("underlying"),
            "expiration": content.get("expiration"),
            "capital": content.get("capital"),
            "currency": content.get("currency"),
            "information_cutoff": content.get("information_cutoff"),
            "candidate_count": len(rows),
            "unavailable_count": sum(row.get("status") == "unavailable" for row in rows),
            "hypothesis_id": content.get("hypothesis", {}).get("id"),
            "execution_eligible": False,
            "synthetic": content.get("synthetic", False),
            "scope": "Conditional scenarios and supplied probabilities; not forecasts or fills.",
        }
    if kind in {"forecast", "forecast_resolution"}:
        fields = (
            "question",
            "status",
            "probability",
            "baseline_probability",
            "registered_at",
            "opens_at",
            "closes_at",
            "outcome",
            "recorded_at",
            "revision",
            "resolver_origin",
            "execution_eligible",
            "synthetic",
            "scope",
        )
        return {key: content[key] for key in fields if key in content}
    if kind == "experiment":
        return {
            "status": content.get("status"),
            "metrics": content.get("metrics"),
            "fold_count": len(content.get("folds", [])),
            "fill_count": len(content.get("trades", [])),
            "validation": content.get("validation"),
            "baseline": content.get("baseline"),
            "assessment": content.get("assessment"),
        }
    if kind == "evidence":
        summary = {
            key: content[key]
            for key in ("id", "query", "total_count", "coverage", "limitations")
            if key in content
        }
        if isinstance(content.get("items"), list):
            summary["records"] = [
                {key: item[key] for key in ("id", "url", "sha256") if key in item}
                for item in content["items"][:20]
            ]
        return summary
    keys = (
        "ok",
        "error",
        "verdict",
        "artifact_id",
        "artifact_sha256",
        "symbol",
        "side",
        "quantity",
        "limit_price",
    )
    return {key: content[key] for key in keys if key in content}


def compact_artifact(artifact):
    """Agent-facing receipt; full immutable artifacts remain available to the API."""
    return {
        **artifact_ref(artifact),
        "case_id": artifact["case_id"],
        "task_id": artifact["task_id"],
        "metadata": _bounded_view(artifact["metadata"], 6000),
        "provenance": _bounded_view(_provenance(artifact)),
        "summary": _bounded_view(_artifact_summary(artifact), 6000),
        "read": _read_hint(artifact["id"]),
        "read_metadata": _read_hint(artifact["id"], section="metadata"),
        "content_included": False,
    }


def _artifact_tool(handler, context, arguments):
    return compact_artifact(handler(context, arguments))


class ResearchTools:
    def __init__(self, store, settings: Settings, sandbox=None):
        self.store, self.settings = store, settings
        self.sandbox = sandbox or DockerSandbox(
            image=settings.sandbox_image, docker_binary=settings.docker_binary
        )

    def artifact(self, identifier, *, kind=None, case_id=None):
        artifact = self.store.get_artifact(identifier)
        if artifact["kind"] in PROTECTED_KINDS:
            raise DomainError(
                "PROTECTED_EVALUATION", "Evaluation labels are unavailable to research agents.", 403
            )
        if kind and artifact["kind"] != kind:
            raise DomainError("ARTIFACT_TYPE", f"This operation requires a {kind} artifact.")
        if case_id and artifact["case_id"] != case_id:
            raise DomainError("ARTIFACT_CASE", "This operation requires an artifact in this case.")
        return artifact

    def read(self, ctx, args: ArtifactRead):
        artifact = self.artifact(args.artifact_id)
        original = artifact[args.section]
        text = _content_text(original)
        if args.offset > len(text):
            raise ToolError("artifact_offset", "Offset exceeds this artifact section's length.")
        result = {
            **artifact_ref(artifact),
            "metadata": _bounded_view(artifact["metadata"]),
            "provenance": _bounded_view(_provenance(artifact)),
            "section": args.section,
            "content_encoding": "text" if isinstance(original, str) else "json_text",
            "offset": args.offset,
            "total_chars": len(text),
            "hash_scope": "sha256 identifies the complete original artifact content",
        }
        page = text[args.offset : args.offset + args.limit]
        # Reserve space for pagination fields; shrink by JSON size when escaping
        # expands source text. Every character remains reachable on the next page.
        budget = MAX_TOOL_RESULT_CHARS - _json_size(result) - 700
        page = _fit_json_text(page, budget)
        end = args.offset + len(page)
        next_offset = end if end < len(text) else None
        return {
            **result,
            "text": page,
            "returned_chars": len(page),
            "next_offset": next_offset,
            "truncated": next_offset is not None,
            "next_read": (
                _read_hint(artifact["id"], offset=end, limit=args.limit, section=args.section)
                if next_offset is not None
                else None
            ),
            "read_metadata": _read_hint(artifact["id"], section="metadata"),
        }

    def save(self, ctx, kind, title, content, metadata=None, *, require_active_case=False):
        ctx.check_cancelled()
        return self.store.put_artifact(
            ctx.case_id,
            ctx.task_id,
            kind,
            title,
            content,
            metadata,
            idempotency_key=ctx.idempotency_key,
            worker_id=ctx.worker_id,
            require_active_case=require_active_case,
        )

    def write(self, ctx: ToolContext, args: ArtifactWrite):
        if args.kind == "code" and self.store.get_task(ctx.task_id)["role"] != "coder":
            raise ToolError("forbidden_artifact", "Delegate executable code to a coder task.")
        sources = [artifact_ref(self.artifact(aid)) for aid in args.source_artifact_ids]
        return self.save(ctx, args.kind, args.title, args.content, {"inputs": sources})

    def search(self, query, limit=5):
        from researchdesk.data.retrieval import retrieve

        documents = [a for a in self.store.list_artifacts() if a["kind"] not in PROTECTED_KINDS]
        result = retrieve(
            query,
            documents,
            mode=self.settings.retrieval_mode,
            model_name=self.settings.embedding_model,
            limit=min(limit * 2, 30),
            cache_dir=self.settings.artifact_dir / "embeddings",
        )
        by_id = {a["id"]: a for a in documents}
        matches = {}
        for match in result["items"]:
            identifier = match["artifact_id"]
            if identifier not in matches:
                matches[identifier] = {**by_id[identifier], "score": match["score"], "passages": []}
            matches[identifier]["passages"].append(match)
        return {**result, "items": list(matches.values())[:limit]}

    def search_tool(self, ctx, args: Search):
        found = self.search(args.query, args.limit)
        result = {
            key: found[key]
            for key in (
                "mode",
                "method",
                "model",
                "corpus_artifacts",
                "corpus_chunks",
                "score_semantics",
                "embedding_cache_hits",
            )
            if key in found
        }
        result.update(
            {
                "items": [],
                "truncated": False,
                "inspection": "Use read_artifact at passage offsets to inspect full content; "
                "use section='metadata' for provenance. Narrow the query for more hits.",
            }
        )
        for artifact in found["items"]:
            item = {
                **artifact_ref(artifact),
                "score": artifact["score"],
                "metadata": _bounded_view(artifact["metadata"], 1000),
                "provenance": _bounded_view(_provenance(artifact), 1500),
                "passages": [],
                "read": _read_hint(artifact["id"]),
            }
            for match in artifact["passages"]:
                # A Unicode-heavy hit must still return an inspectable reference.
                # Retain the original chunk digest separately from this excerpt.
                excerpt = _fit_json_text(match["text"], 3600)
                passage = {
                    "start_char": match["start_char"],
                    "end_char": match["start_char"] + len(excerpt),
                    "text": excerpt,
                    "text_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                    "source_chunk_sha256": match["chunk_sha256"],
                    "source_end_char": match["end_char"],
                    "excerpt_truncated": len(excerpt) < len(match["text"]),
                    "score": match["score"],
                }
                candidate = {**item, "passages": [*item["passages"], passage]}
                if _json_size({**result, "items": [*result["items"], candidate]}) > (
                    MAX_TOOL_RESULT_CHARS - 512
                ):
                    result["truncated"] = True
                    break
                item = candidate
            if item["passages"]:
                item["read"] = _read_hint(artifact["id"], offset=item["passages"][0]["start_char"])
                result["items"].append(item)
            else:
                result["truncated"] = True
            if result["truncated"]:
                break
        result["returned_artifacts"] = len(result["items"])
        return result

    def fetch(self, ctx, args):
        from researchdesk.data.evidence import fetch_evidence

        result = fetch_evidence(
            args.url,
            allowed_hosts=self.settings.allowed_evidence_hosts.split(","),
            max_bytes=self.settings.max_evidence_bytes,
        )
        return self.save(
            ctx,
            "evidence",
            result["title"][:200] or args.url[:200],
            result,
            {
                "url": result["url"],
                "retrieved_at": result["retrieved_at"],
                "untrusted_source": True,
            },
        )

    def clinical(self, ctx, args, method):
        from researchdesk.data.clinical import search_pubmed, search_trials

        result = (search_trials if method == "trials" else search_pubmed)(
            args.query, limit=args.limit
        )
        return self.save(
            ctx,
            "evidence",
            f"{method}: {args.query}"[:200],
            result,
            {"untrusted_source": True, "query": args.query},
        )

    def clinical_trial(self, ctx, args: ClinicalTrial):
        from researchdesk.data.clinical import get_trial

        result = get_trial(args.nct_id)
        return self.save(
            ctx,
            "evidence",
            f"ClinicalTrials.gov · {args.nct_id}",
            result,
            {
                "source": "ClinicalTrials.gov",
                "nct_id": args.nct_id,
                "url": result["url"],
                "provenance": result["provenance"],
                "untrusted_source": True,
            },
        )

    def dataset(self, ctx, args):
        from researchdesk.data.market import acquire_snapshot

        snapshot = acquire_snapshot(args.symbol, args.start.isoformat(), args.end.isoformat())
        return self.save(
            ctx,
            "dataset",
            f"{args.symbol} · {args.start} to {args.end}",
            snapshot.model_dump(mode="json"),
            {"source": snapshot.source, "synthetic": snapshot.synthetic},
        )

    def experiment(self, ctx, args: ExperimentInput):
        dataset = self.artifact(args.dataset_id, kind="dataset")
        snapshot = MarketSnapshot.model_validate(dataset["content"])
        inputs = [artifact_ref(dataset)]
        try:
            if args.mode == "generated_strategy":
                if not args.code_id:
                    raise ToolError("code_required", "Provide an immutable Python code artifact.")
                code = self.artifact(args.code_id, kind="code", case_id=ctx.case_id)
                inputs.append(artifact_ref(code))
                # A fresh process for every decision prevents a strategy from keeping
                # future state; the container never receives the whole dataset.
                if len(snapshot.bars) > 250:
                    raise ToolError(
                        "experiment_limit",
                        "Generated strategies are limited to 250 sessions per experiment.",
                    )

                def policy(history):
                    ctx.check_cancelled()
                    output = self.sandbox.run(
                        code["content"],
                        history.as_payload(),
                        cancelled=ctx.cancelled,
                        timeout_seconds=self.settings.sandbox_timeout_seconds,
                    )
                    if not output.ok:
                        raise ToolError("strategy_execution_failed", str(output.error))
                    if not isinstance(output.output, dict) or set(output.output) != {
                        "target_weight"
                    }:
                        raise ToolError(
                            "strategy_output",
                            "run(payload) must return exactly {target_weight: number}.",
                        )
                    return output.output["target_weight"]

                result = run_backtest(
                    snapshot, spec=args.spec, policy=policy, policy_id=code["sha256"]
                )
            elif args.mode == "walk_forward":
                if args.code_id:
                    raise ToolError(
                        "unsupported_mode",
                        "Walk-forward selection currently supports the declared SMA family only.",
                    )
                result = run_walk_forward(snapshot, walk=args.walk, spec=args.spec)
            else:
                if args.code_id:
                    raise ToolError(
                        "unsupported_mode", "Use generated_strategy to execute the supplied code."
                    )
                result = run_backtest(snapshot, strategy=args.strategy, spec=args.spec)
        except QuantError as exc:
            raise ToolError(exc.code, str(exc)) from exc
        result = assessed_result(result)
        return self.save(
            ctx,
            "experiment",
            f"{snapshot.symbol} · {args.mode}",
            result,
            {
                "inputs": inputs,
                "mode": args.mode,
                "synthetic": snapshot.synthetic,
                "execution_eligible": not snapshot.synthetic,
                "implementation_version": "0.1.0",
            },
        )

    def python(self, ctx, args):
        code = self.artifact(args.code_id, kind="code", case_id=ctx.case_id)
        inputs = [self.artifact(aid) for aid in args.input_artifact_ids]
        result = self.sandbox.run(
            code["content"],
            {"artifacts": [{"id": a["id"], "content": a["content"]} for a in inputs]},
            cancelled=ctx.cancelled,
            timeout_seconds=self.settings.sandbox_timeout_seconds,
        )
        # Analysis execution is recorded, but cannot masquerade as a validated backtest.
        return self.save(
            ctx,
            "note",
            f"Python analysis · {code['title']}"[:200],
            asdict(result),
            {
                "inputs": [artifact_ref(code), *map(artifact_ref, inputs)],
                "execution_eligible": False,
                "analysis_execution": True,
            },
        )

    def review(self, ctx, args):
        target = self.artifact(args.artifact_id, case_id=ctx.case_id)
        if target["task_id"] is None or target["task_id"] == ctx.task_id:
            raise ToolError(
                "independent_review_required", "Review requires another task's immutable output."
            )
        if target["sha256"] != args.artifact_sha256:
            raise ToolError(
                "review_hash_mismatch", "Review must name the exact inspected artifact hash."
            )
        experiments = [
            self.artifact(aid, kind="experiment", case_id=ctx.case_id)
            for aid in args.experiment_ids
        ]
        for experiment in experiments:
            bindings = experiment["metadata"].get("inputs", [])
            if experiment["id"] != target["id"] and not any(
                i["id"] == target["id"] and i["sha256"] == target["sha256"] for i in bindings
            ):
                raise ToolError(
                    "unrelated_experiment", "Cited experiments must evaluate this exact artifact."
                )
        return self.save(
            ctx,
            "review",
            f"{args.verdict.title()} · {target['title']}"[:200],
            args.model_dump(),
            {"inputs": [artifact_ref(target), *map(artifact_ref, experiments)]},
        )

    def validate_decision(self, artifact_id, review_id, *, case_id=None):
        target = self.artifact(artifact_id, kind="experiment", case_id=case_id)
        review = self.artifact(review_id, kind="review", case_id=target["case_id"])
        content = review["content"]
        if (
            content["verdict"] != "accept"
            or content["artifact_id"] != target["id"]
            or content["artifact_sha256"] != target["sha256"]
            or not review["task_id"]
            or review["task_id"] == target["task_id"]
            or self.store.get_task(review["task_id"])["role"] != "reviewer"
        ):
            raise DomainError(
                "REVIEW_REQUIRED",
                "An independent accepting review of this exact experiment is required.",
                409,
            )
        if not target["metadata"].get("execution_eligible"):
            raise DomainError(
                "INELIGIBLE_EXPERIMENT",
                "Synthetic or unvalidated analysis cannot authorize paper orders.",
                409,
            )
        # Confirm all retained input hashes; no prose-only reference can pass this gate.
        for reference in target["metadata"].get("inputs", []):
            actual = self.artifact(reference["id"])
            if actual["sha256"] != reference["sha256"]:
                raise DomainError(
                    "INPUT_HASH_MISMATCH", "An experiment input failed integrity verification.", 409
                )
        return target, review

    def proposal(self, ctx, args):
        from decimal import Decimal

        if Decimal(args.limit_price) <= 0:
            raise ToolError("invalid_price", "Limit price must be positive.")
        target, review = self.validate_decision(
            args.artifact_id, args.review_id, case_id=ctx.case_id
        )
        datasets = [
            self.artifact(r["id"]) for r in target["metadata"]["inputs"] if r["kind"] == "dataset"
        ]
        if not datasets or any(d["content"]["symbol"] != args.symbol for d in datasets):
            raise ToolError(
                "decision_symbol", "Paper decisions must match the evaluated instrument."
            )
        return self.save(
            ctx,
            "paper_intent",
            f"{args.side.upper()} {args.quantity} {args.symbol}",
            args.model_dump(),
            {"inputs": [artifact_ref(target), artifact_ref(review)], "execution_mode": "paper"},
        )

    def registry(self):
        from researchdesk.source_navigation import InspectSourceInput, inspect_source

        registry = ToolRegistry()
        specs = [
            (
                "inspect_source",
                "Navigate retained evidence by exact JSON pointer with bounded child/text pages. "
                "Returns full-content hashes and exact scalar/text citations, preserving raw "
                "types. Follow cursors for complete coverage; missing paths do not establish "
                "absence of clinical evidence.",
                InspectSourceInput,
                ALL_ROLES,
                partial(inspect_source, self),
                "read",
            ),
            (
                "read_artifact",
                "Read an immutable artifact as paginated text (default 12000, maximum 16000 "
                "characters). Follow next_read until next_offset is null. JSON content is "
                "serialized with sorted keys; offsets match search passages. The hash identifies "
                "the complete original content. Use section='metadata' for complete provenance.",
                ArtifactRead,
                ALL_ROLES,
                self.read,
                "read",
            ),
            (
                "write_artifact",
                "Persist notes or Python code. Python defines run(payload); "
                "code requires the coder role.",
                ArtifactWrite,
                ALL_ROLES - {"reviewer"},
                self.write,
                "artifact",
            ),
            (
                "search_library",
                "Retrieve bounded source passages and artifact references, with explicit lexical "
                "or dense retrieval. Inspect full artifacts through read_artifact pagination.",
                Search,
                ALL_ROLES,
                self.search_tool,
                "read",
            ),
            (
                "fetch_evidence",
                "Fetch an allowlisted HTTPS source and retain attributable, untrusted evidence.",
                Fetch,
                ALL_ROLES,
                self.fetch,
                "artifact",
            ),
            (
                "search_clinical_trials",
                "Search ClinicalTrials.gov for study designs, endpoints, and published results.",
                ClinicalSearch,
                ALL_ROLES,
                lambda c, a: self.clinical(c, a, "trials"),
                "artifact",
            ),
            (
                "get_clinical_trial",
                "Fetch a complete current ClinicalTrials.gov record by NCT identifier, retaining "
                "source provenance. Inspect the full record with read_artifact pagination; "
                "registry dates are not verified public readout dates.",
                ClinicalTrial,
                ALL_ROLES,
                self.clinical_trial,
                "artifact",
            ),
            (
                "search_pubmed",
                "Search PubMed citations. Citation hits are not evidence of "
                "efficacy; inspect source findings.",
                ClinicalSearch,
                ALL_ROLES,
                lambda c, a: self.clinical(c, a, "pubmed"),
                "artifact",
            ),
            (
                "acquire_market_data",
                "Acquire daily market bars with source and corporate-action "
                "metadata; end date is exclusive.",
                DatasetInput,
                ALL_ROLES,
                self.dataset,
                "artifact",
            ),
            (
                "run_experiment",
                "Compute a causal cost-aware backtest or chronological SMA "
                "walk-forward; generated Python receives only observed history.",
                ExperimentInput,
                {"coder", "reviewer"},
                self.experiment,
                "artifact",
            ),
            (
                "execute_python",
                "Execute analysis code in an isolated container; this creates "
                "an analysis record, not an execution-eligible backtest.",
                PythonInput,
                {"coder", "reviewer"},
                self.python,
                "artifact",
            ),
            (
                "review_artifact",
                "Record an independent verdict bound to an inspected artifact "
                "hash and related experiments.",
                ReviewInput,
                {"reviewer"},
                self.review,
                "artifact",
            ),
            (
                "propose_paper_order",
                "Propose an order backed by an independently accepted "
                "experiment. Does not execute; deterministic risk admission "
                "follows.",
                ProposalInput,
                {"coordinator"},
                self.proposal,
                "artifact",
            ),
            (
                "compare_binary_rates",
                "Calculate clinical event-rate intervals and risk differences; "
                "never infers causal attribution.",
                BinaryComparison,
                ALL_ROLES,
                lambda c, a: compare_binary_rates(**a.model_dump()),
                "read",
            ),
            (
                "evaluate_scenarios",
                "Compute explicit stock/options expiration payoffs and "
                "assumptions; outputs cannot authorize option execution.",
                ScenarioSpec,
                ALL_ROLES,
                lambda c, a: evaluate_scenarios(a),
                "read",
            ),
        ]
        for name, description, schema, roles, handler, effect in specs:
            if effect == "artifact":
                handler = partial(_artifact_tool, handler)
                description += " Returns a compact receipt; read_artifact inspects full content."
            registry.register(name, description, schema, roles, handler, side_effect=effect)
        from researchdesk.agents.specialists import register_specialists
        from researchdesk.forecast_workflow import register_forecast_tools
        from researchdesk.generated_tools import register_generated_tools
        from researchdesk.instrument_workflow import register_instrument_tools
        from researchdesk.options_workflow import register_options_tools
        from researchdesk.quality_workflow import register_quality_tools

        register_quality_tools(registry, self)
        register_generated_tools(registry, self)
        register_specialists(registry, self)
        register_options_tools(registry, self)
        register_instrument_tools(registry, self)
        register_forecast_tools(registry, self)
        return registry
