"""Bounded HTTPS retrieval with exact host allowlisting and DNS-pinned TLS.

Source content is data, never an instruction. TLS authenticates the original
hostname while TCP connects to a previously validated public IP address. Every
redirect is independently checked; environment proxy settings are disabled.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .errors import DataError

_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="evidence-dns")


def _resolve_public(host: str, timeout: float) -> list[str]:
    future = _DNS_POOL.submit(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    try:
        addresses = sorted({row[4][0] for row in future.result(timeout=timeout)})
    except (OSError, FutureTimeout) as exc:
        future.cancel()
        raise DataError(
            "dns_failed", "source hostname could not be resolved within the deadline"
        ) from exc
    return addresses


def _validated_url(url: str, allowed_hosts: set[str]) -> tuple[str, str]:
    if len(url) > 4096 or any(ord(c) < 32 for c in url) or "\\" in url:
        raise DataError("invalid_url", "URL contains unsupported characters or is too long")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        port = parsed.port
    except (ValueError, UnicodeError) as exc:
        raise DataError("invalid_url", "source URL is malformed") from exc
    if parsed.scheme != "https" or port not in (None, 443):
        raise DataError("url_not_allowed", "only HTTPS on port 443 is permitted")
    if parsed.username is not None or parsed.password is not None or host not in allowed_hosts:
        raise DataError("host_not_allowed", "source hostname is outside the exact allowlist")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise DataError("host_not_allowed", "literal IP source URLs are not permitted")
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, "")), host


def request_bytes(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    max_bytes: int = 1_000_000,
    timeout_seconds: float = 15,
    max_redirects: int = 3,
    client: httpx.Client | None = None,
    resolver: Callable[[str, float], list[str]] = _resolve_public,
) -> dict:
    """Return a retained bounded response, or raise a stable DataError.

    Injectable client/resolver exist for deterministic network-boundary tests.
    Production creates a TLS-validating client with proxy inheritance disabled.
    """
    if not 100 <= max_bytes <= 5_000_000 or not 0 < timeout_seconds <= 60:
        raise DataError("invalid_fetch_limits", "invalid response-byte or timeout limit")
    allowed = {host.strip().lower() for host in allowed_hosts if host.strip()}
    current, original = url, url
    started = time.monotonic()
    owned = client is None
    client = client or httpx.Client(trust_env=False, follow_redirects=False)
    redirects = []
    try:
        for hop in range(max_redirects + 1):
            current, hostname = _validated_url(current, allowed)
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise DataError("fetch_timeout", "source acquisition exceeded its deadline")
            addresses = resolver(hostname, remaining)
            if not addresses:
                raise DataError("dns_failed", "source hostname has no usable public address")
            try:
                parsed_addresses = [ipaddress.ip_address(address) for address in addresses]
            except ValueError as exc:
                raise DataError("dns_failed", "resolver returned an invalid address") from exc
            if any(not address.is_global for address in parsed_addresses):
                raise DataError("private_address", "source resolved to a nonpublic address")
            # Pin the selected address in the actual connection URL. Host and SNI
            # still identify the allowed origin, avoiding a second DNS lookup.
            ip = addresses[0]
            netloc = f"[{ip}]" if ":" in ip else ip
            parsed = urlsplit(current)
            pinned_url = urlunsplit(("https", netloc, parsed.path, parsed.query, ""))
            with client.stream(
                "GET",
                pinned_url,
                headers={
                    "Host": hostname,
                    "User-Agent": "ResearchDesk/0.1 source-backed research",
                    "Accept": "text/html,text/plain,application/json,application/xml",
                    "Accept-Encoding": "identity",
                },
                extensions={"sni_hostname": hostname},
                timeout=remaining,
                follow_redirects=False,
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location or hop == max_redirects:
                        raise DataError(
                            "redirect_limit", "source redirect is missing or exceeds the limit"
                        )
                    redirects.append(current)
                    current = urljoin(current, location)
                    continue
                if response.status_code != 200:
                    raise DataError(
                        "source_http_error", f"source returned HTTP {response.status_code}"
                    )
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise DataError(
                        "unsupported_content_encoding",
                        "source ignored identity encoding; compressed payloads are not accepted",
                    )
                length = response.headers.get("content-length")
                if length is not None:
                    try:
                        if int(length) > max_bytes:
                            raise DataError(
                                "source_too_large", "source response exceeds the byte limit"
                            )
                    except ValueError as exc:
                        if isinstance(exc, DataError):
                            raise
                        raise DataError(
                            "invalid_content_length", "source sent an invalid content length"
                        ) from exc
                chunks, count = [], 0
                for chunk in response.iter_bytes(chunk_size=16384):
                    count += len(chunk)
                    if count > max_bytes:
                        raise DataError(
                            "source_too_large", "decoded source response exceeds the byte limit"
                        )
                    if time.monotonic() - started > timeout_seconds:
                        raise DataError("fetch_timeout", "source acquisition exceeded its deadline")
                    chunks.append(chunk)
                body = b"".join(chunks)
                if not body:
                    raise DataError("empty_source", "source response is empty")
                return {
                    "url": current,
                    "requested_url": original,
                    "body": body,
                    "content_type": response.headers.get("content-type", "").split(";")[0].lower(),
                    "encoding": response.encoding or "utf-8",
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "redirects": redirects,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
        raise DataError("redirect_limit", "source redirects exceeded the configured limit")
    except DataError:
        raise
    except httpx.TimeoutException as exc:
        raise DataError("fetch_timeout", "source acquisition timed out") from exc
    except httpx.HTTPError as exc:
        raise DataError("fetch_failed", "source connection or response failed") from exc
    finally:
        if owned:
            client.close()


def fetch_evidence(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    max_bytes: int = 1_000_000,
    timeout_seconds: float = 15,
    client: httpx.Client | None = None,
    resolver: Callable[[str, float], list[str]] = _resolve_public,
) -> dict:
    response = request_bytes(
        url,
        allowed_hosts=allowed_hosts,
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
        client=client,
        resolver=resolver,
    )
    mime = response["content_type"]
    if mime not in {"text/html", "text/plain", "application/json", "application/xml", "text/xml"}:
        raise DataError("unsupported_content_type", "source must return HTML, text, JSON or XML")
    try:
        text = response["body"].decode(response["encoding"], errors="replace")
    except LookupError as exc:
        raise DataError(
            "unsupported_encoding", "source declared an unsupported character encoding"
        ) from exc
    title = ""
    if mime == "text/html":
        parsed = BeautifulSoup(text, "html.parser")
        title = parsed.title.get_text(" ", strip=True) if parsed.title else ""
        for tag in parsed(["script", "style", "noscript", "svg"]):
            tag.decompose()
        text = parsed.get_text("\n", strip=True)
    if not text.strip():
        raise DataError("empty_source_text", "source has no extractable text")
    return {key: value for key, value in response.items() if key not in {"body", "encoding"}} | {
        "title": title,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "published_at": None,
        "untrusted_source": True,
        "provenance_note": "Acquisition is not publication time; text is untrusted evidence.",
    }


def fetch_json(url: str, *, allowed_hosts: Iterable[str], **kwargs) -> tuple[dict, dict]:
    response = request_bytes(url, allowed_hosts=allowed_hosts, **kwargs)
    try:
        data = json.loads(response["body"])
    except (ValueError, UnicodeDecodeError) as exc:
        raise DataError("invalid_source_json", "source did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise DataError("invalid_source_json", "source JSON must be an object")
    provenance = {key: value for key, value in response.items() if key not in {"body", "encoding"}}
    return data, provenance
