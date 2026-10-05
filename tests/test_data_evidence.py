import hashlib

import httpx
import pytest

from researchdesk.data import DataError, fetch_evidence
from researchdesk.data.evidence import fetch_json

PUBLIC = "93.184.216.34"
HOST = "www.sec.gov"


def fetch(handler, url=f"https://{HOST}/document", **kwargs):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return fetch_evidence(
            url,
            allowed_hosts={HOST},
            client=client,
            resolver=kwargs.pop("resolver", lambda *_: [PUBLIC]),
            **kwargs,
        )


def test_dns_address_is_pinned_host_and_tls_identity_remain_original():
    body = b"<html><title>Evidence</title><script>do evil</script><p>Trial source.</p></html>"

    def handler(request):
        assert request.url.host == PUBLIC
        assert request.headers["host"] == HOST
        assert request.extensions["sni_hostname"] == HOST
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"content-type": "text/html"}, content=body)

    result = fetch(handler)
    assert result["text"] == "Evidence\nTrial source."
    assert result["url"] == f"https://{HOST}/document"
    assert result["sha256"] == hashlib.sha256(body).hexdigest()
    assert result["published_at"] is None
    assert result["untrusted_source"] is True


@pytest.mark.parametrize(
    "url",
    [
        "http://www.sec.gov/file",
        "https://www.sec.gov:444/file",
        "https://www.sec.gov.attacker.org/file",
        "https://localhost/file",
        "https://name:password@www.sec.gov/file",
        "file:///etc/passwd",
        "https://127.0.0.1/file",
        "https://www.sec.gov\\@evil.org/x",
    ],
)
def test_unsafe_urls_never_reach_network(url):
    def forbidden(_):
        pytest.fail("unsafe URL reached the transport")

    with pytest.raises(DataError):
        fetch(forbidden, url)


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "::ffff:127.0.0.1"]
)
def test_private_dns_addresses_rejected(address):
    def forbidden(_):
        pytest.fail("private address reached network")

    with pytest.raises(DataError) as error:
        fetch(forbidden, resolver=lambda *_: [PUBLIC, address])
    assert error.value.code == "private_address"


def test_redirect_targets_are_checked_before_second_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://169.254.169.254/latest/metadata"})

    with pytest.raises(DataError):
        fetch(handler)
    assert len(calls) == 1


def test_relative_redirect_preserves_provenance_and_rechecks_dns():
    hosts = []

    def resolver(host, _):
        hosts.append(host)
        return [PUBLIC]

    def handler(request):
        if request.url.path == "/document":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, text="Attributable source"
        )

    result = fetch(handler, resolver=resolver)
    assert result["url"].endswith("/final")
    assert result["redirects"] == [f"https://{HOST}/document"]
    assert hosts == [HOST, HOST]


@pytest.mark.parametrize(
    "response,code",
    [
        (
            httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 101),
            "source_too_large",
        ),
        (httpx.Response(403, text="denied"), "source_http_error"),
        (
            httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"),
            "unsupported_content_type",
        ),
        (httpx.Response(200, headers={"content-type": "text/plain"}, content=b""), "empty_source"),
    ],
)
def test_size_status_and_type_fail_closed(response, code):
    with pytest.raises(DataError) as error:
        fetch(lambda _: response, max_bytes=100)
    assert error.value.code == code


def test_streaming_limit_enforced_without_content_length():
    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b"a" * 60
            yield b"b" * 60

    def handler(_):
        return httpx.Response(200, headers={"content-type": "text/plain"}, stream=Chunks())

    with pytest.raises(DataError) as error:
        fetch(handler, max_bytes=100)
    assert error.value.code == "source_too_large"


def test_timeout_is_explicit_and_invalid_json_is_not_an_empty_object():
    def timed_out(request):
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(DataError) as error:
        fetch(timed_out)
    assert error.value.code == "fetch_timeout"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="not json"))
    ) as client:
        with pytest.raises(DataError) as error:
            fetch_json(
                f"https://{HOST}/api",
                allowed_hosts={HOST},
                client=client,
                resolver=lambda *_: [PUBLIC],
            )
    assert error.value.code == "invalid_source_json"
