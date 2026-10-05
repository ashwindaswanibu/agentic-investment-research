"""Fixed-capital paper performance from attributed observations and an explicit calendar.

No price or trading-day inference, forward filling, network, or ledger mutation.
Closing observations are near-close marks, not an official closing-auction price.
Fees are already reflected in equity; fee deltas must not be subtracted again.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ZERO = Decimal(0)
MAX_OBSERVATIONS = 100_000
MAX_SESSIONS = 2_000
CLOSE_GRACE_SECONDS = 120
CLOSE_QUOTE_TOLERANCE_SECONDS = 60
INTRADAY_QUOTE_AGE_SECONDS = 60


class PerformanceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone.")
    return value.astimezone(UTC)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class MarketSession(Contract):
    session: date
    open_at: datetime
    close_at: datetime
    timezone: str = "America/New_York"

    _times = field_validator("open_at", "close_at")(_utc)

    @model_validator(mode="after")
    def ordered(self):
        try:
            timezone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Supply a valid exchange timezone.") from exc
        if self.open_at >= self.close_at:
            raise ValueError("A session must open before it closes.")
        if any(
            t.astimezone(timezone).date() != self.session for t in (self.open_at, self.close_at)
        ):
            raise ValueError("Session timestamps must fall on the declared exchange-local date.")
        return self


class ValuationObservation(Contract):
    observation_id: str = Field(min_length=1, max_length=200)
    account_id: str = Field(min_length=1, max_length=200)
    observed_at: datetime
    account_opened_at: datetime
    market_session: date | None = None
    book_version: int = Field(ge=0, strict=True)
    event_count: int = Field(ge=1, strict=True)
    fill_count: int = Field(ge=0, strict=True)
    position_count: int = Field(ge=0, strict=True)
    initial_cash: Decimal = Field(gt=0)
    cash: Decimal = Field(ge=0)
    realized_pnl: Decimal
    fees: Decimal = Field(ge=0)
    equity: Decimal | None = Field(default=None, ge=0)
    oldest_quote_at: datetime | None = None
    missing_symbols: tuple[str, ...] = ()

    _times = field_validator("observed_at", "account_opened_at")(_utc)

    @field_validator("oldest_quote_at")
    @classmethod
    def quote_time(cls, value):
        return _utc(value) if value is not None else None

    @field_validator("initial_cash", "cash", "realized_pnl", "fees", "equity", mode="before")
    @classmethod
    def exact_money(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("Provide monetary values as Decimal, integer, or decimal strings.")
        return value

    @model_validator(mode="after")
    def opening_and_counts(self):
        if self.observed_at < self.account_opened_at:
            raise ValueError("An observation cannot precede account opening.")
        if self.fill_count >= self.event_count:
            raise ValueError("The ledger must include its opening event as well as every fill.")
        return self


def _str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _session_window(observation, session):
    return bool(
        session
        and observation.market_session == session.session
        and session.open_at
        <= observation.observed_at
        <= session.close_at + timedelta(seconds=CLOSE_GRACE_SECONDS)
    )


def _valuation_gap(observation, session):
    if observation.equity is None:
        return "missing_equity"
    if observation.missing_symbols:
        return "missing_quotes"
    if observation.position_count == 0:
        return None if observation.equity == observation.cash else "cash_equity_mismatch"
    if observation.equity < observation.cash:
        return "equity_below_cash"
    quote = observation.oldest_quote_at
    if quote is None:
        return "missing_quote_timestamp"
    if quote > observation.observed_at:
        return "future_quote"
    near_close = (
        _session_window(observation, session) and observation.observed_at >= session.close_at
    )
    cutoff = (
        session.close_at - timedelta(seconds=CLOSE_QUOTE_TOLERANCE_SECONDS)
        if near_close
        else observation.observed_at - timedelta(seconds=INTRADAY_QUOTE_AGE_SECONDS)
    )
    return "stale_quotes" if quote < cutoff else None


def _baseline(observation, equity, *, kind, session=None):
    return {
        "kind": kind,
        "session": session.isoformat() if session else None,
        "observation_id": observation.observation_id,
        "equity": equity,
        "realized_pnl": observation.realized_pnl,
        "fees": observation.fees,
        "fill_count": observation.fill_count,
    }


def _opening_baseline(observation, session):
    local_opened = observation.account_opened_at.astimezone(ZoneInfo(session.timezone))
    if local_opened.date() != session.session or observation.account_opened_at > session.close_at:
        return None
    return {
        "kind": "account_opening",
        "session": session.session.isoformat(),
        "observation_id": None,
        "equity": observation.initial_cash,
        "realized_pnl": ZERO,
        "fees": ZERO,
        "fill_count": 0,
    }


def _changes(observation, equity, baseline):
    empty = {
        "baseline": None,
        "net_pnl": None,
        "net_return": None,
        "realized_pnl_delta": None,
        "unrealized_pnl_delta": None,
        "fees_delta": None,
        "fills_delta": None,
        "movement": None,
    }
    if baseline is None:
        return empty
    realized = observation.realized_pnl - baseline["realized_pnl"]
    pnl = equity - baseline["equity"] if equity is not None else None
    fills = observation.fill_count - baseline["fill_count"]
    return {
        "baseline": {
            "kind": baseline["kind"],
            "session": baseline["session"],
            "observation_id": baseline["observation_id"],
            "equity": _str(baseline["equity"]),
        },
        "net_pnl": _str(pnl),
        "net_return": _str(pnl / baseline["equity"])
        if pnl is not None and baseline["equity"]
        else None,
        "realized_pnl_delta": _str(realized),
        "unrealized_pnl_delta": _str(pnl - realized) if pnl is not None else None,
        "fees_delta": _str(observation.fees - baseline["fees"]),
        "fills_delta": fills,
        "movement": "with_fills" if fills else "without_fills",
    }


def _prepare(observations, sessions):
    if len(observations) > MAX_OBSERVATIONS or len(sessions) > MAX_SESSIONS:
        raise PerformanceError(
            "input_limit", "Performance input exceeds its bounded history limits."
        )
    calendar = sorted((MarketSession.model_validate(s) for s in sessions), key=lambda s: s.open_at)
    if len({s.session for s in calendar}) != len(calendar):
        raise PerformanceError("duplicate_session", "Calendar sessions must have unique dates.")
    for previous, current in zip(calendar, calendar[1:], strict=False):
        if previous.close_at >= current.open_at or previous.session >= current.session:
            raise PerformanceError(
                "invalid_calendar", "Calendar sessions must be ordered and disjoint."
            )
    by_id, by_time = {}, {}
    duplicates = 0
    for raw in observations:
        item = ValuationObservation.model_validate(raw)
        previous = by_id.get(item.observation_id)
        if previous is not None:
            if previous != item:
                raise PerformanceError(
                    "conflicting_observation", "An observation ID changed content."
                )
            duplicates += 1
            continue
        by_id[item.observation_id] = item
        previous = by_time.get(item.observed_at)
        if previous is not None:
            if previous.model_dump(exclude={"observation_id"}) != item.model_dump(
                exclude={"observation_id"}
            ):
                raise PerformanceError(
                    "conflicting_observation", "Conflicting observations share a timestamp."
                )
            duplicates += 1
            if item.observation_id < previous.observation_id:
                by_time[item.observed_at] = item
        else:
            by_time[item.observed_at] = item
    ordered = sorted(by_time.values(), key=lambda item: item.observed_at)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if (current.account_id, current.account_opened_at, current.initial_cash) != (
            previous.account_id,
            previous.account_opened_at,
            previous.initial_cash,
        ):
            raise PerformanceError(
                "account_mismatch", "Use one fixed-capital account and opening event."
            )
        if any(
            getattr(current, key) < getattr(previous, key)
            for key in ("book_version", "event_count", "fill_count", "fees")
        ):
            raise PerformanceError(
                "book_regression", "Ledger counters or cumulative fees regressed."
            )
        if current.fill_count - previous.fill_count > current.event_count - previous.event_count:
            raise PerformanceError(
                "book_regression", "Fill changes exceed the retained event changes."
            )
        if current.fill_count == previous.fill_count and any(
            getattr(current, key) != getattr(previous, key)
            for key in ("cash", "realized_pnl", "fees", "position_count")
        ):
            raise PerformanceError(
                "unsupported_cashflow",
                "Book balances changed without a fill; cash flows are unsupported.",
            )
    return ordered, calendar, duplicates


def build_performance(
    observations: Sequence[ValuationObservation | dict],
    sessions: Sequence[MarketSession | dict],
    *,
    report_as_of: datetime | None = None,
) -> dict:
    """Produce JSON-safe analytics; the caller supplies a complete exchange calendar.

    Equal duplicate observations are ignored. Conflicting identities/timestamps,
    mixed accounts or regressing ledger histories fail explicitly. Market-data
    gaps remain observations whose validated equity is null. ``report_as_of``
    determines whether an absent close is still pending, without advancing the
    actual observation timestamp or valuing an unobserved period. Omission retains
    the deterministic report time of the latest observation.
    """
    ordered, calendar, duplicates = _prepare(observations, sessions)
    as_of = ordered[-1].observed_at if ordered else None
    if report_as_of is not None:
        if not isinstance(report_as_of, datetime):
            raise PerformanceError("invalid_report_time", "Report time must be an aware datetime.")
        try:
            report_as_of = _utc(report_as_of)
        except ValueError as exc:
            raise PerformanceError(
                "invalid_report_time", "Report time must include a timezone."
            ) from exc
        if as_of is not None and report_as_of < as_of:
            raise PerformanceError(
                "invalid_report_time", "Report time cannot precede the latest observation."
            )
    else:
        report_as_of = as_of
    by_session = {session.session: session for session in calendar}
    qualified, series, equities = {}, [], {}
    for observation in ordered:
        session = by_session.get(observation.market_session)
        gap = _valuation_gap(observation, session)
        equity = observation.equity if gap is None else None
        in_window = _session_window(observation, session)
        eligible = bool(
            in_window
            and gap is None
            and observation.observed_at >= session.close_at
            and observation.account_opened_at <= session.close_at
        )
        if eligible:
            qualified[session.session] = observation
        equities[observation.observation_id] = equity
        series.append(
            {
                "observation_id": observation.observation_id,
                "observed_at": observation.observed_at.isoformat(),
                "market_session": observation.market_session.isoformat()
                if observation.market_session
                else None,
                "book_version": observation.book_version,
                "event_count": observation.event_count,
                "fill_count": observation.fill_count,
                "equity": _str(equity),
                "reported_equity": _str(observation.equity),
                "cash": _str(observation.cash),
                "realized_pnl": _str(observation.realized_pnl),
                "fees": _str(observation.fees),
                "oldest_quote_at": observation.oldest_quote_at.isoformat()
                if observation.oldest_quote_at
                else None,
                "missing_symbols": list(observation.missing_symbols),
                "gap_reason": gap,
                "closing_eligible": eligible,
                "within_session_window": in_window,
            }
        )

    def baseline_for(index, observation):
        if index:
            previous_session = calendar[index - 1].session
            previous = qualified.get(previous_session)
            if previous:
                return _baseline(
                    previous, previous.equity, kind="previous_close", session=previous_session
                )
        return _opening_baseline(observation, calendar[index])

    daily = []
    for index, session in enumerate(calendar):
        closing = qualified.get(session.session)
        changes = (
            _changes(closing, closing.equity, baseline_for(index, closing))
            if closing
            else _changes(None, None, None)
        )
        close_status = (
            "qualified"
            if closing
            else "pending"
            if report_as_of is None or report_as_of < session.close_at
            else "missing"
        )
        if ordered and ordered[0].account_opened_at > session.close_at:
            close_status = "not_opened"
        daily.append(
            {
                "session": session.session.isoformat(),
                "open_at": session.open_at.isoformat(),
                "close_at": session.close_at.isoformat(),
                "close_status": close_status,
                "close_observation_id": closing.observation_id if closing else None,
                "close_observed_at": closing.observed_at.isoformat() if closing else None,
                "close_equity": _str(closing.equity) if closing else None,
                "gap_reason": None
                if changes["net_pnl"] is not None
                else ("missing_previous_close" if closing else "no_qualifying_close"),
                **changes,
            }
        )
    latest = None
    if ordered:
        observation = ordered[-1]
        equity = equities[observation.observation_id]
        session = by_session.get(observation.market_session)
        index = next(
            (i for i, s in enumerate(calendar) if session and s.session == session.session), None
        )
        baseline = (
            baseline_for(index, observation)
            if index is not None and _session_window(observation, session)
            else None
        )
        pnl = equity - observation.initial_cash if equity is not None else None
        latest = {
            **series[-1],
            "intraday": _changes(observation, equity, baseline),
            "since_opening": {
                "initial_cash": _str(observation.initial_cash),
                "net_pnl": _str(pnl),
                "net_return": _str(pnl / observation.initial_cash) if pnl is not None else None,
                "realized_pnl": _str(observation.realized_pnl),
                "unrealized_pnl": _str(pnl - observation.realized_pnl) if pnl is not None else None,
                "fees": _str(observation.fees),
            },
        }
    return {
        "account_id": ordered[0].account_id if ordered else None,
        "account_opened_at": ordered[0].account_opened_at.isoformat() if ordered else None,
        "as_of": as_of.isoformat() if as_of else None,
        "report_as_of": report_as_of.isoformat() if report_as_of else None,
        "equity_series": series,
        "daily": daily,
        "latest": latest,
        "duplicates_ignored": duplicates,
        "methodology": {
            "capital": "Fixed initial capital; deposits and withdrawals are unsupported.",
            "daily": "Close-window equity minus the preceding actual session's qualifying close.",
            "opening": "Initial cash is a baseline only on the exchange-local opening date.",
            "marks": "Close-window marks, not auction prices; missing/stale marks remain gaps.",
            "fees": "Already included in net P&L; fees_delta must not be deducted again.",
            "movement": "Fill activity does not isolate trade execution from market price effects.",
            "calendar": "Supply consecutive exchange sessions with holidays and early closes.",
            "report_time": (
                "Close availability is assessed at report_as_of; "
                "as_of remains the latest actual observation."
            ),
        },
    }
