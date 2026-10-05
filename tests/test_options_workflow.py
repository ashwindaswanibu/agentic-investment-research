"""Synthetic acquisition/recovery fixtures; never evidence of market access or edge."""

import copy
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from researchdesk.agents import ToolContext
from researchdesk.config import Settings
from researchdesk.domain import MAX_TOOL_RESULT_CHARS, ExperimentInput, ResearchTools
from researchdesk.errors import DomainError
from researchdesk.options_workflow import (
    OptionsChainInput,
    OptionsExpirationsInput,
    acquire_options,
)
from researchdesk.source_navigation import InspectSourceInput, inspect_source
from researchdesk.store import Store

T = datetime(2026, 10, 5, 15, tzinfo=UTC)


class SyntheticOptions:
    """Explicit changing test feed, preserving old quote times on refresh."""

    calls = 0
    on_fetch = None

    def chain(self, underlying, expiration):
        self.calls += 1
        if self.on_fetch:
            self.on_fetch()
        return {
            "schema_version": "options_chain.v1",
            "provider": "tradier",
            "feed": "sandbox",
            "delay_seconds": 900,
            "execution_eligible": False,
            "synthetic": True,
            "underlying": underlying,
            "expiration": str(expiration),
            "acquisition_started_at": T.isoformat(),
            "received_at": (T + timedelta(seconds=self.calls)).isoformat(),
            "contracts": [
                {
                    "symbol": "TEST261016C00100000",
                    "underlying": underlying,
                    "option_type": "call",
                    "strike": "100",
                    "expiration": str(expiration),
                    "bid": "2",
                    "ask": "2.5",
                    "bid_at": (T - timedelta(minutes=15)).isoformat(),
                    "ask_at": (T - timedelta(minutes=15)).isoformat(),
                    "issues": [],
                }
            ],
            "issues": [],
        }

    def expirations(self, underlying):
        self.calls += 1
        return {
            "schema_version": "options_expirations.v1",
            "provider": "tradier",
            "feed": "sandbox",
            "execution_eligible": False,
            "delay_seconds": 900,
            "synthetic": True,
            "underlying": underlying,
            "dates": ["2026-10-16"],
            "acquisition_started_at": T.isoformat(),
            "received_at": T.isoformat(),
            "issues": [],
        }


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'options.db'}")
    settings = Settings(
        _env_file=None, read_only=False, database_url=f"sqlite:///{tmp_path / 'options.db'}"
    )
    research = ResearchTools(store, settings)
    case = store.create_case("Options integration fixture", "Synthetic boundary tests only")
    provider = SyntheticOptions()
    monkeypatch.setattr("researchdesk.options_workflow.options_provider", lambda _: provider)
    yield store, research, case, provider
    store.close()


def request(**changes):
    return OptionsChainInput(
        **{
            "underlying": "TEST",
            "expiration": date(2026, 10, 16),
            "purpose": "Inspect expiration coverage for the saved research hypothesis.",
            **changes,
        }
    )


def context(store, case, role="researcher", call_id="options-call"):
    task = store.create_task(case["id"], role, "Inspect options research evidence")
    assert store.claim_task("options-worker")["id"] == task["id"]
    return ToolContext(store, case["id"], task["id"], call_id, "options-worker", lambda: False)


def test_agent_tool_retains_chain_and_exact_case_hypothesis_binding(env):
    store, research, case, provider = env
    hypothesis = store.put_artifact(case["id"], None, "note", "Research premise", "Fixture only")
    args = request(source_artifact_ids=[hypothesis["id"]]).model_dump(mode="json")
    ctx = context(store, case)
    result = research.registry().execute("acquire_options_chain", args, ctx)
    assert result["ok"]
    receipt = result["data"]
    artifact = store.get_artifact(receipt["id"])
    assert artifact["kind"] == "options_chain" and artifact["task_id"] == ctx.task_id
    assert artifact["metadata"]["inputs"][0]["sha256"] == hypothesis["sha256"]
    assert artifact["content"]["research_purpose"] == args["purpose"]
    assert artifact["content"]["contracts"][0]["bid_at"] == (T - timedelta(minutes=15)).isoformat()
    assert receipt["summary"]["delay_seconds"] == 900
    assert receipt["summary"]["execution_eligible"] is False
    assert not receipt["content_included"] and provider.calls == 1
    assert len(json.dumps(result)) < MAX_TOOL_RESULT_CHARS
    inspected = inspect_source(
        research,
        ctx,
        InspectSourceInput(artifact_id=artifact["id"], source_path="/contracts/0/bid_at"),
    )
    assert inspected["artifact_sha256"] == artifact["sha256"]


def test_committed_tool_retry_recovers_original_snapshot_without_refetch(env):
    store, research, case, provider = env
    ctx = context(store, case)
    args = request().model_dump(mode="json")
    store.begin_tool_call(
        ctx.task_id, ctx.call_id, "acquire_options_chain", args, worker_id=ctx.worker_id
    )
    registry = research.registry()
    first = registry.execute("acquire_options_chain", args, ctx)
    second = registry.execute("acquire_options_chain", args, ctx)
    assert first["ok"] and second == first
    assert provider.calls == 1
    assert len(store.list_artifacts(case["id"])) == 1


def test_explicit_refresh_creates_new_immutable_observation(env):
    store, research, case, _ = env
    first = acquire_options(research, request(), case_id=case["id"])
    original = copy.deepcopy(first)
    second = acquire_options(research, request(), case_id=case["id"])
    assert first["id"] != second["id"] and first["sha256"] != second["sha256"]
    assert store.get_artifact(first["id"]) == original
    assert first["content"]["contracts"] == second["content"]["contracts"]
    assert first["content"]["received_at"] < second["content"]["received_at"]
    assert first["task_id"] is None  # Operator acquisition is not agent-generated.


def test_foreign_case_or_protected_input_rejected_before_network(env):
    store, research, case, provider = env
    other = store.create_case("Other", "Unrelated investigation")
    foreign = store.put_artifact(other["id"], None, "note", "Other source", {})
    protected = store.put_artifact(case["id"], None, "evaluation_reference", "Protected", {})
    for artifact, code in [(foreign, "ARTIFACT_CASE"), (protected, "PROTECTED_EVALUATION")]:
        with pytest.raises(DomainError) as error:
            acquire_options(
                research, request(source_artifact_ids=[artifact["id"]]), case_id=case["id"]
            )
        assert error.value.code == code
    assert provider.calls == 0


@pytest.mark.parametrize("during_fetch", [False, True])
def test_case_cancellation_blocks_operator_commit(env, during_fetch):
    store, research, case, provider = env
    if during_fetch:
        provider.on_fetch = lambda: store.cancel_case(case["id"])
    else:
        store.cancel_case(case["id"])
    with pytest.raises(DomainError) as error:
        acquire_options(research, request(), case_id=case["id"])
    assert error.value.code == "CANCELLED"
    assert not store.list_artifacts(case["id"])


def test_readonly_acquisition_denied_without_network(env):
    _, research, case, provider = env
    research.settings.read_only = True
    with pytest.raises(DomainError) as error:
        acquire_options(research, request(), case_id=case["id"])
    assert error.value.code == "READ_ONLY" and provider.calls == 0


def test_agent_case_cancelled_during_fetch_cannot_commit(env):
    store, research, case, provider = env
    ctx = context(store, case)
    provider.on_fetch = lambda: store.cancel_case(case["id"])
    result = research.registry().execute("acquire_options_chain", request().model_dump(), ctx)
    assert not result["ok"]
    assert not store.list_artifacts(case["id"])


def test_large_expiration_receipt_keeps_timing_flags_visible(env):
    store, research, case, provider = env
    original = provider.expirations

    def many_dates(symbol):
        return {
            **original(symbol),
            "dates": [(T.date() + timedelta(days=i)).isoformat() for i in range(500)],
        }

    provider.expirations = many_dates
    ctx = context(store, case)
    args = {"underlying": "TEST", "purpose": "研究" * 500}
    result = research.registry().execute("discover_options_expirations", args, ctx)
    assert result["ok"]
    summary = result["data"]["summary"]
    assert summary["execution_eligible"] is False
    assert summary["delay_seconds"] == 900 and summary["dates_truncated"]
    assert summary["date_count"] == 500 and len(summary["dates"]) == 20
    assert len(json.dumps(result)) < MAX_TOOL_RESULT_CHARS


def test_options_cannot_enter_equity_backtest_or_authorize_order(env):
    _, research, case, _ = env
    artifact = acquire_options(research, request(), case_id=case["id"])
    for operation in (
        lambda: research.experiment(None, ExperimentInput(dataset_id=artifact["id"])),
        lambda: research.validate_decision(artifact["id"], "even-an-accepting-review"),
    ):
        with pytest.raises(DomainError) as error:
            operation()
        assert error.value.code == "ARTIFACT_TYPE"


@pytest.mark.parametrize("role", ["coordinator", "researcher", "coder", "reviewer"])
def test_expiration_discovery_available_to_all_research_roles(env, role):
    store, research, case, _ = env
    ctx = context(store, case, role)
    args = OptionsExpirationsInput(underlying="TEST", purpose="Inspect horizon availability.")
    result = research.registry().execute("discover_options_expirations", args.model_dump(), ctx)
    assert result["ok"] and result["data"]["kind"] == "options_expirations"
    assert result["data"]["summary"]["dates"] == ["2026-10-16"]


def test_cli_uses_same_acquisition_and_records_operator_attribution(env, monkeypatch, capsys):
    from researchdesk.cli import main

    store, research, case, provider = env
    monkeypatch.setattr("researchdesk.cli.Settings", lambda: research.settings)
    monkeypatch.setattr(
        "sys.argv",
        [
            "researchdesk",
            "options-chain",
            "--case-id",
            case["id"],
            "--underlying",
            "TEST",
            "--expiration",
            "2026-10-16",
            "--purpose",
            "Verify the delayed research acquisition path.",
        ],
    )
    main()
    output = json.loads(capsys.readouterr().out)
    assert output["summary"]["execution_eligible"] is False
    assert store.get_artifact(output["id"])["task_id"] is None
    assert provider.calls == 1
