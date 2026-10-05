"""Bounded, read-only Tradier sandbox option observations, never execution quotes.

Official contracts checked 2026-10-05:
https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains
https://docs.tradier.com/reference/brokerage-api-markets-get-options-expirations
https://docs.tradier.com/docs/market-data
https://docs.tradier.com/reference/brokerage-api-markets-get-quotes
https://docs.tradier.com/docs/quotes

Sandbox quotes are delayed 15 minutes and have no Greeks. The current chain
example uses second-looking timestamps, whereas the current Quotes example uses
milliseconds. Only plausible millisecond epochs are normalized here; ambiguous
units remain raw with an issue. Generic quote documentation calls sizes "in
hundreds" without resolving the options convention. Sizes remain provider units,
not guessed contract liquidity. Neither contract_size=100 nor a plain OCC root
proves the deliverable. A qualified executable contract needs further evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, DecimalException

import httpx
from pydantic import SecretStr

from .errors import DataError

EXPIRATIONS_URL = "https://sandbox.tradier.com/v1/markets/options/expirations"
CHAIN_URL = "https://sandbox.tradier.com/v1/markets/options/chains"
_URLS = frozenset({EXPIRATIONS_URL, CHAIN_URL})
DELAY_SECONDS = 900
MAX_SNAPSHOT_BYTES = 1_900_000  # Leave room for application request/purpose metadata.
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9/.\-]{0,14}$")
_OPTION = re.compile(r"^([A-Z][A-Z0-9.]{0,5})(\d{6})([CP])(\d{8})$")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MIN_MILLIS = 946684800000  # 2000-01-01; current-chain acquisition, not historical replay.
_MAX_MILLIS = 4102444800000  # 2100-01-01.
_MAX_INTEGER = 2**63 - 1


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Options acquisition requires an aware clock.")
    return value.astimezone(UTC)


def _symbol(value):
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise DataError("invalid_options_symbol", "Use one uppercase underlying symbol.", 400)
    return value


def _date(value):
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            result = date.fromisoformat(value)
            if result.isoformat() == value:
                return result
        except ValueError:
            pass
    raise ValueError("An ISO YYYY-MM-DD date is required.")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys.")
        result[key] = value
    return result


def _integer(value):
    # Bound JSON conversion before Python allocates a huge integer.
    if len(value.lstrip("-")) > 19:
        raise ValueError("Oversize integer.")
    return int(value)


def _decimal(value):
    if len(value) > 80:
        raise ValueError("Oversize decimal.")
    try:
        result = Decimal(value)
    except DecimalException:
        raise ValueError("Invalid decimal.") from None
    if not result.is_finite() or not -30 <= result.as_tuple().exponent <= 30:
        raise ValueError("Nonfinite or unbounded decimal.")
    return result


def _invalid_constant(value):
    raise ValueError("Nonfinite JSON value.")


def _reject_pagination(data, envelope):
    # These two endpoints document no pagination; do not discard a new continuation.
    if any(
        key in container
        for container in (data, envelope or {})
        for key in ("next", "next_page", "next_page_token", "nextPageToken", "pagination")
    ):
        raise DataError("tradier_pagination_unsupported", "Unexpected options pagination.")


def _number(value, *, positive=False):
    if type(value) not in {int, Decimal}:
        raise ValueError("A JSON number is required.")
    result = Decimal(value)
    if not result.is_finite() or abs(result) > 1_000_000_000 or (positive and result <= 0):
        raise ValueError("Invalid numeric value.")
    return format(result, "f")


def _count(value):
    if type(value) is not int or not 0 <= value <= _MAX_INTEGER:
        raise ValueError("A nonnegative integer is required.")
    return value


def _timestamp(value, field, received_at, issues):
    if value is None:
        issues.append(f"{field}_timestamp_missing")
        return None, None
    if type(value) is not int or not 0 <= value <= _MAX_INTEGER:
        raise ValueError("Invalid timestamp type.")
    if value == 0:
        issues.append(f"{field}_timestamp_missing")
        return None, None
    if not _MIN_MILLIS <= value < _MAX_MILLIS:
        issues.append(f"{field}_timestamp_unit_unverified")
        return None, None
    timestamp = _EPOCH + timedelta(milliseconds=value)
    age = (received_at - timestamp).total_seconds()
    if age < 0:
        issues.append(f"{field}_timestamp_future")
    elif age < DELAY_SECONDS - 5:
        issues.append(f"{field}_within_nominal_delay")
    elif age > DELAY_SECONDS + 300:
        # Diagnostic, not a fill gate: illiquid/closed-market quotes may not update.
        issues.append(f"{field}_older_than_delay_window")
    return timestamp.isoformat(), age


def _contract(row, underlying, expiration, received_at):
    if not isinstance(row, dict):
        raise ValueError("Option rows must be objects.")
    symbol = row.get("symbol")
    match = _OPTION.fullmatch(symbol) if isinstance(symbol, str) else None
    if match is None or row.get("type") != "option":
        raise ValueError("An OCC option identity is required.")
    root, compact_date, right, compact_strike = match.groups()
    occ_date = date(2000 + int(compact_date[:2]), int(compact_date[2:4]), int(compact_date[4:]))
    strike = _number(row.get("strike"), positive=True)
    if (
        row.get("underlying") != underlying
        or _date(row.get("expiration_date")) != expiration
        or occ_date != expiration
        or row.get("option_type") != {"C": "call", "P": "put"}[right]
        or Decimal(strike) != Decimal(compact_strike) / 1000
        or (row.get("root_symbol") is not None and row["root_symbol"] != root)
    ):
        raise ValueError("Option identity conflicts with the requested chain or OCC symbol.")
    issues = ["contract_deliverable_unverified", "quote_size_unit_unverified"]
    contract_size = row.get("contract_size")
    if contract_size is not None:
        contract_size = _count(contract_size)
    unsupported = False
    if contract_size is None:
        issues.append("contract_size_missing")
    elif contract_size != 100:
        issues.append("nonstandard_contract_size")
        unsupported = True
    if root != underlying.replace("/", "."):
        issues.append("adjusted_or_nonmatching_root_unsupported")
        unsupported = True
    if row.get("root_symbol") is None:
        issues.append("root_metadata_missing")
    result = {
        "symbol": symbol,
        "underlying": underlying,
        "root_symbol": root,
        "option_type": row["option_type"],
        "strike": strike,
        "expiration": expiration.isoformat(),
        "contract_size": contract_size,
        "contract_status": "unsupported" if unsupported else "unverified",
        "premium_multiplier": None,
        "deliverable": None,
        "exercise_style": None,
        "settlement_type": None,
        "size_unit": "provider_reported_unverified",
        "greeks": None,
        "implied_volatility": None,
        "issues": issues,
    }
    for side in ("bid", "ask"):
        price = row.get(side)
        result[side] = _number(price) if price is not None else None
        if price is None:
            issues.append(f"{side}_missing")
        elif Decimal(result[side]) <= 0:
            issues.append(f"{side}_nonpositive")
        size = row.get(f"{side}size")
        result[f"{side}_size"] = _count(size) if size is not None else None
        if size is None:
            issues.append(f"{side}_size_missing")
        elif size == 0:
            issues.append(f"{side}_size_zero")
        raw_at = row.get(f"{side}_date")
        at, age = _timestamp(raw_at, side, received_at, issues)
        result[f"{side}_timestamp_raw"] = raw_at
        result[f"{side}_at"] = at
        result[f"{side}_age_seconds"] = age
    if result["bid"] is not None and result["ask"] is not None:
        if Decimal(result["bid"]) > Decimal(result["ask"]):
            issues.append("crossed_quote")
    if result["bid_at"] and result["ask_at"] and result["bid_at"] != result["ask_at"]:
        issues.append("asynchronous_quote_sides")
    for field in ("open_interest", "volume"):
        result[field] = _count(row[field]) if row.get(field) is not None else None
        if result[field] is None:
            issues.append(f"{field}_missing")
    # No field in this endpoint dates these measures independently. Do not call them current.
    result["open_interest_at"] = None
    result["volume_session"] = None
    return result


class TradierOptionsProvider:
    """Two fixed sandbox GETs, no broker-account or order capability.

    An injected client/clock is a test seam. Production uses verified TLS, no
    environment proxies or redirects, no automatic retries or feed fallback.
    Limits fail the acquisition rather than silently truncating a chain.
    """

    def __init__(
        self,
        token: SecretStr | str,
        *,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
        timeout_seconds: float = 10,
        max_bytes: int = 1_000_000,
        max_contracts: int = 1000,
    ):
        if not isinstance(token, (SecretStr, str)):
            raise ValueError("Tradier token must be a string or SecretStr.")
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30
            or type(max_bytes) is not int
            or not 256 <= max_bytes <= 1_500_000
            or type(max_contracts) is not int
            or not 1 <= max_contracts <= 1000
            or (now is not None and not callable(now))
        ):
            raise ValueError("Invalid Tradier acquisition limits.")
        self._token = token if isinstance(token, SecretStr) else SecretStr(token)
        self._client, self._now = client, now or (lambda: datetime.now(UTC))
        self.timeout_seconds = timeout_seconds
        self.max_bytes, self.max_contracts = max_bytes, max_contracts

    def health(self):
        raw = self._token.get_secret_value()
        configured = 1 <= len(raw) <= 512 and all(32 < ord(char) < 127 for char in raw)
        return {
            "provider": "tradier",
            "feed": "sandbox",
            "delay_seconds": DELAY_SECONDS,
            "configured": configured,
            "execution_eligible": False,
            "reason": (
                "A sandbox token is configured; authentication and data access are unverified."
                if configured
                else "Configure a Tradier sandbox token to acquire delayed options research data."
            ),
        }

    def _request(self, url, params):
        if url not in _URLS:
            raise DataError("tradier_endpoint_forbidden", "Unsupported read-only endpoint.", 400)
        if not self.health()["configured"]:
            raise DataError("tradier_unconfigured", "Tradier sandbox token is not configured.", 409)
        acquisition_started_at = _utc(self._now())
        started = time.monotonic()
        owned = self._client is None
        client = self._client or httpx.Client(trust_env=False, follow_redirects=False)
        try:
            with client.stream(
                "GET",
                url,
                params=params,
                headers={
                    "Authorization": "Bearer " + self._token.get_secret_value(),
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "User-Agent": "ResearchDesk/0.1 delayed-options-research",
                },
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code == 429:
                    raise DataError("tradier_rate_limited", "Tradier rate limit reached.", 429)
                if response.status_code in {401, 403}:
                    raise DataError(
                        "tradier_access_denied", "Tradier rejected sandbox credentials or access."
                    )
                if response.status_code != 200:
                    raise DataError(
                        "tradier_http_error", f"Tradier returned HTTP {response.status_code}."
                    )
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise DataError("tradier_encoding", "Compressed responses are not accepted.")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type != "application/json":
                    raise DataError("tradier_content_type", "Tradier did not return JSON.")
                length = response.headers.get("content-length")
                if length is not None and (not length.isdigit() or len(length) > 10):
                    raise DataError("tradier_response_invalid", "Invalid response length.")
                if length is not None and int(length) > self.max_bytes:
                    raise DataError(
                        "tradier_response_too_large", "Options response exceeds its cap."
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() - started > self.timeout_seconds:
                        raise DataError("tradier_timeout", "Options request exceeded its deadline.")
                    if len(body) + len(chunk) > self.max_bytes:
                        raise DataError(
                            "tradier_response_too_large", "Options response exceeds its cap."
                        )
                    body.extend(chunk)
                if time.monotonic() - started > self.timeout_seconds:
                    raise DataError("tradier_timeout", "Options request exceeded its deadline.")
            received_at = _utc(self._now())
            if received_at < acquisition_started_at:
                raise DataError("tradier_clock_invalid", "Acquisition clock moved backwards.")
            try:
                data = json.loads(
                    body,
                    parse_int=_integer,
                    parse_float=_decimal,
                    parse_constant=_invalid_constant,
                    object_pairs_hook=_unique_object,
                )
            except (ValueError, UnicodeError, RecursionError):
                raise DataError(
                    "tradier_response_invalid", "Invalid finite JSON response."
                ) from None
            if not isinstance(data, dict) or "error" in data or "errors" in data:
                raise DataError("tradier_response_invalid", "Tradier returned an error envelope.")
            return data, {
                "provider": "tradier",
                "feed": "sandbox",
                "delay_seconds": DELAY_SECONDS,
                "execution_eligible": False,
                "acquisition_started_at": acquisition_started_at.isoformat(),
                "received_at": received_at.isoformat(),
                "source": url,
                "request": dict(params),
                "response_sha256": hashlib.sha256(body).hexdigest(),
            }
        except DataError:
            raise
        except httpx.TimeoutException:
            raise DataError("tradier_timeout", "Tradier sandbox request timed out.") from None
        except (httpx.HTTPError, OSError, ValueError):
            raise DataError(
                "tradier_connection_failed", "Tradier sandbox connection failed."
            ) from None
        finally:
            if owned:
                client.close()

    @staticmethod
    def _bounded(snapshot):
        if (
            len(json.dumps(snapshot, ensure_ascii=True, allow_nan=False).encode())
            > MAX_SNAPSHOT_BYTES
        ):
            raise DataError("tradier_snapshot_too_large", "Normalized snapshot exceeds its cap.")
        return snapshot

    def expirations(self, underlying: str):
        underlying = _symbol(underlying)
        data, provenance = self._request(
            EXPIRATIONS_URL,
            {
                "symbol": underlying,
                "includeAllRoots": "true",
                "strikes": "false",
                "contractSize": "false",
                "expirationType": "false",
            },
        )
        try:
            if "expirations" not in data:
                raise ValueError("Missing expirations envelope.")
            envelope = data["expirations"]
            if envelope is None:
                dates = []
            elif isinstance(envelope, dict) and "date" in envelope:
                dates = envelope["date"]
                dates = [] if dates is None else [dates] if isinstance(dates, str) else dates
            else:
                raise ValueError("Invalid expirations envelope.")
            if not isinstance(dates, list) or len(dates) > 500:
                raise ValueError("Invalid expiration list.")
            _reject_pagination(data, envelope)
            parsed = [_date(value).isoformat() for value in dates]
            if len(set(parsed)) != len(parsed):
                raise ValueError("Duplicate expirations.")
        except (ValueError, TypeError):
            raise DataError("tradier_expirations_invalid", "Invalid expiration response.") from None
        return self._bounded(
            {
                "schema_version": "options_expirations.v1",
                **provenance,
                "underlying": underlying,
                "dates": sorted(parsed),
                "issues": ["market_coverage_unverified", "research_only"],
                "coverage": "Provider-returned dates; not a historical or verified full universe.",
            }
        )

    def chain(self, underlying: str, expiration: date | str):
        underlying = _symbol(underlying)
        try:
            expiration = _date(expiration)
        except ValueError:
            raise DataError(
                "invalid_options_expiration", "Use an ISO expiration date.", 400
            ) from None
        data, provenance = self._request(
            CHAIN_URL,
            {"symbol": underlying, "expiration": expiration.isoformat(), "greeks": "false"},
        )
        try:
            if "options" not in data:
                raise ValueError("Missing options envelope.")
            envelope = data["options"]
            if envelope is None:
                records = []
            elif isinstance(envelope, dict) and "option" in envelope:
                records = envelope["option"]
                records = (
                    [] if records is None else [records] if isinstance(records, dict) else records
                )
            else:
                raise ValueError("Invalid options envelope.")
            if not isinstance(records, list):
                raise ValueError("Invalid option list.")
            if len(records) > self.max_contracts:
                raise DataError("tradier_contract_limit", "Chain exceeds the contract cap.")
            _reject_pagination(data, envelope)
            contracts, identities, duplicates = [], {}, 0
            received_at = datetime.fromisoformat(provenance["received_at"])
            for record in records:
                row = _contract(record, underlying, expiration, received_at)
                previous = identities.get(row["symbol"])
                if previous is not None:
                    if previous != row:
                        raise DataError(
                            "tradier_duplicate_contract", "Conflicting duplicate option identity."
                        )
                    duplicates += 1
                    continue
                identities[row["symbol"]] = row
                contracts.append(row)
            contracts.sort(
                key=lambda row: (Decimal(row["strike"]), row["option_type"], row["symbol"])
            )
        except DataError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError):
            raise DataError(
                "tradier_chain_invalid", "Chain identity or fields are invalid."
            ) from None
        return self._bounded(
            {
                "schema_version": "options_chain.v1",
                **provenance,
                "underlying": underlying,
                "expiration": expiration.isoformat(),
                "contracts": contracts,
                "issues": [
                    "delayed_research_only",
                    "market_coverage_unverified",
                    "contract_terms_unverified",
                    "quote_size_unit_unverified",
                    "greeks_unavailable_in_sandbox",
                ],
                "coverage": {
                    "scope": "single_underlying_single_expiration",
                    "response_status": "returned" if contracts else "empty",
                    "returned_rows": len(records),
                    "retained_contracts": len(contracts),
                    "duplicate_rows_removed": duplicates,
                    "provider_universe_verified": False,
                    "atomic_snapshot": False,
                    "pagination": "not_offered_by_endpoint",
                },
                "timestamp_unit": "epoch_milliseconds_only; ambiguous units retained unnormalized",
                "freshness_policy": {
                    "diagnostic_age_seconds": DELAY_SECONDS + 300,
                    "market_session_checked": False,
                    "note": "Quote ages are diagnostic. Illiquid or closed-market quotes can be "
                    "older; the declared delay does not guarantee any quote's age or freshness.",
                },
                "limitations": [
                    "Received time is when this collector obtained the record, not market time.",
                    "No timestamp is advanced by the nominal delay; no paper fills are authorized.",
                    "Provider-returned rows do not prove exchange-wide or historical completeness.",
                    "Quote sizes retain provider units; they are not qualified contract liquidity.",
                    "Contract size does not prove premium multiplier, deliverable "
                    "or settlement terms.",
                    "Open interest date and volume session are unavailable in this response.",
                ],
            }
        )
