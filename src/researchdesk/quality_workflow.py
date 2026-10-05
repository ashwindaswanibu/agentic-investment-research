"""Persist falsifiable research records and evaluate frozen outputs outside agent tools."""

from functools import partial
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from researchdesk.errors import DomainError
from researchdesk.research import (
    ClinicalDossier,
    ClinicalDossierV2,
    ExtractionReference,
    score_extraction,
)
from researchdesk.research.quality import (
    MAX_SOURCE_CONTENT_BYTES,
    bounded_json_size,
    check_dossier_budget,
    validate_dossier,
)
from researchdesk.store import content_hash


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HypothesisInput(Input):
    title: str = Field(min_length=5, max_length=200)
    mechanism: str = Field(min_length=30, max_length=6000)
    prediction: str = Field(min_length=20, max_length=4000)
    falsification_rule: str = Field(min_length=20, max_length=4000)
    evaluation_plan: str = Field(min_length=30, max_length=6000)
    competing_explanation: str = Field(min_length=20, max_length=4000)
    status: Literal["proposed", "revised", "rejected", "inconclusive"] = "proposed"
    disposition_reason: str = Field(min_length=20, max_length=4000)
    source_artifact_ids: list[str] = Field(min_length=1, max_length=30)
    prior_hypothesis_id: str | None = None


class DossierInput(Input):
    title: str = Field(min_length=5, max_length=200)
    dossier: ClinicalDossierV2 | ClinicalDossier
    hypothesis_id: str | None = None


def save_hypothesis(research, ctx, args):
    from researchdesk.domain import artifact_ref

    prior = None
    if args.prior_hypothesis_id:
        prior = research.artifact(args.prior_hypothesis_id, kind="hypothesis", case_id=ctx.case_id)
    if args.status == "revised" and prior is None:
        raise DomainError("PRIOR_REQUIRED", "A revision must identify its previous hypothesis.")
    sources = [research.artifact(aid) for aid in dict.fromkeys(args.source_artifact_ids)]
    return research.save(
        ctx,
        "hypothesis",
        args.title,
        args.model_dump(),
        {
            "inputs": [artifact_ref(a) for a in sources],
            "prior": artifact_ref(prior) if prior else None,
            "family_id": prior["metadata"]["family_id"] if prior else ctx.idempotency_key,
            "execution_eligible": False,
        },
    )


def save_dossier(research, ctx, args):
    from researchdesk.domain import artifact_ref

    try:
        identifiers = check_dossier_budget(args.dossier)
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise DomainError(
            "DOSSIER_LIMIT",
            "A dossier must fit 200 KB and cite at most 30 distinct source artifacts.",
        ) from exc
    sources = {}
    source_bytes = 0
    for aid in sorted(identifiers):
        ctx.check_cancelled()
        try:
            artifact = research.artifact(aid)
        except DomainError as exc:
            if exc.code != "NOT_FOUND":
                raise
            continue
        try:
            source_bytes += bounded_json_size(
                artifact["content"], MAX_SOURCE_CONTENT_BYTES - source_bytes
            )
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise DomainError(
                "DOSSIER_SOURCE_LIMIT",
                "Combined source artifact content must fit 8 MB of finite JSON.",
            ) from exc
        sources[aid] = artifact
    hypothesis = (
        research.artifact(args.hypothesis_id, kind="hypothesis", case_id=ctx.case_id)
        if args.hypothesis_id
        else None
    )
    report = validate_dossier(args.dossier, sources)
    # Retain failures so that revisions do not erase unsuccessful attempts.
    return research.save(
        ctx,
        "clinical_dossier",
        args.title,
        {"dossier": args.dossier.model_dump(mode="json"), "validation": report.model_dump()},
        {
            "inputs": [artifact_ref(a) for a in sources.values()],
            "hypothesis": artifact_ref(hypothesis) if hypothesis else None,
            "traceability_valid": report.valid,
            "execution_eligible": False,
            "quality_scope": "structure and attribution; not clinical truth or predictive skill",
        },
    )


def register_quality_tools(registry, research):
    from researchdesk.domain import _artifact_tool

    for name, description, schema, handler in [
        (
            "record_hypothesis",
            "Register a falsifiable mechanism, prediction, competing explanation and evaluation "
            "plan. Link revisions and rejections to the previous immutable hypothesis; keep "
            "unsuccessful attempts. Registration does not establish out-of-sample validity.",
            HypothesisInput,
            save_hypothesis,
        ),
        (
            "submit_clinical_dossier",
            "Persist a clinical-dossier.v2 with source-qualified analysis contexts, design, "
            "population counts, endpoints, reconciliation and forecast or abstention. Preserve "
            "different populations and analyses; do not flatten them to one trial-wide answer. "
            "Legacy v1 remains readable. Use inspect_source for exact paths and citations. "
            "Runs structural and attribution checks, retaining failures. Inspect validation "
            "and seek independent review; a passing check does not establish claim truth. "
            "Admission limits: 200 KB dossier, 30 source artifacts, 8 MB combined source content.",
            DossierInput,
            save_dossier,
        ),
    ]:
        registry.register(
            name,
            description,
            schema,
            {"researcher", "coordinator"},
            partial(_artifact_tool, partial(handler, research)),
            side_effect="artifact",
        )


def evaluate_extraction(store, *, candidate_id, baseline_id, reference, case_id, key):
    """Operator-only paired comparison. Never registered as an agent-callable tool.

    Reference must be prepared independently. Hidden labels prevent direct tool
    access, not prior model knowledge or leakage through the operator's brief.
    """
    reference = ExtractionReference.model_validate(reference)
    candidates = [store.get_artifact(aid) for aid in (candidate_id, baseline_id)]
    if candidate_id == baseline_id:
        raise DomainError("BASELINE_REQUIRED", "Use a distinct frozen baseline output.")
    if any(a["kind"] != "clinical_dossier" or a["case_id"] != case_id for a in candidates):
        raise DomainError(
            "EVALUATION_INPUT", "Both outputs must be clinical dossiers in this case."
        )
    scores = [score_extraction(a["content"]["dossier"], reference) for a in candidates]
    if not all(score.valid for score in scores):
        raise DomainError("EVALUATION_SCHEMA", "Candidate, baseline and reference must be valid.")
    gold = store.put_artifact(
        case_id,
        None,
        "evaluation_reference",
        f"Protected reference · {reference.reference_id}"[:200],
        reference.model_dump(mode="json"),
        {"model_access": False},
        idempotency_key=f"evaluation:{key}:reference",
    )
    bindings = [{k: a[k] for k in ("id", "sha256", "kind")} for a in [*candidates, gold]]
    result = {
        "reference_id": reference.reference_id,
        "candidate": scores[0].model_dump(),
        "baseline": scores[1].model_dump(),
        "f1_delta": (
            scores[0].f1 - scores[1].f1
            if scores[0].f1 is not None and scores[1].f1 is not None
            else None
        ),
        "scope": "One paired extraction assessment; not investment performance "
        "or a population estimate.",
        "protocol": "Frozen outputs compared against operator-supplied labels; "
        "no agent label access.",
        "inputs": bindings,
    }
    return store.put_artifact(
        case_id,
        None,
        "evaluation_report",
        f"Extraction evaluation · {reference.reference_id}"[:200],
        result,
        {
            "model_access": False,
            "inputs": bindings,
            "protocol_sha256": content_hash(result["protocol"]),
        },
        idempotency_key=f"evaluation:{key}:report",
    )
