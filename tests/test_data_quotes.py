"""Synthetic HTTP fixtures test read-only market-data boundaries, never real quotes."""

import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from researchdesk.data import quotes as module
from researchdesk.data.errors import DataError
from researchdesk.data.quotes import (
    CALENDAR_URL,
    CLOCK_URL,
    QUOTE_URL,
    AlpacaQuoteProvider,
    MarketClock,
    MarketSession,
    QuoteBatch,
)

KEY = "SYNTHETIC_TEST_KEY"
SECRET = "SYNTHETIC_TEST_SECRET"
QUOTE = {
    "t": "2026-10-05T14:30:00.123456789Z",
    "bp": 100.125,
    "ap": 100.25,
    "bs": 125,
    "as": 250,
    "bx": "V",
    "ax": "V",
    "c": ["R"],
}
CLOCK = {
    "timestamp": "2026-10-05T10:30:00-04:00",
    "is_open": True,
    "next_open": "2026-10-06T09:30:00-04:00",
    "next_close": "2026-10-05T16:00:00-04:00",
}


@pytest.fixture
def make_provider():
    clients = []

    def make(
        data=None, *, status=200, content=None, headers=None, feed="iex", handler=None, **kwargs
    ):
        requests = []

        def respond(request):
            requests.append(request)
            if handler:
                return handler(request)
            if content is not None:
                return httpx.Response(status, content=content, headers=headers)
            return httpx.Response(status, json=data, headers=headers)

        client = httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False, follow_redirects=True
        )
        clients.append(client)
        provider = AlpacaQuoteProvider(
            SecretStr(KEY), SecretStr(SECRET), feed, client=client, **kwargs
        )
        return provider, requests

    yield make
    for client in clients:
        client.close()


@pytest.mark.parametrize("feed,coverage", [("iex", "single exchange"), ("sip", "consolidated US")])
def test_quotes_use_only_fixed_get_endpoint_and_current_share_units(make_provider, feed, coverage):
    data = {"quotes": {"AAPL": QUOTE, "BRK.B": {**QUOTE, "bp": 400, "ap": 401, "bs": 1, "as": 4}}}
    provider, requests = make_provider(data, feed=feed)
    before = datetime.now(UTC)
    batch = provider.quotes(["AAPL", "BRK.B"])
    after = datetime.now(UTC)
    assert before <= batch.observed_at <= after
    assert batch.provider == "alpaca" and batch.feed == feed
    assert set(batch.quotes) == {"AAPL", "BRK.B"}
    assert batch.quotes["AAPL"].bid == Decimal("100.125")
    assert batch.quotes["AAPL"].bid_size == 125
    assert batch.quotes["BRK.B"].ask_size == 4  # No historical round-lot ×100 conversion.
    assert batch.quotes["AAPL"].as_of == datetime(2026, 10, 5, 14, 30, 0, 123456, tzinfo=UTC)
    assert QUOTE["t"] in batch.quotes["AAPL"].source  # Preserve full provider nanoseconds.
    assert coverage in batch.quotes["AAPL"].source
    assert "sizes=shares" in batch.quotes["AAPL"].source
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url.copy_with(query=None)) == QUOTE_URL
    assert dict(request.url.params) == {"symbols": "AAPL,BRK.B", "feed": feed, "currency": "USD"}
    assert request.headers["APCA-API-KEY-ID"] == KEY
    assert request.headers["APCA-API-SECRET-KEY"] == SECRET
    assert SECRET not in str(request.url) and KEY not in str(request.url)
    assert request.headers["accept-encoding"] == "identity"
    assert request.extensions["timeout"]["read"] == 10
    assert len(requests) == 1


def test_prices_keep_json_decimal_precision(make_provider):
    content = (
        '{"quotes":{"AAPL":{"t":"2026-10-05T14:30:00Z",'
        '"bp":0.1000000000000000001,"ap":0.1000000000000000002,"bs":1,"as":1}}}'
    )
    provider, _ = make_provider(content=content)
    quote = provider.quotes(["AAPL"]).quotes["AAPL"]
    assert quote.bid == Decimal("0.1000000000000000001")
    assert quote.ask == Decimal("0.1000000000000000002")


@pytest.mark.parametrize(
    "symbols",
    [
        [],
        ["aapl"],
        ["AAPL", "AAPL"],
        ["../orders"],
        ["AAPL,MSFT"],
        ["A" * 16],
        "AAPL",
        [True],
        ["A" + str(i) for i in range(31)],
    ],
)
def test_symbol_limits_fail_before_any_network_request(make_provider, symbols):
    provider, requests = make_provider({})
    with pytest.raises(DataError) as error:
        provider.quotes(symbols)
    assert error.value.code == "invalid_quote_symbols"
    assert requests == []


@pytest.mark.parametrize("records", [{}, {"MSFT": QUOTE}, {"AAPL": QUOTE, "MSFT": QUOTE}])
def test_missing_or_unrequested_symbols_reject_the_entire_batch(make_provider, records):
    provider, _ = make_provider({"quotes": records})
    with pytest.raises(DataError) as error:
        provider.quotes(["AAPL"])
    assert error.value.code == "alpaca_incomplete_quotes"


@pytest.mark.parametrize(
    "field,value",
    [
        ("bp", 0),
        ("ap", 0),
        ("bp", -1),
        ("bp", 101),
        ("bp", True),
        ("bp", "100"),
        ("ap", None),
        ("bp", 1_000_000_001),
        ("bs", True),
        ("as", 1.5),
        ("bs", -1),
        ("as", "100"),
        ("bs", 2**63),
        ("t", "2026-10-05T14:30:00"),
        ("t", "2026-10-05"),
        ("t", 12345),
        ("t", "2025-10-31T14:30:00Z"),
        ("t", "2026-10-05T14:30:00+24:00"),
        ("t", "2026-10-05T14:30:00+02:60"),
        ("t", "2026-10-05T14:30:00-00:00"),
    ],
)
def test_invalid_quotes_fail_closed_without_coercing_types_or_guessing_units(
    make_provider, field, value
):
    provider, _ = make_provider({"quotes": {"AAPL": {**QUOTE, field: value}}})
    with pytest.raises(DataError) as error:
        provider.quotes(["AAPL"])
    assert error.value.code == "alpaca_quote_invalid"


def test_zero_available_shares_are_preserved_not_invented(make_provider):
    provider, _ = make_provider({"quotes": {"AAPL": {**QUOTE, "bs": 0, "as": 0}}})
    result = provider.quotes(["AAPL"]).quotes["AAPL"]
    assert result.bid_size == result.ask_size == 0


@pytest.mark.parametrize("data", [[], {}, {"quotes": None}, {"quotes": []}])
def test_malformed_quote_container_is_rejected(make_provider, data):
    provider, _ = make_provider(data)
    with pytest.raises(DataError) as error:
        provider.quotes(["AAPL"])
    assert error.value.code == "alpaca_quote_schema"


def test_clock_reads_only_the_paper_clock_and_converts_aware_times(make_provider):
    provider, requests = make_provider(CLOCK)
    result = provider.clock()
    assert result.timestamp == datetime(2026, 10, 5, 14, 30, tzinfo=UTC)
    assert result.next_close == datetime(2026, 10, 5, 20, tzinfo=UTC)
    assert result.next_open == datetime(2026, 10, 6, 13, 30, tzinfo=UTC)
    assert result.is_open is True
    assert requests[0].method == "GET" and str(requests[0].url) == CLOCK_URL


@pytest.mark.parametrize(
    "field,value",
    [
        ("is_open", 1),
        ("is_open", "true"),
        ("timestamp", "2026-10-05T10:30:00"),
        ("next_open", None),
        ("next_close", "bad"),
    ],
)
def test_clock_rejects_naive_missing_or_coerced_fields(make_provider, field, value):
    provider, _ = make_provider({**CLOCK, field: value})
    with pytest.raises(DataError) as error:
        provider.clock()
    assert error.value.code == "alpaca_clock_invalid"


def test_calendar_uses_provider_sessions_for_holiday_and_half_day(make_provider):
    # Synthetic response shape around Thanksgiving: no inferred Thursday session.
    provider, requests = make_provider(
        [
            {"date": "2026-11-25", "open": "09:30", "close": "16:00"},
            {"date": "2026-11-27", "open": "09:30", "close": "13:00"},
        ]
    )
    result = provider.calendar(date(2026, 11, 25), date(2026, 11, 27))
    assert [item.session for item in result] == [date(2026, 11, 25), date(2026, 11, 27)]
    assert result[0].close == datetime(2026, 11, 25, 21, tzinfo=UTC)
    assert result[1].close == datetime(2026, 11, 27, 18, tzinfo=UTC)
    assert str(requests[0].url.copy_with(query=None)) == CALENDAR_URL
    assert requests[0].method == "GET"
    assert dict(requests[0].url.params) == {"start": "2026-11-25", "end": "2026-11-27"}


def test_calendar_applies_new_york_dst_instead_of_fixed_offset(make_provider):
    provider, _ = make_provider(
        [
            {"date": "2026-03-06", "open": "09:30", "close": "16:00"},
            {"date": "2026-03-09", "open": "09:30", "close": "16:00"},
        ]
    )
    result = provider.calendar(date(2026, 3, 6), date(2026, 3, 9))
    assert result[0].open.hour == 14 and result[0].close.hour == 21
    assert result[1].open.hour == 13 and result[1].close.hour == 20


@pytest.mark.parametrize(
    "day,start,end", [("2026-03-08", "02:30", "16:00"), ("2026-11-01", "01:30", "16:00")]
)
def test_calendar_rejects_dst_gap_or_ambiguous_wall_clock_times(make_provider, day, start, end):
    provider, _ = make_provider([{"date": day, "open": start, "close": end}])
    with pytest.raises(DataError) as error:
        provider.calendar(date.fromisoformat(day), date.fromisoformat(day))
    assert error.value.code == "alpaca_calendar_invalid"


@pytest.mark.parametrize(
    "rows",
    [
        {},
        [{"date": "2026-10-06", "open": "09:30", "close": "16:00"}],
        [{"date": "20261005", "open": "09:30", "close": "16:00"}],
        [{"date": "2026-10-05", "open": "16:00", "close": "09:30"}],
        [{"date": "2026-10-05", "open": "0930", "close": "16:00"}],
        [{"date": "2026-10-05", "open": "09:30:00", "close": "16:00"}],
        [{"date": "2026-10-05", "open": "09:30", "close": "16:00"}] * 2,
        [None],
    ],
)
def test_calendar_rejects_malformed_out_of_range_or_duplicate_sessions(make_provider, rows):
    provider, _ = make_provider(rows)
    with pytest.raises(DataError) as error:
        provider.calendar(date(2026, 10, 5), date(2026, 10, 5))
    assert error.value.code == "alpaca_calendar_invalid"


def test_empty_calendar_is_not_filled_with_assumed_weekdays(make_provider):
    provider, _ = make_provider([])
    assert provider.calendar(date(2026, 11, 26), date(2026, 11, 26)) == []


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2026, 1, 1), date(2026, 2, 1)),
        (date(2026, 1, 2), date(2026, 1, 1)),
        ("2026-01-01", date(2026, 1, 1)),
        (datetime(2026, 1, 1, tzinfo=UTC), date(2026, 1, 1)),
    ],
)
def test_calendar_bounds_are_validated_before_request(make_provider, start, end):
    provider, requests = make_provider([])
    with pytest.raises(DataError) as error:
        provider.calendar(start, end)
    assert error.value.code == "invalid_calendar_range"
    assert not requests


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "alpaca_access_denied"),
        (403, "alpaca_access_denied"),
        (429, "alpaca_rate_limited"),
        (500, "alpaca_http_error"),
    ],
)
def test_status_errors_are_sanitized_and_never_retried(make_provider, status, code):
    provider, requests = make_provider(status=status, content=f"private body {KEY} {SECRET}")
    with pytest.raises(DataError) as error:
        provider.clock()
    assert error.value.code == code
    assert KEY not in str(error.value) and SECRET not in str(error.value)
    assert "private body" not in str(error.value)
    assert len(requests) == 1


def test_redirect_cannot_send_credentials_to_another_host(make_provider):
    provider, requests = make_provider(
        status=307, headers={"location": "https://evil.invalid/steal"}, content=""
    )
    with pytest.raises(DataError) as error:
        provider.clock()
    assert error.value.code == "alpaca_http_error"
    assert len(requests) == 1 and requests[0].url.host == "paper-api.alpaca.markets"


@pytest.mark.parametrize(
    "error_type,code",
    [(httpx.ConnectError, "alpaca_connection_failed"), (httpx.ReadTimeout, "alpaca_timeout")],
)
def test_transport_exception_does_not_leak_request_or_credentials(make_provider, error_type, code):
    def failure(request):
        raise error_type(f"private connection info {KEY} {SECRET}", request=request)

    provider, requests = make_provider(handler=failure)
    with pytest.raises(DataError) as error:
        provider.clock()
    assert error.value.code == code
    assert KEY not in repr(error.value) and SECRET not in repr(error.value)
    assert error.value.__cause__ is None
    assert len(requests) == 1


@pytest.mark.parametrize(
    "body", [b"", b"not json", b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1,"x":2}', b"\xff"]
)
def test_invalid_or_ambiguous_json_is_rejected(make_provider, body):
    provider, _ = make_provider(content=body)
    with pytest.raises(DataError) as error:
        provider.clock()
    assert error.value.code == "alpaca_response_invalid"


class ChunkFixture(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.observed = 0

    def __iter__(self):
        for chunk in self.chunks:
            self.observed += 1
            yield chunk


@pytest.mark.parametrize(
    "headers,code",
    [
        ({"content-length": "1001"}, "alpaca_response_too_large"),
        ({"content-length": "-1"}, "alpaca_response_invalid"),
        ({"content-encoding": "gzip"}, "alpaca_encoding"),
    ],
)
def test_invalid_size_headers_and_compression_fail_before_reading(make_provider, headers, code):
    stream = ChunkFixture([b"private content"])
    provider, _ = make_provider(
        handler=lambda _: httpx.Response(200, stream=stream, headers=headers), max_bytes=1000
    )
    with pytest.raises(DataError) as error:
        provider.clock()
    assert error.value.code == code
    assert stream.observed == 0


def test_actual_response_limit_stops_stream_without_trusting_missing_length(make_provider):
    stream = ChunkFixture([b"x" * 200, b"y" * 200, b"z" * 200])
    provider, _ = make_provider(handler=lambda _: httpx.Response(200, stream=stream), max_bytes=256)
    with pytest.raises(DataError) as error:
        provider.clock()
    assert error.value.code == "alpaca_response_too_large"
    assert stream.observed == 2


def test_stream_deadline_is_checked_between_chunks(make_provider, monkeypatch):
    ticks = iter([0, 11])
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    provider, _ = make_provider(CLOCK)
    with pytest.raises(DataError) as error:
        provider.clock()
    assert error.value.code == "alpaca_timeout"


def test_default_client_disables_environment_proxy_and_is_closed(monkeypatch):
    seen = {}
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=CLOCK)))

    def factory(**kwargs):
        seen.update(kwargs)
        return client

    monkeypatch.setattr(module.httpx, "Client", factory)
    provider = AlpacaQuoteProvider(KEY, SECRET)
    assert provider.clock().is_open
    assert seen == {"trust_env": False, "follow_redirects": False}
    assert client.is_closed


def test_injected_client_remains_caller_owned(make_provider):
    provider, requests = make_provider(CLOCK)
    provider.clock()
    provider.clock()
    assert len(requests) == 2 and not provider._client.is_closed


@pytest.mark.parametrize(
    "key,secret", [("", SECRET), (KEY, ""), ("has\nnewline", SECRET), (KEY, " has whitespace ")]
)
def test_missing_or_invalid_credentials_are_local_and_never_sent(make_provider, key, secret):
    provider, requests = make_provider(CLOCK)
    provider._key, provider._secret = SecretStr(key), SecretStr(secret)
    assert provider.health()["configured"] is False
    with pytest.raises(DataError) as error:
        provider.clock()
    assert error.value.code == "alpaca_unconfigured"
    assert not requests


def test_health_has_no_secrets_or_remote_auth_claim(make_provider):
    provider, requests = make_provider(CLOCK)
    health = provider.health()
    assert health["configured"] is True
    assert "unverified" in health["reason"]
    assert KEY not in json.dumps(health) and SECRET not in json.dumps(health)
    assert KEY not in repr(provider) and SECRET not in repr(provider)
    assert not requests


def test_arbitrary_endpoint_is_unavailable_even_with_credentials(make_provider):
    provider, requests = make_provider({})
    with pytest.raises(DataError) as error:
        provider._request("https://api.alpaca.markets/v2/orders")
    assert error.value.code == "alpaca_endpoint_forbidden"
    assert not requests
    assert not hasattr(provider, "order") and not hasattr(provider, "submit_order")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"feed": "delayed_sip"},
        {"timeout_seconds": 0},
        {"timeout_seconds": 31},
        {"timeout_seconds": float("nan")},
        {"max_bytes": 255},
        {"max_bytes": True},
    ],
)
def test_provider_rejects_unbounded_or_unsupported_configuration(kwargs):
    with pytest.raises(ValueError):
        AlpacaQuoteProvider(KEY, SECRET, **kwargs)


def test_typed_records_reject_naive_times_and_nonboolean_clock():
    naive = datetime(2026, 1, 1)
    aware = naive.replace(tzinfo=UTC)
    with pytest.raises(ValueError):
        QuoteBatch(naive, {})
    with pytest.raises(ValueError):
        MarketClock(aware, 1, aware, aware)
    with pytest.raises(ValueError):
        MarketSession(date(2026, 1, 1), naive, aware)


@pytest.mark.live
def test_opt_in_real_read_only_alpaca_smoke():
    if os.environ.get("RESEARCHDESK_LIVE_ALPACA") != "1":
        pytest.skip("Explicit opt-in required for real authenticated read-only Alpaca requests.")
    key = os.environ.get("RESEARCHDESK_ALPACA_API_KEY", "")
    secret = os.environ.get("RESEARCHDESK_ALPACA_SECRET_KEY", "")
    if not key or not secret:
        pytest.skip("Alpaca paper credentials are not configured in the local test environment.")
    provider = AlpacaQuoteProvider(key, secret, feed="iex")
    clock = provider.clock()
    assert clock.timestamp.tzinfo is UTC
    sessions = provider.calendar(clock.timestamp.date(), clock.timestamp.date())
    assert len(sessions) <= 1
    if clock.is_open:
        batch = provider.quotes(["SPY"])
        assert batch.quotes["SPY"].bid > 0


def test_non_usd_response_cannot_become_a_usd_paper_quote(make_provider):
    provider, _ = make_provider({"currency": "EUR", "quotes": {"AAPL": QUOTE}})
    with pytest.raises(DataError) as error:
        provider.quotes(["AAPL"])
    assert error.value.code == "alpaca_quote_schema"
