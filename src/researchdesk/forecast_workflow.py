"""Immutable binary forecasts and explicit operator adjudications.

Registration records server timing, not whether an event was genuinely unknown.
Citation validation checks retained source presence, not truth or entailment.
"""

from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)
from sqlalchemy import select

from researchdesk.db import ArtifactRow
from researchdesk.errors import DomainError
from researchdesk.research.models import SourceReference
from researchdesk.research.quality import CitationValidator, bounded_json_size
from researchdesk.store import PROTECTED_KINDS, content_hash, require, row_dict

SOURCE_KINDS = {"evidence", "dataset", "options_chain", "options_expirations", "note"}
Text = Annotated[str, Field(min_length=1, max_length=4000, strict=True)]
Identifier = Annotated[str, Field(min_length=1, max_length=200, strict=True)]
Probability = Annotated[float, Field(ge=0, le=1, strict=True, allow_inf_nan=False)]
REGISTRATION_SCOPE = (
    "Server registration precedes the declared event window. This timing record does not "
    "prove that the outcome was unknown or absent from prior knowledge."
)
RESOLUTION_SCOPE = (
    "Operator adjudication against declared rules; citations establish retained source "
    "presence, not truth or entailment. Individual Brier arithmetic is not a skill claim."
)


class ForecastInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    hypothesis_id: Identifier
    hypothesis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    question: Text
    opens_at: AwareDatetime
    closes_at: AwareDatetime
    yes_rule: Text
    no_rule: Text
    unresolvable_rule: Text
    resolution_source: Text
    status: Literal["forecast", "abstain"]
    probability: Probability | None = None
    abstention_reason: Text | None = None
    baseline_probability: Probability
    baseline_rationale: Text
    source_artifact_ids: list[Identifier] = Field(min_length=1, max_length=10)

    @field_validator("opens_at", "closes_at", mode="before")
    @classmethod
    def explicit_timestamp(cls, value):
        if not isinstance(value, str | datetime):
            raise ValueError("Use an explicit timezone-aware timestamp.")
        return value

    @field_validator("opens_at", "closes_at")
    @classmethod
    def utc_timestamp(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self):
        if self.opens_at >= self.closes_at:
            raise ValueError("The event window must open before it closes.")
        if self.status == "forecast":
            if self.probability is None or self.abstention_reason is not None:
                raise ValueError("A forecast requires probability and no abstention reason.")
        elif self.probability is not None or self.abstention_reason is None:
            raise ValueError("An abstention requires a reason and no probability.")
        if len(set(self.source_artifact_ids)) != len(self.source_artifact_ids):
            raise ValueError("Source artifact IDs must be distinct.")
        return self


class ResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    outcome: Literal["yes", "no", "unresolvable"]
    rationale: Text
    source_refs: list[SourceReference] = Field(min_length=1, max_length=10)
    previous_resolution_id: Identifier | None = None


def _receipt(artifact):
    return {key: artifact[key] for key in ("id", "sha256", "kind", "title")}


def _time(value):
    try:
        return TypeAdapter(AwareDatetime).validate_python(value).astimezone(UTC)
    except (ValueError, TypeError) as exc:
        raise DomainError(
            "FORECAST_TIME", "Source times must be timezone-aware timestamps."
        ) from exc


def _available(artifact, now):
    timestamps = [artifact["created_at"]]
    for value in (artifact["content"], artifact["metadata"]):
        if isinstance(value, dict):
            timestamps.extend(
                value[key]
                for key in (
                    "created_at",
                    "received_at",
                    "retrieved_at",
                    "acquisition_started_at",
                )
                if value.get(key) is not None
            )
    if any(_time(value) > now for value in timestamps):
        raise DomainError(
            "INPUT_AFTER_REGISTRATION",
            "A referenced source has a future retention or receipt time.",
        )


def _load(session, identifier, case_id, kinds=None):
    artifact = row_dict(require(session, ArtifactRow, identifier))
    if artifact["kind"] in PROTECTED_KINDS:
        raise DomainError("PROTECTED_EVALUATION", "Evaluation labels are protected.", 403)
    if artifact["case_id"] != case_id:
        raise DomainError("ARTIFACT_CASE", "Forecast references must belong to this case.")
    if kinds is not None and artifact["kind"] not in kinds:
        raise DomainError("ARTIFACT_TYPE", "This reference is not an allowed retained source.")
    if content_hash(artifact["content"]) != artifact["sha256"]:
        raise DomainError("ARTIFACT_CORRUPT", "Source content failed integrity verification.", 409)
    return artifact


def _synthetic(session, artifacts, case_id, now):
    # Hypothesis creation predates this lifecycle and may only retain input refs.
    # Follow that explicit lineage, with a hard admission limit and cycle guard.
    pending, visited, synthetic = list(artifacts), set(), False
    while pending:
        artifact = pending.pop()
        if artifact["id"] in visited:
            continue
        visited.add(artifact["id"])
        if len(visited) > 100:
            raise DomainError("FORECAST_SOURCE_LIMIT", "Source lineage exceeds 100 artifacts.")
        _available(artifact, now)
        content, metadata = artifact["content"], artifact["metadata"]
        synthetic |= metadata.get("synthetic") is True
        synthetic |= isinstance(content, dict) and content.get("synthetic") is True
        if artifact["kind"] == "hypothesis":
            identifiers = {
                ref["id"]
                for ref in metadata.get("inputs", [])
                if isinstance(ref, dict) and isinstance(ref.get("id"), str)
            }
            if isinstance(content, dict):
                identifiers.update(content.get("source_artifact_ids", []))
            if len(identifiers) > 100:
                raise DomainError("FORECAST_SOURCE_LIMIT", "Source lineage exceeds 100 artifacts.")
            pending.extend(_load(session, aid, case_id) for aid in identifiers - visited)
    return synthetic


def _write_access(research, context=None, case_id=None):
    if research.settings.read_only:
        raise DomainError("READ_ONLY", "Read-only deployments cannot write forecasts.", 403)
    if context:
        context.check_cancelled()
        if context.case_id != case_id:
            raise DomainError("ARTIFACT_CASE", "The forecast must belong to the current case.")
        if research.store.get_task(context.task_id)["role"] not in {"researcher", "coordinator"}:
            raise DomainError("FORECAST_ROLE", "This task cannot register forecasts.", 403)


def register_forecast(research, args, *, case_id, key=None, context=None):
    """Register an attempt using only server time, including for operator writes."""
    _write_access(research, context, case_id)
    args = ForecastInput.model_validate(args)

    def guard(now):
        # The store holds and rechecks the case/task write fence here. Do not
        # open a nested Session through the context's cancellation callback:
        # an in-memory SQLite store shares that callback's physical connection.
        _write_access(research)
        if not now < args.opens_at < args.closes_at:
            raise DomainError(
                "FORECAST_WINDOW", "Registration must precede the opening of the event window.", 409
            )

    def build(session, now):
        guard(now)
        hypothesis = _load(session, args.hypothesis_id, case_id, {"hypothesis"})
        if hypothesis["sha256"] != args.hypothesis_sha256:
            raise DomainError("HYPOTHESIS_HASH", "Name the exact retained hypothesis hash.")
        sources = [_load(session, aid, case_id, SOURCE_KINDS) for aid in args.source_artifact_ids]
        synthetic = _synthetic(session, [hypothesis, *sources], case_id, now)
        content = {
            "schema_version": "forecast.v1",
            **args.model_dump(mode="json"),
            "registered_at": now.isoformat(),
            "hypothesis": _receipt(hypothesis),
            "source_refs": [_receipt(source) for source in sources],
            "synthetic": synthetic,
            "execution_eligible": False,
            "scope": REGISTRATION_SCOPE,
        }
        return (
            args.question[:200],
            content,
            {
                "inputs": [_receipt(hypothesis), *map(_receipt, sources)],
                "synthetic": synthetic,
                "execution_eligible": False,
                "registration_origin": "agent_tool" if context else "operator_api",
            },
        )

    return research.store.put_forecast_artifact(
        case_id,
        "forecast",
        args.model_dump(mode="json"),
        build,
        guard,
        idempotency_key=context.idempotency_key if context else key,
        task_id=context.task_id if context else None,
        worker_id=context.worker_id if context else None,
    )


def _resolutions(session, case_id, forecast_id):
    rows = session.scalars(
        select(ArtifactRow).where(
            ArtifactRow.case_id == case_id,
            ArtifactRow.kind == "forecast_resolution",
        )
    )
    results = []
    for row in rows:
        if (
            isinstance(row.content, dict)
            and row.content.get("forecast", {}).get("id") == forecast_id
        ):
            if content_hash(row.content) != row.sha256:
                raise DomainError("ARTIFACT_CORRUPT", "Resolution history failed integrity.", 409)
            results.append(row_dict(row))
    return sorted(results, key=lambda artifact: artifact["content"]["revision"])


def resolve_forecast(research, forecast_id, args, *, key=None):
    """Operator-only append/CAS; intentionally absent from every agent registry."""
    _write_access(research)
    args = ResolutionInput.model_validate(args)
    forecast = research.artifact(forecast_id, kind="forecast")
    case_id = forecast["case_id"]

    def guard(now):
        _write_access(research)
        if now < _time(forecast["content"]["closes_at"]):
            raise DomainError(
                "FORECAST_NOT_DUE", "Resolve only after the event window closes.", 409
            )

    def build(session, now):
        guard(now)
        current = _load(session, forecast_id, case_id, {"forecast"})
        _available(current, now)
        history = _resolutions(session, case_id, forecast_id)
        previous = history[-1] if history else None
        if args.previous_resolution_id != (previous["id"] if previous else None):
            raise DomainError(
                "RESOLUTION_CONFLICT",
                "Name the latest resolution before appending a correction.",
                409,
            )
        if previous:
            _available(previous, now)
        sources = {
            ref.artifact_id: _load(session, ref.artifact_id, case_id, {"evidence"})
            for ref in args.source_refs
        }
        total = 0
        for source in sources.values():
            _available(source, now)
            try:
                total += bounded_json_size(source["content"], 8_000_000 - total)
            except ValueError as exc:
                raise DomainError(
                    "FORECAST_SOURCE_LIMIT", "Cited source content exceeds 8 MB."
                ) from exc
        citations = CitationValidator(sources)
        for index, ref in enumerate(args.source_refs):
            failed = [
                check
                for check in citations.validate(ref, f"/source_refs/{index}")
                if not check.passed
            ]
            if failed:
                raise DomainError(
                    "RESOLUTION_SOURCE",
                    f"Citation {index + 1} does not match the selected evidence. "
                    "Reopen the source and check the excerpt, version and optional JSON pointer.",
                )
        inputs = [current, *sources.values(), *([previous] if previous else [])]
        synthetic = _synthetic(session, inputs, case_id, now)
        content = {
            "schema_version": "forecast-resolution.v1",
            **args.model_dump(mode="json"),
            "forecast": _receipt(current),
            "previous_resolution": _receipt(previous) if previous else None,
            "revision": len(history) + 1,
            "recorded_at": now.isoformat(),
            "resolver_origin": "operator_api",
            "synthetic": synthetic,
            "execution_eligible": False,
            "scope": RESOLUTION_SCOPE,
        }
        return (
            f"Resolution · {current['title']}"[:200],
            content,
            {
                "inputs": list(map(_receipt, inputs)),
                "synthetic": synthetic,
                "execution_eligible": False,
                "resolver_origin": "operator_api",
            },
        )

    return research.store.put_forecast_artifact(
        case_id,
        "forecast_resolution",
        {"forecast_id": forecast_id, **args.model_dump(mode="json")},
        build,
        guard,
        idempotency_key=key,
    )


def assessment(forecast, latest_resolution, now=None):
    content = forecast["content"]
    result = {
        "status": "pending",
        "scored": False,
        "brier": None,
        "baseline_brier": None,
        "improvement": None,
        "execution_eligible": False,
    }
    if content["status"] == "abstain":
        result["status"] = "abstained"
    elif latest_resolution:
        outcome = latest_resolution["content"]["outcome"]
        result["status"] = "unresolvable" if outcome == "unresolvable" else "resolved"
        if outcome in {"yes", "no"}:
            y = 1 if outcome == "yes" else 0
            brier = (content["probability"] - y) ** 2
            baseline = (content["baseline_probability"] - y) ** 2
            result.update(
                scored=True, brier=brier, baseline_brier=baseline, improvement=baseline - brier
            )
    elif (now or datetime.now(UTC)) >= _time(content["closes_at"]):
        result["status"] = "due"
    return result


def list_forecasts(research, case_id):
    artifacts = research.store.list_forecast_artifacts(case_id)
    forecasts = [artifact for artifact in artifacts if artifact["kind"] == "forecast"]
    histories = {}
    for artifact in artifacts:
        if artifact["kind"] == "forecast_resolution":
            histories.setdefault(artifact["content"]["forecast"]["id"], []).append(artifact)
    items = []
    now = datetime.now(UTC)
    for forecast in forecasts:
        history = sorted(histories.get(forecast["id"], []), key=lambda a: a["content"]["revision"])
        latest = history[-1] if history else None
        items.append(
            {
                "forecast": forecast,
                "resolutions": history,
                "latest_resolution": latest,
                "assessment": assessment(forecast, latest, now),
            }
        )
    return {"items": items}


def _tool(research, ctx, args):
    from researchdesk.domain import compact_artifact

    return compact_artifact(register_forecast(research, args, case_id=ctx.case_id, context=ctx))


def register_forecast_tools(registry, research):
    registry.register(
        "register_forecast",
        "Register an immutable binary forecast or explicit abstention tied to an exact saved "
        "hypothesis ID/hash and 1–10 same-case retained source IDs. Supply future opening and "
        "closing timestamps, yes/no/unresolvable rules, resolution source and a fixed baseline "
        "probability/rationale. Registration uses server time and must precede the window. "
        "It does not prove the event was unknown. Only operators can resolve outcomes after "
        "the window closes. Every attempt remains visible; no execution authorization or "
        "claim of forecasting skill. Returns a receipt; inspect with read_artifact.",
        ForecastInput,
        {"researcher", "coordinator"},
        partial(_tool, research),
        side_effect="artifact",
    )
