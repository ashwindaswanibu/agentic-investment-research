"""Synthetic HTTP fixtures verify research acquisition, never actual feed access."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from researchdesk.data import options as module
from researchdesk.data.errors import DataError
from researchdesk.data.options import CHAIN_URL, EXPIRATIONS_URL, TradierOptionsProvider

TOKEN = "SYNTHETIC_TRADIER_TOKEN_NOT_A_CREDENTIAL"
NOW = datetime(2026, 10, 5, 16, tzinfo=UTC)
EXPIRATION = date(2026, 10, 16)
QUOTE_AT = NOW - timedelta(minutes=15)
MILLIS = int(QUOTE_AT.timestamp()) * 1000
ROW = {
    "symbol": "AAPL261016C00200000",
    "type": "option",
    "underlying": "AAPL",
    "strike": 200,
    "expiration_date": "2026-10-16",
    "option_type": "call",
    "root_symbol": "AAPL",
    "contract_size": 100,
    "bid": 2.25,
    "ask": 2.35,
    "bidsize": 12,
    "asksize": 15,
    "bid_date": MILLIS,
    "ask_date": MILLIS + 1,
    "open_interest": 220,
    "volume": 17,
}


@pytest.fixture
def make_provider():
    clients = []

    def make(data=None, *, content=None, status=200, headers=None, handler=None, **kwargs):
        requests = []

        def respond(request):
            requests.append(request)
            if handler:
                return handler(request)
            if content is not None:
                return httpx.Response(
                    status,
                    content=content,
                    headers={"content-type": "application/json", **(headers or {})},
                )
            return httpx.Response(status, json=data, headers=headers)

        client = httpx.Client(
            transport=httpx.MockTransport(respond), trust_env=False, follow_redirects=True
        )
        clients.append(client)
        return (
            TradierOptionsProvider(
                SecretStr(TOKEN), client=client, now=kwargs.pop("now", lambda: NOW), **kwargs
            ),
            requests,
        )

    yield make
    for client in clients:
        client.close()


def chain_data(*rows):
    return {"options": {"option": list(rows or [ROW])}}


def test_chain_retains_distinct_market_and_receipt_times_without_shift(make_provider):
    clock = iter([NOW - timedelta(seconds=1), NOW])
    provider, requests = make_provider(chain_data(), now=lambda: next(clock))
    result = provider.chain("AAPL", EXPIRATION)
    row = result["contracts"][0]
    assert result["schema_version"] == "options_chain.v1"
    assert result["provider"] == "tradier" and result["feed"] == "sandbox"
    assert result["delay_seconds"] == 900 and result["execution_eligible"] is False
    assert result["acquisition_started_at"] == (NOW - timedelta(seconds=1)).isoformat()
    assert result["received_at"] == NOW.isoformat()
    assert row["bid_at"] == QUOTE_AT.isoformat()
    assert row["ask_at"] == (QUOTE_AT + timedelta(milliseconds=1)).isoformat()
    assert row["bid_timestamp_raw"] == MILLIS and row["ask_timestamp_raw"] == MILLIS + 1
    assert row["bid_age_seconds"] == 900
    assert row["ask_age_seconds"] == 899.999
    assert row["bid"] == "2.25" and row["ask"] == "2.35"
    assert "asynchronous_quote_sides" in row["issues"]
    assert row["bid_size"] == 12 and row["ask_size"] == 15
    assert row["size_unit"] == "provider_reported_unverified"
    assert row["contract_size"] == 100 and row["contract_status"] == "unverified"
    assert row["premium_multiplier"] is None and row["deliverable"] is None
    assert row["greeks"] is None and row["implied_volatility"] is None
    assert row["open_interest_at"] is None and row["volume_session"] is None
    assert result["coverage"]["atomic_snapshot"] is False
    assert result["coverage"]["provider_universe_verified"] is False
    assert len(result["response_sha256"]) == 64
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url.copy_with(query=None)) == CHAIN_URL
    assert dict(request.url.params) == {
        "symbol": "AAPL",
        "expiration": "2026-10-16",
        "greeks": "false",
    }
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.headers["accept-encoding"] == "identity"
    assert request.extensions["timeout"]["read"] == 10
    assert TOKEN not in json.dumps(result) and TOKEN not in str(request.url)


def test_expirations_are_bounded_provider_dates_not_a_full_market_claim(make_provider):
    provider, requests = make_provider({"expirations": {"date": ["2026-11-20", "2026-10-16"]}})
    result = provider.expirations("AAPL")
    assert result["schema_version"] == "options_expirations.v1"
    assert result["dates"] == ["2026-10-16", "2026-11-20"]
    assert result["execution_eligible"] is False
    assert "market_coverage_unverified" in result["issues"]
    assert len(requests) == 1
    assert str(requests[0].url.copy_with(query=None)) == EXPIRATIONS_URL
    assert dict(requests[0].url.params) == {
        "symbol": "AAPL",
        "includeAllRoots": "true",
        "strikes": "false",
        "contractSize": "false",
        "expirationType": "false",
    }


@pytest.mark.parametrize("envelope", [None, {"date": None}, {"date": []}])
def test_explicit_empty_expirations_remain_successful_empty(make_provider, envelope):
    provider, _ = make_provider({"expirations": envelope})
    assert provider.expirations("AAPL")["dates"] == []


def test_singleton_provider_shapes_are_supported(make_provider):
    provider, _ = make_provider({"options": {"option": ROW}})
    assert len(provider.chain("AAPL", EXPIRATION)["contracts"]) == 1
    provider, _ = make_provider({"expirations": {"date": "2026-10-16"}})
    assert provider.expirations("AAPL")["dates"] == ["2026-10-16"]


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"expirations": {}},
        {"expirations": []},
        {"expirations": {"date": ["2026-02-30"]}},
        {"expirations": {"date": [False]}},
        {"expirations": {"date": ["2026-10-16", "2026-10-16"]}},
        {"expirations": {"date": ["2026-10-16"] * 501}},
    ],
)
def test_malformed_expirations_never_become_an_empty_success(make_provider, data):
    provider, _ = make_provider(data)
    with pytest.raises(DataError) as error:
        provider.expirations("AAPL")
    assert error.value.code == "tradier_expirations_invalid"


@pytest.mark.parametrize("envelope", [None, {"option": None}, {"option": []}])
def test_explicit_empty_chain_retains_empty_coverage(make_provider, envelope):
    provider, _ = make_provider({"options": envelope})
    result = provider.chain("AAPL", EXPIRATION)
    assert result["contracts"] == []
    assert result["coverage"]["response_status"] == "empty"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"options": {}},
        {"options": []},
        {"options": "null"},
        {"options": {"option": "empty"}},
        {"options": {"option": [None]}},
    ],
)
def test_malformed_chain_is_failure_not_no_options(make_provider, data):
    provider, _ = make_provider(data)
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_chain_invalid"


def test_zero_missing_negative_crossed_and_old_quotes_remain_visible(make_provider):
    provider, _ = make_provider(
        chain_data(
            {
                **ROW,
                "bid": 0,
                "ask": None,
                "bidsize": 0,
                "asksize": None,
                "bid_date": None,
                "ask_date": 0,
                "volume": 0,
                "open_interest": None,
            }
        )
    )
    row = provider.chain("AAPL", EXPIRATION)["contracts"][0]
    assert row["bid"] == "0" and row["ask"] is None
    assert row["bid_size"] == 0 and row["ask_size"] is None
    assert row["volume"] == 0 and row["open_interest"] is None
    assert row["bid_timestamp_raw"] is None and row["ask_timestamp_raw"] == 0
    assert {
        "bid_nonpositive",
        "ask_missing",
        "bid_size_zero",
        "ask_size_missing",
        "bid_timestamp_missing",
        "ask_timestamp_missing",
        "open_interest_missing",
    } <= set(row["issues"])
    provider, _ = make_provider(
        chain_data(
            {
                **ROW,
                "bid": 3,
                "ask": -1,
                "bid_date": MILLIS - 3_600_000,
                "ask_date": int(NOW.timestamp() * 1000) + 1,
            }
        )
    )
    row = provider.chain("AAPL", EXPIRATION)["contracts"][0]
    assert {
        "crossed_quote",
        "ask_nonpositive",
        "bid_older_than_delay_window",
        "ask_timestamp_future",
    } <= set(row["issues"])
    assert row["bid_age_seconds"] == 4500


def test_feed_delay_is_a_label_not_timestamp_adjustment_or_expected_exact_age(make_provider):
    provider, _ = make_provider(chain_data({**ROW, "bid_date": int(NOW.timestamp() * 1000)}))
    result = provider.chain("AAPL", EXPIRATION)
    row = result["contracts"][0]
    assert row["bid_at"] == NOW.isoformat() and row["bid_age_seconds"] == 0
    assert "bid_within_nominal_delay" in row["issues"]
    assert result["execution_eligible"] is False
    assert result["freshness_policy"]["market_session_checked"] is False


def test_ambiguous_seconds_are_raw_not_guessed_as_current_milliseconds(make_provider):
    provider, _ = make_provider(chain_data({**ROW, "bid_date": MILLIS // 1000}))
    row = provider.chain("AAPL", EXPIRATION)["contracts"][0]
    assert row["bid_timestamp_raw"] == MILLIS // 1000
    assert row["bid_at"] is None and row["bid_age_seconds"] is None
    assert "bid_timestamp_unit_unverified" in row["issues"]


@pytest.mark.parametrize(
    "change",
    [
        {"symbol": "invalid"},
        {"type": "stock"},
        {"underlying": "MSFT"},
        {"strike": 201},
        {"strike": None},
        {"option_type": "put"},
        {"expiration_date": "2026-10-23"},
        {"symbol": "AAPL261023C00200000"},
        {"symbol": "AAPL260230C00200000"},
        {"root_symbol": "MSFT"},
        {"bid": "2.25"},
        {"ask": True},
        {"bidsize": -1},
        {"asksize": 1.5},
        {"bid_date": False},
        {"ask_date": "179"},
        {"bid_date": -1},
        {"contract_size": True},
        {"open_interest": -1},
        {"volume": False},
    ],
)
def test_conflicting_identity_and_malformed_fields_fail_atomically(make_provider, change):
    provider, _ = make_provider(chain_data({**ROW, **change}))
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_chain_invalid"


def test_adjusted_contracts_are_retained_unsupported_and_never_assumed_100_shares(make_provider):
    provider, _ = make_provider(
        chain_data(
            {
                **ROW,
                "symbol": "AAPL1261016C00200000",
                "root_symbol": "AAPL1",
                "contract_size": 10,
            }
        )
    )
    row = provider.chain("AAPL", EXPIRATION)["contracts"][0]
    assert row["contract_size"] == 10 and row["contract_status"] == "unsupported"
    assert row["deliverable"] is None and row["premium_multiplier"] is None
    assert {"nonstandard_contract_size", "adjusted_or_nonmatching_root_unsupported"} <= set(
        row["issues"]
    )


def test_missing_terms_do_not_invent_deliverable_or_classify_as_qualified(make_provider):
    value = {k: v for k, v in ROW.items() if k not in {"contract_size", "root_symbol"}}
    provider, _ = make_provider(chain_data(value))
    row = provider.chain("AAPL", EXPIRATION)["contracts"][0]
    assert row["contract_size"] is None and row["contract_status"] == "unverified"
    assert "contract_size_missing" in row["issues"] and "root_metadata_missing" in row["issues"]


def test_class_share_underlying_and_occ_root_remain_distinct(make_provider):
    provider, _ = make_provider(
        chain_data(
            {
                **ROW,
                "symbol": "BRK.B261016C00200000",
                "root_symbol": "BRK.B",
                "underlying": "BRK/B",
            }
        )
    )
    row = provider.chain("BRK/B", EXPIRATION)["contracts"][0]
    assert row["root_symbol"] == "BRK.B" and row["underlying"] == "BRK/B"
    assert "adjusted_or_nonmatching_root_unsupported" not in row["issues"]


def test_duplicate_rows_are_counted_and_conflicting_identity_never_overwritten(make_provider):
    provider, _ = make_provider(chain_data(ROW, ROW))
    result = provider.chain("AAPL", EXPIRATION)
    assert len(result["contracts"]) == 1
    assert result["coverage"]["duplicate_rows_removed"] == 1
    provider, _ = make_provider(chain_data(ROW, {**ROW, "ask": 3}))
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_duplicate_contract"


def test_price_precision_and_strike_sort_do_not_use_float(make_provider):
    content = json.dumps(chain_data()).replace('"bid": 2.25', '"bid": 2.2500000000000000001')
    provider, _ = make_provider(content=content)
    assert provider.chain("AAPL", EXPIRATION)["contracts"][0]["bid"] == "2.2500000000000000001"
    provider, _ = make_provider(
        chain_data(
            ROW, {**ROW, "symbol": "AAPL261016P00190000", "option_type": "put", "strike": 190}
        )
    )
    assert [row["strike"] for row in provider.chain("AAPL", EXPIRATION)["contracts"]] == [
        "190",
        "200",
    ]


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "tradier_access_denied"),
        (403, "tradier_access_denied"),
        (429, "tradier_rate_limited"),
        (500, "tradier_http_error"),
        (302, "tradier_http_error"),
    ],
)
def test_http_failure_is_sanitized_and_never_retried(make_provider, status, code):
    provider, requests = make_provider(
        content=TOKEN, status=status, headers={"location": "https://evil.example/steal"}
    )
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == code
    assert TOKEN not in str(error.value) and len(requests) == 1
    assert "evil.example" not in str(error.value)


@pytest.mark.parametrize(
    "error_cls,code",
    [(httpx.ReadTimeout, "tradier_timeout"), (httpx.ConnectError, "tradier_connection_failed")],
)
def test_transport_failure_does_not_expose_token(make_provider, error_cls, code):
    def fail(request):
        raise error_cls(TOKEN, request=request)

    provider, requests = make_provider(handler=fail)
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == code and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "content",
    [
        '{"options":null,"options":{}}',
        '{"options":{"option":[{"bid":NaN}]}}',
        '{"options":{"option":[{"bid":Infinity}]}}',
        '{"x":1e99999999}',
        '{"expirations":{"date":[]},"ignored":1e99999999999999999999}',
        '{"x":123456789012345678901234567890}',
        '{"errors":{"error":"secret"}}',
        '"hello"',
        "[]",
        "<html>error</html>",
        b"\xff",
        "[" * 2000 + "]" * 2000,
    ],
)
def test_malicious_or_nonfinite_json_is_rejected_without_echo(make_provider, content):
    provider, _ = make_provider(content=content)
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_response_invalid"
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "headers,code",
    [
        ({"content-type": "text/html"}, "tradier_content_type"),
        ({"content-encoding": "gzip"}, "tradier_encoding"),
        ({"content-length": "bad"}, "tradier_response_invalid"),
        ({"content-length": "99999999999999999999999999"}, "tradier_response_invalid"),
        ({"content-length": "1000001"}, "tradier_response_too_large"),
    ],
)
def test_response_headers_enforce_transport_contract(make_provider, headers, code):
    # Streaming avoids a mock response pre-decoding a deliberately false gzip header.
    def respond(_):
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"{}"),
            headers={"content-type": "application/json", **headers},
        )

    provider, _ = make_provider(handler=respond)
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == code


def test_streaming_byte_deadline_contract_and_normalized_caps(make_provider, monkeypatch):
    provider, _ = make_provider(content=" " * 300, max_bytes=256)
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_response_too_large"
    provider, _ = make_provider(chain_data(ROW, ROW), max_contracts=1)
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_contract_limit"
    provider, _ = make_provider(chain_data())
    times = iter([0, 20])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(times))
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_timeout"
    monkeypatch.undo()
    monkeypatch.setattr(module, "MAX_SNAPSHOT_BYTES", 100)
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_snapshot_too_large"


def test_unknown_pagination_is_not_a_complete_chain(make_provider):
    provider, _ = make_provider({**chain_data(), "next_page_token": "secret-next-page"})
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_pagination_unsupported"
    assert "secret-next-page" not in str(error.value)


def test_expiration_pagination_is_not_silently_discarded(make_provider):
    provider, _ = make_provider({"expirations": {"date": [], "next": "token"}})
    with pytest.raises(DataError) as error:
        provider.expirations("AAPL")
    assert error.value.code == "tradier_pagination_unsupported"


def test_chunked_response_without_length_still_has_a_byte_cap(make_provider):
    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b" " * 200
            yield b" " * 200

    provider, requests = make_provider(
        max_bytes=256,
        handler=lambda _: httpx.Response(
            200, stream=Chunks(), headers={"content-type": "application/json"}
        ),
    )
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_response_too_large"
    assert len(requests) == 1


def test_decimal_zero_is_not_accepted_as_an_integer_timestamp(make_provider):
    content = json.dumps(chain_data()).replace(f'"bid_date": {MILLIS}', '"bid_date": 0.0')
    provider, _ = make_provider(content=content)
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_chain_invalid"


@pytest.mark.parametrize("token", ["", "bad\nheader", "a b", "x" * 513])
def test_unconfigured_token_does_not_make_request_or_leak(token):
    def forbidden(_):
        pytest.fail("Unconfigured provider must not open a request")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        provider = TradierOptionsProvider(token, client=client)
        assert provider.health()["configured"] is False
        with pytest.raises(DataError) as error:
            provider.chain("AAPL", EXPIRATION)
        assert error.value.code == "tradier_unconfigured"
        assert token == "" or token not in str(error.value)


@pytest.mark.parametrize("symbol", ["aapl", "AAPL,MSFT", "../orders", "AAPL?token=x", " AAPL", ""])
def test_bad_symbols_never_reach_provider(make_provider, symbol):
    provider, requests = make_provider(chain_data())
    with pytest.raises(DataError) as error:
        provider.chain(symbol, EXPIRATION)
    assert error.value.code == "invalid_options_symbol" and requests == []


@pytest.mark.parametrize(
    "expiration", ["20261016", "2026-02-30", "2026-10-16T12:00:00Z", NOW, False]
)
def test_bad_expiration_never_reaches_provider(make_provider, expiration):
    provider, requests = make_provider(chain_data())
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", expiration)
    assert error.value.code == "invalid_options_expiration" and requests == []


def test_only_fixed_get_endpoints_are_callable(make_provider):
    provider, requests = make_provider(chain_data())
    for url in (
        "https://api.tradier.com/v1/markets/options/chains",
        "https://sandbox.tradier.com/v1/accounts/123/orders",
        "https://evil.example/",
    ):
        with pytest.raises(DataError) as error:
            provider._request(url, {})
        assert error.value.code == "tradier_endpoint_forbidden"
    assert requests == []


def test_clock_rollback_cannot_create_a_misordered_receipt(make_provider):
    clock = iter([NOW, NOW - timedelta(seconds=1)])
    provider, _ = make_provider(chain_data(), now=lambda: next(clock))
    with pytest.raises(DataError) as error:
        provider.chain("AAPL", EXPIRATION)
    assert error.value.code == "tradier_clock_invalid"


def test_client_uses_no_environment_proxies_and_is_closed(monkeypatch):
    real_client = httpx.Client
    received = {}

    def build(**kwargs):
        received.update(kwargs)
        client = real_client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=chain_data())),
            **kwargs,
        )
        received["client"] = client
        return client

    monkeypatch.setattr(module.httpx, "Client", build)
    provider = TradierOptionsProvider(TOKEN, now=lambda: NOW)
    provider.chain("AAPL", EXPIRATION)
    assert received["trust_env"] is False and received["follow_redirects"] is False
    assert received["client"].is_closed


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": False},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 31},
        {"max_bytes": 255},
        {"max_bytes": 1_500_001},
        {"max_contracts": 0},
        {"max_contracts": 1001},
        {"max_contracts": True},
        {"now": NOW},
    ],
)
def test_invalid_resource_limits_are_rejected(kwargs):
    with pytest.raises(ValueError):
        TradierOptionsProvider(TOKEN, **kwargs)


def test_normalized_1000_row_snapshot_fits_storage_budget(make_provider):
    rows = [
        {**ROW, "symbol": f"AAPL261016C{(strike * 1000):08d}", "strike": strike}
        for strike in range(1, 1001)
    ]
    provider, _ = make_provider(chain_data(*rows))
    result = provider.chain("AAPL", EXPIRATION)
    assert len(result["contracts"]) == 1000
    assert len(json.dumps(result).encode()) < module.MAX_SNAPSHOT_BYTES
    assert all(Decimal(row["strike"]) > 0 for row in result["contracts"])
