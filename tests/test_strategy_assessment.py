"""Small synthetic accounting examples, not investment evidence."""

from copy import deepcopy
from decimal import Decimal

import pytest

from researchdesk.quant.assessment import assess_result, assess_saved_experiment, assessed_result
from researchdesk.store import Store, content_hash


def result():
    return {
        "status": "completed",
        "spec": {
            "start_session": "2020-01-01",
            "end_session": "2020-01-03",
            "execution": {"fee_bps": "0", "slippage_bps": "0"},
        },
        "validation": {"synthetic_data": True},
        "metrics": {
            "initial_cash": "100",
            "final_equity": "110",
            "net_return": "0.1",
            "max_drawdown": "0",
            "fill_count": 1,
            "fees": "0",
        },
        "equity_curve": [
            {"session": "2020-01-01", "cash": "100", "quantity": 0, "mark": "10", "equity": "100"},
            {"session": "2020-01-02", "cash": "50", "quantity": 5, "mark": "10", "equity": "100"},
            {"session": "2020-01-03", "cash": "50", "quantity": 5, "mark": "12", "equity": "110"},
        ],
        "trades": [{"fee": "0"}],
        "folds": [],
        "baseline": {
            "cash": {"net_return": "0", "final_equity": "100"},
            "buy_hold": {"net_return": "0.18", "final_equity": "118"},
        },
    }


def test_positive_history_is_not_alpha_and_exposure_is_computed():
    report = assess_result(result())
    assert report["status"] == "assessed"
    assert report["profitability"] == "positive"
    assert report["edge_status"] == "unestablished"
    period = report["periods"][0]
    assert Decimal(period["mean_close_exposure"]) == pytest.approx(Decimal(23) / Decimal(66))
    assert period["invested_sessions"] == 2
    assert period["baselines"]["buy_hold"]["outperformed"] is False
    assert Decimal(period["baselines"]["buy_hold"]["difference"]) == Decimal("-0.08")
    assert report["synthetic_data"] is True
    assert any(c["code"] == "search_history" and c["status"] == "missing" for c in report["checks"])


def test_loss_can_beat_falling_benchmark_while_losing_to_cash():
    value = result()
    value["equity_curve"][-1].update(mark="8", equity="90")
    value["metrics"].update(final_equity="90", net_return="-0.1", max_drawdown="0.1")
    value["baseline"]["buy_hold"].update(net_return="-0.2", final_equity="80")
    report = assess_result(value)
    assert report["profitability"] == "negative"
    assert report["headline"] == "This simulation lost money."
    baselines = report["periods"][0]["baselines"]
    assert baselines["buy_hold"]["outperformed"] is True
    assert baselines["cash"]["outperformed"] is False


@pytest.mark.parametrize(
    "key,value",
    [
        ("net_return", "0.3"),
        ("max_drawdown", "0.4"),
        ("fill_count", 9),
        ("fees", "8"),
        ("final_equity", "NaN"),
        ("initial_cash", True),
    ],
)
def test_inconsistent_or_invalid_metrics_fail_explicitly(key, value):
    value_result = result()
    value_result["metrics"][key] = value
    report = assess_result(value_result)
    assert report["status"] == "unavailable"
    assert report["periods"] == []
    assert report["profitability"] == "unknown"


@pytest.mark.parametrize(
    "value",
    [None, [], {}, {"status": "failed"}, {"status": "completed", "spec": [], "validation": None}],
)
def test_malformed_legacy_outputs_do_not_become_passing_assessments(value):
    assert assess_result(value)["status"] == "unavailable"


def test_duplicate_dates_and_missing_baselines_are_distinct():
    value = result()
    value["equity_curve"][1]["session"] = "2020-01-01"
    assert assess_result(value)["status"] == "unavailable"
    value = result()
    del value["baseline"]
    report = assess_result(value)
    assert report["status"] == "assessed"
    assert next(c for c in report["checks"] if c["code"] == "baselines")["status"] == "missing"


def test_offsetting_negative_fill_fees_cannot_pass_accounting():
    value = result()
    value["trades"] = [{"fee": "-1"}, {"fee": "1"}]
    value["metrics"]["fill_count"] = 2
    assert assess_result(value)["status"] == "unavailable"


def walk_result():
    fold = result()
    fold.update(
        train_start="2019-01-01",
        train_end="2019-12-31",
        test_start="2020-01-01",
        test_end="2020-01-03",
    )
    return {
        "status": "completed",
        "spec": {"walk_forward": {}, "execution": {"fee_bps": "0", "slippage_bps": "0"}},
        "validation": {"synthetic_data": True},
        "metrics": {"geometrically_linked_fold_return": "0.1"},
        "folds": [fold],
    }


def test_fold_result_preserves_resets_and_rejects_leaking_or_overlapping_folds():
    value = walk_result()
    report = assess_result(value)
    assert report["status"] == "assessed"
    assert report["basis"] == "reset_walk_forward_folds"
    assert "continuous" in report["limitations"][-1]
    assert "max_drawdown" not in report
    value["folds"][0]["train_end"] = "2020-01-01"
    assert assess_result(value)["status"] == "unavailable"
    value = walk_result()
    value["folds"].append(deepcopy(value["folds"][0]))
    assert assess_result(value)["status"] == "unavailable"


def test_report_and_result_are_sealed_together_without_mutating_input():
    original = result()
    saved = assessed_result(original)
    assert "assessment" not in original
    assert saved["assessment"]["status"] == "assessed"
    assert saved["result_sha256"] == content_hash(
        {k: v for k, v in saved.items() if k != "result_sha256"}
    )
    assert assessed_result(saved) == saved


def test_backfill_is_immutable_bound_to_original_and_idempotent(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'assessment.db'}")
    try:
        case = store.create_case("Synthetic assessment", "Verify reproducible assessments")
        original = store.put_artifact(
            case["id"], None, "experiment", "Synthetic experiment", result()
        )
        first = assess_saved_experiment(store, original["id"])
        second = assess_saved_experiment(store, original["id"])
        assert first["id"] == second["id"]
        assert first["content"]["experiment"]["sha256"] == original["sha256"]
        assert store.get_artifact(original["id"]) == original
        assert first["metadata"]["execution_eligible"] is False
    finally:
        store.close()
