"""Read-only Alpaca stock quotes and US market sessions for the local paper ledger.

Only three fixed GET endpoints exist here; no broker order/account operation exists.
Alpaca's 2025-11-03 change reports stock quote sizes in shares, not round lots:
https://docs.alpaca.markets/us/changelog/marketdata-bid-and-ask-size-display-change
https://github.com/alpacahq/alpaca-skills/blob/main/skills/broker-api/market-data/SKILL.md
The latter also documents IEX versus SIP and calendar HH:MM fields. Older streaming
examples still describe round lots; this current-quote adapter rejects pre-change
quote timestamps instead of guessing historical per-security lot sizes.

Endpoint and calendar references:
https://docs.alpaca.markets/us/reference/stocklatestquotes-1
https://docs.alpaca.markets/us/reference/legacyclock
https://docs.alpaca.markets/us/reference/legacycalendar
https://alpaca.markets/sdks/python/api_reference/trading/models.html
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr, ValidationError

from researchdesk.paper import Quote

from .errors import DataError

QUOTE_URL = "https://data.alpaca.markets/v2/stocks/quotes/latest"
CLOCK_URL = "https://paper-api.alpaca.markets/v2/clock"
CALENDAR_URL = "https://paper-api.alpaca.markets/v2/calendar"
_ALLOWED_URLS = frozenset({QUOTE_URL, CLOCK_URL, CALENDAR_URL})
_SHARE_SIZE_START = datetime(2025, 11, 3, tzinfo=UTC)
_NEW_YORK = ZoneInfo("America/New_York")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?"
    r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)
_COVERAGE = {
    "iex": "IEX single exchange; not consolidated NBBO",
    "sip": "SIP consolidated US exchanges",
}


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware datetime is required.")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class QuoteBatch:
    observed_at: datetime
    quotes: dict[str, Quote]
    provider: str = "alpaca"
    feed: Literal["iex", "sip"] = "iex"

    def __post_init__(self):
        object.__setattr__(self, "observed_at", _utc(self.observed_at))


@dataclass(frozen=True)
class MarketClock:
    timestamp: datetime
    is_open: bool
    next_open: datetime
    next_close: datetime

    def __post_init__(self):
        if type(self.is_open) is not bool:
            raise ValueError("Market is_open must be a boolean.")
        for name in ("timestamp", "next_open", "next_close"):
            object.__setattr__(self, name, _utc(getattr(self, name)))


@dataclass(frozen=True)
class MarketSession:
    session: date
    open: datetime
    close: datetime

    def __post_init__(self):
        if type(self.session) is not date:
            raise ValueError("Session must be a date.")
        object.__setattr__(self, "open", _utc(self.open))
        object.__setattr__(self, "close", _utc(self.close))
        if self.close <= self.open:
            raise ValueError("Market close must follow open.")
        if any(
            value.astimezone(_NEW_YORK).date() != self.session for value in (self.open, self.close)
        ):
            raise ValueError("Session boundaries must belong to the stated New York date.")


class QuoteProvider(Protocol):
    def quotes(self, symbols: Sequence[str]) -> QuoteBatch: ...

    def clock(self) -> MarketClock: ...

    def calendar(self, start: date, end: date) -> list[MarketSession]: ...

    def health(self) -> dict: ...


def _timestamp(value) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value) or value.endswith("-00:00"):
        raise ValueError("Timestamp must be timezone-aware RFC3339.")
    return _utc(datetime.fromisoformat(value))


def _session_time(day: date, value) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError("Calendar time must be HH:MM in New York time.")
    hour, minute = map(int, value.split(":"))
    naive = datetime(day.year, day.month, day.day, hour, minute)
    local = naive.replace(tzinfo=_NEW_YORK)
    # Reject both non-existent spring-forward times and ambiguous fall-back times.
    if local.astimezone(UTC).astimezone(_NEW_YORK).replace(tzinfo=None) != naive:
        raise ValueError("Calendar time falls in a daylight-saving gap.")
    if local.utcoffset() != local.replace(fold=1).utcoffset():
        raise ValueError("Calendar time falls in a daylight-saving overlap.")
    return local.astimezone(UTC)


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON keys are not accepted.")
        result[name] = value
    return result


def _invalid_constant(value):
    raise ValueError("JSON contains a nonfinite value.")


class AlpacaQuoteProvider:
    """Reads current quotes, clock and calendar without any trading capability.

    Credentials remain SecretStr values and appear only in authentication headers.
    Supplying a client is intended for tests; its transport is caller-owned. The
    production client rejects environment proxies and redirects, uses normal TLS
    verification, and is closed after each bounded request. No automatic retries
    or subscription changes occur. Health reports configuration, not valid access.
    """

    def __init__(
        self,
        key: SecretStr | str,
        secret: SecretStr | str,
        feed: Literal["iex", "sip"] = "iex",
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10,
        max_bytes: int = 100_000,
    ):
        if feed not in _COVERAGE:
            raise ValueError("Only explicit iex or sip feeds are supported.")
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30
            or type(max_bytes) is not int
            or not 256 <= max_bytes <= 1_000_000
        ):
            raise ValueError("Invalid Alpaca request limits.")
        if not isinstance(key, (str, SecretStr)) or not isinstance(secret, (str, SecretStr)):
            raise ValueError("Alpaca credentials must be strings or SecretStr values.")
        self._key = key if isinstance(key, SecretStr) else SecretStr(key)
        self._secret = secret if isinstance(secret, SecretStr) else SecretStr(secret)
        self.feed, self._client = feed, client
        self.timeout_seconds, self.max_bytes = timeout_seconds, max_bytes

    def health(self) -> dict:
        def valid(value):
            raw = value.get_secret_value()
            return 1 <= len(raw) <= 512 and all(32 < ord(char) < 127 for char in raw)

        configured = valid(self._key) and valid(self._secret)
        return {
            "provider": "alpaca",
            "feed": self.feed,
            "configured": configured,
            "coverage": _COVERAGE[self.feed],
            "reason": (
                "Credentials are configured; authentication and feed access are unverified."
                if configured
                else "Configure a valid Alpaca paper API key and secret to read market data."
            ),
        }

    def _request(self, url, params=None):
        if url not in _ALLOWED_URLS:
            raise DataError("alpaca_endpoint_forbidden", "Unsupported read-only endpoint.", 400)
        if not self.health()["configured"]:
            raise DataError(
                "alpaca_unconfigured", "Alpaca quote credentials are not configured.", 409
            )
        owned = self._client is None
        client = self._client or httpx.Client(trust_env=False, follow_redirects=False)
        started = time.monotonic()
        try:
            with client.stream(
                "GET",
                url,
                params=params,
                headers={
                    "APCA-API-KEY-ID": self._key.get_secret_value(),
                    "APCA-API-SECRET-KEY": self._secret.get_secret_value(),
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "User-Agent": "ResearchDesk/0.1 read-only paper-market-data",
                },
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code == 429:
                    raise DataError(
                        "alpaca_rate_limited", "Alpaca rate limit reached; retry later.", 429
                    )
                if response.status_code in {401, 403}:
                    raise DataError(
                        "alpaca_access_denied",
                        "Alpaca rejected credentials or feed access; no subscription was changed.",
                        502,
                    )
                if response.status_code != 200:
                    raise DataError(
                        "alpaca_http_error", f"Alpaca returned HTTP {response.status_code}."
                    )
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise DataError(
                        "alpaca_encoding", "Compressed market-data responses are not accepted."
                    )
                length = response.headers.get("content-length")
                if length is not None:
                    if not length.isdigit():
                        raise DataError("alpaca_response_invalid", "Invalid response length.")
                    if int(length) > self.max_bytes:
                        raise DataError(
                            "alpaca_response_too_large",
                            "Market-data response exceeds its byte limit.",
                        )
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() - started > self.timeout_seconds:
                        raise DataError(
                            "alpaca_timeout", "Market-data request exceeded its deadline."
                        )
                    if len(body) + len(chunk) > self.max_bytes:
                        raise DataError(
                            "alpaca_response_too_large",
                            "Market-data response exceeds its byte limit.",
                        )
                    body.extend(chunk)
                if time.monotonic() - started > self.timeout_seconds:
                    raise DataError("alpaca_timeout", "Market-data request exceeded its deadline.")
            try:
                return json.loads(
                    body,
                    parse_float=Decimal,
                    parse_constant=_invalid_constant,
                    object_pairs_hook=_unique_object,
                )
            except (ValueError, UnicodeError, RecursionError):
                raise DataError(
                    "alpaca_response_invalid", "Market-data response is not valid finite JSON."
                ) from None
        except DataError:
            raise
        except httpx.TimeoutException:
            raise DataError("alpaca_timeout", "Market-data request timed out.") from None
        except (httpx.HTTPError, OSError, ValueError):
            raise DataError("alpaca_connection_failed", "Market-data connection failed.") from None
        finally:
            if owned:
                client.close()

    def quotes(self, symbols: Sequence[str]) -> QuoteBatch:
        if (
            not isinstance(symbols, Sequence)
            or isinstance(symbols, (str, bytes))
            or not 1 <= len(symbols) <= 30
            or any(
                not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol) for symbol in symbols
            )
            or len(set(symbols)) != len(symbols)
        ):
            raise DataError(
                "invalid_quote_symbols", "Provide 1–30 distinct uppercase stock symbols.", 400
            )
        data = self._request(
            QUOTE_URL, {"symbols": ",".join(symbols), "feed": self.feed, "currency": "USD"}
        )
        observed_at = datetime.now(UTC)
        if not isinstance(data, dict) or not isinstance(data.get("quotes"), dict):
            raise DataError("alpaca_quote_schema", "Alpaca did not return a quote map.")
        if data.get("currency", "USD") != "USD":
            raise DataError("alpaca_quote_schema", "Only USD-denominated quotes are supported.")
        records = data["quotes"]
        if set(records) != set(symbols):
            raise DataError(
                "alpaca_incomplete_quotes",
                "The response must include exactly the requested symbols.",
            )
        quotes = {}
        try:
            for symbol in symbols:
                row = records[symbol]
                if not isinstance(row, dict):
                    raise ValueError("Missing quote record.")
                as_of = _timestamp(row["t"])
                if as_of < _SHARE_SIZE_START:
                    raise ValueError("Pre-change quote size units are unsupported.")
                prices = [row["bp"], row["ap"]]
                if any(type(value) not in {int, Decimal} for value in prices):
                    raise ValueError("Prices must be JSON numbers.")
                if any(
                    not Decimal(value).is_finite() or not 0 < value <= 1_000_000_000
                    for value in prices
                ):
                    raise ValueError("Quote prices are invalid.")
                sizes = [row["bs"], row["as"]]
                if any(type(value) is not int or not 0 <= value <= 2**63 - 1 for value in sizes):
                    raise ValueError("Sizes must be nonnegative integer shares.")
                quotes[symbol] = Quote(
                    symbol=symbol,
                    bid=row["bp"],
                    ask=row["ap"],
                    as_of=as_of,
                    bid_size=row["bs"],
                    ask_size=row["as"],
                    source=f"Alpaca/{self.feed}; {_COVERAGE[self.feed]}; sizes=shares; "
                    f"event_time={row['t']}; {QUOTE_URL}",
                )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise DataError(
                "alpaca_quote_invalid", "Alpaca returned an invalid price, size or aware timestamp."
            ) from None
        return QuoteBatch(observed_at=observed_at, quotes=quotes, provider="alpaca", feed=self.feed)

    def clock(self) -> MarketClock:
        data = self._request(CLOCK_URL)
        try:
            if not isinstance(data, dict) or type(data["is_open"]) is not bool:
                raise ValueError("Clock must provide a strict boolean session state.")
            return MarketClock(
                timestamp=_timestamp(data["timestamp"]),
                is_open=data["is_open"],
                next_open=_timestamp(data["next_open"]),
                next_close=_timestamp(data["next_close"]),
            )
        except (KeyError, TypeError, ValueError):
            raise DataError(
                "alpaca_clock_invalid", "Alpaca returned an invalid market clock."
            ) from None

    def calendar(self, start: date, end: date) -> list[MarketSession]:
        if type(start) is not date or type(end) is not date or not 0 <= (end - start).days < 31:
            raise DataError(
                "invalid_calendar_range", "Request an inclusive range of at most 31 dates.", 400
            )
        data = self._request(CALENDAR_URL, {"start": start.isoformat(), "end": end.isoformat()})
        if not isinstance(data, list) or len(data) > 31:
            raise DataError("alpaca_calendar_invalid", "Alpaca returned an invalid session list.")
        result = []
        try:
            for row in data:
                if not isinstance(row, dict) or not isinstance(row["date"], str):
                    raise ValueError("A session date is required.")
                day = date.fromisoformat(row["date"])
                if day.isoformat() != row["date"] or not start <= day <= end:
                    raise ValueError("Session date is outside the requested range.")
                if result and day <= result[-1].session:
                    raise ValueError("Calendar must be ordered without duplicate sessions.")
                result.append(
                    MarketSession(
                        day, _session_time(day, row["open"]), _session_time(day, row["close"])
                    )
                )
        except (KeyError, TypeError, ValueError):
            raise DataError(
                "alpaca_calendar_invalid", "Alpaca returned an invalid or ambiguous market session."
            ) from None
        return result
