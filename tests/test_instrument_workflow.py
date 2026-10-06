"""Synthetic conditional comparisons; no forecast, fill or market-edge evidence."""

import copy
from datetime import UTC, datetime, timedelta, timezone

import pytest

from researchdesk.agents import ToolContext
from researchdesk.config import Settings
from researchdesk.domain import ExperimentInput, ResearchTools
from researchdesk.errors import DomainError
from researchdesk.instrument_workflow import InstrumentComparisonInput, save_instrument_comparison
from researchdesk.store import Store


@pytest.fixture
def env(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'comparison.db'}")
    settings = Settings(_env_file=None, read_only=False)
    research = ResearchTools(store, settings)
    case = store.create_case("Synthetic comparison", "Engineering arithmetic and provenance only")
    received = datetime.now(UTC) - timedelta(seconds=2)
    expiry = (received + timedelta(days=30)).date()
    symbol = f"TEST{expiry:%y%m%d}C00100000"
    market_time = (received - timedelta(minutes=15)).isoformat()
    source = store.put_artifact(
        case["id"],
        None,
        "note",
        "Synthetic rationale",
        {
            "synthetic": True,
            "description": "Invented outcomes; not calibrated market probabilities.",
        },
    )
    hypothesis = store.put_artifact(
        case["id"],
        None,
        "hypothesis",
        "Synthetic upside thesis",
        {
            "prediction": "TEST reaches one of the explicitly invented expiration prices.",
            "status": "proposed",
        },
    )
    chain_content = {
        "schema_version": "options_chain.v1",
        "underlying": "TEST",
        "expiration": str(expiry),
        "provider": "tradier",
        "feed": "sandbox",
        "delay_seconds": 900,
        "synthetic": True,
        "received_at": received.isoformat(),
        "acquisition_started_at": received.isoformat(),
        "contracts": [
            {
                "symbol": symbol,
                "underlying": "TEST",
                "root_symbol": "TEST",
                "option_type": "call",
                "strike": "100",
                "expiration": str(expiry),
                "contract_size": 100,
                "contract_status": "unverified",
                "premium_multiplier": None,
                "deliverable": None,
                "bid": "1.9",
                "ask": "2",
                "bid_at": market_time,
                "ask_at": market_time,
                "bid_size": 10,
                "ask_size": 10,
                "issues": ["contract_deliverable_unverified"],
            }
        ],
        "issues": [],
    }
    chain = store.put_artifact(case["id"], None, "options_chain", "Synthetic chain", chain_content)
    values = {
        "title": "Conditional thesis expressions",
        "purpose": "Compare explicit instruments with a cash alternative.",
        "hypothesis_id": hypothesis["id"],
        "chain_artifact_id": chain["id"],
        "information_cutoff": datetime.now(UTC).isoformat(),
        "scenario_horizon": str(expiry),
        "scenario_rationale": "Invented engineering cases test payoff "
        "and attribution; not estimated odds.",
        "scenario_source_ids": [source["id"]],
        "assumptions": {
            "currency": "USD",
            "capital": "1000",
            "option_fee_per_contract": "1",
            "stock_fee_flat": "1",
            "cash_return_over_horizon": "0",
            "adverse_price_bps": "500",
            "standard_contract_assumption": "Assume standard USD contracts, multiplier 100 "
            "and 100 shares; unverified.",
            "standard_contract_mode": "hypothetical_100_share_usd",
            "scenarios": [
                {"label": "Down", "underlying_at_expiry": "80", "probability": "0.5"},
                {"label": "Up", "underlying_at_expiry": "120", "probability": "0.5"},
            ],
        },
        "candidates": [
            {
                "candidate_id": "call",
                "label": "Long 100 call",
                "instrument": "long_call",
                "long_symbol": symbol,
                "rationale": "Express the upside thesis with a defined expiration premium.",
            }
        ],
        "stock_reference": {
            "kind": "assumed_price",
            "price": "100",
            "rationale": "An explicitly assumed engineering stock price, not observed data.",
        },
    }
    yield store, research, case, source, hypothesis, chain, values
    store.close()


def ctx(store, case, call_id="comparison-call"):
    task = store.create_task(case["id"], "researcher", "Compare conditional thesis expressions")
    assert store.claim_task("comparison-worker")["id"] == task["id"]
    return ToolContext(store, case["id"], task["id"], call_id, "comparison-worker", lambda: False)


def test_real_tool_binds_exact_sources_and_preserves_delayed_observations(env):
    store, research, case, source, hypothesis, chain, values = env
    context = ctx(store, case)
    result = research.registry().execute("compare_instruments", values, context)
    assert result["ok"], result
    saved = store.get_artifact(result["data"]["id"])
    report = saved["content"]
    assert saved["kind"] == "instrument_comparison" and saved["task_id"] == context.task_id
    assert report["source_bindings"]["chain"]["sha256"] == chain["sha256"]
    assert report["source_bindings"]["hypothesis"]["sha256"] == hypothesis["sha256"]
    assert report["source_bindings"]["scenario_sources"][0]["sha256"] == source["sha256"]
    assert report["timing"]["chain_received_at"] == chain["content"]["received_at"]
    assert report["timing"]["stock_reference"]["observed_at"] is None
    assert report["synthetic"] and report["execution_eligible"] is False
    assert result["data"]["summary"]["candidate_count"] == 3
    assert report["candidates"][2]["base"]["quantity"] == 4


def test_committed_retry_recovers_report_without_recalculation(env, monkeypatch):
    store, research, case, _, _, _, values = env
    context = ctx(store, case)
    store.begin_tool_call(
        context.task_id, context.call_id, "compare_instruments", values, worker_id=context.worker_id
    )
    registry = research.registry()
    first = registry.execute("compare_instruments", values, context)
    assert first["ok"], first

    def forbidden(*args, **kwargs):
        raise AssertionError("Committed report must recover without recomputation")

    monkeypatch.setattr("researchdesk.instrument_workflow.compare_instruments", forbidden)
    assert registry.execute("compare_instruments", values, context) == first


def test_revision_is_new_report_without_replacing_original(env):
    store, research, case, _, _, _, values = env
    first = save_instrument_comparison(
        research, InstrumentComparisonInput(**values), case_id=case["id"]
    )
    original = copy.deepcopy(first)
    values["assumptions"]["adverse_price_bps"] = "1000"
    second = save_instrument_comparison(
        research, InstrumentComparisonInput(**values), case_id=case["id"]
    )
    assert first["id"] != second["id"] and first["sha256"] != second["sha256"]
    assert store.get_artifact(first["id"]) == original
    assert first["task_id"] is None


@pytest.mark.parametrize(
    "field,change,code",
    [
        (
            "scenario_horizon",
            lambda v: str(
                datetime.fromisoformat(v["information_cutoff"]).date() + timedelta(days=31)
            ),
            "COMPARISON_HORIZON",
        ),
        (
            "information_cutoff",
            lambda v: (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "COMPARISON_TIME",
        ),
        (
            "information_cutoff",
            lambda v: (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "INPUT_AFTER_CUTOFF",
        ),
    ],
)
def test_cutoff_and_horizon_rejected(env, field, change, code):
    _, research, case, _, _, _, values = env
    values[field] = change(values)
    with pytest.raises(DomainError) as error:
        save_instrument_comparison(
            research, InstrumentComparisonInput(**values), case_id=case["id"]
        )
    assert error.value.code == code


def test_source_scope_and_protected_data_rejected(env):
    store, research, case, _, _, _, values = env
    other = store.create_case("Other", "Foreign source")
    foreign = store.put_artifact(other["id"], None, "note", "Other source", {})
    protected = store.put_artifact(case["id"], None, "evaluation_reference", "Protected", {})
    for source, code in [(foreign, "ARTIFACT_CASE"), (protected, "PROTECTED_EVALUATION")]:
        values["scenario_source_ids"] = [source["id"]]
        with pytest.raises(DomainError) as error:
            save_instrument_comparison(
                research, InstrumentComparisonInput(**values), case_id=case["id"]
            )
        assert error.value.code == code


def test_readonly_and_cancelled_case_cannot_save(env):
    store, research, case, _, _, _, values = env
    args = InstrumentComparisonInput(**values)
    research.settings.read_only = True
    with pytest.raises(DomainError, match="Read-only"):
        save_instrument_comparison(research, args, case_id=case["id"])
    research.settings.read_only = False
    store.cancel_case(case["id"])
    with pytest.raises(DomainError) as error:
        save_instrument_comparison(research, args, case_id=case["id"])
    assert error.value.code == "CANCELLED"


def test_cancellation_during_calculation_fences_commit(env, monkeypatch):
    import researchdesk.instrument_workflow as module

    store, research, case, _, _, _, values = env
    context = ctx(store, case)
    calculate = module.compare_instruments

    def cancelled(*args, **kwargs):
        result = calculate(*args, **kwargs)
        store.cancel_case(case["id"])
        return result

    monkeypatch.setattr(module, "compare_instruments", cancelled)
    result = research.registry().execute("compare_instruments", values, context)
    assert not result["ok"] and result["error"]["code"] == "CANCELLED"
    assert not [a for a in store.list_artifacts(case["id"]) if a["kind"] == "instrument_comparison"]


def test_comparison_report_cannot_be_used_as_equity_experiment(env):
    store, research, case, _, _, _, values = env
    saved = save_instrument_comparison(
        research, InstrumentComparisonInput(**values), case_id=case["id"]
    )
    with pytest.raises(DomainError) as error:
        research.experiment(ctx(store, case), ExperimentInput(dataset_id=saved["id"]))
    assert error.value.code == "ARTIFACT_TYPE"
    with pytest.raises(DomainError) as approval:
        research.validate_decision(saved["id"], "unused-review", case_id=case["id"])
    assert approval.value.code == "ARTIFACT_TYPE"


@pytest.mark.parametrize("basis", ["raw_no_corporate_actions", "split_adjusted"])
def test_dataset_stock_reference_uses_exact_saved_close_and_explicit_share_basis(env, basis):
    store, research, case, _, _, _, values = env
    today = datetime.now(UTC).date()
    sessions = [today - timedelta(days=offset) for offset in (3, 2, 1)]
    dataset = store.put_artifact(
        case["id"],
        None,
        "dataset",
        "Synthetic raw stock closes",
        {
            "symbol": "TEST",
            "source": "Synthetic daily closes",
            "synthetic": True,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "price_basis": basis,
            "corporate_actions_checked": False,
            "bars": [
                {
                    "session": str(day),
                    "open": "100",
                    "high": "103",
                    "low": "99",
                    "close": str(101 + i),
                    "volume": 10,
                }
                for i, day in enumerate(sessions)
            ],
        },
    )
    values["information_cutoff"] = datetime.now(UTC).isoformat()
    values["stock_reference"] = {
        "kind": "dataset_close",
        "dataset_id": dataset["id"],
        "session": str(sessions[-1]),
        "rationale": "Use the prior raw close while exposing its different observation time.",
        "share_basis_assumption": "Assume this saved close is comparable "
        "to the scenario share basis.",
    }
    saved = save_instrument_comparison(
        research, InstrumentComparisonInput(**values), case_id=case["id"]
    )
    reference = saved["content"]["timing"]["stock_reference"]
    assert reference["price"] == "103" and reference["source_path"] == "/bars/2/close"
    assert reference["observed_at"] is None and reference["observation_session"] == str(
        sessions[-1]
    )
    assert reference["corporate_actions_checked"] is False
    assert reference["source_price_basis"] == basis
    assert reference["assumption"] is (basis == "split_adjusted")
    assert (
        reference["share_basis_assumption"] == values["stock_reference"]["share_basis_assumption"]
    )
    assert saved["content"]["source_bindings"]["stock"]["sha256"] == dataset["sha256"]
    values["stock_reference"]["session"] = str(today)
    # A caller's positive offset must not turn today's UTC session into yesterday.
    values["information_cutoff"] = (
        datetime.now(UTC).astimezone(timezone(timedelta(hours=14))).isoformat()
    )
    with pytest.raises(DomainError) as error:
        save_instrument_comparison(
            research, InstrumentComparisonInput(**values), case_id=case["id"]
        )
    assert error.value.code == "STOCK_REFERENCE_TIME"
