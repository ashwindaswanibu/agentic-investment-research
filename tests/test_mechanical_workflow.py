"""Protected operator receipts, using synthetic source fixtures only."""

import json
from copy import deepcopy

import pytest
from test_scoped_quality import fixture as fixture_data

from researchdesk.agents import ToolContext
from researchdesk.config import Settings
from researchdesk.domain import ResearchTools
from researchdesk.errors import DomainError
from researchdesk.mechanical_workflow import evaluate_mechanical_comparison
from researchdesk.research.scoped_models import MechanicalReference, MechanicalScope
from researchdesk.research.scoped_quality import ReferenceValidationError
from researchdesk.store import Store

scoped_fixture = fixture_data


@pytest.fixture
def comparison(tmp_path, scoped_fixture):
    dossier, scope, reference, sources = scoped_fixture
    scope = MechanicalScope.model_validate(scope)
    reference = MechanicalReference.model_validate(reference)
    store = Store(f"sqlite:///{tmp_path / 'mechanical.sqlite'}")
    case = store.create_case("Synthetic mechanical comparison", "Engineering verification only")
    source = store.put_artifact(
        case["id"], None, "evidence", "Synthetic source", sources["stable-source"]["content"]
    )
    dossier = json.loads(json.dumps(dossier).replace("local-artifact", source["id"]))
    candidate = store.put_artifact(
        case["id"], None, "clinical_dossier", "Candidate", {"dossier": dossier}
    )
    worse = deepcopy(dossier)
    worse["observations"][0]["count"]["value"] = 11
    baseline = store.put_artifact(
        case["id"], None, "clinical_dossier", "Baseline", {"dossier": worse}
    )
    args = dict(
        candidate_id=candidate["id"],
        baseline_id=baseline["id"],
        scope=scope,
        reference=reference,
        source_bindings={"stable-source": source["id"]},
        case_id=case["id"],
        key="synthetic-comparison",
    )
    yield store, args, candidate, baseline
    store.close()


def test_paired_receipt_binds_inputs_and_is_replayable(comparison):
    store, args, candidate, baseline = comparison
    report = evaluate_mechanical_comparison(store, **args)
    assert evaluate_mechanical_comparison(store, **args)["id"] == report["id"]
    content = report["content"]
    assert content["schema_version"] == "clinical-mechanical-comparison.v1"
    assert content["dataset_case_id"] == "case"
    assert content["database_case_id"] == args["case_id"] != "case"
    assert content["candidate"]["matched_fields"] > content["baseline"]["matched_fields"]
    assert content["delivered_scoped_fraction_delta"] > 0
    assert [item["id"] for item in content["inputs"][:2]] == [candidate["id"], baseline["id"]]
    assert content["scope_sha256"] == args["scope"].sha256
    assert "expected_value" not in json.dumps(content)
    assert "PRIVATE_NOTES" not in json.dumps(content)
    assert len(store.list_artifacts(kind="evaluation_reference")) == 1


def test_reusing_key_with_changed_candidate_cannot_return_old_comparison(comparison):
    store, args, _, _ = comparison
    evaluate_mechanical_comparison(store, **args)
    changed = dict(args, candidate_id=args["baseline_id"], baseline_id=args["candidate_id"])
    with pytest.raises(DomainError, match="different"):
        evaluate_mechanical_comparison(store, **changed)


def test_reference_error_is_not_a_candidate_zero_or_persisted_report(comparison):
    store, args, _, _ = comparison
    invalid = args["reference"].model_dump(mode="json")
    invalid["fields"][0]["expected_value"] = 999
    with pytest.raises(ReferenceValidationError):
        evaluate_mechanical_comparison(store, **dict(args, reference=invalid))
    assert not store.list_artifacts(kind="evaluation_report")
    assert not store.list_artifacts(kind="evaluation_reference")


def test_malformed_candidate_remains_a_visible_failed_output(comparison):
    store, args, _, _ = comparison
    invalid = store.put_artifact(
        args["case_id"], None, "clinical_dossier", "Malformed", {"dossier": "bad"}
    )
    result = evaluate_mechanical_comparison(store, **dict(args, candidate_id=invalid["id"]))[
        "content"
    ]
    assert result["candidate"]["status"] == "invalid_output"
    assert result["candidate"]["matched_fields"] == 0
    assert result["candidate"]["expected_fields"] == result["baseline"]["expected_fields"]


def test_distinct_same_case_outputs_and_exact_source_bindings_required(comparison):
    store, args, _, _ = comparison
    with pytest.raises(DomainError) as exc:
        evaluate_mechanical_comparison(store, **dict(args, baseline_id=args["candidate_id"]))
    assert exc.value.code == "BASELINE_REQUIRED"
    with pytest.raises(DomainError) as exc:
        evaluate_mechanical_comparison(store, **dict(args, source_bindings={}))
    assert exc.value.code == "EVALUATION_SOURCES"
    other = store.create_case("Other case", "Synthetic unrelated case")
    with pytest.raises(DomainError) as exc:
        evaluate_mechanical_comparison(store, **dict(args, case_id=other["id"]))
    assert exc.value.code == "EVALUATION_INPUT"


def test_agent_tools_cannot_read_reports_or_private_reference(comparison, tmp_path):
    store, args, _, _ = comparison
    report = evaluate_mechanical_comparison(store, **args)
    task = store.create_task(args["case_id"], "researcher", "Check protected access")
    store.claim_task("worker", task_id=task["id"])
    context = ToolContext(store, args["case_id"], task["id"], "read", "worker", lambda: False)
    registry = ResearchTools(store, Settings(_env_file=None, artifact_dir=tmp_path)).registry()
    for artifact in [report, *store.list_artifacts(kind="evaluation_reference")]:
        result = registry.execute("read_artifact", {"artifact_id": artifact["id"]}, context)
        assert not result["ok"]
        assert "PRIVATE_NOTES" not in json.dumps(result)
    assert "evaluate_mechanical" not in {item["name"] for item in registry.tools_for("coordinator")}
