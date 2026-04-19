from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.config.block_signatures import BLOCK_SIGNATURES
from app.services.field_value_utils import clean_text
from app.services.network_resolution import (
    address_family_preference,
    build_async_http_client,
    should_retry_with_forced_ipv4,
)
from app.services.structured_sources import harvest_js_state_objects, parse_json_ld

logger = logging.getLogger(__name__)

_SHARED_HTTP_CLIENTS: dict[tuple[str | None, str], httpx.AsyncClient] = {}
_SHARED_HTTP_CLIENT_LOCK = asyncio.Lock()


@dataclass(slots=True)
class PageFetchResult:
    url: str
    final_url: str
    html: str
    status_code: int
    method: str
    content_type: str = "text/html"
    blocked: bool = False
    headers: httpx.Headers = field(default_factory=httpx.Headers)
    network_payloads: list[dict[str, object]] = field(default_factory=list)
    browser_diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NetworkPayloadReadResult:
    body: bytes | None
    outcome: str
    error: str | None = None


def is_retryable_http_status(status_code: int) -> bool:
    return status_code in {403, 429} or 500 <= int(status_code or 0) <= 599


def is_non_retryable_http_status(status_code: int) -> bool:
    code = int(status_code or 0)
    return 400 <= code <= 499 and code not in {403, 429}


def is_blocked_html(html: str, status_code: int) -> bool:
    if status_code in {401, 403, 429}:
        return True
    lowered = str(html or "").lower()
    if not lowered.strip():
        return False

    for item in _mapping_sequence(BLOCK_SIGNATURES.get("active_provider_markers")):
        marker = str(item.get("marker") or "").strip().lower()
        if marker and marker in lowered:
            return True

    soup = BeautifulSoup(html, "html.parser")
    for node in list(soup.find_all(["script", "style", "noscript"])):
        node.decompose()
    visible_text = clean_text(soup.get_text(" ", strip=True)).lower()
    title_text = clean_text(
        soup.title.get_text(" ", strip=True) if soup.title else ""
    ).lower()

    title_patterns = _string_sequence(BLOCK_SIGNATURES.get("title_regexes"))
    for pattern in title_patterns:
        raw_pattern = str(pattern or "").strip()
        if not raw_pattern:
            continue
        try:
            if re.search(raw_pattern, title_text, re.IGNORECASE):
                return True
        except re.error as exc:
            logger.warning(
                "Skipping invalid block signature title regex %r: %s",
                raw_pattern,
                exc,
            )

    strong_markers = [
        str(marker or "").strip().lower()
        for marker in _mapping_or_empty(
            BLOCK_SIGNATURES.get("browser_challenge_strong_markers")
        ).keys()
        if str(marker or "").strip()
    ]
    weak_markers = [
        str(marker or "").strip().lower()
        for marker in _mapping_or_empty(
            BLOCK_SIGNATURES.get("browser_challenge_weak_markers")
        ).keys()
        if str(marker or "").strip()
    ]
    provider_markers = [
        str(marker or "").strip().lower()
        for marker in _string_sequence(BLOCK_SIGNATURES.get("provider_markers"))
        if str(marker or "").strip()
    ]

    strong_hits = {
        marker for marker in strong_markers if marker in visible_text or marker in title_text
    }
    weak_hits = {
        marker for marker in weak_markers if marker in visible_text or marker in title_text
    }
    provider_hits = {marker for marker in provider_markers if marker in lowered}

    if len(strong_hits) >= 2:
        return True
    if strong_hits and provider_hits:
        return True
    if "access denied" in strong_hits:
        return True
    if "just a moment" in strong_hits and (
        "cloudflare" in provider_hits or "cf-challenge" in lowered
    ):
        return True
    return bool(strong_hits and weak_hits and provider_hits)


def should_escalate_to_browser(
    result: PageFetchResult,
    *,
    surface: str | None = None,
) -> bool:
    if is_non_retryable_http_status(result.status_code):
        return False
    if result.blocked or is_retryable_http_status(result.status_code):
        return True
    has_detail_signals = _has_extractable_detail_signals(result.html)
    if _looks_like_js_shell(result.html) and not has_detail_signals:
        return True
    if "detail" in str(surface or "").lower() and not has_detail_signals:
        return True
    return False


async def is_blocked_html_async(html: str, status_code: int) -> bool:
    return await asyncio.to_thread(is_blocked_html, html, status_code)


async def should_escalate_to_browser_async(
    result: PageFetchResult,
    *,
    surface: str | None = None,
) -> bool:
    return await asyncio.to_thread(should_escalate_to_browser, result, surface=surface)


async def get_shared_http_client(*, proxy: str | None = None) -> httpx.AsyncClient:
    family_preference = address_family_preference()
    key = (str(proxy or "").strip() or None, family_preference)
    client = _SHARED_HTTP_CLIENTS.get(key)
    if client is not None and not client.is_closed:
        return client
    async with _SHARED_HTTP_CLIENT_LOCK:
        client = _SHARED_HTTP_CLIENTS.get(key)
        if client is None or client.is_closed:
            client = build_async_http_client(
                follow_redirects=True,
                timeout=settings.http_timeout_seconds,
                limits=httpx.Limits(
                    max_connections=settings.http_max_connections,
                    max_keepalive_connections=settings.http_max_keepalive_connections,
                ),
                proxy=key[0],
            )
            _SHARED_HTTP_CLIENTS[key] = client
        return client


async def close_shared_http_client() -> None:
    async with _SHARED_HTTP_CLIENT_LOCK:
        clients = list(_SHARED_HTTP_CLIENTS.values())
        _SHARED_HTTP_CLIENTS.clear()
    for client in clients:
        if client is not None and not client.is_closed:
            await client.aclose()


async def http_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
    get_client=get_shared_http_client,
    client_builder=build_async_http_client,
    blocked_html_checker=is_blocked_html_async,
) -> PageFetchResult:
    client = await get_client(proxy=proxy)
    try:
        response = await client.get(url, timeout=timeout_seconds)
    except Exception as exc:
        if not should_retry_with_forced_ipv4(exc):
            raise
        async with client_builder(
            follow_redirects=True,
            timeout=settings.http_timeout_seconds,
            limits=httpx.Limits(
                max_connections=settings.http_max_connections,
                max_keepalive_connections=settings.http_max_keepalive_connections,
            ),
            proxy=proxy,
            force_ipv4=True,
        ) as retry_client:
            response = await retry_client.get(url, timeout=timeout_seconds)
    html = response.text or ""
    blocked = await blocked_html_checker(html, response.status_code)
    return PageFetchResult(
        url=url,
        final_url=str(response.url),
        html=html,
        status_code=response.status_code,
        method="httpx",
        content_type=response.headers.get("content-type", "text/html"),
        blocked=blocked,
        headers=copy_headers(response.headers),
    )


async def curl_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
) -> PageFetchResult:
    return await asyncio.to_thread(_curl_fetch_sync, url, timeout_seconds, proxy=proxy)


def copy_headers(headers: Any) -> httpx.Headers:
    if isinstance(headers, httpx.Headers):
        return httpx.Headers(list(headers.multi_items()))
    if hasattr(headers, "multi_items"):
        return httpx.Headers(list(headers.multi_items()))
    if isinstance(headers, dict):
        return httpx.Headers(headers)
    return httpx.Headers(list(getattr(headers, "items", lambda: [])()))


def _curl_fetch_sync(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
) -> PageFetchResult:
    from curl_cffi import requests as curl_requests

    response = curl_requests.get(
        url,
        impersonate="chrome124",
        allow_redirects=True,
        timeout=timeout_seconds,
        proxy=proxy,
    )
    html = response.text or ""
    return PageFetchResult(
        url=url,
        final_url=str(response.url),
        html=html,
        status_code=response.status_code,
        method="curl_cffi",
        content_type=response.headers.get("content-type", "text/html"),
        blocked=is_blocked_html(html, response.status_code),
        headers=copy_headers(response.headers),
    )


def _looks_like_js_shell(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    if len(clean_text(soup.get_text(" ", strip=True))) > 120:
        return False
    root = soup.find(id=re.compile(r"root|app|__next", re.I))
    scripts = soup.find_all("script")
    return root is not None and len(scripts) >= 3


def _has_extractable_detail_signals(html: str) -> bool:
    text = str(html or "")
    if not text:
        return False
    soup = BeautifulSoup(text, "html.parser")
    for payload in parse_json_ld(soup):
        if not isinstance(payload, dict):
            continue
        raw_type = payload.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        ).lower()
        if any(token in normalized_type for token in ("product", "productgroup", "jobposting")):
            return True
    js_states = harvest_js_state_objects(soup, text)
    if any(_state_payload_has_content(payload) for payload in js_states.values()):
        return True
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "shopifyanalytics.meta",
            "var meta = {\"product\"",
            "window.__remixcontext",
            "__next_data__",
            "__nuxt__",
        )
    )


def _state_payload_has_content(payload: Any) -> bool:
    if isinstance(payload, dict):
        if not payload:
            return False
        meaningful_keys = {
            key
            for key, value in payload.items()
            if value not in (None, "", [], {})
            and str(key or "").strip().lower() not in {"config", "env", "locale"}
        }
        if meaningful_keys:
            return True
        return any(_state_payload_has_content(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_state_payload_has_content(item) for item in payload[:10])
    return payload not in (None, "")


def _mapping_or_empty(value: object) -> dict[object, object]:
    return dict(value) if isinstance(value, dict) else {}


def _mapping_sequence(value: object) -> list[dict[object, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_sequence(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


async def fetch_page(*args, **kwargs):
    from app.services.crawl_fetch_runtime import fetch_page as crawl_fetch_page

    return await crawl_fetch_page(*args, **kwargs)

__all__ = [
    "NetworkPayloadReadResult",
    "PageFetchResult",
    "close_shared_http_client",
    "copy_headers",
    "curl_fetch",
    "fetch_page",
    "get_shared_http_client",
    "http_fetch",
    "is_blocked_html",
    "is_blocked_html_async",
    "is_non_retryable_http_status",
    "is_retryable_http_status",
    "should_escalate_to_browser",
    "should_escalate_to_browser_async",
]
