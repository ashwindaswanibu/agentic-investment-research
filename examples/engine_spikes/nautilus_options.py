"""Synthetic, isolated Nautilus 2.0.0rc6 feasibility experiment; not production code.

No provider, broker, ResearchDesk database or real market data is used.
Run with a separate Python environment containing exactly nautilus_trader==2.0.0rc6.
"""

import argparse
import json
import platform
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import nautilus_trader
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import LogLevel
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, StrategyConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    AggressorSide,
    AssetClass,
    Currency,
    Equity,
    InstrumentId,
    Money,
    OmsType,
    OptionContract,
    OptionKind,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TradeId,
    TradeTick,
    Venue,
)
from nautilus_trader.trading import Strategy

USD = Currency.from_str("USD")
VENUE = Venue("XTEST")
START = int(datetime(2026, 1, 16, 20, 59, 55, tzinfo=UTC).timestamp()) * 1_000_000_000
EXPIRY = START + 5_000_000_000
EQUITY_ID = InstrumentId.from_str("TEST.XTEST")
OPTION_ID = InstrumentId.from_str("TEST260116C00100000.XTEST")


def instruments():
    equity = Equity(
        instrument_id=EQUITY_ID,
        raw_symbol=Symbol("TEST"),
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        ts_event=START,
        ts_init=START,
    )
    option = OptionContract(
        instrument_id=OPTION_ID,
        raw_symbol=Symbol("TEST260116C00100000"),
        asset_class=AssetClass.EQUITY,
        underlying="TEST",
        option_kind=OptionKind.CALL,
        strike_price=Price.from_str("100.00"),
        currency=USD,
        activation_ns=START - 86_400_000_000_000,
        expiration_ns=EXPIRY,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        multiplier=Quantity.from_int(100),
        lot_size=Quantity.from_int(1),
        ts_event=START,
        ts_init=START,
    )
    return equity, option


def trade(price, timestamp, suffix):
    return TradeTick(
        instrument_id=EQUITY_ID,
        price=Price.from_str(price),
        size=Quantity.from_int(100),
        aggressor_side=AggressorSide.NO_AGGRESSOR,
        trade_id=TradeId(suffix),
        ts_event=timestamp,
        ts_init=timestamp,
    )


def quote(price, timestamp, size=1, instrument_id=OPTION_ID):
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str(price),
        ask_price=Price.from_str(price),
        bid_size=Quantity.from_int(size),
        ask_size=Quantity.from_int(size),
        ts_event=timestamp,
        ts_init=timestamp,
    )


class PartialCall(Strategy):
    def __init__(self):
        super().__init__(StrategyConfig(log_events=False, log_commands=False))
        self.submitted = False
        self.records = []
        self.identifiers = []

    def on_start(self):
        self.subscribe_quotes(OPTION_ID)
        self.subscribe_trades(EQUITY_ID)

    def on_quote(self, event):
        if not self.submitted:
            self.submitted = True
            order = self.order_factory.limit(
                instrument_id=OPTION_ID,
                order_side=OrderSide.BUY,
                quantity=Quantity.from_int(2),
                price=Price.from_str("2.00"),
            )
            self.submit_order(order)

    def on_order_filled(self, event):
        self.identifiers.append(
            {"client_order_id": str(event.client_order_id), "trade_id": str(event.trade_id)}
        )
        self.records.append(
            {
                "event": "fill",
                "instrument": str(event.instrument_id),
                "side": str(event.order_side),
                "quantity": str(event.last_qty),
                "price": str(event.last_px),
                "commission": str(event.commission),
                "ts_event": event.ts_event,
            }
        )
        if event.instrument_id == OPTION_ID and event.order_side == OrderSide.BUY:
            order = self.cache.order(event.client_order_id)
            if order.is_open:
                self.cancel_order(event.client_order_id)

    def on_order_canceled(self, event):
        self.records.append({"event": "cancel", "ts_event": event.ts_event})


def run(*, capital=20000, spot="110.00", underlying_mode="trades"):
    assert nautilus_trader.__version__ == "2.0.0rc6"
    engine = BacktestEngine(
        BacktestEngineConfig(logging=LoggerConfig(stdout_level=LogLevel.ERROR), run_analysis=False)
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=USD,
        starting_balances=[Money(capital, USD)],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
        liquidity_consumption=True,
    )
    for instrument in instruments():
        engine.add_instrument(instrument)
    tape = [
        quote("2.00", START + 1_000_000_000),
        quote("2.00", START + 2_000_000_000, size=10),
    ]
    if underlying_mode == "trades":
        tape += [
            trade("100.00", START, "initial"),
            trade(spot, EXPIRY, "at-expiry"),
            trade(spot, EXPIRY + 1_000_000_000, "after-expiry"),
        ]
    else:
        tape += [
            quote(spot, START, size=100, instrument_id=EQUITY_ID),
            quote(spot, EXPIRY, size=100, instrument_id=EQUITY_ID),
            quote(spot, EXPIRY + 1_000_000_000, size=100, instrument_id=EQUITY_ID),
        ]
        if underlying_mode == "stale_trade":
            tape.append(trade("110.00", START - 86_400_000_000_000, "prior-day-last-trade"))
    engine.add_data(tape)
    strategy = PartialCall()
    engine.add_strategy(strategy)
    error = None
    try:
        engine.run()
    except RuntimeError as exc:
        # Keep the failure, but omit random settlement UUIDs from normalized output.
        error = re.sub(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", "<uuid>", str(exc))
    account = engine.cache.account_for_venue(VENUE)
    result = {
        "synthetic": True,
        "engine": nautilus_trader.__version__,
        "capital": str(capital),
        "underlying_mode": underlying_mode,
        "terminal_underlying_price": spot,
        "error": error,
        "events": strategy.records,
        "raw_identifiers": strategy.identifiers,
        "cash": str(account.balance_total(USD).as_decimal()),
        "positions": sorted(
            [
                {
                    "instrument": str(p.instrument_id),
                    "side": str(p.side),
                    "quantity": str(p.quantity),
                    "realized_pnl": str(p.realized_pnl.as_decimal()) if p.realized_pnl else None,
                }
                for p in engine.cache.positions()
            ],
            key=lambda p: p["instrument"],
        ),
        "orders": sorted(
            [
                {
                    "instrument": str(o.instrument_id),
                    "side": str(o.side),
                    "quantity": str(o.quantity),
                    "filled_qty": str(o.filled_qty),
                    "status": str(o.status),
                    "tags": o.tags,
                }
                for o in engine.cache.orders()
            ],
            key=lambda o: (o["instrument"], o["side"]),
        ),
    }
    engine.dispose()
    return result


def economic_result(result):
    return {k: v for k, v in result.items() if k != "raw_identifiers"}


def verify():
    successful = run()
    repeated = run()
    assert economic_result(successful) == economic_result(repeated)
    assert successful["raw_identifiers"] != repeated["raw_identifiers"]
    assert successful["error"] is None
    assert Decimal(successful["cash"]) == Decimal(20000) - 2 * 100 - 100 * 100
    assert successful["positions"][0]["quantity"] == "100"
    assert successful["positions"][1]["quantity"] == "0"
    assert [event["event"] for event in successful["events"]] == ["fill", "cancel", "fill", "fill"]
    entry = next(o for o in successful["orders"] if o["status"] == "CANCELED")
    assert entry["quantity"] == "2" and entry["filled_qty"] == "1"
    expected_equity = Decimal(successful["cash"]) + Decimal(100) * Decimal(110)
    assert expected_equity == 20800 and expected_equity - Decimal(20000) == 800
    otm = run(spot="90.00")
    assert otm["error"] is None and Decimal(otm["cash"]) == 19800
    assert all(p["quantity"] == "0" for p in otm["positions"])
    shortfall = run(capital=10000)
    assert shortfall["error"] is not None and "negative" in shortfall["error"]
    assert Decimal(shortfall["cash"]) == 9800
    assert shortfall["positions"][0]["quantity"] == "100"
    quotes_only = run(underlying_mode="quotes_only")
    assert quotes_only["error"] is None and Decimal(quotes_only["cash"]) == 19800
    assert quotes_only["positions"][0]["quantity"] == "1"
    stale_trade = run(spot="90.00", underlying_mode="stale_trade")
    assert stale_trade["error"] is None and Decimal(stale_trade["cash"]) == 9800
    assert stale_trade["positions"][0]["quantity"] == "100"
    return {
        "synthetic": True,
        "production_qualified": False,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "nautilus_commit": "7b766f8825b2539c5b2ac1375e9d97b41c509edb",
        "assumptions": {
            "instrument": (
                "Unadjusted USD equity call, strike100, multiplier100, deliverable100shares"
            ),
            "fees": "Zero explicitly configured; fees are not independently qualified here",
            "execution": (
                "Synthetic bid/ask tape, liquidity_consumption=True, no latency or queue model"
            ),
            "exercise": "Expiry only; American early exercise/assignment not established",
        },
        "funded_itm": successful,
        "otm": otm,
        "funding_shortfall": shortfall,
        "missing_last_trade": quotes_only,
        "stale_last_trade": stale_trade,
        "economic_replay_equal": True,
        "settlement_identifiers_replay_equal": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save synthetic observed output as JSON")
    args = parser.parse_args()
    output = json.dumps(verify(), indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
        print(f"Six synthetic engine runs checked; results: {args.output}")
    else:
        print(output, end="")
