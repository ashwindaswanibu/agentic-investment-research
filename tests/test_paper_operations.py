"""Synthetic boundary scenarios; these are accounting tests, not market results."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import researchdesk.paper_operations as module
from researchdesk.api import create_app
from researchdesk.config import Settings
from researchdesk.data.quotes import MarketClock, MarketSession, QuoteBatch
from researchdesk.db import ArtifactRow, MarketSessionRow, PaperObservationRow, SystemRow
from researchdesk.errors import DomainError
from researchdesk.paper import PaperEvent, Quote, replay
from researchdesk.paper_operations import ControlInput, MandateInput, PaperOperations
from researchdesk.store import Store

T = datetime(2026, 10, 5, 14, tzinfo=UTC)


class Clock(datetime):
    value = T

    @classmethod
    def now(cls, tz=None):
        return cls.value.astimezone(tz or UTC)


class SyntheticMarket:
    """Explicit fixture market with controllable freshness and failures."""

    configured = True
    is_open = True
    stale = False
    price = "10"
    size = 5
    quote_at = None
    on_quotes = None

    def health(self):
        return {
            "configured": self.configured,
            "provider": "synthetic test fixture",
            "reason": "Fixture only",
        }

    def clock(self):
        return MarketClock(Clock.value, self.is_open, T + timedelta(days=1), T.replace(hour=20))

    def calendar(self, start, end):
        return [MarketSession(T.date(), T.replace(hour=13, minute=30), T.replace(hour=20))]

    def quotes(self, symbols):
        if self.on_quotes:
            self.on_quotes()
        at = self.quote_at or (Clock.value - timedelta(minutes=5) if self.stale else Clock.value)
        return QuoteBatch(
            Clock.value,
            {
                symbol: Quote(
                    symbol=symbol,
                    bid=self.price,
                    ask=self.price,
                    as_of=at,
                    bid_size=self.size,
                    ask_size=self.size,
                    source="Synthetic operations-test quote",
                )
                for symbol in symbols
            },
        )


class ReviewedDecisions:
    """Isolates orchestration; real review/artifact binding has domain regressions."""

    def __init__(self, store):
        self.store = store
        self.invalid = False

    def artifact(self, identifier, kind):
        artifact = self.store.get_artifact(identifier)
        assert artifact["kind"] == kind
        return artifact

    def validate_decision(self, *args, **kwargs):
        if self.invalid:
            raise DomainError("REVIEW_REJECTED", "Synthetic negative review.", 409)


def mandate(**changes):
    return MandateInput.model_validate(
        {
            "name": "Explicit synthetic test mandate",
            "allowed_symbols": ["TEST"],
            "policy": {
                "max_symbol_weight": "0.5",
                "max_order_notional": "100",
                "max_quote_age_seconds": 30,
                "fee_bps": "0",
            },
            "max_open_orders": 2,
            "order_ttl_seconds": 120,
            "max_decision_age_seconds": 3600,
            "poll_interval_seconds": 5,
            "max_drawdown_amount": "20",
            "expires_at": T + timedelta(days=1),
            **changes,
        }
    )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    Clock.value = T
    monkeypatch.setattr(module, "datetime", Clock)
    store = Store(f"sqlite:///{tmp_path}/operations.db")
    market = SyntheticMarket()
    research = ReviewedDecisions(store)
    ops = PaperOperations(store, research, market)
    opening = PaperEvent(
        kind="account_opened",
        occurred_at=T - timedelta(minutes=1),
        idempotency_key="fixture-opening",
        payload={"account_id": "paper-main", "cash": "1000", "currency": "USD"},
    ).model_dump(mode="json")
    store.ledger_transaction("fixture-opening", lambda _: [opening])
    case = store.create_case("Synthetic operations case", "Not an investment result")
    saved = ops.create_mandate(mandate(), "fixture-mandate")
    yield ops, store, market, case, saved
    store.close()


def activate(ops, saved, mode="active"):
    return ops.set_control(
        ControlInput(
            mandate_id=saved["id"], mode=mode, expected_version=ops.status()["control"]["version"]
        )
    )


def intent(store, case, *, side="buy", quantity=10, price="10", created_at=T, symbol="TEST"):
    artifact = store.put_artifact(
        case["id"],
        None,
        "paper_intent",
        "Synthetic intent",
        {
            "artifact_id": "fixture-experiment",
            "review_id": "fixture-review",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "limit_price": price,
        },
    )
    with store.transaction() as session:
        session.get(ArtifactRow, artifact["id"]).created_at = created_at.isoformat()
    return artifact["id"]


def tick(ops, seconds=0):
    Clock.value += timedelta(seconds=seconds)
    return ops.tick("fixture-worker")


def test_save_is_immutable_idempotent_and_does_not_activate(setup):
    ops, _, _, _, saved = setup
    assert ops.status()["control"] == {"version": 0, "mode": "halted", "mandate_id": None}
    assert ops.create_mandate(mandate(), "fixture-mandate")["id"] == saved["id"]
    with pytest.raises(DomainError, match="different fields"):
        ops.create_mandate(mandate(name="Different mandate"), "fixture-mandate")
    assert len(ops.status()["mandates"]) == 1
    with pytest.raises(ValidationError):
        MandateInput.model_validate({"name": "No implicit risk defaults"})


def test_controls_use_compare_and_swap_and_require_open_account(setup, tmp_path):
    ops, _, _, _, saved = setup
    assert activate(ops, saved)["version"] == 1
    with pytest.raises(DomainError) as exc:
        ops.set_control(ControlInput(mandate_id=saved["id"], mode="halted", expected_version=0))
    assert exc.value.code == "CONTROL_CONFLICT"
    empty_store = Store(f"sqlite:///{tmp_path}/empty.db")
    try:
        empty = PaperOperations(empty_store, ReviewedDecisions(empty_store), SyntheticMarket())
        saved_empty = empty.create_mandate(mandate(), "saved")
        with pytest.raises(DomainError) as exc:
            activate(empty, saved_empty)
        assert exc.value.code == "ACCOUNT_REQUIRED"
    finally:
        empty_store.close()


def test_reserve_then_fill_requires_new_quote_and_cannot_reuse_liquidity(setup):
    ops, store, market, case, saved = setup
    oid = intent(store, case)
    activate(ops, saved)
    assert tick(ops)["actions"] == [{"action": "reserved", "order_id": oid}]
    assert replay(store.ledger_events()).positions == {}
    tick(ops, 1)
    assert replay(store.ledger_events()).positions["TEST"].quantity == 5
    market.quote_at = Clock.value
    tick(ops, 1)
    assert replay(store.ledger_events()).positions["TEST"].quantity == 5
    market.quote_at = None
    tick(ops, 1)
    state = replay(store.ledger_events())
    assert state.positions["TEST"].quantity == 10
    assert state.cash == Decimal("900")
    assert state.orders[oid].status == "filled"
    tick(ops, 1)
    assert replay(store.ledger_events()).event_count == 4
    snapshot = ops.status()["latest_observation"]
    assert snapshot["event_count"] == 4 and snapshot["fill_count"] == 2
    assert snapshot["equity"] == "1000"


@pytest.mark.parametrize(
    "condition", ["stale", "closed", "unconfigured", "bad_review", "old_intent", "outside_universe"]
)
def test_invalid_inputs_do_not_reserve_or_fill(setup, condition):
    ops, store, market, case, saved = setup
    intent(
        store,
        case,
        created_at=T - timedelta(hours=2) if condition == "old_intent" else T,
        symbol="OTHER" if condition == "outside_universe" else "TEST",
    )
    activate(ops, saved)
    market.stale = condition == "stale"
    market.is_open = condition != "closed"
    market.configured = condition != "unconfigured"
    ops.research.invalid = condition == "bad_review"
    tick(ops)
    assert len(store.ledger_events()) == 1


def test_control_change_during_network_call_fences_old_worker(setup):
    ops, store, market, case, saved = setup
    intent(store, case)
    activate(ops, saved)
    market.on_quotes = lambda: activate(ops, saved, "halted")
    with pytest.raises(DomainError) as exc:
        tick(ops)
    assert exc.value.code == "PAPER_LEASE_LOST"
    assert len(store.ledger_events()) == 1
    assert ops.status()["control"]["mode"] == "halted"


def test_claim_serializes_workers_and_expired_worker_cannot_commit(setup):
    ops, store, _, _, _ = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(ops.claim, ["worker-a", "worker-b"]))
    token = next(t for t in tokens if t)
    assert sum(t is not None for t in tokens) == 1
    Clock.value += timedelta(seconds=121)
    assert ops.claim("replacement")
    with store.transaction() as session, pytest.raises(DomainError) as exc:
        ops._fenced(session, token)
    assert exc.value.code == "PAPER_LEASE_LOST"


@pytest.mark.parametrize("cause", ["expiry", "order_ttl", "case_cancelled", "exit_only", "halted"])
def test_controls_and_expiry_cancel_orders_without_liquidating(setup, cause):
    ops, store, _, case, saved = setup
    oid = intent(store, case)
    activate(ops, saved)
    tick(ops)
    tick(ops, 1)
    assert replay(store.ledger_events()).positions["TEST"].quantity == 5
    if cause == "case_cancelled":
        store.cancel_case(case["id"])
    elif cause in {"exit_only", "halted"}:
        activate(ops, saved, cause)
    tick(ops, 86400 if cause == "expiry" else 120 if cause == "order_ttl" else 1)
    state = replay(store.ledger_events())
    assert state.orders[oid].status == "cancelled"
    assert state.positions["TEST"].quantity == 5
    assert state.reserved_cash == 0


def test_drawdown_latches_entries_but_preserves_positions_and_allows_reviewed_exit(setup):
    ops, store, market, case, saved = setup
    oid = intent(store, case)
    activate(ops, saved)
    tick(ops)
    tick(ops, 1)
    market.price = "5"
    tick(ops, 1)
    status = ops.status()
    assert status["control"]["mode"] == "exit_only"
    assert status["drawdown"]["tripped"]
    assert replay(store.ledger_events()).orders[oid].status == "cancelled"
    with pytest.raises(DomainError) as exc:
        activate(ops, saved)
    assert exc.value.code == "DRAWDOWN_LATCHED"
    sid = intent(store, case, side="sell", quantity=5, price="5", created_at=Clock.value)
    tick(ops, 1)
    tick(ops, 1)
    assert replay(store.ledger_events()).orders[sid].status == "filled"
    assert replay(store.ledger_events()).positions == {}


def test_feed_failure_retains_a_gap_not_old_or_zero_equity(setup):
    ops, store, market, case, saved = setup
    intent(store, case)
    activate(ops, saved)
    tick(ops)
    tick(ops, 1)
    market.configured = False
    assert tick(ops, 61)["status"] == "data_blocked"
    observation = ops.status()["latest_observation"]
    assert observation["equity"] is None
    assert observation["cash"] == "950"
    assert observation["missing_symbols"] == ["TEST"]
    assert ops.performance()["latest"]["equity"] is None


def test_observation_failure_rolls_back_fill_and_recovery_is_safe(setup, monkeypatch):
    ops, store, _, case, saved = setup
    intent(store, case)
    activate(ops, saved)
    tick(ops)
    original = ops._observation

    def fail(*args, **kwargs):
        raise RuntimeError("Injected failure after candidate fills")

    monkeypatch.setattr(ops, "_observation", fail)
    with pytest.raises(RuntimeError):
        tick(ops, 1)
    assert len(store.ledger_events()) == 2
    monkeypatch.setattr(ops, "_observation", original)
    tick(ops, 121)
    assert replay(store.ledger_events()).positions == {}  # expired order is cancelled
    assert len(store.ledger_events()) == 3


def test_managed_account_cannot_bypass_controls_through_manual_order_route(setup):
    ops, store, _, _, saved = setup
    activate(ops, saved, "halted")
    with pytest.raises(DomainError) as exc:
        store.ledger_transaction("manual-bypass", lambda _: [], request={"action": "fill"})
    assert exc.value.code == "MANAGED_ACCOUNT"


def test_api_operations_are_authenticated_read_only_and_have_no_implicit_activation(tmp_path):
    store = Store(f"sqlite:///{tmp_path}/api.db")
    try:
        app = create_app(
            Settings(_env_file=None, read_only=True, operator_token="test-secret"), store
        )
        with TestClient(app) as client:
            assert client.get("/api/paper/operations").status_code == 401
            headers = {"Authorization": "Bearer test-secret"}
            response = client.get("/api/paper/operations", headers=headers)
            assert response.status_code == 200
            assert response.json()["control"]["mode"] == "halted"
            assert response.json()["mandates"] == []
            assert (
                client.post(
                    "/api/paper/operations/control",
                    json={"mode": "active", "mandate_id": None, "expected_version": 0},
                    headers=headers,
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/api/paper/mandates",
                    json={},
                    headers={**headers, "Idempotency-Key": "read-only-key"},
                ).status_code
                == 403
            )
    finally:
        store.close()


@pytest.mark.parametrize("close_hour", [20, 17], ids=["regular-close", "early-close"])
def test_slow_mandate_polling_still_records_the_actual_calendar_close(
    setup, monkeypatch, close_hour
):
    ops, _, market, _, _ = setup
    close = T.replace(hour=close_hour)
    monkeypatch.setattr(
        market,
        "calendar",
        lambda start, end: [MarketSession(T.date(), T.replace(hour=13, minute=30), close)],
    )
    slow = ops.create_mandate(mandate(poll_interval_seconds=300), "slow-close-fixture")
    activate(ops, slow)
    Clock.value = close - timedelta(seconds=60)

    # Sleeping the ordinary five-minute interval would skip the whole close window.
    result = tick(ops)
    assert 0 < result["next_poll_seconds"] <= 60
    for _ in range(12):
        Clock.value += timedelta(seconds=result["next_poll_seconds"])
        market.is_open = Clock.value < close
        result = tick(ops)
        report = ops.performance()
        if report["latest"]["closing_eligible"]:
            break
    else:
        pytest.fail("The scheduler never captured the supplied calendar close.")

    latest_at = datetime.fromisoformat(report["latest"]["observed_at"])
    assert close <= latest_at <= close + timedelta(seconds=120)
    day = next(row for row in report["daily"] if row["session"] == T.date().isoformat())
    assert day["close_status"] == "qualified"
    assert Decimal(day["net_pnl"]) == 0


@pytest.mark.parametrize("quote_seconds_before_close", [1, 60, 61])
def test_close_valuation_tolerance_does_not_lose_a_valid_retained_quote(
    setup, quote_seconds_before_close
):
    ops, store, market, case, saved = setup
    intent(store, case, quantity=5)
    activate(ops, saved)
    tick(ops)
    tick(ops, 1)
    assert replay(store.ledger_events()).positions["TEST"].quantity == 5

    close = T.replace(hour=20)
    Clock.value = close + timedelta(seconds=61)
    market.is_open = False
    market.quote_at = close - timedelta(seconds=quote_seconds_before_close)
    market.price = "11"
    before = store.ledger_events()
    tick(ops)
    report = ops.performance()
    assert store.ledger_events() == before  # Valuation tolerance grants no trading authority.
    if quote_seconds_before_close <= 60:
        assert report["latest"]["closing_eligible"]
        assert Decimal(report["latest"]["equity"]) == 1005  # Cash950 plus five shares at11.
    else:
        assert not report["latest"]["closing_eligible"]
        assert report["latest"]["equity"] is None


def test_close_valuation_grace_does_not_relax_intraday_trading_freshness(setup):
    ops, store, market, case, saved = setup
    oid = intent(store, case, quantity=5)
    activate(ops, saved)
    tick(ops)
    market.quote_at = Clock.value
    tick(ops, 31)  # Mandate allows30seconds; the close-mark rule must not apply intraday.
    state = replay(store.ledger_events())
    assert state.orders[oid].remaining == 5
    assert state.positions == {}


def test_first_fill_drawdown_stops_a_second_buy_in_the_same_tick(setup, monkeypatch):
    ops, store, market, case, _ = setup
    saved = ops.create_mandate(
        mandate(
            allowed_symbols=["AAA", "BBB"],
            max_drawdown_amount="30",
            policy={
                "max_symbol_weight": "1",
                "max_order_notional": "500",
                "max_quote_age_seconds": 30,
                "fee_bps": "0",
            },
        ),
        "same-tick-drawdown-fixture",
    )

    def spread_quotes(symbols):
        return QuoteBatch(
            Clock.value,
            {
                symbol: Quote(
                    symbol=symbol,
                    bid="9",
                    ask="10",
                    as_of=Clock.value,
                    bid_size=40,
                    ask_size=40,
                    source="Synthetic two-order spread fixture",
                )
                for symbol in symbols
            },
        )

    monkeypatch.setattr(market, "quotes", spread_quotes)
    identifiers = [intent(store, case, symbol=symbol, quantity=40) for symbol in ("AAA", "BBB")]
    activate(ops, saved)
    tick(ops)
    assert replay(store.ledger_events()).reserved_cash == 800
    result = tick(ops, 1)

    # First buy costs400 but marks360: equity960 crosses the30 drawdown limit.
    # Filling both before rechecking would produce equity920 and double exposure.
    state = replay(store.ledger_events())
    assert sorted(state.orders[identifier].status for identifier in identifiers) == [
        "cancelled",
        "filled",
    ]
    assert sum(position.quantity for position in state.positions.values()) == 40
    assert state.cash == 600 and state.reserved_cash == 0
    assert ops.status()["control"]["mode"] == "exit_only"
    assert ops.status()["drawdown"]["tripped"]
    assert sum(action["action"] == "filled" for action in result["actions"]) == 1
    assert ops.status()["latest_observation"]["equity"] == "960"


@pytest.mark.parametrize("transition", ["clear-selection", "different-mandate"])
def test_drawdown_latch_survives_leaving_and_reselecting_the_saved_mandate(setup, transition):
    ops, store, market, case, saved = setup
    intent(store, case, quantity=5)
    activate(ops, saved)
    tick(ops)
    tick(ops, 1)
    market.price = "5"
    tick(ops, 1)
    assert ops.status()["drawdown"]["tripped"]

    if transition == "clear-selection":
        ops.set_control(
            ControlInput(
                mandate_id=None,
                mode="halted",
                expected_version=ops.status()["control"]["version"],
            )
        )
    else:
        different = ops.create_mandate(
            mandate(name="Explicitly reviewed replacement fixture"), "replacement-fixture"
        )
        activate(ops, different)
    before = ops.status()["control"]
    with pytest.raises(DomainError) as error:
        activate(ops, saved)
    assert error.value.code == "DRAWDOWN_LATCHED"
    assert ops.status()["control"] == before
    assert replay(store.ledger_events()).positions["TEST"].quantity == 5


def test_provider_omission_of_a_retained_session_blocks_execution(setup, monkeypatch):
    ops, store, market, case, saved = setup
    oid = intent(store, case, quantity=5)
    activate(ops, saved)
    tick(ops)  # Stores the successful calendar and reserves the order.
    monkeypatch.setattr(market, "calendar", lambda start, end: [])
    result = tick(ops, 1)
    assert result["status"] == "data_blocked"
    assert result["error"]["code"] == "CALENDAR_CHANGED"
    state = replay(store.ledger_events())
    assert state.positions == {}
    assert state.orders[oid].remaining == 5


@pytest.mark.parametrize("already_reserved", [False, True])
def test_case_cancelled_during_quote_fetch_cannot_reserve_or_fill(setup, already_reserved):
    ops, store, market, case, saved = setup
    oid = intent(store, case, quantity=5)
    activate(ops, saved)
    if already_reserved:
        tick(ops)
    market.on_quotes = lambda: store.cancel_case(case["id"])
    result = tick(ops, 1)
    state = replay(store.ledger_events())
    assert state.positions == {}
    assert not any(action["action"] in {"filled", "reserved"} for action in result["actions"])
    if already_reserved:
        assert state.orders[oid].status == "cancelled"
    else:
        assert oid not in state.orders


PERFORMANCE_DAYS = (
    "2026-09-28",
    "2026-09-29",
    "2026-09-30",
    "2026-10-01",
    "2026-10-02",
    "2026-10-05",
    "2026-10-06",
)


def retained_performance_fixture(tmp_path, monkeypatch, *, missing_session=None, coverage=True):
    """Explicit synthetic stored history, including the baseline outside the display window."""
    Clock.value = datetime(2026, 10, 6, 21, tzinfo=UTC)
    monkeypatch.setattr(module, "datetime", Clock)
    store = Store(f"sqlite:///{tmp_path}/performance-operations.db")
    ops = PaperOperations(store, ReviewedDecisions(store), SyntheticMarket())
    with store.transaction() as session:
        for day in PERFORMANCE_DAYS:
            if day != missing_session:
                session.add(
                    MarketSessionRow(
                        session=day,
                        payload={
                            "session": day,
                            "open_at": f"{day}T13:30:00+00:00",
                            "close_at": f"{day}T20:00:00+00:00",
                            "timezone": "America/New_York",
                        },
                    )
                )
        if coverage:
            session.add(
                SystemRow(
                    key="paper_calendar_coverage",
                    value={
                        "start": PERFORMANCE_DAYS[0],
                        "end": PERFORMANCE_DAYS[-1],
                        "sessions": list(PERFORMANCE_DAYS),
                        "verified_at": Clock.value.isoformat(),
                    },
                )
            )
    return ops, store


def retain_observation(store, day, *, equity, at="20:00:30"):
    """Fixed synthetic holdings: no fills between marks, so equity movement is unrealized."""
    observed_at = f"{day}T{at}+00:00"
    payload = {
        "observation_id": f"synthetic-{day}-{at}",
        "account_id": "paper-main",
        "observed_at": observed_at,
        "account_opened_at": "2026-09-28T12:00:00+00:00",
        "market_session": day,
        "book_version": 2,
        "event_count": 3,
        "fill_count": 1,
        "position_count": 1,
        "initial_cash": "1000",
        "cash": "500",
        "realized_pnl": "0",
        "fees": "0",
        "equity": equity,
        "oldest_quote_at": observed_at,
        "missing_symbols": [],
    }
    with store.transaction() as session:
        session.add(
            PaperObservationRow(account_id="paper-main", observed_at=observed_at, payload=payload)
        )


def test_performance_retains_previous_session_baseline_before_display_window(tmp_path, monkeypatch):
    ops, store = retained_performance_fixture(tmp_path, monkeypatch)
    try:
        # The seven-day cutoff is Sep29at21:00. Sep29close remains the required
        # predecessor of the first displayed session (Sep30), even though hidden.
        retain_observation(store, "2026-09-29", equity="1000")
        retain_observation(store, "2026-09-30", equity="1050")
        report = ops.performance()
        day = next(row for row in report["daily"] if row["session"] == "2026-09-30")
        assert day["baseline"]["session"] == "2026-09-29"
        assert Decimal(day["net_pnl"]) == 50
        assert Decimal(day["unrealized_pnl_delta"]) == 50
        assert day["fills_delta"] == 0
        assert all(
            datetime.fromisoformat(row["observed_at"]) >= Clock.value - timedelta(days=7)
            for row in report["equity_series"]
        )
    finally:
        store.close()


def test_performance_marks_elapsed_close_missing_when_worker_stopped_intraday(
    tmp_path, monkeypatch
):
    ops, store = retained_performance_fixture(tmp_path, monkeypatch)
    try:
        retain_observation(store, "2026-10-06", equity="1020", at="19:00:00")
        report = ops.performance()  # Report21:00UTC, last actual observation19:00UTC.
        day = next(row for row in report["daily"] if row["session"] == "2026-10-06")
        assert day["close_status"] == "missing"
        assert day["close_equity"] is None
        assert report["as_of"] == "2026-10-06T19:00:00+00:00"
        assert report["report_as_of"] == Clock.value.isoformat()
        assert report["latest"]["equity"] == "1020"  # Historical mark is not rewritten.
    finally:
        store.close()


@pytest.mark.parametrize(
    "missing_session,coverage,reason",
    [
        (None, False, "CALENDAR_COVERAGE_MISSING"),
        ("2026-10-01", True, "CALENDAR_COVERAGE_INCOMPLETE"),
    ],
)
def test_unverified_calendar_cannot_bridge_an_unobserved_trading_session(
    tmp_path, monkeypatch, missing_session, coverage, reason
):
    ops, store = retained_performance_fixture(
        tmp_path, monkeypatch, missing_session=missing_session, coverage=coverage
    )
    try:
        retain_observation(store, "2026-09-30", equity="1000")
        retain_observation(store, "2026-10-02", equity="1050")
        report = ops.performance()
        assert report["calendar_coverage"]["complete"] is False
        assert report["calendar_coverage"]["reason"] == reason
        assert report["latest"]["intraday"]["net_pnl"] is None
        assert all(row["net_pnl"] is None for row in report["daily"])
    finally:
        store.close()
