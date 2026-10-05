"""Mocked provider frames exercise ingestion contracts, not market performance."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from researchdesk.data import DataError, acquire_snapshot
from researchdesk.quant import QuantError, run_backtest


def frame():
    return pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [11.0, 12.0, 13.0],
            "Low": [9.0, 10.0, 11.0],
            "Close": [10.0, 11.0, 12.0],
            "Volume": [1000, 1100, 1200],
            "Dividends": [0.0, 0.0, 0.0],
            "Stock Splits": [0.0, 0.0, 0.0],
        },
        index=pd.date_range("2024-01-02", periods=3, tz="America/New_York"),
    )


def factory(data, calls=None):
    class FakeTicker:
        def history(self, **kwargs):
            if calls is not None:
                calls.append(kwargs)
            return data

    return lambda _: FakeTicker()


def acquire(data, calls=None):
    return acquire_snapshot(
        "TEST",
        "2024-01-01",
        "2024-01-05",
        ticker_factory=factory(data, calls),
        now=datetime(2025, 1, 1, tzinfo=UTC),
    )


def test_provider_flags_hash_and_declared_price_basis():
    calls = []
    data = acquire(frame(), calls)
    assert calls[0]["auto_adjust"] is False
    assert calls[0]["actions"] is True
    assert calls[0]["raise_errors"] is True
    assert calls[0]["keepna"] is True
    assert data.corporate_actions_checked is True
    assert data.price_basis == "split_adjusted"
    assert data.synthetic is False
    assert len(data.content_hash) == 64
    assert data.bars[0].session.isoformat() == "2024-01-02"


def test_dividend_is_retained_and_backtest_rejects_unsupported_action():
    raw = frame()
    raw.loc[raw.index[1], "Dividends"] = 0.5
    data = acquire(raw)
    assert data.corporate_actions[0].kind == "cash_dividend"
    with pytest.raises(QuantError) as error:
        run_backtest(data)
    assert error.value.code == "unsupported_corporate_action"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x.drop(columns="Stock Splits"),
        lambda x: x.assign(Close=float("nan")),
        lambda x: x.assign(Volume=1.5),
        lambda x: x.iloc[::-1],
        lambda x: x.iloc[0:0],
    ],
)
def test_invalid_provider_data_never_becomes_success(mutate):
    with pytest.raises(DataError):
        acquire(mutate(frame()))


def test_provider_exception_is_explicit_and_not_empty_data():
    class Broken:
        def history(self, **kwargs):
            raise OSError("provider unavailable")

    with pytest.raises(DataError) as error:
        acquire_snapshot("TEST", "2024-01-01", "2024-01-05", ticker_factory=lambda _: Broken())
    assert error.value.code == "market_provider_failed"


@pytest.mark.parametrize(
    "symbol,start,end",
    [
        ("../secret", "2024-01-01", "2024-02-01"),
        ("TEST", "2024-02-01", "2024-01-01"),
        ("TEST", "2025-01-01", "2025-01-03"),
    ],
)
def test_bad_symbol_dates_and_incomplete_sessions_rejected_without_provider(symbol, start, end):
    def forbidden(_):
        pytest.fail("invalid request reached provider")

    with pytest.raises(DataError):
        acquire_snapshot(
            symbol, start, end, ticker_factory=forbidden, now=datetime(2025, 1, 1, tzinfo=UTC)
        )
