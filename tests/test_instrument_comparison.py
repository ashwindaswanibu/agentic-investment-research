"""Independent expiry arithmetic and rejection tests; all quotes are synthetic."""

import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext

import pytest
from pydantic import ValidationError

from researchdesk.quant.instrument_comparison import (
    ComparisonAssumptions,
    InstrumentCandidate,
    compare_instruments,
)

RECEIPT = datetime(2026, 10, 5, 16, tzinfo=UTC)
MARKET = RECEIPT - timedelta(minutes=15)


def contract(right="call", strike=100, bid="2.9", ask="3"):
    symbol = f"AAPL261016{'C' if right == 'call' else 'P'}{strike * 1000:08d}"
    return {
        "symbol": symbol,
        "underlying": "AAPL",
        "root_symbol": "AAPL",
        "option_type": right,
        "strike": str(strike),
        "expiration": "2026-10-16",
        "contract_size": 100,
        "contract_status": "unverified",
        "premium_multiplier": None,
        "deliverable": None,
        "exercise_style": None,
        "settlement_type": None,
        "bid": bid,
        "ask": ask,
        "bid_at": MARKET.isoformat(),
        "ask_at": MARKET.isoformat(),
        "bid_size": 10,
        "ask_size": 10,
        "size_unit": "provider_reported_unverified",
        "issues": ["contract_deliverable_unverified"],
    }


def chain(*contracts):
    return {
        "schema_version": "options_chain.v1",
        "provider": "tradier",
        "feed": "sandbox",
        "delay_seconds": 900,
        "execution_eligible": False,
        "underlying": "AAPL",
        "expiration": "2026-10-16",
        "received_at": RECEIPT.isoformat(),
        "contracts": list(contracts or [contract()]),
    }


def assumptions(**updates):
    return {
        "currency": "USD",
        "capital": "1000",
        "option_fee_per_contract": "1",
        "stock_fee_flat": "2",
        "cash_return_over_horizon": "0.01",
        "adverse_price_bps": "100",
        "standard_contract_mode": "hypothetical_100_share_usd",
        "standard_contract_assumption": "Hypothetically use 100 premium units and 100 shares; "
        "the provider has not verified the deliverable or lifecycle terms.",
        "scenarios": [
            {"label": "down", "underlying_at_expiry": "90", "probability": "0.25"},
            {"label": "flat", "underlying_at_expiry": "100", "probability": "0.5"},
            {"label": "up", "underlying_at_expiry": "110", "probability": "0.25"},
        ],
        **updates,
    }


def candidate(instrument="long_call", long=None, short=None, candidate_id="candidate", **updates):
    return {
        "candidate_id": candidate_id,
        "label": "Nominated expression",
        "instrument": instrument,
        "long_symbol": long or contract()["symbol"],
        "short_symbol": short,
        "rationale": "Explicit investigator-nominated scenario expression.",
        **updates,
    }


def stock(**updates):
    return {
        "underlying": "AAPL",
        "price": "95",
        "observed_at": MARKET.isoformat(),
        "received_at": RECEIPT.isoformat(),
        "observation_session": None,
        "source": "Retained synthetic test observation",
        "assumption": False,
        "rationale": "A separate stock observation used for comparison; "
        "not an aligned options fill.",
        **updates,
    }


def issues(row):
    return {issue["code"] for issue in row["issues"]}


def test_cash_stock_call_independent_arithmetic_including_fees_residual_cash_and_yield():
    report = compare_instruments(assumptions(), [candidate()], chain(), stock())
    assert report["currency"] == "USD" and report["execution_eligible"] is False
    assert report["probability_basis"] == "supplied_scenario_assumptions"
    cash, shares, call = report["candidates"]
    assert [row["candidate_id"] for row in report["candidates"]] == ["cash", "stock", "candidate"]
    assert cash["base"]["entry_cost"] == "0"
    assert D(cash["base"]["remaining_cash"]) == 1000
    assert D(cash["base"]["assumption_weighted_pnl"]) == 10
    # Ten $95 shares plus $2 entry fee leaves $48 cash earning $0.48.
    assert shares["base"]["quantity"] == 10
    assert D(shares["base"]["entry_cost"]) == 952
    assert D(shares["base"]["remaining_cash"]) == 48
    assert [D(row["pnl"]) for row in shares["base"]["scenarios"]] == [
        D("-51.52"),
        D("48.48"),
        D("148.48"),
    ]
    assert D(shares["base"]["assumption_weighted_pnl"]) == D("48.48")
    assert D(shares["base"]["excess_vs_cash"]) == D("38.48")
    assert D(shares["base"]["expiry_loss_bound"]) == D("951.52")
    # Three calls cost 3*100*$3 + 3*$1 = $903. $97 cash becomes $97.97.
    assert call["base"]["quantity"] == 3
    assert D(call["base"]["entry_cost"]) == 903
    assert D(call["base"]["fees"]) == 3
    assert D(call["base"]["remaining_cash"]) == 97
    assert [D(row["pnl"]) for row in call["base"]["scenarios"]] == [
        D("-902.03"),
        D("-902.03"),
        D("2097.97"),
    ]
    assert D(call["base"]["assumption_weighted_pnl"]) == D("-152.03")
    assert D(call["base"]["excess_vs_cash"]) == D("-162.03")
    assert D(call["base"]["position_expiry_loss_bound"]) == 903
    assert D(call["base"]["expiry_loss_bound"]) == D("902.03")
    assert D(call["base"]["scenarios"][2]["return_on_capital"]) == D("2.09797")
    assert D(call["base"]["scenarios"][2]["terminal_capital"]) == D("3097.97")
    assert call["legs"][0]["selected_price"] == "3"
    assert call["legs"][0]["market_at"] == MARKET.isoformat()
    assert call["legs"][0]["contract_terms_status"] == "assumed_not_verified"
    assert "contract_terms_assumed" in issues(call)
    assert "recommendation" not in report and "winner" not in report
    json.dumps(report, allow_nan=False)


def test_put_and_debit_spreads_have_correct_sides_strikes_contract_fees_and_joint_payoffs():
    c100, c110 = contract(), contract(strike=110, bid="1", ask="1.1")
    p100, p90 = contract("put", bid="1.9", ask="2"), contract("put", 90, bid="0.5", ask="0.6")
    nominations = [
        candidate("long_put", p100["symbol"], candidate_id="put"),
        candidate("call_debit_spread", c100["symbol"], c110["symbol"], "callspread"),
        candidate("put_debit_spread", p100["symbol"], p90["symbol"], "putspread"),
    ]
    report = compare_instruments(assumptions(), nominations, chain(c100, c110, p100, p90))
    put, callspread, putspread = report["candidates"][2:]
    for case in ("base", "adverse"):
        assert put[case]["quantity_unit"] == "contracts"
        assert callspread[case]["quantity_unit"] == "spreads"
        assert putspread[case]["quantity_unit"] == "spreads"
        # Quantity counts two-leg spreads; fees still count each individual contract.
        for spread in (callspread, putspread):
            assert D(spread[case]["fees"]) == spread[case]["quantity"] * 2
    assert put["base"]["quantity"] == 4
    assert D(put["base"]["entry_cost"]) == 804
    assert [D(row["pnl"]) for row in put["base"]["scenarios"]] == [
        D("3197.96"),
        D("-802.04"),
        D("-802.04"),
    ]
    assert D(put["base"]["assumption_weighted_pnl"]) == D("197.96")
    # Four call verticals: ($3 ask - $1 bid)*100 + $2 fees each = $808.
    assert callspread["base"]["quantity"] == 4
    assert D(callspread["base"]["fees"]) == 8
    assert D(callspread["base"]["entry_cost"]) == 808
    assert [D(row["pnl"]) for row in callspread["base"]["scenarios"]] == [
        D("-806.08"),
        D("-806.08"),
        D("3193.92"),
    ]
    assert D(callspread["base"]["assumption_weighted_pnl"]) == D("193.92")
    assert [leg["side"] for leg in callspread["legs"]] == ["buy", "sell"]
    assert callspread["legs"][1]["selected_price"] == "1"
    # Six put verticals: ($2 ask - $0.50 bid)*100 + $2 fees each = $912.
    assert putspread["base"]["quantity"] == 6
    assert D(putspread["base"]["entry_cost"]) == 912
    assert [D(row["pnl"]) for row in putspread["base"]["scenarios"]] == [
        D("5088.88"),
        D("-911.12"),
        D("-911.12"),
    ]
    assert D(putspread["base"]["assumption_weighted_pnl"]) == D("588.88")


def test_unweighted_grid_never_invents_an_average_probability_or_expected_return():
    spec = assumptions(scenarios=[{"label": "up", "underlying_at_expiry": "110"}])
    report = compare_instruments(spec, [candidate()], chain(), stock())
    assert report["probability_basis"] == "unweighted_scenarios"
    for row in report["candidates"]:
        assert row["base"]["assumption_weighted_pnl"] is None
        assert row["base"]["excess_vs_cash"] is None
        assert row["base"]["scenarios"][0]["probability"] is None
        assert row["base"]["scenarios"][0]["excess_vs_cash"] is not None
    call = report["candidates"][2]["base"]
    assert D(call["scenario_worst_pnl"]) == D("2097.97")  # Grid contains only an upside case.
    assert D(call["expiry_loss_bound"]) == D("902.03")  # All-price loss bound remains meaningful.


def test_adverse_prices_keep_quantity_fee_schedule_and_cash_yield():
    call = compare_instruments(assumptions(), [candidate()], chain())["candidates"][2]
    assert call["base"]["quantity"] == call["adverse"]["quantity"] == 3
    assert D(call["adverse"]["entry_cost"]) == 912  # Ask $3.03 * 300 + $3 fees.
    assert D(call["adverse"]["remaining_cash"]) == 88
    assert D(call["adverse"]["scenarios"][2]["pnl"]) == D("2088.88")
    c110 = contract(strike=110, bid="1", ask="1.1")
    spread = compare_instruments(
        assumptions(),
        [candidate("call_debit_spread", short=c110["symbol"])],
        chain(contract(), c110),
    )["candidates"][2]
    assert spread["adverse"]["quantity"] == 4
    # Buy ask rises to 3.03; short bid falls to .99; four verticals cost $824 with fees.
    assert D(spread["adverse"]["entry_cost"]) == 824


def test_unaffordable_stress_is_not_resized_and_does_not_create_borrowed_cash():
    spec = assumptions(option_fee_per_contract="0", stock_fee_flat="0", adverse_price_bps="1000")
    report = compare_instruments(
        spec, [candidate()], chain(contract(bid="4.9", ask="5")), stock(price="100")
    )
    for row, qty in [(report["candidates"][1], 10), (report["candidates"][2], 2)]:
        assert row["base"]["quantity"] == row["adverse"]["quantity"] == qty
        assert row["adverse"]["status"] == "not_affordable"
        assert D(row["adverse"]["required_capital"]) == 1100
        assert row["adverse"]["remaining_cash"] is None
        assert row["adverse"]["scenarios"] == []
        assert row["adverse"]["expiry_loss_bound"] is None


def test_entry_fees_can_make_one_otherwise_affordable_contract_unavailable():
    row = compare_instruments(assumptions(capital="300"), [candidate()], chain())["candidates"][2]
    assert row["status"] == "unavailable" and row["base"] is None
    assert "no_affordable_unit" in issues(row)
    assert "301" in row["issues"][-1]["message"]


@pytest.mark.parametrize(
    "change,code",
    [
        ({"bid": None}, "quote_invalid"),
        ({"ask": "0"}, "quote_invalid"),
        ({"bid": "4"}, "quote_invalid"),
        ({"bid": "-1"}, "quote_invalid"),
        ({"bid_at": None}, "quote_time_invalid"),
        ({"ask_at": (RECEIPT + timedelta(seconds=1)).isoformat()}, "quote_time_invalid"),
        ({"bid_at": "2026-10-05T15:45:00"}, "quote_time_invalid"),
        ({"expiration": "2026-11-20"}, "contract_identity_invalid"),
        ({"option_type": "put"}, "contract_identity_invalid"),
        ({"strike": "101"}, "contract_identity_invalid"),
        ({"underlying": "MSFT"}, "contract_identity_invalid"),
        ({"contract_size": None}, "contract_terms_unsupported"),
        ({"contract_size": 10}, "contract_terms_unsupported"),
        ({"contract_size": True}, "contract_terms_unsupported"),
        ({"root_symbol": "AAPL1"}, "contract_terms_unsupported"),
        ({"contract_status": "unsupported"}, "contract_terms_unsupported"),
        ({"premium_multiplier": "10"}, "contract_terms_conflict"),
        ({"deliverable": {"shares": 10}}, "contract_terms_conflict"),
        ({"currency": "EUR"}, "contract_terms_conflict"),
        ({"exercise_style": "bermudan"}, "contract_terms_conflict"),
        ({"settlement_type": "cash"}, "contract_terms_conflict"),
    ],
)
def test_unavailable_candidates_are_retained_with_reasons_and_cash_survives(change, code):
    result = compare_instruments(assumptions(), [candidate()], chain({**contract(), **change}))
    assert result["candidates"][0]["status"] == "available"
    row = result["candidates"][2]
    assert row["candidate_id"] == "candidate" and row["rationale"] == candidate()["rationale"]
    assert row["status"] == "unavailable" and row["base"] is None
    assert code in issues(row)


def test_adjusted_occ_symbol_cannot_hide_behind_standard_metadata():
    adjusted = {**contract(), "symbol": "AAPL1261016C00100000", "root_symbol": "AAPL1"}
    row = compare_instruments(assumptions(), [candidate(long=adjusted["symbol"])], chain(adjusted))[
        "candidates"
    ][2]
    assert "contract_terms_unsupported" in issues(row)


def test_explicit_compatible_terms_do_not_remove_assumption_and_lifecycle_limits():
    recorded = {
        **contract(),
        "premium_multiplier": 100,
        "currency": "USD",
        "deliverable": {"underlying": "AAPL", "shares": 100, "cash": "0", "currency": "USD"},
        "exercise_style": "american",
        "settlement_type": "physical",
    }
    result = compare_instruments(assumptions(), [candidate()], chain(recorded))
    assert result["candidates"][2]["status"] == "available"
    assert result["execution_eligible"] is False
    assert "contract_terms_assumed" in issues(result["candidates"][2])


def test_wrong_option_side_missing_contract_and_wrong_spread_order_are_retained():
    call, put = contract(), contract("put", bid="1.9", ask="2")
    high = contract(strike=110, bid="1", ask="1.1")
    candidates = [
        candidate("long_call", put["symbol"], candidate_id="wrongside"),
        candidate(long="AAPL261016C00120000", candidate_id="missing"),
        candidate("call_debit_spread", high["symbol"], call["symbol"], "wrongorder"),
    ]
    rows = compare_instruments(assumptions(), candidates, chain(call, put, high))["candidates"][2:]
    assert "option_type_mismatch" in issues(rows[0])
    assert "contract_missing" in issues(rows[1])
    assert "nonpositive_debit" in issues(rows[2])


def test_adverse_debit_beyond_spread_width_is_explicitly_unsupported_not_silent_payoff():
    long, short = contract(bid="1.9", ask="2"), contract(strike=101, bid="1", ask="1.1")
    row = compare_instruments(
        assumptions(capital="190", option_fee_per_contract="0"),
        [candidate("call_debit_spread", long["symbol"], short["symbol"])],
        chain(long, short),
    )["candidates"][2]
    assert row["base"]["status"] == "computed"
    assert row["adverse"]["status"] == "unavailable"
    assert "debit_exceeds_width" in issues(row["adverse"])


def test_stock_reference_missing_or_invalid_is_visible_not_an_invented_spot():
    report = compare_instruments(assumptions(), [candidate()], chain())
    assert report["candidates"][1]["status"] == "unavailable"
    assert "stock_reference_missing" in issues(report["candidates"][1])
    assert report["candidates"][2]["status"] == "available"
    for reference, reason in [
        (stock(price="0"), "stock_price_invalid"),
        (stock(underlying="MSFT"), "stock_reference_invalid"),
        (stock(source=""), "stock_reference_invalid"),
        (stock(observed_at="yesterday"), "stock_time_invalid"),
    ]:
        row = compare_instruments(assumptions(), [candidate()], chain(), reference)["candidates"][1]
        assert reason in issues(row)


def test_explicit_assumed_stock_and_newer_stock_observation_are_not_claimed_aligned():
    reference = stock(assumption=True, observed_at=None, received_at=None)
    row = compare_instruments(assumptions(), [candidate()], chain(), reference)["candidates"][1]
    assert row["status"] == "available" and "stock_price_assumed" in issues(row)
    assert "stock_price_alignment_unverified" in issues(row)
    later = (RECEIPT + timedelta(minutes=10)).isoformat()
    row = compare_instruments(
        assumptions(), [candidate()], chain(), stock(observed_at=later, received_at=later)
    )["candidates"][1]
    assert row["status"] == "available"  # Report cutoff validation belongs to the workflow.
    assert row["legs"][0]["observed_at"] == later


def test_precision_is_deterministic_under_low_ambient_decimal_context():
    high = chain(contract(bid="3.123456789011", ask="3.123456789012"))
    spec = assumptions(capital="1234.123456789012", cash_return_over_horizon="0.123456789012")
    expected = compare_instruments(spec, [candidate()], high)
    with localcontext() as ctx:
        ctx.prec = 8
        actual = compare_instruments(spec, [candidate()], high)
    assert actual == expected
    # JSON retains plain fixed decimal values; no coercion to float for money.
    assert "E" not in actual["candidates"][2]["base"]["entry_cost"]


def test_inputs_remain_unchanged_and_equal_inputs_reproduce_equal_reports():
    args = (assumptions(), [candidate()], chain(), stock())
    before = copy.deepcopy(args)
    result = compare_instruments(*args)
    assert args == before
    assert compare_instruments(*args) == result


@pytest.mark.parametrize(
    "change",
    [
        {"capital": True},
        {"capital": "NaN"},
        {"capital": "1e999999999999999999"},
        {"capital": "1e-100"},
        {"capital": "10000001"},
        {"currency": "EUR"},
        {"standard_contract_mode": "assume_anything"},
        {"standard_contract_assumption": ""},
        {"option_fee_per_contract": "-1"},
        {"adverse_price_bps": "10001"},
        {"cash_return_over_horizon": "-1.01"},
        {"scenarios": [{"label": "x", "underlying_at_expiry": "1e999"}]},
        {"scenarios": [{"label": "x", "underlying_at_expiry": "100", "probability": ".5"}]},
        {
            "scenarios": [
                {"label": "x", "underlying_at_expiry": "100", "probability": ".5"},
                {"label": "y", "underlying_at_expiry": "200"},
            ]
        },
        {
            "scenarios": [
                {"label": "same", "underlying_at_expiry": "100"},
                {"label": "same", "underlying_at_expiry": "200"},
            ]
        },
        {
            "scenarios": [
                {"label": str(index), "underlying_at_expiry": "100"} for index in range(21)
            ]
        },
    ],
)
def test_invalid_unbounded_or_incoherent_assumptions_rejected(change):
    with pytest.raises((ValueError, ValidationError)):
        compare_instruments(assumptions(**change), [candidate()], chain())


def test_required_contract_mode_cannot_be_replaced_by_vague_rationale():
    spec = assumptions()
    del spec["standard_contract_mode"]
    with pytest.raises(ValidationError):
        ComparisonAssumptions.model_validate(spec)


def test_candidate_ids_and_leg_schema_are_explicit_not_auto_nominated():
    with pytest.raises(ValueError, match="unique"):
        compare_instruments(assumptions(), [candidate(), candidate()], chain())
    for nominated in [
        candidate(candidate_id="cash"),
        candidate(candidate_id="stock"),
        candidate("call_debit_spread"),
        candidate(short="AAPL261016C00110000"),
        candidate(instrument="stock"),
    ]:
        with pytest.raises(ValidationError):
            InstrumentCandidate.model_validate(nominated)


def test_one_capital_budget_is_reused_independently_not_allocated_across_candidates():
    nominees = [candidate(candidate_id="first"), candidate(candidate_id="second")]
    result = compare_instruments(assumptions(), nominees, chain())
    first, second = result["candidates"][2:]
    assert first["base"] == second["base"]
    assert first["base"]["quantity"] == 3  # Not three split across two strategy books.
    assert result["capital"] == "1000"


def test_negative_cash_return_is_applied_to_cash_and_unspent_balance_consistently():
    report = compare_instruments(
        assumptions(cash_return_over_horizon="-0.01"), [candidate()], chain()
    )
    assert D(report["candidates"][0]["base"]["scenario_worst_pnl"]) == -10
    assert D(report["candidates"][0]["base"]["expiry_loss_bound"]) == 10
    assert D(report["candidates"][2]["base"]["expiry_loss_bound"]) == D("903.97")


def test_computational_quantity_bound_does_not_silently_resize_alternative():
    row = compare_instruments(
        assumptions(capital="10000000", option_fee_per_contract="0"),
        [candidate()],
        chain(contract(bid="0.0000001", ask="0.0000001")),
    )["candidates"][2]
    assert row["status"] == "unavailable" and "quantity_limit" in issues(row)


def test_requested_option_quantity_preserves_cash_and_uses_same_quantity_in_stress():
    row = compare_instruments(
        assumptions(adverse_price_bps="1000"), [candidate(quantity=1)], chain()
    )["candidates"][2]
    assert row["sizing_basis"] == "requested_quantity" and row["requested_quantity"] == 1
    assert row["base"]["quantity"] == row["adverse"]["quantity"] == 1
    # One call: $300 premium + $1 fee; $699 cash grows to $705.99.
    assert D(row["base"]["entry_cost"]) == 301
    assert D(row["base"]["remaining_cash"]) == 699
    assert D(row["base"]["scenarios"][2]["pnl"]) == D("705.99")
    # Stress ask becomes $3.30, same one contract + $1 fee, no resizing.
    assert row["adverse"]["status"] == "computed"
    assert D(row["adverse"]["entry_cost"]) == 331
    assert D(row["adverse"]["remaining_cash"]) == 669
    assert D(row["adverse"]["scenarios"][2]["pnl"]) == D("675.69")


def test_explicit_quantity_above_budget_is_unavailable_not_capped_to_maximum():
    row = compare_instruments(assumptions(), [candidate(quantity=4)], chain())["candidates"][2]
    assert row["status"] == "unavailable" and row["base"] is None
    assert row["sizing_basis"] == "requested_quantity" and row["requested_quantity"] == 4
    assert "requested_quantity_unaffordable" in issues(row)
    assert "1204" in row["issues"][-1]["message"]


def test_explicit_stock_quantity_changes_only_position_and_preserves_requested_stress_size():
    report = compare_instruments(
        assumptions(adverse_price_bps="1000"), [candidate()], chain(), stock(quantity=5)
    )
    row = report["candidates"][1]
    assert row["sizing_basis"] == "requested_quantity" and row["requested_quantity"] == 5
    assert row["base"]["quantity"] == row["adverse"]["quantity"] == 5
    # Five $95 shares plus $2 fees leave $523 cash, becoming $528.23.
    assert D(row["base"]["entry_cost"]) == 477
    assert D(row["base"]["scenarios"][1]["pnl"]) == D("28.23")
    # 10% stressed share price: 5 * $104.50 + $2 = $524.50.
    assert row["adverse"]["status"] == "computed"
    assert D(row["adverse"]["entry_cost"]) == D("524.50")
    assert report["candidates"][0]["sizing_basis"] == "cash"
    assert report["candidates"][2]["sizing_basis"] == "maximum_affordable"
    row = compare_instruments(assumptions(), [candidate()], chain(), stock(quantity=11))[
        "candidates"
    ][1]
    assert "requested_quantity_unaffordable" in issues(row)


@pytest.mark.parametrize("quantity", [True, False, 0, -1, 1.5, "2", 1_000_001])
def test_requested_quantities_are_strict_positive_bounded_integers(quantity):
    with pytest.raises(ValidationError):
        InstrumentCandidate.model_validate(candidate(quantity=quantity))
    row = compare_instruments(assumptions(), [candidate()], chain(), stock(quantity=quantity))[
        "candidates"
    ][1]
    assert row["status"] == "unavailable" and "quantity_invalid" in issues(row)


def test_none_quantity_keeps_maximum_affordable_results_unchanged():
    prior = compare_instruments(assumptions(), [candidate()], chain(), stock())
    explicit_none = compare_instruments(
        assumptions(), [candidate(quantity=None)], chain(), stock(quantity=None)
    )
    assert prior == explicit_none
