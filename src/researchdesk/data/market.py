"""Daily Yahoo Finance acquisition with declared adjustment and action semantics.

Yahoo/yfinance data is a research input, not executable broker quotes. No absent
data, provider failures or missing corporate-action columns become valid snapshots.
See https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.history.html
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from researchdesk.quant import MarketSnapshot

from .errors import DataError


def acquire_snapshot(
    symbol: str,
    start: str,
    end: str,
    *,
    ticker_factory: Callable[[str], Any] | None = None,
    now: datetime | None = None,
) -> MarketSnapshot:
    symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol):
        raise DataError("invalid_symbol", "use a single valid equity or ETF symbol")
    try:
        beginning, ending = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise DataError("invalid_date", "start and end must use YYYY-MM-DD") from exc
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise DataError("invalid_timestamp", "acquisition clock must include a timezone")
    if beginning >= ending or (ending - beginning).days > 3653:
        raise DataError("invalid_window", "choose a positive interval no longer than ten years")
    # End is exclusive; completed daily observations only, no current-session partial bar.
    if ending > now.astimezone(UTC).date():
        raise DataError("incomplete_session", "end must be today or earlier (exclusive)")
    if ticker_factory is None:
        import yfinance

        ticker_factory = yfinance.Ticker
    try:
        data = ticker_factory(symbol).history(
            start=start,
            end=end,
            interval="1d",
            auto_adjust=False,
            back_adjust=False,
            actions=True,
            repair=False,
            keepna=True,
            rounding=False,
            timeout=15,
            raise_errors=True,
        )
    except Exception as exc:
        raise DataError(
            "market_provider_failed", "Yahoo Finance history acquisition failed"
        ) from exc
    if data is None or data.empty:
        raise DataError("market_data_empty", "provider returned no daily observations")
    columns = {"Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"}
    if not columns.issubset(data.columns):
        raise DataError(
            "market_schema_changed", "provider response lacks prices or corporate-action fields"
        )
    bars, actions = [], []
    try:
        for index, row in data.iterrows():
            session = index.date()
            if not beginning <= session < ending:
                raise DataError(
                    "out_of_window_data",
                    "provider returned a session outside the requested interval",
                )
            numeric = {name: float(row[name]) for name in columns}
            if not all(math.isfinite(value) for value in numeric.values()):
                raise DataError(
                    "invalid_market_observation", "nonfinite or missing daily observation"
                )
            if "Capital Gains" in data.columns:
                distribution = float(row["Capital Gains"])
                if not math.isfinite(distribution) or distribution != 0:
                    raise DataError(
                        "unsupported_corporate_action",
                        "capital-gain distributions require accounting not implemented in v1",
                    )
            volume = numeric["Volume"]
            if volume < 0 or not volume.is_integer():
                raise DataError(
                    "invalid_market_observation", "daily volume must be a nonnegative integer"
                )
            bars.append(
                {
                    "session": session.isoformat(),
                    "open": str(row["Open"]),
                    "high": str(row["High"]),
                    "low": str(row["Low"]),
                    "close": str(row["Close"]),
                    "volume": int(volume),
                }
            )
            for name, kind in (("Dividends", "cash_dividend"), ("Stock Splits", "split")):
                value = Decimal(str(row[name]))
                if value < 0:
                    raise DataError("invalid_corporate_action", "negative corporate-action amount")
                if value:
                    actions.append(
                        {"session": session.isoformat(), "kind": kind, "value": str(value)}
                    )
        return MarketSnapshot.model_validate(
            {
                "symbol": symbol,
                "source": f"Yahoo Finance via yfinance Ticker.history; {symbol}; [{start}, {end})",
                "retrieved_at": now.isoformat(),
                "price_basis": "split_adjusted",
                "synthetic": False,
                "corporate_actions_checked": True,
                "corporate_actions": actions,
                "bars": bars,
                "notes": "Yahoo daily OHLC with auto_adjust=False; split-adjusted price history, "
                "cash dividends excluded. Action-bearing intervals are blocked by the "
                "v1 backtester. Retrospective vendor history, not an original point-in-time "
                "archive or executable quote. Provider corrections may change later downloads.",
            }
        )
    except DataError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ValidationError) as exc:
        raise DataError("invalid_market_data", "provider data failed snapshot validation") from exc
