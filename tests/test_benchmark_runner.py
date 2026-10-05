"""Synthetic orchestration fixtures only; these are not model-quality results."""

import json
import time
from copy import deepcopy
from dataclasses import replace

import pytest
from test_benchmark_bundle import inputs as inputs_fixture
from test_research_quality import dossier as dossier_fixture
from test_research_quality import evidence as evidence_fixture

from researchdesk.agents import ProviderTurn, ToolCall, ToolContext, register_delegation
from researchdesk.config import Settings
from researchdesk.domain import ResearchTools
from researchdesk.research.benchmark_bundle import freeze_bundle, load_bundle
from researchdesk.research.benchmark_journal import Journal
from researchdesk.research.benchmark_runner import (
    CORE_TOOLS,
    _prepare,
    _run_attempt,
    benchmark_registry,
    report,
    run_suite,
)
from researchdesk.store import Store

inputs = inputs_fixture
evidence = evidence_fixture
dossier = dossier_fixture


@pytest.fixture
def suite(inputs, tmp_path):  # noqa: F811
    freeze_bundle(**inputs)
    manifest, protocol, binding = load_bundle(inputs["output"])
    output = tmp_path / "run"
    output.mkdir()
    journal = Journal(output)
    journal.initialize(binding=binding, manifest=manifest, protocol=protocol, split="development")
    value = dict(
        bundle_path=inputs["output"],
        output=output,
        manifest=manifest,
        protocol=protocol,
        journal=journal,
        settings=Settings(_env_file=None, artifact_dir=tmp_path),
    )
    yield value
    journal.close()


class Scripted:
    def __init__(self, turns):
        self.turns, self.calls = iter(turns), 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        return next(self.turns)


def test_prose_claim_is_not_success_and_every_planned_attempt_stays_visible(suite):
    attempt = suite["journal"].attempts()[0]
    provider = Scripted([ProviderTurn("I completed every check successfully.")])
    _run_attempt(**suite, attempt=attempt, provider=provider)
    result = report(suite["output"])
    assert result["planned_attempts"] == 6
    assert result["statuses"] == {"failed": 1, "planned": 5}
    outcome = result["attempts"][0]["result"]
    assert outcome["model_calls"] == 1
    assert outcome["selected_dossier"] is None
    assert outcome["clinical_quality_score"] is None
    assert outcome["cost_usd"] is None
    assert outcome["error_codes"] == ["benchmark_missing_submission"]


def test_private_labels_never_enter_attempt_database_or_candidate_brief(suite):
    attempt = suite["journal"].attempts()[0]
    _run_attempt(**suite, attempt=attempt, provider=Scripted([ProviderTurn("No output")]))
    store = Store(f"sqlite:///{suite['output'] / 'attempts' / attempt['id'] / 'research.sqlite'}")
    try:
        artifacts = store.list_artifacts()
        serialized = json.dumps(artifacts)
        assert "SYNTHETIC GOLD LABEL" not in serialized
        assert "synthetic-private-reference" not in serialized
        assert "synthetic-private-source" not in serialized
        assert {item["kind"] for item in artifacts} == {"evidence", "note"}
        briefing = next(item for item in artifacts if item["kind"] == "note")
        source = next(item for item in artifacts if item["kind"] == "evidence")
        assert briefing["content"]["sources"][0]["artifact_id"] == source["id"]
        assert source["sha256"] == suite["manifest"].sources[0].artifact_sha256
    finally:
        store.close()


@pytest.mark.parametrize("arm", ["generalist", "fixed_specialists", "adaptive_specialists"])
def test_core_analysis_capability_equal_and_production_role_permissions_unchanged(suite, arm):
    store = Store("sqlite:///:memory:")
    try:
        case = store.create_case("Synthetic capability fixture", "No real research or market data")
        task = store.create_task(case["id"], "coordinator", "Test coordinator code authorship")
        store.claim_task("w", task_id=task["id"])
        research = ResearchTools(store, suite["settings"])
        registry = benchmark_registry(research, arm, suite["protocol"])
        register_delegation(registry)
        policy = registry.task_policy(store, task)
        advertised = {
            tool["name"]
            for tool in registry.tools_for("coordinator", allowed_tools=policy.allowed_tools)
        }
        assert CORE_TOOLS <= advertised
        assert ("delegate_task" in advertised) == (arm != "generalist")
        assert ("propose_specialist" in advertised) == (arm == "adaptive_specialists")
        assert (
            not {
                "fetch_evidence",
                "get_clinical_trial",
                "propose_paper_order",
                "qualify_research_tool",
            }
            & advertised
        )
        context = ToolContext(store, case["id"], task["id"], "code", "w", lambda: False)
        args = {
            "kind": "code",
            "title": "Synthetic fixture",
            "content": "def run(payload): return 1",
        }
        assert (
            research.registry().execute("write_artifact", args, context)["error"]["code"]
            == "forbidden_artifact"
        )
        store.begin_tool_call(task["id"], "code", "write_artifact", args, worker_id="w")
        assert registry.execute("write_artifact", args, context)["ok"] is True
        denied = registry.execute("fetch_evidence", {"url": "https://example.org/"}, context)
        assert denied["ok"] is False
        if arm == "generalist":
            denied = registry.execute(
                "delegate_task",
                {"role": "researcher", "instruction": "Should not be delegated"},
                context,
            )
            assert denied["error"]["code"] == "specialist_tool_forbidden"
    finally:
        store.close()


class DossierScript:
    def __init__(self, template, evidence_text):
        self.template, self.evidence_text, self.calls = template, evidence_text, 0

    def complete(self, messages, tools, instruction, cancelled=lambda: False):
        self.calls += 1
        if self.calls == 1:
            initial = json.loads(messages[0]["content"])
            # Real artifacts are imported before the agent starts; IDs vary per attempt.
            source_id = initial["input_artifact_ids"][1]
            candidate = deepcopy(self.template)
            for claim in candidate["claims"]:
                for ref in claim["source_refs"]:
                    ref.update(
                        artifact_id=source_id, excerpt=self.evidence_text, source_path="/text"
                    )
            return ProviderTurn(
                tool_calls=[
                    ToolCall(
                        "dossier",
                        "submit_clinical_dossier",
                        {"title": "Synthetic dossier", "dossier": candidate},
                    )
                ]
            )
        receipt = next(
            (m["content"]["data"] for m in messages if m.get("name") == "submit_clinical_dossier"),
            None,
        )
        if self.calls == 2:
            return ProviderTurn(
                tool_calls=[
                    ToolCall(
                        "select",
                        "submit_benchmark_result",
                        {"dossier_id": receipt["id"], "dossier_sha256": receipt["sha256"]},
                    )
                ]
            )
        return ProviderTurn("Selected the retained fixture output.", usage={"input_tokens": 17})


def test_complete_attempt_requires_frozen_submission_and_retains_diagnostics(suite, dossier):  # noqa: F811
    source = suite["manifest"].sources[0]
    for claim in dossier["claims"]:
        for ref in claim["source_refs"]:
            ref["artifact_sha256"] = source.artifact_sha256
    provider = DossierScript(dossier, "SYNTHETIC evidence: Test A compared with Test B.")
    attempt = next(item for item in suite["journal"].attempts() if item["arm"] == "generalist")
    _run_attempt(**suite, attempt=attempt, provider=provider)
    result = next(
        item for item in report(suite["output"])["attempts"] if item["id"] == attempt["id"]
    )
    assert result["status"] == "completed"
    assert result["result"]["selected_dossier"]["sha256"]
    assert result["result"]["model_calls"] == 3
    assert result["result"]["tool_calls"] == 2
    assert result["result"]["clinical_quality_score"] is None
    assert result["result"]["provider_usage"][-1] == {"input_tokens": 17}


def test_resume_keeps_original_deadline_and_does_not_call_model_after_expiry(suite):
    attempt = suite["journal"].attempts()[0]
    suite["journal"].start(attempt["id"], now=time.time() - 1000)
    provider = Scripted([])
    _run_attempt(**suite, attempt=attempt, provider=provider)
    result = suite["journal"].attempts()[0]
    assert provider.calls == 0
    assert result["status"] == "blocked"
    assert "benchmark_deadline" in result["result"]["error_codes"]


def test_operator_cannot_accidentally_run_final_split(suite):
    with pytest.raises(ValueError, match="Final-set execution"):
        run_suite(
            bundle_path=suite["bundle_path"],
            output=suite["output"],
            split="final",
            settings=suite["settings"],
        )


def test_first_submission_is_immutable_and_bound_to_exact_dossier(suite, dossier):  # noqa: F811
    store = Store("sqlite:///:memory:")
    try:
        attempt = suite["journal"].attempts()[0]
        record, root = _prepare(
            store,
            suite["bundle_path"],
            suite["manifest"],
            suite["protocol"],
            suite["manifest"].cases[0],
            attempt,
        )
        store.claim_task("w", task_id=root["id"])
        research = ResearchTools(store, suite["settings"])
        registry = benchmark_registry(research, "generalist", suite["protocol"])
        artifact = store.put_artifact(
            record["id"],
            root["id"],
            "clinical_dossier",
            "Synthetic dossier",
            {"dossier": dossier},
            worker_id="w",
        )
        context = ToolContext(store, record["id"], root["id"], "select", "w", lambda: False)
        args = {"dossier_id": artifact["id"], "dossier_sha256": "a" * 64}
        assert (
            registry.execute("submit_benchmark_result", args, context)["error"]["code"]
            == "benchmark_hash_mismatch"
        )
        args["dossier_sha256"] = artifact["sha256"]
        store.begin_tool_call(root["id"], "select", "submit_benchmark_result", args, worker_id="w")
        assert registry.execute("submit_benchmark_result", args, context)["ok"]
        context = replace(context, call_id="replace")
        assert (
            registry.execute("submit_benchmark_result", args, context)["error"]["code"]
            == "benchmark_already_submitted"
        )
    finally:
        store.close()
