"""Synthetic, hand-calculated engineering fixtures; never investment results."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from researchdesk.quant import (
    BacktestSpec,
    MarketSnapshot,
    QuantError,
    StrategySpec,
    compare_binary_rates,
    evaluate_scenarios,
    run_backtest,
    run_walk_forward,
)


def snapshot(prices, opens=None):
    start = date(2020, 1, 1)
    opens = opens or prices
    return MarketSnapshot.model_validate(
        {
            "symbol": "TEST",
            "source": "Synthetic hand-calculated test fixture",
            "retrieved_at": "2025-01-01T00:00:00Z",
            "price_basis": "raw_no_corporate_actions",
            "synthetic": True,
            "bars": [
                {
                    "session": (start + timedelta(days=i)).isoformat(),
                    "open": str(o),
                    "high": str(max(o, c)),
                    "low": str(min(o, c)),
                    "close": str(c),
                    "volume": 10000,
                }
                for i, (o, c) in enumerate(zip(opens, prices, strict=True))
            ],
        }
    )


def no_cost(cash="1000"):
    return BacktestSpec(initial_cash=cash, fee_bps=0, slippage_bps=0, max_allocation=1)


def test_next_session_open_and_final_fill_costs_are_in_nav():
    data = snapshot([10, 20, 30], [10, 15, 25])
    result = run_backtest(data, StrategySpec(kind="buy_hold", allocation=1), no_cost())
    assert result["trades"][0]["session"] == "2020-01-02"
    assert result["trades"][0]["decision_session"] == "2020-01-01"
    assert result["trades"][0]["price"] == "15"
    assert result["trades"][0]["quantity"] == 66
    assert D(result["equity_curve"][1]["equity"]) == 10 + 66 * 20
    assert D(result["metrics"]["final_equity"]) == 1990
    assert result["validation"]["synthetic_data"] is True


def test_roundtrip_preserves_realized_profit_after_position_is_closed():
    data = snapshot([10, 10, 12, 12])

    def policy(ctx):
        return "1" if len(ctx.bars) == 1 else "0"

    result = run_backtest(data, spec=no_cost(), policy=policy, policy_id="test-policy")
    assert D(result["metrics"]["realized_pnl"]) == 200
    assert D(result["metrics"]["final_equity"]) == 1200
    assert D(result["metrics"]["unrealized_pnl"]) == 0
    assert result["equity_curve"][-1]["quantity"] == 0


def test_last_executable_fill_has_fee_in_final_equity():
    data = snapshot([10, 10, 10])

    def policy(ctx):
        return "0.9" if len(ctx.bars) == 2 else None

    result = run_backtest(
        data,
        spec=BacktestSpec(initial_cash=1000, fee_bps=100, slippage_bps=0),
        policy=policy,
        policy_id="test-policy",
    )
    # 89 shares at $10 with a $8.90 commission; no terminal liquidation.
    assert D(result["metrics"]["final_equity"]) == D("991.1")
    assert D(result["metrics"]["fees"]) == D("8.9")


def test_future_mutation_cannot_change_builtin_earlier_decisions():
    a = snapshot([10, 11, 12, 9, 8, 10, 11, 12])
    b = snapshot([10, 11, 12, 9, 8, 100, 200, 300])
    ra = run_backtest(a, StrategySpec(kind="sma", lookback=2), no_cost())
    rb = run_backtest(b, StrategySpec(kind="sma", lookback=2), no_cost())
    assert ra["decisions"][:5] == rb["decisions"][:5]
    assert ra["equity_curve"][:5] == rb["equity_curve"][:5]


def test_external_policy_receives_only_observed_immutable_prefixes():
    observations = []

    def policy(ctx):
        observations.append(ctx.as_payload())
        with pytest.raises(ValidationError):
            ctx.bars[0].close = D(999)
        return None

    run_backtest(snapshot([10, 11, 12, 13]), spec=no_cost(), policy=policy, policy_id="digest")
    assert [len(row["history"]) for row in observations] == [1, 2, 3]
    assert all("future" not in row for row in observations)
    assert observations[0]["history"][-1]["session"] == "2020-01-01"


@pytest.mark.parametrize("invalid", [True, "NaN", "Infinity", "-0.1", "1.01", {"target": 0.5}])
def test_bad_policy_output_is_a_failed_experiment_not_no_trade(invalid):
    with pytest.raises(QuantError, match="target weight"):
        run_backtest(
            snapshot([10, 11, 12]), spec=no_cost(), policy=lambda _: invalid, policy_id="digest"
        )


def test_policy_exception_propagates_instead_of_fabricating_completed_result():
    def failed(_):
        raise RuntimeError("sandbox unavailable")

    with pytest.raises(RuntimeError, match="sandbox unavailable"):
        run_backtest(snapshot([10, 11, 12]), spec=no_cost(), policy=failed, policy_id="digest")


def test_costs_lower_flat_price_buy_hold_result():
    data = snapshot([10] * 10)
    strategy = StrategySpec(kind="buy_hold", allocation=0.9)
    a = run_backtest(data, strategy, no_cost())
    b = run_backtest(data, strategy, BacktestSpec(initial_cash=1000, fee_bps=20, slippage_bps=50))
    assert D(a["metrics"]["net_return"]) == 0
    assert D(b["metrics"]["net_return"]) < 0


def test_cash_baseline_and_reproducible_result_hash():
    data = snapshot([10, 11, 9, 20])
    a = run_backtest(data, StrategySpec(kind="cash"), no_cost())
    b = run_backtest(data, StrategySpec(kind="cash"), no_cost())
    assert a == b
    assert a["trades"] == []
    assert D(a["metrics"]["net_return"]) == 0
    assert a["metrics"]["sharpe"] is None


def test_reject_invalid_snapshot_values_and_order():
    valid = snapshot([10, 11, 12]).model_dump(mode="json")
    for field, value in [("high", "1"), ("close", "NaN"), ("volume", -1), ("open", "Infinity")]:
        candidate = {**valid, "bars": [dict(row) for row in valid["bars"]]}
        candidate["bars"][1][field] = value
        with pytest.raises(ValidationError):
            MarketSnapshot.model_validate(candidate)
    for dates in (["2020-01-01"] * 3, ["2020-01-03", "2020-01-02", "2020-01-01"]):
        candidate = {
            **valid,
            "bars": [{**row, "session": d} for row, d in zip(valid["bars"], dates, strict=True)],
        }
        with pytest.raises(ValidationError):
            MarketSnapshot.model_validate(candidate)


def test_corporate_actions_and_unchecked_real_data_are_explicitly_blocked():
    data = snapshot([10, 11, 12]).model_dump(mode="json")
    data["synthetic"] = False
    with pytest.raises(QuantError) as error:
        run_backtest(data)
    assert error.value.code == "unchecked_corporate_actions"
    data["corporate_actions_checked"] = True
    data["corporate_actions"] = [{"session": "2020-01-02", "kind": "cash_dividend", "value": ".5"}]
    with pytest.raises(QuantError) as error:
        run_backtest(data)
    assert error.value.code == "unsupported_corporate_action"


@pytest.mark.parametrize("anchored", [False, True])
def test_walkforward_advances_and_compounds_disjoint_fold_returns(anchored):
    data = snapshot([10 + i + (-1) ** i for i in range(31)])
    result = run_walk_forward(
        data,
        {"train_size": 10, "test_size": 5, "lookbacks": [2, 3], "anchored": anchored},
        no_cost(),
    )
    assert len(result["folds"]) == 4
    assert result["validation"]["unused_trailing_sessions"] == 1
    fold_returns = [D(f["metrics"]["net_return"]) for f in result["folds"]]
    product = D(1)
    for i, fold in enumerate(result["folds"]):
        assert fold["train_end"] < fold["test_start"]
        if i:
            assert result["folds"][i - 1]["test_end"] < fold["test_start"]
        if anchored:
            assert fold["train_start"] == "2020-01-01"
        product *= 1 + fold_returns[i]
    assert D(result["metrics"]["geometrically_linked_fold_return"]) == product - 1


def test_external_policy_allocation_cap_does_not_validate_unused_builtin_default():
    result = run_backtest(
        snapshot([10, 11, 12]),
        spec=BacktestSpec(initial_cash=1000, max_allocation=".5"),
        policy=lambda _: ".5",
        policy_id="external-half-allocation",
    )
    assert result["status"] == "completed"
    assert result["decisions"][0]["target_weight"] == "0.5"
    assert result["baseline"]["buy_hold_spec"]["allocation"] == "0.5"


def test_protected_test_outcomes_do_not_change_selected_training_parameter():
    train = [10, 11, 10, 13, 9, 10, 8, 11, 12, 9]
    walk = {"train_size": 10, "test_size": 5, "lookbacks": [2, 3]}
    a = run_walk_forward(snapshot(train + [10, 11, 12, 13, 14]), walk, no_cost())
    b = run_walk_forward(snapshot(train + [100, 50, 1, 90, 500]), walk, no_cost())
    assert a["folds"][0]["candidates"] == b["folds"][0]["candidates"]
    assert a["folds"][0]["selected_lookback"] == b["folds"][0]["selected_lookback"]


def test_debit_spread_hand_calculated_and_explicit_assumptions():
    result = evaluate_scenarios(
        {
            "instrument": "call_debit_spread",
            "entry_price": "2",
            "quantity": 1,
            "strike": "10",
            "short_strike": "15",
            "fees": "1",
            "assumptions": "Synthetic test prices, not observed quotes.",
            "scenarios": [
                {"label": "down", "underlying_at_expiry": 8},
                {"label": "middle", "underlying_at_expiry": 13},
                {"label": "up", "underlying_at_expiry": 20},
            ],
        }
    )
    assert [D(row["pnl"]) for row in result["scenarios"]] == [D(-201), D(99), D(299)]
    assert result["assumption_weighted_pnl"] is None
    assert result["validation"]["execution_eligible"] is False


def test_scenario_probability_and_strike_validation():
    bad = {
        "instrument": "long_call",
        "entry_price": "2",
        "quantity": 1,
        "strike": "10",
        "assumptions": "Synthetic fixture",
        "scenarios": [{"label": "up", "underlying_at_expiry": 20, "probability": ".7"}],
    }
    with pytest.raises(ValidationError):
        evaluate_scenarios(bad)


def test_binary_rate_estimates_and_zero_cell_no_hidden_pseudocount():
    result = compare_binary_rates(20, 100, 40, 100)
    assert result["risk_difference"] == pytest.approx(-0.2)
    assert result["relative_risk"] == pytest.approx(0.5)
    assert result["relative_risk_log_95"][0] < 0.5 < result["relative_risk_log_95"][1]
    zero = compare_binary_rates(0, 10, 0, 10)
    assert zero["relative_risk"] is None
    assert zero["relative_risk_log_95"] is None
    assert zero["risk_difference_newcombe_95"][0] < 0 < zero["risk_difference_newcombe_95"][1]
    with pytest.raises(ValueError):
        compare_binary_rates(11, 10, 1, 10)
