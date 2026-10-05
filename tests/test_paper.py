"""Hand-checked synthetic quote fixtures; no live orders or provider dependency."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from random import Random

import pytest
from pydantic import ValidationError

from researchdesk.paper import (
    OrderIntent,
    PaperError,
    PaperEvent,
    PaperPolicy,
    Quote,
    fill_order,
    mark_portfolio,
    replay,
    reserve_order,
)

T = datetime(2025, 1, 1, 12, tzinfo=UTC)
POLICY = PaperPolicy(max_symbol_weight=1, max_order_notional=10000, fee_bps=0)


def opening(cash="1000"):
    return PaperEvent(
        event_id="opening",
        idempotency_key="open",
        kind="account_opened",
        occurred_at=T,
        payload={"account_id": "test", "cash": cash, "currency": "USD"},
    )


def quote(price="10", size=100, at=T, symbol="TEST"):
    return Quote(
        symbol=symbol,
        bid=price,
        ask=price,
        as_of=at,
        source="Synthetic hand-calculated test fixture",
        bid_size=size,
        ask_size=size,
    )


def order(side="buy", quantity=10, price="10", order_id="one", symbol="TEST"):
    return OrderIntent(
        order_id=order_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        limit_price=price,
        decision_id="reviewed-test-decision",
    )


def reserve(events, intent, q=None, policy=POLICY, at=T):
    q = q or quote(at=at)
    e = reserve_order(
        replay(events),
        intent,
        policy,
        {intent.symbol: q},
        at,
        idempotency_key=f"reserve-{intent.order_id}",
    )
    events.append(e)
    return e


def fill(events, order_id, q=None, policy=POLICY, at=T, key=None):
    e = fill_order(
        replay(events),
        order_id,
        q or quote(at=at),
        policy,
        at,
        idempotency_key=key or f"fill-{order_id}",
    )
    events.append(e)
    return e


def test_roundtrip_cash_realized_profit_and_replay_after_position_closed():
    events = [opening()]
    reserve(events, order())
    fill(events, "one")
    reserve(events, order("sell", price="12", order_id="sell"), quote("12"))
    fill(events, "sell", quote("12"))
    state = replay(events)
    assert state.cash == D(1020)
    assert state.realized_pnl == D(20)
    assert state.positions == {}
    assert state.reserved_cash == 0
    assert replay([e.model_dump(mode="json") for e in events]).as_dict() == state.as_dict()


def test_partial_fills_fees_cost_basis_and_cancellation_release():
    policy = PaperPolicy(max_symbol_weight=1, max_order_notional=10000, fee_bps=100)
    events = [opening()]
    reserve(events, order(quantity=10), policy=policy)
    assert replay(events).reserved_cash == D(101)
    fill(events, "one", quote(size=4), policy=policy, key="first")
    state = replay(events)
    assert state.positions["TEST"].quantity == 4
    assert state.positions["TEST"].cost_basis == D("40.4")
    assert state.cash == D("959.6")
    assert state.reserved_cash == D("60.6")
    events.append(
        PaperEvent(
            idempotency_key="cancel",
            kind="order_cancelled",
            occurred_at=T,
            payload={"order_id": "one", "reason": "test cancellation"},
        )
    )
    assert replay(events).available_cash == D("959.6")
    reserve(
        events, order("sell", quantity=4, price="12", order_id="sell"), quote("12"), policy=policy
    )
    fill(events, "sell", quote("12"), policy=policy)
    final = replay(events)
    assert final.realized_pnl == D("7.12")  # 48 - .48 - 40.40
    assert final.cash == D("1007.12")
    assert final.fees == D(".88")


def test_duplicate_events_are_idempotent_conflicting_retry_is_rejected():
    events = [opening()]
    reserve(events, order())
    e = fill(events, "one")
    assert replay(events + [e]).as_dict() == replay(events).as_dict()
    payload = {**e.payload, "quantity": 3}
    with pytest.raises(PaperError, match="different content"):
        replay(events + [e.model_copy(update={"payload": payload})])


def test_cumulative_concentration_counts_prior_holding_not_only_new_order():
    policy = PaperPolicy(max_symbol_weight=".5", max_order_notional=10000, fee_bps=0)
    events = [opening()]
    reserve(events, order(quantity=40), policy=policy)
    fill(events, "one", policy=policy)
    with pytest.raises(PaperError) as error:
        reserve(events, order(quantity=40, order_id="second"), policy=policy)
    assert error.value.code == "concentration_limit"


def test_unfilled_orders_reserve_cash_and_concentration():
    events = [opening()]
    reserve(events, order(quantity=60))
    with pytest.raises(PaperError) as error:
        reserve(events, order(quantity=60, order_id="second"))
    assert error.value.code == "insufficient_cash"
    assert replay(events).available_cash == 400
    limited = PaperPolicy(max_symbol_weight=".5", max_order_notional=10000, fee_bps=0)
    events = [opening()]
    reserve(events, order(quantity=30), policy=limited)
    with pytest.raises(PaperError) as error:
        reserve(events, order(quantity=30, order_id="other"), policy=limited)
    assert error.value.code == "concentration_limit"


def test_sell_reservations_prevent_shorting_and_allow_risk_reduction():
    events = [opening()]
    reserve(events, order(quantity=60))
    fill(events, "one")
    limited = PaperPolicy(max_symbol_weight=".1", max_order_notional=10000, fee_bps=0)
    reserve(events, order("sell", quantity=50, order_id="sell"), policy=limited)
    with pytest.raises(PaperError) as error:
        reserve(events, order("sell", quantity=20, order_id="sell2"), policy=limited)
    assert error.value.code == "insufficient_shares"


@pytest.mark.parametrize("offset,code", [(-61, "stale_quote"), (1, "future_quote")])
def test_stale_and_future_quotes_are_rejected(offset, code):
    with pytest.raises(PaperError) as error:
        reserve([opening()], order(), quote(at=T + timedelta(seconds=offset)))
    assert error.value.code == code


def test_predecision_fill_and_unmarketable_limit_and_no_size_rejected():
    events = [opening()]
    reserve(events, order(), at=T + timedelta(seconds=10))
    with pytest.raises(PaperError) as error:
        fill(events, "one", quote(at=T), at=T + timedelta(seconds=10))
    assert error.value.code == "predecision_quote"
    with pytest.raises(PaperError) as error:
        fill(events, "one", quote("11", at=T + timedelta(seconds=10)), at=T + timedelta(seconds=10))
    assert error.value.code == "limit_not_marketable"
    with pytest.raises(PaperError) as error:
        fill(
            events, "one", quote(size=0, at=T + timedelta(seconds=10)), at=T + timedelta(seconds=10)
        )
    assert error.value.code == "no_liquidity"


def test_missing_mark_is_not_zero_and_marked_pnl_reconciles():
    events = [opening()]
    reserve(events, order())
    fill(events, "one")
    state = replay(events)
    with pytest.raises(PaperError) as error:
        mark_portfolio(state, {}, T, POLICY)
    assert error.value.code == "missing_quote"
    marked = mark_portfolio(state, {"TEST": quote("12")}, T, POLICY)
    assert D(marked["equity"]) == 1020
    assert D(marked["total_pnl"]) == D(marked["realized_pnl"]) + D(
        marked["positions"][0]["unrealized_pnl"]
    )


def test_unsupported_instrument_nan_and_crossed_quote_fail():
    with pytest.raises(ValidationError):
        OrderIntent(
            order_id="option",
            symbol="TEST",
            side="buy",
            quantity=1,
            limit_price=2,
            decision_id="test",
            instrument="option",
        )
    with pytest.raises(ValidationError):
        quote("NaN")
    with pytest.raises(ValidationError):
        Quote(symbol="TEST", bid=12, ask=10, as_of=T, source="test", bid_size=1, ask_size=1)


def test_reducer_rejects_overfill_and_fee_tampering_even_if_admission_bypassed():
    events = [opening()]
    reserve(events, order())
    correct = fill_order(replay(events), "one", quote(), POLICY, T, idempotency_key="fill")
    for change, expected in [({"quantity": 11}, "overfill"), ({"fee": "1"}, "invalid_fee")]:
        tampered = correct.model_copy(update={"payload": {**correct.payload, **change}})
        with pytest.raises(PaperError) as error:
            replay(events + [tampered])
        assert error.value.code == expected


def test_fill_rechecks_changed_mandate_before_increasing_risk():
    events = [opening()]
    reserve(events, order(quantity=40))
    stricter = PaperPolicy(max_symbol_weight=".2", max_order_notional=10000, fee_bps=0)
    with pytest.raises(PaperError) as error:
        fill(events, "one", policy=stricter)
    assert error.value.code == "concentration_limit"
    assert replay(events).cash == 1000


def test_seeded_partial_fills_preserve_cash_cost_basis_identity():
    random = Random(617)
    policy = PaperPolicy(max_symbol_weight=1, max_order_notional=10000, fee_bps=7)
    events = [opening("10000")]
    for step in range(35):
        state = replay(events)
        shares = state.positions["TEST"].quantity if "TEST" in state.positions else 0
        side = "sell" if shares and random.random() < 0.5 else "buy"
        quantity = random.randint(1, min(shares, 5) if side == "sell" else 5)
        price = str(random.randint(5, 20))
        moment = T + timedelta(seconds=step)
        q = quote(price, size=random.randint(1, quantity), at=moment)
        intent = order(side, quantity, price, order_id=f"order-{step}")
        reserve(events, intent, q, policy=policy, at=moment)
        fill(events, intent.order_id, q, policy=policy, at=moment)
        state = replay(events)
        if state.orders[intent.order_id].remaining:
            events.append(
                PaperEvent(
                    idempotency_key=f"cancel-{step}",
                    kind="order_cancelled",
                    occurred_at=moment,
                    payload={"order_id": intent.order_id, "reason": "synthetic IOC example"},
                )
            )
        state = replay(events)
        basis = sum((p.cost_basis for p in state.positions.values()), D(0))
        assert abs(state.cash + basis - state.initial_cash - state.realized_pnl) < D("1e-20")
        assert state.available_cash == state.cash
