"""Workflow/label-isolation tests using explicit synthetic clinical fixtures."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_research_quality import dossier as dossier_fixture
from test_research_quality import evidence as evidence_fixture
from test_research_quality import reference as reference_fixture

from researchdesk.agents import ToolContext
from researchdesk.config import Settings
from researchdesk.domain import ArtifactRead, PythonInput, ResearchTools
from researchdesk.errors import DomainError
from researchdesk.quality_workflow import evaluate_extraction
from researchdesk.store import Store

dossier = dossier_fixture
evidence = evidence_fixture
reference = reference_fixture


@pytest.fixture
def workbench(tmp_path, evidence, dossier):  # noqa: F811
    store = Store(f"sqlite:///{tmp_path / 'quality.db'}")
    case = store.create_case("Synthetic clinical workflow", "Engineering validation only")
    task = store.create_task(
        case["id"], "researcher", "Inspect synthetic sources and record findings"
    )
    store.claim_task("quality-worker", task_id=task["id"])
    ctx = ToolContext(store, case["id"], task["id"], "first", "quality-worker", lambda: False)
    source = store.put_artifact(
        case["id"], None, "evidence", "Synthetic source", evidence["synthetic-source"]["content"]
    )
    for claim in dossier["claims"]:
        for ref in claim["source_refs"]:
            ref.update(artifact_id=source["id"], artifact_sha256=source["sha256"])
    research = ResearchTools(store, Settings(_env_file=None, artifact_dir=tmp_path))
    yield store, case, ctx, research, source, dossier
    store.close()


def submit(workbench, dossier, call_id):
    _, _, ctx, research, _, _ = workbench
    return research.registry().execute(
        "submit_clinical_dossier",
        {"title": "Synthetic dossier", "dossier": dossier},
        replace(ctx, call_id=call_id),
    )


def test_invalid_source_quote_is_retained_as_failed_attribution_not_rejected(workbench):
    store, _, _, _, _, dossier = workbench
    dossier["claims"][0]["source_refs"][0]["excerpt"] = "This statement is absent from source."
    receipt = submit(workbench, dossier, "failed-quote")
    assert receipt["ok"]
    saved = store.get_artifact(receipt["data"]["id"])
    assert not saved["content"]["validation"]["valid"]
    assert not saved["metadata"]["execution_eligible"]
    assert any(i["code"] == "quote_present" for i in saved["content"]["validation"]["issues"])
    assert "content" not in receipt["data"]


def test_hypothesis_history_survives_rejection_and_retries(workbench):
    store, case, ctx, research, source, _ = workbench
    registry = research.registry()
    args = {
        "title": "Synthetic testable mechanism",
        "mechanism": "A fictional mechanism links the observed event to an outcome.",
        "prediction": "A declared future outcome differs from the comparison group.",
        "falsification_rule": "Reject if the predefined comparison fails "
        "on protected observations.",
        "evaluation_plan": "Compare the frozen candidate against an independent fixed baseline.",
        "competing_explanation": "The difference is explained by sampling variation alone.",
        "disposition_reason": "Initial research question, with no performance claim.",
        "source_artifact_ids": [source["id"]],
    }
    first = registry.execute("record_hypothesis", args, ctx)
    assert first["ok"]
    assert registry.execute("record_hypothesis", args, ctx)["data"]["id"] == first["data"]["id"]
    second = registry.execute(
        "record_hypothesis",
        {
            **args,
            "status": "rejected",
            "prior_hypothesis_id": first["data"]["id"],
            "disposition_reason": "The synthetic comparison did not support "
            "the original mechanism.",
        },
        replace(ctx, call_id="reject"),
    )
    assert second["ok"]
    history = store.list_artifacts(case["id"], kind="hypothesis")
    assert len(history) == 2
    assert len({a["metadata"]["family_id"] for a in history}) == 1


def test_operator_evaluation_compares_frozen_baseline_and_hides_gold(workbench, reference):  # noqa: F811
    store, case, ctx, research, _, dossier = workbench
    candidate = submit(workbench, dossier, "candidate")["data"]
    worse = deepcopy(dossier)
    worse["trials"][0]["design"]["allocation"] = "nonrandomized"
    baseline = submit(workbench, worse, "baseline")["data"]
    report = evaluate_extraction(
        store,
        candidate_id=candidate["id"],
        baseline_id=baseline["id"],
        reference=reference,
        case_id=case["id"],
        key="synthetic-paired-evaluation",
    )
    assert report["content"]["candidate"]["f1"] == 1
    assert report["content"]["baseline"]["critical_errors"]
    assert report["content"]["f1_delta"] > 0
    assert (
        evaluate_extraction(
            store,
            candidate_id=candidate["id"],
            baseline_id=baseline["id"],
            reference=reference,
            case_id=case["id"],
            key="synthetic-paired-evaluation",
        )["id"]
        == report["id"]
    )
    protected = [report, *store.list_artifacts(case["id"], "evaluation_reference")]
    for item in protected:
        with pytest.raises(DomainError, match="unavailable"):
            research.read(ctx, ArtifactRead(artifact_id=item["id"]))
        code = store.put_artifact(
            case["id"], ctx.task_id, "code", "Synthetic code", "def run(payload): return payload"
        )
        with pytest.raises(DomainError, match="unavailable"):
            research.python(ctx, PythonInput(code_id=code["id"], input_artifact_ids=[item["id"]]))
    hits = research.search("synthetic-gold-v1", limit=20)
    assert not {a["id"] for a in protected}.intersection(a["id"] for a in hits["items"])
    assert "evaluate_extraction" not in {t["name"] for t in research.registry().describe()}


def test_oversized_dossier_is_rejected_before_source_reads_or_artifact_creation(
    workbench, monkeypatch
):
    store, case, _, research, _, dossier = workbench
    dossier["uncertainty"] = ["x" * 12000] * 20
    fetched = []
    monkeypatch.setattr(research, "artifact", lambda aid: fetched.append(aid))
    result = submit(workbench, dossier, "oversized")
    assert not result["ok"] and result["error"]["code"] == "DOSSIER_LIMIT"
    assert not fetched
    assert not store.list_artifacts(case["id"], "clinical_dossier")


def test_distinct_source_limit_precedes_even_the_first_fetch(workbench, monkeypatch):
    store, case, _, research, _, dossier = workbench
    reference = dossier["claims"][0]["source_refs"][0]
    references = [{**reference, "artifact_id": f"synthetic-{i}"} for i in range(31)]
    dossier["claims"][0]["source_refs"] = references[:30]
    dossier["claims"][1]["source_refs"] = references[30:]
    fetched = []
    monkeypatch.setattr(research, "artifact", lambda aid: fetched.append(aid))
    result = submit(workbench, dossier, "too-many-sources")
    assert not result["ok"] and result["error"]["code"] == "DOSSIER_LIMIT"
    assert not fetched
    assert not store.list_artifacts(case["id"], "clinical_dossier")


def test_aggregate_source_budget_stops_fetching_as_soon_as_limit_is_exceeded(
    workbench, monkeypatch
):
    store, case, _, research, _, dossier = workbench
    references = []
    for index in range(6):
        artifact = store.put_artifact(
            case["id"],
            None,
            "evidence",
            f"Large synthetic source {index}",
            {"description": "x" * 1_700_000},
        )
        references.append(
            {
                "artifact_id": artifact["id"],
                "artifact_sha256": artifact["sha256"],
                "excerpt": "xxx",
                "source_path": "/description",
            }
        )
    for claim in dossier["claims"]:
        claim["source_refs"] = references
    fetched = []
    original = research.artifact

    def tracked(identifier):
        fetched.append(identifier)
        return original(identifier)

    monkeypatch.setattr(research, "artifact", tracked)
    result = submit(workbench, dossier, "too-large-sources")
    assert not result["ok"] and result["error"]["code"] == "DOSSIER_SOURCE_LIMIT"
    assert len(fetched) == 5  # Four fit; the fifth exceeds 8 MB, so the sixth is never read.
    assert not store.list_artifacts(case["id"], "clinical_dossier")
