"""Hand-calculated synthetic books and explicit calendar fixtures, never real returns."""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from researchdesk.paper.performance import (
    MarketSession,
    PerformanceError,
    ValuationObservation,
    build_performance,
)


def session(day, close="20:00:00"):
    return {
        "session": day,
        "open_at": f"{day}T13:30:00Z",
        "close_at": f"{day}T{close}Z",
    }


CALENDAR = [session("2025-07-02"), session("2025-07-03", "17:00:00"), session("2025-07-07")]


def observation(day="2025-07-02", *, at="20:00:30", **changes):
    values = {
        "observation_id": f"{day}-{at}",
        "account_id": "synthetic-account",
        "observed_at": f"{day}T{at}Z",
        "account_opened_at": "2025-07-02T12:00:00Z",
        "market_session": day,
        "book_version": 2,
        "event_count": 3,
        "fill_count": 1,
        "position_count": 1,
        "initial_cash": "1000",
        "cash": "499",
        "realized_pnl": "0",
        "fees": "1",
        "equity": "1049",
        "oldest_quote_at": f"{day}T{at}Z",
        "missing_symbols": [],
    }
    values.update(changes)
    return values


def test_opening_day_and_hold_change_are_hand_calculated_without_double_charging_fees():
    # Opening: 1000; buy 50 shares at 10 plus fee1; mark at11 => equity1049.
    first = observation()
    # Next close, same 50 shares at12 and no fills:499+600=1099, daily gain50.
    held = observation("2025-07-03", at="17:00:40", equity="1099")
    report = build_performance([first, held], CALENDAR)
    day_one, day_two = report["daily"][:2]
    assert day_one["baseline"]["kind"] == "account_opening"
    assert Decimal(day_one["net_pnl"]) == 49
    assert Decimal(day_one["fees_delta"]) == 1
    assert Decimal(day_one["unrealized_pnl_delta"]) == 49
    assert Decimal(day_two["net_pnl"]) == 50
    assert Decimal(day_two["realized_pnl_delta"]) == 0
    assert Decimal(day_two["unrealized_pnl_delta"]) == 50
    assert Decimal(day_two["fees_delta"]) == 0
    assert day_two["fills_delta"] == 0 and day_two["movement"] == "without_fills"


def test_sale_moves_unrealized_to_realized_and_fees_are_already_in_equity():
    first = observation()
    held = observation("2025-07-03", at="17:00:40", equity="1099")
    # Sell50 at13 minus fee1: cash499+650−1=1148; profit650−1−501=148.
    sold = observation(
        "2025-07-07",
        cash="1148",
        equity="1148",
        realized_pnl="148",
        fees="2",
        book_version=4,
        event_count=5,
        fill_count=2,
        position_count=0,
        oldest_quote_at=None,
    )
    day = build_performance([first, held, sold], CALENDAR)["daily"][-1]
    assert day["baseline"]["session"] == "2025-07-03"  # July4holiday and weekend are absent.
    assert Decimal(day["net_pnl"]) == 49
    assert Decimal(day["realized_pnl_delta"]) == 148
    assert Decimal(day["unrealized_pnl_delta"]) == -99
    assert Decimal(day["fees_delta"]) == 1
    assert day["fills_delta"] == 1 and day["movement"] == "with_fills"


def test_intraday_uses_previous_validated_close_and_keeps_current_daily_close_pending():
    first = observation()
    intraday = observation("2025-07-03", at="15:00:00", equity="1059")
    report = build_performance([first, intraday], CALENDAR)
    assert report["daily"][1]["close_status"] == "pending"
    assert report["daily"][1]["net_pnl"] is None
    assert Decimal(report["latest"]["intraday"]["net_pnl"]) == 10
    assert Decimal(report["latest"]["since_opening"]["net_pnl"]) == 59


def test_actual_missing_session_prevents_spanning_daily_pnl_or_intraday_baseline():
    first = observation()
    third = observation("2025-07-07", equity="1099")
    report = build_performance([first, third], CALENDAR)
    assert report["daily"][1]["close_status"] == "missing"
    last = report["daily"][-1]
    assert last["close_equity"] == "1099" and last["net_pnl"] is None
    assert last["gap_reason"] == "missing_previous_close"
    assert report["latest"]["intraday"]["net_pnl"] is None
    assert Decimal(report["latest"]["since_opening"]["net_pnl"]) == 99


def test_early_close_uses_the_given_calendar_time_not_a_fixed_wall_clock():
    proper = observation("2025-07-03", at="17:00:30")
    late = observation("2025-07-03", at="20:00:30", observation_id="wrong-close")
    proper_report = build_performance([proper], CALENDAR)
    assert proper_report["daily"][1]["close_status"] == "qualified"
    late_report = build_performance([late], CALENDAR)
    assert late_report["daily"][1]["close_equity"] is None
    assert not late_report["latest"]["closing_eligible"]
    assert late_report["latest"]["intraday"]["baseline"] is None


@pytest.mark.parametrize(
    "changes,gap",
    [
        ({"oldest_quote_at": "2025-07-02T19:58:59Z"}, "stale_quotes"),
        ({"oldest_quote_at": "2025-07-02T20:00:31Z"}, "future_quote"),
        ({"oldest_quote_at": None}, "missing_quote_timestamp"),
        ({"equity": None, "missing_symbols": ["TEST"]}, "missing_equity"),
        ({"missing_symbols": ["TEST"]}, "missing_quotes"),
    ],
)
def test_bad_closing_marks_are_explicit_equity_gaps(changes, gap):
    report = build_performance([observation(**changes)], CALENDAR)
    assert report["latest"]["equity"] is None and report["latest"]["gap_reason"] == gap
    assert report["daily"][0]["close_equity"] is None
    assert report["daily"][0]["net_pnl"] is None


def test_close_window_boundaries_are_inclusive_but_a_later_snapshot_is_not_a_close():
    boundary = observation(at="20:02:00", oldest_quote_at="2025-07-02T19:59:00Z")
    assert build_performance([boundary], CALENDAR)["latest"]["closing_eligible"]
    later = observation(at="20:02:01", oldest_quote_at="2025-07-02T20:02:01Z")
    assert not build_performance([later], CALENDAR)["latest"]["closing_eligible"]


def test_cash_only_close_needs_no_quote_and_reports_valid_zero_pnl():
    cash = observation(
        cash="1000",
        equity="1000",
        position_count=0,
        fill_count=0,
        event_count=1,
        book_version=1,
        fees="0",
        oldest_quote_at=None,
    )
    report = build_performance([cash], CALENDAR)
    assert report["latest"]["closing_eligible"]
    assert Decimal(report["daily"][0]["net_pnl"]) == 0
    assert report["daily"][0]["movement"] == "without_fills"


def test_old_account_cannot_invent_an_initial_cash_daily_baseline():
    old = observation(account_opened_at="2025-07-01T12:00:00Z")
    report = build_performance([old], CALENDAR)
    assert report["daily"][0]["net_pnl"] is None
    assert report["daily"][0]["baseline"] is None


def test_opening_date_uses_exchange_timezone_and_after_close_opening_is_not_that_close():
    # 00:30UTCJuly2 is still July1 in New York, not the July2 opening session.
    overnight = observation(account_opened_at="2025-07-02T00:30:00Z")
    assert build_performance([overnight], CALENDAR)["daily"][0]["baseline"] is None
    late_opening = observation(account_opened_at="2025-07-02T20:00:10Z")
    assert not build_performance([late_opening], CALENDAR)["latest"]["closing_eligible"]


def test_unknown_or_incorrect_session_tag_never_qualifies_a_close():
    for tag in (None, "2025-07-03", "2025-07-04"):
        report = build_performance([observation(market_session=tag)], CALENDAR)
        assert not report["latest"]["closing_eligible"]
        assert report["latest"]["intraday"]["baseline"] is None


def test_intraday_stale_quote_retains_gap_instead_of_previous_equity():
    first = observation()
    stale = observation("2025-07-03", at="15:00:00", oldest_quote_at="2025-07-03T14:58:59Z")
    report = build_performance([first, stale], CALENDAR)
    assert [row["equity"] for row in report["equity_series"]] == ["1049", None]
    assert report["latest"]["intraday"]["net_pnl"] is None
    assert report["latest"]["intraday"]["realized_pnl_delta"] == "0"


def test_order_changes_do_not_count_as_trades():
    first = observation()
    later = observation("2025-07-03", at="17:00:30", book_version=4, event_count=5, equity="1059")
    report = build_performance([first, later], CALENDAR)
    assert report["daily"][1]["fills_delta"] == 0
    assert report["daily"][1]["movement"] == "without_fills"


def test_out_of_order_and_identical_duplicate_inputs_have_deterministic_results():
    first = observation()
    later = observation("2025-07-03", at="17:00:30", equity="1059")
    original = deepcopy([first, later])
    expected = build_performance([first, later], CALENDAR)
    repeated = build_performance([later, first, first], list(reversed(CALENDAR)))
    assert repeated["equity_series"] == expected["equity_series"]
    assert repeated["daily"] == expected["daily"]
    assert repeated["duplicates_ignored"] == 1
    assert [first, later] == original


@pytest.mark.parametrize(
    "change", [{"equity": "1100"}, {"observation_id": "different", "equity": "1100"}]
)
def test_conflicting_duplicate_ids_or_timestamps_fail_explicitly(change):
    first = observation()
    with pytest.raises(PerformanceError) as error:
        build_performance([first, {**first, **change}], CALENDAR)
    assert error.value.code == "conflicting_observation"


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"initial_cash": "2000"}, "account_mismatch"),
        ({"account_id": "other"}, "account_mismatch"),
        ({"event_count": 2}, "book_regression"),
        ({"cash": "600"}, "unsupported_cashflow"),
    ],
)
def test_account_changes_or_regressing_books_are_not_performance(changes, code):
    later = observation("2025-07-03", at="17:00:30", **changes)
    with pytest.raises(PerformanceError) as error:
        build_performance([observation(), later], CALENDAR)
    assert error.value.code == code


def test_decimal_values_remain_exact_and_float_money_is_rejected():
    with pytest.raises(ValidationError):
        ValuationObservation.model_validate(observation(cash=499.1))
    precise = observation(cash="499.00000000000000000000001", equity="1049.00000000000000000000001")
    report = build_performance([precise], CALENDAR)
    assert report["latest"]["equity"] == "1049.00000000000000000000001"
    assert Decimal(report["daily"][0]["net_pnl"]) == Decimal("49.00000000000000000000001")


def test_empty_observations_have_no_fabricated_equity_or_pnl():
    report = build_performance([], CALENDAR)
    assert report["latest"] is None and report["equity_series"] == []
    assert all(row["net_pnl"] is None for row in report["daily"])


def test_invalid_calendar_or_timezone_naive_observations_fail():
    with pytest.raises(PerformanceError, match="unique"):
        build_performance([], [CALENDAR[0], CALENDAR[0]])
    with pytest.raises(ValidationError):
        MarketSession.model_validate({**CALENDAR[0], "close_at": "2025-07-02T12:00:00Z"})
    with pytest.raises(ValidationError):
        ValuationObservation.model_validate(observation(observed_at=datetime(2025, 7, 2, 20)))
    assert ValuationObservation.model_validate(observation()).observed_at.tzinfo == UTC


def test_stopped_worker_close_becomes_missing_at_report_time_without_advancing_valuation():
    first = observation()
    intraday = observation("2025-07-03", at="15:00:00", equity="1059")
    original = build_performance([first, intraday], CALENDAR)
    reported = build_performance(
        [first, intraday], CALENDAR, report_as_of=datetime(2025, 7, 3, 17, 2, 1, tzinfo=UTC)
    )
    assert original["daily"][1]["close_status"] == "pending"
    assert reported["daily"][1]["close_status"] == "missing"
    assert reported["daily"][1]["net_pnl"] is None
    assert reported["daily"][2]["close_status"] == "pending"
    assert reported["as_of"] == original["as_of"] == "2025-07-03T15:00:00+00:00"
    assert reported["report_as_of"] == "2025-07-03T17:02:01+00:00"
    assert reported["latest"] == original["latest"]
    assert reported["equity_series"] == original["equity_series"]
    assert reported["daily"][0] == original["daily"][0]


def test_report_time_without_observations_classifies_only_elapsed_closes_as_missing():
    report = build_performance([], CALENDAR, report_as_of=datetime(2025, 7, 3, 16, tzinfo=UTC))
    assert [day["close_status"] for day in report["daily"]] == ["missing", "pending", "pending"]
    assert report["as_of"] is None and report["latest"] is None
    assert report["equity_series"] == []
    assert all(day["net_pnl"] is None for day in report["daily"])


@pytest.mark.parametrize(
    "report_time",
    [datetime(2025, 7, 2, 20), datetime(2025, 7, 2, 20, tzinfo=UTC), "2025-07-03T20:00:00Z"],
)
def test_naive_invalid_or_preobservation_report_time_is_rejected(report_time):
    with pytest.raises(PerformanceError) as error:
        build_performance([observation()], CALENDAR, report_as_of=report_time)
    assert error.value.code == "invalid_report_time"


def test_report_time_accepts_equal_instant_in_other_timezone_and_normalizes_to_utc():
    reported_at = datetime.fromisoformat("2025-07-02T16:00:30-04:00")
    report = build_performance([observation()], CALENDAR, report_as_of=reported_at)
    assert report["as_of"] == report["report_as_of"] == "2025-07-02T20:00:30+00:00"
    assert report["daily"][0]["close_status"] == "qualified"
