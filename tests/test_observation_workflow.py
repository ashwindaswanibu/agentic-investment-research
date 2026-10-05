"""Versioned tool integration with explicitly synthetic engineering evidence."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_benchmark_bundle import inputs as benchmark_inputs_fixture
from test_observation_models import (  # noqa: F401
    anchor,
    availability,
    count,
    design,
    dossier_v2,
    endpoint,
    ref,
)
from test_research_quality import dossier as legacy_dossier_fixture
from test_research_quality import evidence as legacy_evidence_fixture
from test_research_quality import reference as reference_fixture

from researchdesk.agents import ToolContext
from researchdesk.config import Settings
from researchdesk.domain import ResearchTools
from researchdesk.errors import DomainError
from researchdesk.quality_workflow import evaluate_extraction
from researchdesk.research import ClinicalDossierV2, parse_dossier, validate_dossier
from researchdesk.research.benchmark_models import BenchmarkProtocol
from researchdesk.research.benchmark_runner import benchmark_registry
from researchdesk.store import Store

reference = reference_fixture
dossier = legacy_dossier_fixture
evidence = legacy_evidence_fixture
benchmark_inputs = benchmark_inputs_fixture


@pytest.fixture
def observation_workbench(tmp_path, dossier_v2):  # noqa: F811
    store = Store(f"sqlite:///{tmp_path / 'observations.sqlite'}")
    case = store.create_case("Synthetic observation workflow", "Engineering checks only")
    task = store.create_task(case["id"], "researcher", "Record synthetic source observations")
    store.claim_task("observations-worker", task_id=task["id"])
    ctx = ToolContext(store, case["id"], task["id"], "submit", "observations-worker", lambda: False)
    source = store.put_artifact(
        case["id"],
        None,
        "evidence",
        "Synthetic source only",
        {
            "record": {
                "text": "Synthetic test statement.",
                "count": 12,
                "available": False,
                "groups": [{"id": "GROUP0"}],
            }
        },
    )
    dossier = deepcopy(dossier_v2)

    def remap(value):
        if isinstance(value, dict):
            if "artifact_id" in value:
                value.update(artifact_id=source["id"], artifact_sha256=source["sha256"])
            for child in value.values():
                remap(child)
        elif isinstance(value, list):
            for child in value:
                remap(child)

    remap(dossier)
    dossier["observations"][1]["endpoint_observation_id"] = "synthetic.endpoint"
    dossier["forecast"] = None
    research = ResearchTools(store, Settings(_env_file=None, artifact_dir=tmp_path))
    yield store, case, ctx, research, source, dossier
    store.close()


def test_registered_v2_submission_persists_exact_version_and_idempotent_diagnostics(
    observation_workbench,
):
    store, _, ctx, research, source, dossier = observation_workbench
    registry = research.registry()
    args = {"title": "Synthetic observations", "dossier": dossier}
    result = registry.execute("submit_clinical_dossier", args, ctx)
    assert result["ok"], result
    saved = store.get_artifact(result["data"]["id"])
    assert saved["content"]["dossier"]["schema_version"] == "clinical-dossier.v2"
    assert saved["content"]["dossier"]["forecast"] is None
    assert saved["content"]["validation"]["valid"], saved["content"]["validation"]
    assert not saved["metadata"]["execution_eligible"]
    assert saved["metadata"]["inputs"][0]["id"] == source["id"]
    assert isinstance(parse_dossier(saved["content"]["dossier"]), ClinicalDossierV2)
    assert registry.execute("submit_clinical_dossier", args, ctx)["data"]["id"] == saved["id"]


def test_failed_count_check_is_retained_without_erasing_prior_submission(observation_workbench):
    store, case, ctx, research, _, dossier = observation_workbench
    registry = research.registry()
    good = registry.execute(
        "submit_clinical_dossier", {"title": "Synthetic valid structure", "dossier": dossier}, ctx
    )
    assert good["ok"], good
    dossier["observations"][1]["count"]["value"] = 13
    bad = registry.execute(
        "submit_clinical_dossier",
        {"title": "Synthetic inconsistent count", "dossier": dossier},
        replace(ctx, call_id="failed-count"),
    )
    assert bad["ok"], bad
    saved = store.get_artifact(bad["data"]["id"])
    assert not saved["metadata"]["traceability_valid"]
    assert any(
        issue["code"] == "count_value_matches_source"
        for issue in saved["content"]["validation"]["issues"]
    )
    assert len(store.list_artifacts(case["id"], "clinical_dossier")) == 2


def test_source_inspection_is_registered_and_cannot_read_protected_reference(observation_workbench):
    store, case, ctx, research, source, _ = observation_workbench
    registry = research.registry()
    result = registry.execute(
        "inspect_source", {"artifact_id": source["id"], "source_path": "/record/count"}, ctx
    )
    assert result["ok"], result
    assert result["data"]["value"] == 12
    assert result["data"]["node_type"] == "integer"
    assert result["data"]["citation"]["source_path"] == "/record/count"
    protected = store.put_artifact(
        case["id"], None, "evaluation_reference", "Synthetic private reference", {"answer": 12}
    )
    denied = registry.execute("inspect_source", {"artifact_id": protected["id"]}, ctx)
    assert not denied["ok"]


def test_legacy_scorer_rejects_v2_instead_of_flattening_it(observation_workbench, reference):
    store, case, ctx, research, _, dossier = observation_workbench
    registry = research.registry()
    args = {"title": "Synthetic source-qualified dossier", "dossier": dossier}
    candidate = registry.execute("submit_clinical_dossier", args, ctx)["data"]
    baseline = registry.execute("submit_clinical_dossier", args, replace(ctx, call_id="baseline"))[
        "data"
    ]
    with pytest.raises(DomainError, match="Candidate, baseline and reference must be valid"):
        evaluate_extraction(
            store,
            candidate_id=candidate["id"],
            baseline_id=baseline["id"],
            reference=reference,
            case_id=case["id"],
            key="v2-not-legacy",
        )
    assert not store.list_artifacts(case["id"], "evaluation_reference")
    assert not store.list_artifacts(case["id"], "evaluation_report")


def test_v2_global_dispatch_keeps_source_paths_exact(observation_workbench):
    _, _, _, _, source, dossier = observation_workbench
    parsed = parse_dossier(dossier)
    report = validate_dossier(parsed, {source["id"]: source})
    assert report.valid, report.failed_checks
    assert report.coverage.observations == 4
    assert report.coverage.fully_attributed_observations == 4


@pytest.mark.parametrize("arm", ["generalist", "fixed_specialists", "adaptive_specialists"])
def test_all_benchmark_arms_navigate_sources_and_freeze_v2_without_flattening(
    observation_workbench, benchmark_inputs, arm
):
    store, case, ctx, research, source, dossier = observation_workbench
    candidate = research.registry().execute(
        "submit_clinical_dossier", {"title": "Synthetic v2 candidate", "dossier": dossier}, ctx
    )["data"]
    protocol = BenchmarkProtocol.model_validate_json(benchmark_inputs["protocol_path"].read_text())
    registry = benchmark_registry(research, arm, protocol)
    store.update_task(ctx.task_id, worker_id=ctx.worker_id, status="completed")
    coordinator = store.create_task(case["id"], "coordinator", "Select synthetic v2 dossier")
    store.claim_task("benchmark-worker", task_id=coordinator["id"])
    context = replace(
        ctx, task_id=coordinator["id"], worker_id="benchmark-worker", call_id="selection"
    )
    source_result = registry.execute(
        "inspect_source", {"artifact_id": source["id"], "source_path": "/record/count"}, context
    )
    assert source_result["ok"] and source_result["data"]["value"] == 12
    selected = registry.execute(
        "submit_benchmark_result",
        {"dossier_id": candidate["id"], "dossier_sha256": candidate["sha256"]},
        context,
    )
    assert selected["ok"], selected
    receipt = store.get_artifact(selected["data"]["id"])
    assert receipt["metadata"]["benchmark_submission"] is True
    assert receipt["content"]["dossier_sha256"] == candidate["sha256"]
    frozen = store.get_artifact(receipt["content"]["dossier_id"])["content"]["dossier"]
    assert frozen["schema_version"] == "clinical-dossier.v2"
    assert frozen == ClinicalDossierV2.model_validate(dossier).model_dump(mode="json")
