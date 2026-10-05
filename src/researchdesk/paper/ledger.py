"""Replayable long-only paper account. Persistence/serialization belong to the store.

The store must lock the account or compare its version and atomically append all
events in an operation. Replay validates invariants but does not replace that
transaction. No model/provider/broker code can write balances directly.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from researchdesk.quant.models import StrictModel

D = Decimal


class PaperError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


class Quote(StrictModel):
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    as_of: datetime
    source: str = Field(min_length=1, max_length=500)
    bid_size: int = Field(ge=0, strict=True)
    ask_size: int = Field(ge=0, strict=True)

    _aware = field_validator("as_of")(_utc)

    @model_validator(mode="after")
    def ordered_prices(self) -> Quote:
        if self.bid > self.ask:
            raise ValueError("crossed quote: bid exceeds ask")
        return self


class PaperPolicy(StrictModel):
    max_symbol_weight: Decimal = Field(default=D("0.25"), gt=0, le=1)
    max_order_notional: Decimal = Field(default=D("2500"), gt=0)
    max_quote_age_seconds: int = Field(default=60, ge=1, le=86400, strict=True)
    fee_bps: Decimal = Field(default=D("1"), ge=0, le=1000)


class OrderIntent(StrictModel):
    order_id: str = Field(min_length=1, max_length=200)
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0, le=10000000, strict=True)
    limit_price: Decimal = Field(gt=0)
    decision_id: str = Field(min_length=1, max_length=200)
    instrument: Literal["equity", "etf"] = "equity"


class PaperEvent(StrictModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    idempotency_key: str = Field(min_length=1, max_length=300)
    kind: Literal["account_opened", "order_reserved", "fill", "order_cancelled"]
    occurred_at: datetime
    payload: dict

    _aware = field_validator("occurred_at")(_utc)


class _Opening(StrictModel):
    account_id: str = Field(min_length=1, max_length=200)
    cash: Decimal = Field(gt=0)
    currency: Literal["USD"] = "USD"


class _Reserved(OrderIntent):
    fee_bps: Decimal = Field(ge=0, le=1000)
    reserved_cash: Decimal = Field(ge=0)


class _Fill(StrictModel):
    order_id: str
    quantity: int = Field(gt=0, strict=True)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    quote_at: datetime
    quote_source: str = Field(min_length=1)
    quote: Quote

    _aware = field_validator("quote_at")(_utc)


class _Cancelled(StrictModel):
    order_id: str
    reason: str = Field(min_length=1, max_length=1000)


@dataclass
class Holding:
    quantity: int = 0
    cost_basis: Decimal = D(0)  # buy commissions are capitalized


@dataclass
class OpenOrder:
    intent: OrderIntent
    fee_bps: Decimal
    remaining: int
    reserved_cash: Decimal
    submitted_at: datetime
    status: str = "open"


@dataclass
class PaperState:
    account_id: str | None = None
    initial_cash: Decimal = D(0)
    cash: Decimal = D(0)
    realized_pnl: Decimal = D(0)
    fees: Decimal = D(0)
    positions: dict[str, Holding] = field(default_factory=dict)
    orders: dict[str, OpenOrder] = field(default_factory=dict)
    event_count: int = 0
    liquidity_used: dict[str, int] = field(default_factory=dict)

    @property
    def reserved_cash(self) -> Decimal:
        return sum(
            (order.reserved_cash for order in self.orders.values() if order.status == "open"), D(0)
        )

    @property
    def available_cash(self) -> Decimal:
        return self.cash - self.reserved_cash

    def as_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "currency": "USD",
            "execution_mode": "paper",
            "initial_cash": str(self.initial_cash),
            "cash": str(self.cash),
            "reserved_cash": str(self.reserved_cash),
            "available_cash": str(self.available_cash),
            "realized_pnl": str(self.realized_pnl),
            "fees": str(self.fees),
            "positions": {
                symbol: {"quantity": p.quantity, "cost_basis": str(p.cost_basis)}
                for symbol, p in self.positions.items()
            },
            "orders": {
                key: {
                    **order.intent.model_dump(mode="json"),
                    "remaining": order.remaining,
                    "reserved_cash": str(order.reserved_cash),
                    "fee_bps": str(order.fee_bps),
                    "submitted_at": order.submitted_at.isoformat(),
                    "status": order.status,
                }
                for key, order in self.orders.items()
            },
            "event_count": self.event_count,
        }


def _fingerprint(event: PaperEvent) -> str:
    payload = event.model_dump(mode="json", exclude={"event_id"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _reserved_shares(state: PaperState, symbol: str) -> int:
    return sum(
        order.remaining
        for order in state.orders.values()
        if order.status == "open" and order.intent.symbol == symbol and order.intent.side == "sell"
    )


def liquidity_key(quote: Quote, side: str) -> str:
    """An unchanged displayed quote cannot supply fresh liquidity on every poll."""
    raw = {"quote": quote.model_dump(mode="json"), "side": side}
    for name in ("bid", "ask"):
        # normalize() can round long Decimals under the active context; fixed
        # formatting and trailing-zero removal preserve the exact economic value.
        price = format(getattr(quote, name), "f")
        raw["quote"][name] = price.rstrip("0").rstrip(".") if "." in price else price
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()


def replay(events: list[PaperEvent | dict]) -> PaperState:
    state = PaperState()
    keys: dict[str, str] = {}
    ids: dict[str, str] = {}
    previous_at: datetime | None = None
    for raw in events:
        event = PaperEvent.model_validate(raw)
        fingerprint = _fingerprint(event)
        for mapping, key in ((keys, event.idempotency_key), (ids, event.event_id)):
            if key in mapping and mapping[key] != fingerprint:
                raise PaperError(
                    "idempotency_conflict", "duplicate ledger identifier has different content"
                )
        if event.idempotency_key in keys or event.event_id in ids:
            keys[event.idempotency_key] = ids[event.event_id] = fingerprint
            continue
        if previous_at is not None and event.occurred_at < previous_at:
            raise PaperError("event_order", "ledger events must be chronological")
        if event.kind == "account_opened":
            opening = _Opening.model_validate(event.payload)
            if state.account_id is not None:
                raise PaperError("account_already_open", "account opening is immutable")
            state.account_id, state.cash = opening.account_id, opening.cash
            state.initial_cash = opening.cash
        elif state.account_id is None:
            raise PaperError("account_not_open", "the first event must open an account")
        elif event.kind == "order_reserved":
            record = _Reserved.model_validate(event.payload)
            if record.order_id in state.orders:
                raise PaperError("duplicate_order", "order_id already exists")
            required = (
                record.quantity * record.limit_price * (1 + record.fee_bps / 10000)
                if record.side == "buy"
                else D(0)
            )
            if required != record.reserved_cash:
                raise PaperError(
                    "invalid_reservation", "reservation does not match the worst-case order cost"
                )
            if required > state.available_cash:
                raise PaperError("insufficient_cash", "reservation exceeds available cash")
            if record.side == "sell":
                shares = state.positions.get(record.symbol, Holding()).quantity - _reserved_shares(
                    state, record.symbol
                )
                if record.quantity > shares:
                    raise PaperError(
                        "insufficient_shares", "sell reservation exceeds unreserved holdings"
                    )
            intent = OrderIntent.model_validate(
                record.model_dump(exclude={"fee_bps", "reserved_cash"})
            )
            state.orders[record.order_id] = OpenOrder(
                intent, record.fee_bps, record.quantity, required, event.occurred_at
            )
        elif event.kind == "fill":
            fill = _Fill.model_validate(event.payload)
            order = state.orders.get(fill.order_id)
            if order is None or order.status != "open":
                raise PaperError("order_not_open", "fill requires an open order")
            if fill.quantity > order.remaining:
                raise PaperError("overfill", "fill exceeds the unfilled order quantity")
            if not order.submitted_at <= fill.quote_at <= event.occurred_at:
                raise PaperError(
                    "invalid_fill_time",
                    "fill quote must follow reservation and precede application",
                )
            buy = order.intent.side == "buy"
            if (
                fill.quote.as_of != fill.quote_at
                or fill.quote.source != fill.quote_source
                or fill.quote.symbol != order.intent.symbol
                or fill.price != (fill.quote.ask if buy else fill.quote.bid)
                or fill.quantity > (fill.quote.ask_size if buy else fill.quote.bid_size)
            ):
                raise PaperError(
                    "invalid_quote_fill",
                    "fill does not match its retained quote and displayed size",
                )
            if fill.fee != fill.quantity * fill.price * order.fee_bps / 10000:
                raise PaperError("invalid_fee", "fill fee does not match the reserved fee schedule")
            symbol, side = order.intent.symbol, order.intent.side
            quote_key = liquidity_key(fill.quote, side)
            consumed = state.liquidity_used.get(quote_key, 0) + fill.quantity
            if consumed > (fill.quote.ask_size if buy else fill.quote.bid_size):
                raise PaperError(
                    "quote_liquidity_exhausted", "displayed quote liquidity was already consumed"
                )
            state.liquidity_used[quote_key] = consumed
            position = state.positions.setdefault(symbol, Holding())
            if side == "buy":
                if fill.price > order.intent.limit_price:
                    raise PaperError("limit_violated", "buy fill exceeds its limit")
                cost = fill.quantity * fill.price + fill.fee
                state.cash -= cost
                position.quantity += fill.quantity
                position.cost_basis += cost
            else:
                if fill.price < order.intent.limit_price:
                    raise PaperError("limit_violated", "sell fill is below its limit")
                if fill.quantity > position.quantity:
                    raise PaperError("insufficient_shares", "fill would create a short position")
                basis = position.cost_basis * fill.quantity / position.quantity
                proceeds = fill.quantity * fill.price - fill.fee
                state.cash += proceeds
                state.realized_pnl += proceeds - basis
                position.cost_basis -= basis
                position.quantity -= fill.quantity
            state.fees += fill.fee
            order.remaining -= fill.quantity
            order.reserved_cash = (
                order.remaining * order.intent.limit_price * (1 + order.fee_bps / 10000)
                if side == "buy"
                else D(0)
            )
            if order.remaining == 0:
                order.status = "filled"
            if position.quantity == 0:
                del state.positions[symbol]
        elif event.kind == "order_cancelled":
            record = _Cancelled.model_validate(event.payload)
            order = state.orders.get(record.order_id)
            if order is None or order.status != "open":
                raise PaperError("order_not_open", "cancellation requires an open order")
            order.status, order.reserved_cash = "cancelled", D(0)
        if state.cash < 0 or state.available_cash < 0:
            raise PaperError(
                "accounting_invariant", "ledger operation creates negative available cash"
            )
        keys[event.idempotency_key] = ids[event.event_id] = fingerprint
        previous_at = event.occurred_at
        state.event_count += 1
    return state


def _quote(quote: Quote | dict, at: datetime, policy: PaperPolicy) -> Quote:
    quote = Quote.model_validate(quote)
    age = (_utc(at) - quote.as_of).total_seconds()
    if age < 0:
        raise PaperError("future_quote", "quote timestamp is later than the decision")
    if age > policy.max_quote_age_seconds:
        raise PaperError("stale_quote", "quote is too old for paper admission or fill")
    return quote


def reserve_order(
    state: PaperState,
    intent: OrderIntent | dict,
    policy: PaperPolicy | dict,
    quotes: dict[str, Quote | dict],
    at: datetime,
    *,
    idempotency_key: str,
    event_id: str | None = None,
) -> PaperEvent:
    intent, policy = OrderIntent.model_validate(intent), PaperPolicy.model_validate(policy)
    at = _utc(at)
    if state.account_id is None:
        raise PaperError("account_not_open", "open the account before submitting an order")
    if intent.order_id in state.orders:
        raise PaperError("duplicate_order", "order_id already exists")
    if intent.symbol not in quotes:
        raise PaperError("missing_quote", "order requires a current attributable quote")
    quote = _quote(quotes[intent.symbol], at, policy)
    if quote.symbol != intent.symbol:
        raise PaperError("symbol_mismatch", "quote symbol does not match order")
    notional = intent.quantity * intent.limit_price
    if notional > policy.max_order_notional:
        raise PaperError("order_limit", "order exceeds the configured notional limit")
    required = notional * (1 + policy.fee_bps / 10000) if intent.side == "buy" else D(0)
    if intent.side == "buy":
        if required > state.available_cash:
            raise PaperError(
                "insufficient_cash", "order would exceed cash after existing reservations"
            )
        marks = {}
        pending_buys = [
            o for o in state.orders.values() if o.status == "open" and o.intent.side == "buy"
        ]
        mark_symbols = set(state.positions) | {o.intent.symbol for o in pending_buys}
        for symbol in mark_symbols:
            if symbol not in quotes:
                raise PaperError(
                    "missing_quote", "fresh marks are required for existing portfolio positions"
                )
            mark = _quote(quotes[symbol], at, policy)
            if mark.symbol != symbol:
                raise PaperError("symbol_mismatch", "portfolio quote symbol is incorrect")
            marks[symbol] = mark.bid  # conservative liquidation value
        nav = state.cash + sum((p.quantity * marks[s] for s, p in state.positions.items()), D(0))
        existing = state.positions.get(intent.symbol, Holding()).quantity * quote.bid
        pending = sum(
            (
                o.remaining * o.intent.limit_price
                for o in pending_buys
                if o.intent.symbol == intent.symbol
            ),
            D(0),
        )
        pending_costs = sum(
            (
                max(D(0), o.remaining * (o.intent.limit_price - marks[o.intent.symbol]))
                + o.remaining * o.intent.limit_price * o.fee_bps / 10000
                for o in pending_buys
            ),
            D(0),
        )
        # New buy fees/spread reduce NAV. Conservative mark of new shares at min(bid, limit).
        acquisition_loss = (
            max(D(0), notional - intent.quantity * quote.bid)
            + notional * policy.fee_bps / 10000
            + pending_costs
        )
        if nav <= acquisition_loss or existing + pending + notional > policy.max_symbol_weight * (
            nav - acquisition_loss
        ):
            raise PaperError("concentration_limit", "resulting symbol exposure exceeds the mandate")
    elif intent.quantity > state.positions.get(
        intent.symbol, Holding()
    ).quantity - _reserved_shares(state, intent.symbol):
        raise PaperError(
            "insufficient_shares", "order exceeds holdings after existing sell reservations"
        )
    payload = {
        **intent.model_dump(mode="json"),
        "fee_bps": str(policy.fee_bps),
        "reserved_cash": str(required),
    }
    return PaperEvent(
        event_id=event_id or str(uuid4()),
        idempotency_key=idempotency_key,
        kind="order_reserved",
        occurred_at=at,
        payload=payload,
    )


def fill_order(
    state: PaperState,
    order_id: str,
    quote: Quote | dict,
    policy: PaperPolicy | dict,
    at: datetime,
    *,
    idempotency_key: str,
    event_id: str | None = None,
    quantity: int | None = None,
    portfolio_quotes: dict[str, Quote | dict] | None = None,
) -> PaperEvent:
    policy = PaperPolicy.model_validate(policy)
    quote = _quote(quote, at, policy)
    order = state.orders.get(order_id)
    if order is None or order.status != "open":
        raise PaperError("order_not_open", "fill requires an open reserved order")
    if quote.symbol != order.intent.symbol:
        raise PaperError("symbol_mismatch", "quote symbol does not match order")
    if quote.as_of < order.submitted_at:
        raise PaperError(
            "predecision_quote", "paper fill needs an observation at or after reservation"
        )
    if order.intent.side == "buy":
        # Prices and policy may have changed since admission. Re-admit the remaining
        # buy against fresh portfolio marks before mutating the economic record.
        check_state = deepcopy(state)
        del check_state.orders[order_id]
        reserve_order(
            check_state,
            order.intent.model_copy(update={"quantity": order.remaining}),
            policy.model_copy(update={"fee_bps": order.fee_bps}),
            {**(portfolio_quotes or {}), quote.symbol: quote},
            at,
            idempotency_key="fill-risk-check",
        )
    buy = order.intent.side == "buy"
    price, size = (quote.ask, quote.ask_size) if buy else (quote.bid, quote.bid_size)
    size -= state.liquidity_used.get(liquidity_key(quote, order.intent.side), 0)
    if (buy and price > order.intent.limit_price) or (not buy and price < order.intent.limit_price):
        raise PaperError(
            "limit_not_marketable", "current quoted price does not meet the order limit"
        )
    if quantity is not None and (
        type(quantity) is not int or quantity <= 0 or quantity > order.remaining
    ):
        raise PaperError("invalid_quantity", "requested fill must be a positive unfilled quantity")
    filled = min(order.remaining if quantity is None else quantity, size)
    if filled <= 0:
        raise PaperError("no_liquidity", "quote has no displayed size on the required side")
    fee = filled * price * order.fee_bps / 10000
    return PaperEvent(
        event_id=event_id or str(uuid4()),
        idempotency_key=idempotency_key,
        kind="fill",
        occurred_at=_utc(at),
        payload={
            "order_id": order_id,
            "quantity": filled,
            "price": str(price),
            "fee": str(fee),
            "quote_at": quote.as_of.isoformat(),
            "quote_source": quote.source,
            "quote": quote.model_dump(mode="json"),
        },
    )


def mark_portfolio(
    state: PaperState, quotes: dict[str, Quote | dict], at: datetime, policy: PaperPolicy | dict
) -> dict:
    """Marks must be explicit and fresh; missing marks never become zero prices."""
    policy = PaperPolicy.model_validate(policy)
    output = state.as_dict()
    equity = state.cash
    rows = []
    for symbol, position in sorted(state.positions.items()):
        if symbol not in quotes:
            raise PaperError("missing_quote", f"no mark supplied for {symbol}")
        quote = _quote(quotes[symbol], at, policy)
        if quote.symbol != symbol:
            raise PaperError("symbol_mismatch", "mark symbol does not match holding")
        value = position.quantity * quote.bid
        equity += value
        rows.append(
            {
                "symbol": symbol,
                "quantity": position.quantity,
                "cost_basis": str(position.cost_basis),
                "mark": str(quote.bid),
                "market_value": str(value),
                "unrealized_pnl": str(value - position.cost_basis),
                "marked_at": quote.as_of.isoformat(),
            }
        )
    output.update(
        {
            "equity": str(equity),
            "positions": rows,
            "valuation_basis": "bid liquidation mark",
            "total_pnl": str(equity - state.initial_cash),
        }
    )
    return output
