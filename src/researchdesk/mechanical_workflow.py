"""Operator-only, immutable paired receipts for guided source extraction.

These references and reports use the existing protected artifact kinds. Neither
this function nor its private inputs are registered in an agent's tool registry.
"""

from collections.abc import Mapping

from researchdesk.errors import DomainError
from researchdesk.research.quality import bounded_json_size
from researchdesk.research.scoped_models import MechanicalReference, MechanicalScope
from researchdesk.research.scoped_quality import (
    score_mechanical_dossier,
    validate_mechanical_reference,
)
from researchdesk.store import content_hash


def _receipt(artifact):
    return {key: artifact[key] for key in ("id", "sha256", "kind")}


def _verified_artifact(store, identifier):
    artifact = store.get_artifact(identifier)
    if content_hash(artifact["content"]) != artifact["sha256"]:
        raise DomainError("EVALUATION_INTEGRITY", "A frozen evaluation input failed integrity.")
    return artifact


def evaluate_mechanical_comparison(
    store, *, candidate_id, baseline_id, scope, reference, source_bindings, case_id, key
):
    """Compare selected outputs; caller-supplied source IDs bind exact local evidence.

    The public dataset case ID and database case UUID are distinct identities.
    Their association and every input digest are retained in the protected receipt.
    A damaged reference stops evaluation; a malformed candidate remains a result.
    """
    if not isinstance(key, str) or not key.strip() or len(key) > 200:
        raise DomainError(
            "EVALUATION_KEY", "Use a nonempty comparison key of at most 200 characters."
        )
    if candidate_id == baseline_id:
        raise DomainError("BASELINE_REQUIRED", "Use a distinct frozen baseline output.")
    scope = MechanicalScope.model_validate(scope)
    reference = MechanicalReference.model_validate(reference)
    if (
        not isinstance(source_bindings, Mapping)
        or set(source_bindings) != {source.source_id for source in scope.sources}
        or any(not isinstance(value, str) for value in source_bindings.values())
    ):
        raise DomainError(
            "EVALUATION_SOURCES", "Bind every declared source ID to one evidence artifact."
        )
    sources = {
        source_id: _verified_artifact(store, identifier)
        for source_id, identifier in source_bindings.items()
    }
    validate_mechanical_reference(scope, reference, sources)
    candidates = [_verified_artifact(store, aid) for aid in (candidate_id, baseline_id)]
    if any(item["kind"] != "clinical_dossier" or item["case_id"] != case_id for item in candidates):
        raise DomainError(
            "EVALUATION_INPUT", "Both outputs must be clinical dossiers in this case."
        )
    scores = [
        score_mechanical_dossier(
            item["content"].get("dossier")
            if isinstance(item["content"], dict)
            else item["content"],
            scope,
            reference,
            sources,
        )
        for item in candidates
    ]
    source_receipts = [
        {"source_id": source_id, **_receipt(artifact)}
        for source_id, artifact in sorted(sources.items())
    ]
    protected = {
        "schema_version": "clinical-mechanical-evaluation-inputs.v1",
        "database_case_id": case_id,
        "dataset_case_id": scope.case_id,
        "scope": scope.model_dump(mode="json"),
        "reference": reference.model_dump(mode="json"),
        "sources": source_receipts,
    }
    bounded_json_size(protected, 1_900_000)
    # Derive the receipt identity from all immutable inputs. Reusing a key with
    # changed inputs must trigger Store's idempotency conflict, never return an
    # unrelated previous comparison.
    input_receipts = [_receipt(item) for item in candidates]
    gold = store.put_artifact(
        case_id,
        None,
        "evaluation_reference",
        f"Protected mechanical reference · {reference.reference_id}"[:200],
        protected,
        {"model_access": False, "inputs": input_receipts},
        idempotency_key=f"mechanical:{key}:reference",
    )
    inputs = [*input_receipts, _receipt(gold)]
    result = {
        "schema_version": "clinical-mechanical-comparison.v1",
        "dataset_case_id": scope.case_id,
        "database_case_id": case_id,
        "scope_sha256": scope.sha256,
        "reference_sha256": reference.sha256,
        "candidate": scores[0],
        "baseline": scores[1],
        "delivered_scoped_fraction_delta": (
            scores[0]["delivered_scoped_fraction"] - scores[1]["delivered_scoped_fraction"]
        ),
        "scope": "One paired guided extraction diagnostic over predeclared source fields. "
        "No clinical truth, research superiority, investment return, or generalization claim.",
        "inputs": inputs,
        "sources": source_receipts,
    }
    bounded_json_size(result, 1_900_000)
    return store.put_artifact(
        case_id,
        None,
        "evaluation_report",
        "Guided registry extraction comparison",
        result,
        {"model_access": False, "inputs": inputs, "execution_eligible": False},
        idempotency_key=f"mechanical:{key}:report",
    )
