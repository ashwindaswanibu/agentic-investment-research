"""Pure guided-extraction agreement; no clinical judgment, network, or persistence.

Private reference corruption raises an evaluator error. Candidate omissions and
mistakes remain explicit field outcomes against an unchanged public denominator.
"""

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

from pydantic import BaseModel, TypeAdapter, ValidationError

from .models import SourceReference
from .observation_models import (
    AvailabilityObservation,
    ClinicalDossierV2,
    DesignObservation,
    EndpointObservation,
    ObservationContext,
    PopulationCountObservation,
    SourceAnchor,
    TrialIdentity,
)
from .quality import CitationValidator, _hash, _normalize, _pointer, bounded_json_size
from .scoped_models import MechanicalReference, MechanicalScope

MAX_CANDIDATE_BYTES = 200_000
MAX_SCOPE_BYTES = 200_000
MAX_REFERENCE_BYTES = 500_000
MAX_SOURCE_BYTES = 8_000_000
MAX_REPORT_BYTES = 750_000
LIMITATIONS = [
    "Guided registry extraction agreement over declared fields only; not clinical truth, "
    "semantic entailment, research completeness, or agent superiority.",
    "Out-of-scope assertions are not judged. Source locations assist extraction; "
    "no precision/F1, clinical grade, or predictive score is produced.",
    "Reviewer records describe provenance, not independent expert certification.",
    "Conditional value agreement excludes unavailable/invalid field records and ignores "
    "citation correctness; delivered scoped fraction requires value AND source binding.",
]
_MODELS = {
    "design": DesignObservation,
    "population_count": PopulationCountObservation,
    "endpoint": EndpointObservation,
    "availability": AvailabilityObservation,
}


class ReferenceValidationError(ValueError):
    """Safe evaluator-input error: never includes private reference values."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"Mechanical reference validation failed: {code}")


def _data(value):
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def _within(path, parent):
    return parent == "" or path == parent or path.startswith(parent + "/")


def _same(left, right):
    return type(left) is type(right) and left == right


def _project(value, operation, enum_map=None):
    if operation == "identity":
        if value is not None and type(value) not in (str, int, bool):
            raise ReferenceValidationError("reference_scalar_type")
        return value
    if type(value) is not str:
        raise ReferenceValidationError("normalization_source_type")
    if operation == "canonical_digit_string":
        if len(value) > 20 or re.fullmatch(r"0|[1-9][0-9]*", value) is None:
            raise ReferenceValidationError("noncanonical_integer_string")
        try:
            return int(value)
        except ValueError as exc:
            raise ReferenceValidationError("integer_string_limit") from exc
    if operation == "lowercase_enum":
        return value.lower()
    if operation == "enum_lookup":
        for entry in enum_map or ():
            if value == entry.source_token:
                return entry.value
        raise ReferenceValidationError("undeclared_enum_token")
    if operation == "nfc_whitespace":
        return _normalize(value)
    raise ReferenceValidationError("unknown_normalization")


@lru_cache(maxsize=40)
def _field_adapter(kind, name):
    return TypeAdapter(_MODELS[kind].model_fields[name].annotation)


@dataclass
class _Prepared:
    scope: MechanicalScope
    reference: MechanicalReference
    sources: dict
    contexts: dict
    observations: dict
    rules: dict
    citations: CitationValidator


def _prepare(scope, reference, sources):
    try:
        raw_scope, raw_reference = _data(scope), _data(reference)
        bounded_json_size(raw_scope, MAX_SCOPE_BYTES)
        bounded_json_size(raw_reference, MAX_REFERENCE_BYTES)
        scope = MechanicalScope.model_validate(raw_scope)
        reference = MechanicalReference.model_validate(raw_reference)
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ReferenceValidationError("reference_or_scope_schema_budget") from exc
    if reference.scope_sha256 != scope.sha256:
        raise ReferenceValidationError("scope_hash_mismatch")
    rules = {rule.field_id: rule for rule in reference.fields}
    if set(rules) != {field.field_id for field in scope.fields}:
        raise ReferenceValidationError("reference_field_coverage")
    if not isinstance(sources, Mapping) or len(sources) > 30:
        raise ReferenceValidationError("source_count")
    if set(sources) != {source.source_id for source in scope.sources}:
        raise ReferenceValidationError("source_set")
    artifacts, hashes, admitted, size = {}, {}, {}, 0
    for selected in scope.sources:
        artifact = sources[selected.source_id]
        try:
            if not isinstance(artifact, Mapping) or artifact.get("kind") != "evidence":
                raise ReferenceValidationError("source_kind")
            identifier = artifact["id"]
            SourceAnchor(
                artifact_id=identifier,
                artifact_sha256=selected.artifact_sha256,
                source_path="",
            )
            if identifier in artifacts:
                raise ReferenceValidationError("source_identity_ambiguous")
            size += bounded_json_size(artifact["content"], MAX_SOURCE_BYTES - size)
            digest = _hash(artifact["content"])
            if digest != artifact.get("sha256") or digest != selected.artifact_sha256:
                raise ReferenceValidationError("source_integrity")
        except ReferenceValidationError:
            raise
        except (KeyError, ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise ReferenceValidationError("source_schema_budget") from exc
        admitted[selected.source_id] = artifact
        artifacts[identifier], hashes[identifier] = artifact, digest
    citations = CitationValidator(artifacts)
    citations.hashes.update(hashes)  # One full-content hash per admitted source.
    contexts = {item.context_id: item for item in scope.contexts}
    observations = {item.observation_id: item for item in scope.observations}
    for context in scope.contexts:
        _select(admitted[context.source_id], context.source_path)
    for observation in scope.observations:
        if observation.group:
            context = contexts[observation.context_id]
            container = _select(admitted[context.source_id], context.source_path)
            groups = container.get("groups") if isinstance(container, dict) else None
            if (
                not isinstance(groups, list)
                or sum(
                    isinstance(group, dict) and group.get("id") == observation.group.local_id
                    for group in groups
                )
                != 1
            ):
                raise ReferenceValidationError("source_group_identity")
    for field in scope.fields:
        rule, observation = rules[field.field_id], observations[field.observation_id]
        if rule.normalization != field.normalization:
            raise ReferenceValidationError("normalization_not_public")
        requested_path = rule.source_path
        if rule.expected_state == "source_absent":
            requested_path += "/" + rule.missing_key.replace("~", "~0").replace("/", "~1")
        if requested_path != field.source_path:
            raise ReferenceValidationError("field_selector_not_public")
        context = contexts[observation.context_id]
        if rule.source_id != context.source_id or not _within(
            rule.source_path, context.source_path
        ):
            raise ReferenceValidationError("field_source_context")
        selected = _select(admitted[rule.source_id], rule.source_path)
        if rule.expected_state == "source_absent":
            if not isinstance(selected, dict) or rule.missing_key in selected:
                raise ReferenceValidationError("missing_key_not_proven")
        else:
            derived = _project(selected, rule.normalization, field.enum_map)
            if not _same(derived, rule.expected_value):
                raise ReferenceValidationError("expected_value_not_derived")
            try:
                _field_adapter(observation.kind, field.field_name).validate_python(
                    {"state": "present", "value": rule.expected_value}, strict=True
                )
            except ValidationError as exc:
                raise ReferenceValidationError("unrepresentable_expected_value") from exc
            grouped_count = (
                observation.kind == "population_count"
                and field.field_name == "count"
                and observation.group is not None
            )
            if grouped_count:
                group_path = rule.source_group_path
                if (
                    group_path is None
                    or group_path == rule.source_path
                    or not group_path.endswith("/groupId")
                    or group_path.rsplit("/", 1)[0] != rule.source_path.rsplit("/", 1)[0]
                    or not _within(group_path, context.source_path)
                    or _select(admitted[rule.source_id], group_path) != observation.group.local_id
                ):
                    raise ReferenceValidationError("count_group_selector")
            elif rule.source_group_path is not None:
                raise ReferenceValidationError("unexpected_group_selector")
    return _Prepared(scope, reference, admitted, contexts, observations, rules, citations)


def _select(artifact, path):
    try:
        return _pointer(artifact["content"], path)
    except (KeyError, ValueError, TypeError, IndexError, OverflowError, RecursionError) as exc:
        raise ReferenceValidationError("source_pointer") from exc


def validate_mechanical_reference(scope, reference, source_artifacts_by_source_id):
    """Preflight all declared rules; invalid evaluator inputs raise, never score zero."""
    _prepare(scope, reference, source_artifacts_by_source_id)


def _index(items, key):
    result = defaultdict(list)
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and type(item.get(key)) is str:
                result[item[key].strip()].append(item)
    return result


def _anchor(artifact, path):
    return {
        "artifact_id": artifact["id"],
        "artifact_sha256": artifact["sha256"],
        "source_path": path,
    }


def _logical(value):
    return value.strip() if type(value) is str else None


def _identity(prepared, public, observations, contexts, trials):
    records = observations[public.observation_id]
    if not records:
        return None, "omitted", "observation_missing"
    if len(records) != 1:
        return None, "ambiguous", "observation_duplicate"
    record = records[0]
    context = prepared.contexts[public.context_id]
    if (
        record.get("kind") != public.kind
        or _logical(record.get("context_id")) != context.context_id
    ):
        return None, "identity_error", "observation_identity"
    if public.kind == "design" and record.get("design_scope") != public.design_scope:
        return None, "identity_error", "design_scope"
    context_records, trial_records = contexts[context.context_id], trials[context.trial_id]
    if len(context_records) > 1 or len(trial_records) > 1:
        return None, "ambiguous", "context_or_trial_duplicate"
    if not context_records or not trial_records:
        return None, "identity_error", "context_or_trial_missing"
    try:
        candidate_context = ObservationContext.model_validate(context_records[0])
        candidate_trial = TrialIdentity.model_validate(trial_records[0])
    except ValidationError:
        return None, "invalid_record", "context_or_trial_schema"
    artifact = prepared.sources[context.source_id]
    expected_anchor = _anchor(artifact, context.source_path)
    if (
        candidate_context.source.model_dump() != expected_anchor
        or candidate_context.trial_id != context.trial_id
        or candidate_context.kind != context.kind
        or candidate_context.analysis_id != context.analysis_id
        or candidate_trial.trial_family_id != context.trial_family_id
    ):
        return None, "identity_error", "context_or_trial_binding"
    if public.kind == "population_count":
        expected_group = (
            {"container": expected_anchor, "local_id": public.group.local_id}
            if public.group is not None
            else None
        )
        if "group" not in record or record["group"] != expected_group:
            return None, "identity_error", "group_binding"
        if public.endpoint_observation_id is not None:
            endpoint_id = public.endpoint_observation_id
            if _logical(record.get("endpoint_observation_id")) != endpoint_id:
                return None, "identity_error", "endpoint_binding"
            endpoint_records = observations[endpoint_id]
            if len(endpoint_records) > 1:
                return None, "ambiguous", "endpoint_duplicate"
            if not endpoint_records:
                return None, "identity_error", "endpoint_missing"
            endpoint = endpoint_records[0]
            members = endpoint.get("population_count_ids")
            if (
                endpoint.get("kind") != "endpoint"
                or _logical(endpoint.get("context_id")) != public.context_id
                or not isinstance(members, list)
                or len(members) > 100
                or any(type(member) is not str for member in members)
                or len({_logical(member) for member in members}) != len(members)
                or sum(_logical(member) == public.observation_id for member in members) != 1
            ):
                return None, "identity_error", "endpoint_reciprocity"
            if expected_group is not None:
                groups = endpoint.get("groups")
                if not isinstance(groups, list) or groups.count(expected_group) != 1:
                    return None, "identity_error", "endpoint_group_binding"
    return record, None, None


def _cited(prepared, raw, artifact, path):
    try:
        ref = SourceReference.model_validate(raw)
    except (ValidationError, TypeError):
        return False
    if (
        ref.artifact_id != artifact["id"]
        or ref.artifact_sha256 != artifact["sha256"]
        or ref.source_path != path
    ):
        return False
    return all(check.passed for check in prepared.citations.validate(ref, "/field"))


def _field_result(prepared, field, record):
    rule = prepared.rules[field.field_id]
    public = prepared.observations[field.observation_id]
    if field.field_name not in record:
        return "omitted", "field_missing", None
    try:
        value = _field_adapter(public.kind, field.field_name).validate_python(
            record[field.field_name], strict=True
        )
    except (ValidationError, TypeError):
        return "invalid_record", "field_schema", None
    if value.state != rule.expected_state:
        return "wrong_state", "state_mismatch", False
    artifact = prepared.sources[rule.source_id]
    if value.state == "source_absent":
        if field.field_name == "count" and (
            record.get("count_source_ref") is not None
            or record.get("count_normalization") != "none"
        ):
            return "invalid_record", "absence_count_dependencies", None
        if field.field_name == "available" and record.get("available_source_ref") is not None:
            return "invalid_record", "absence_availability_dependencies", None
        valid = (
            value.proof.parent.model_dump() == _anchor(artifact, rule.source_path)
            and value.proof.key == rule.missing_key
        )
        return (
            ("matched", "exact_missing_key", True)
            if valid
            else ("unattributed", "absence_proof_binding", True)
        )
    candidate_value = value.value
    # Apply only the declared text comparison rule. A count must already be the
    # typed normalized integer, never a coerced candidate string/bool/float.
    if rule.normalization in ("lowercase_enum", "nfc_whitespace"):
        if type(candidate_value) is not str:
            return "wrong_value", "value_type", False
        candidate_value = _project(candidate_value, rule.normalization)
    if not _same(candidate_value, rule.expected_value):
        return "wrong_value", "value_mismatch", False
    refs = record.get("source_refs")
    if not isinstance(refs, list) or not refs or len(refs) > 30:
        return "unattributed", "source_refs_schema", True
    if field.field_name == "count":
        expected_normalization = (
            "integer_from_digit_string"
            if rule.normalization == "canonical_digit_string"
            else "none"
        )
        if record.get("count_normalization") != expected_normalization:
            return "invalid_record", "count_normalization", True
        selected_refs = [record.get("count_source_ref")]
    elif field.field_name == "available":
        selected_refs = [record.get("available_source_ref")]
    elif field.field_name == "prespecification":
        selected_refs = record.get("prespecification_refs")
    else:
        selected_refs = refs
    if not isinstance(selected_refs, list) or len(selected_refs) > 30:
        return "unattributed", "field_citation_missing", True
    attributed = any(_cited(prepared, ref, artifact, rule.source_path) for ref in selected_refs)
    # Count/availability fields have dedicated selectors; other citations may
    # legitimately support different, unscored fields in the same observation.
    if not attributed:
        return "unattributed", "field_citation_binding", True
    return "matched", "value_and_source", True


def _validation(raw):
    try:
        ClinicalDossierV2.model_validate(raw)
        return {"schema_valid": True, "issue_count": 0, "code": "schema_valid"}
    except ValidationError as exc:
        return {"schema_valid": False, "issue_count": exc.error_count(), "code": "schema_invalid"}


def _candidate_sources(raw):
    identifiers, stack = set(), [raw]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if type(value.get("artifact_id")) is str:
                identifiers.add(value["artifact_id"])
                if len(identifiers) > 30:
                    raise ValueError("source_count")
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def score_mechanical_dossier(candidate, scope, reference, source_artifacts_by_source_id):
    """Score declared fields only; expected values and review notes never enter reports."""
    prepared = _prepare(scope, reference, source_artifacts_by_source_id)
    scope, reference = prepared.scope, prepared.reference
    status, raw = "scored", None
    validation = {"schema_valid": None, "issue_count": 0, "code": "no_submission"}
    if candidate is None:
        status = "no_submission"
    else:
        try:
            raw = _data(candidate)
            bounded_json_size(raw, MAX_CANDIDATE_BYTES)
            _candidate_sources(raw)
            if not isinstance(raw, dict) or raw.get("schema_version") != "clinical-dossier.v2":
                raise ValueError("root")
            if any(
                not isinstance(raw.get(key), list) for key in ("observations", "contexts", "trials")
            ):
                raise ValueError("collections")
        except (ValueError, TypeError, OverflowError, RecursionError):
            status = "invalid_output"
            validation = {"schema_valid": False, "issue_count": 1, "code": "root_or_budget"}
        else:
            validation = _validation(raw)
    results = []
    if status == "scored":
        observations = _index(raw["observations"], "observation_id")
        contexts, trials = _index(raw["contexts"], "context_id"), _index(raw["trials"], "trial_id")
        identities = {
            item.observation_id: _identity(prepared, item, observations, contexts, trials)
            for item in scope.observations
        }
    for field in scope.fields:
        if status != "scored":
            field_status = "omitted" if status == "no_submission" else "invalid_record"
            reason, agreement = status, None
        else:
            record, field_status, reason = identities[field.observation_id]
            agreement = None
            if record is not None:
                field_status, reason, agreement = _field_result(prepared, field, record)
        results.append(
            {
                "field_id": field.field_id,
                "observation_id": field.observation_id,
                "field_name": field.field_name,
                "status": field_status,
                "reason": reason,
                "value_agreement": agreement,
            }
        )
    matched = sum(item["status"] == "matched" for item in results)
    compared = sum(item["value_agreement"] is not None for item in results)
    agreed = sum(item["value_agreement"] is True for item in results)
    report = {
        "schema_version": "clinical-mechanical-score.v1",
        "status": status,
        "scope_sha256": scope.sha256,
        "reference_sha256": reference.sha256,
        "expected_fields": len(results),
        "matched_fields": matched,
        "delivered_scoped_fraction": matched / len(results),
        "compared_fields": compared,
        "value_agreeing_fields": agreed,
        "conditional_value_agreement": agreed / compared if compared else None,
        "field_results": results,
        "candidate_validation": validation,
        "review_count": len(reference.reviewers),
        "reviewer_kinds": sorted({reviewer.kind for reviewer in reference.reviewers}),
        "limitations": LIMITATIONS,
    }
    try:
        bounded_json_size(report, MAX_REPORT_BYTES)
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ReferenceValidationError("report_budget") from exc
    return report
