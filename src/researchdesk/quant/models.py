"""Immutable data and experiment contracts; money never passes through binary floats."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QuantError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Bar(StrictModel):
    session: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def valid_range(self) -> Bar:
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC range does not contain open and close")
        return self


class CorporateAction(StrictModel):
    session: date
    kind: Literal["cash_dividend", "split"]
    value: Decimal = Field(gt=0)


class MarketSnapshot(StrictModel):
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")
    source: str = Field(min_length=1, max_length=500)
    retrieved_at: datetime
    price_basis: Literal["raw_no_corporate_actions", "split_adjusted"]
    bars: tuple[Bar, ...] = Field(min_length=3, max_length=100_000)
    synthetic: bool = False
    notes: str = Field(default="", max_length=4000)
    corporate_actions_checked: bool = False
    corporate_actions: tuple[CorporateAction, ...] = ()

    @field_validator("retrieved_at")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @model_validator(mode="after")
    def ordered_sessions(self) -> MarketSnapshot:
        dates = [bar.session for bar in self.bars]
        if any(a >= b for a, b in zip(dates, dates[1:], strict=False)):
            raise ValueError("sessions must be strictly increasing and unique")
        # A completed daily bar cannot precede its own session.
        if dates[-1] > self.retrieved_at.date():
            raise ValueError("snapshot contains a future session")
        return self

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


class StrategySpec(StrictModel):
    kind: Literal["buy_hold", "cash", "sma"] = "sma"
    lookback: int = Field(default=20, ge=2, le=1000, strict=True)
    allocation: Decimal = Field(default=Decimal("0.9"), ge=0, le=1)


class BacktestSpec(StrictModel):
    initial_cash: Decimal = Field(default=Decimal("10000"), gt=0)
    fee_bps: Decimal = Field(default=Decimal("1"), ge=0, le=1000)
    slippage_bps: Decimal = Field(default=Decimal("5"), ge=0, le=1000)
    max_allocation: Decimal = Field(default=Decimal("0.95"), gt=0, le=1)
    annual_sessions: int = Field(default=252, ge=1, le=366, strict=True)


class WalkForwardSpec(StrictModel):
    train_size: int = Field(default=126, ge=5, le=10000, strict=True)
    test_size: int = Field(default=42, ge=2, le=10000, strict=True)
    lookbacks: tuple[int, ...] = (10, 20, 40)
    allocation: Decimal = Field(default=Decimal("0.9"), ge=0, le=1)
    anchored: bool = False

    @model_validator(mode="after")
    def admissible_candidates(self) -> WalkForwardSpec:
        if not 1 <= len(self.lookbacks) <= 30 or len(set(self.lookbacks)) != len(self.lookbacks):
            raise ValueError("provide 1–30 distinct lookbacks")
        if any(type(n) is not int or not 2 <= n < self.train_size for n in self.lookbacks):
            raise ValueError("each lookback must be an integer smaller than train_size")
        return self
