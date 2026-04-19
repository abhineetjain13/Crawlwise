from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup, Comment

from app.core.config import settings
from app.services.config.block_signatures import BLOCK_SIGNATURES
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_value_utils import clean_text
from app.services.network_resolution import (
    address_family_preference,
    build_async_http_client,
    should_retry_with_forced_ipv4,
)
from app.services.structured_sources import harvest_js_state_objects, parse_json_ld

logger = logging.getLogger(__name__)

_SHARED_HTTP_CLIENTS: dict[tuple[str | None, str, bool], httpx.AsyncClient] = {}
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
    artifacts: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NetworkPayloadReadResult:
    body: bytes | None
    outcome: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BlockPageClassification:
    blocked: bool
    outcome: str
    evidence: list[str] = field(default_factory=list)
    provider_hits: list[str] = field(default_factory=list)
    active_provider_hits: list[str] = field(default_factory=list)
    strong_hits: list[str] = field(default_factory=list)
    weak_hits: list[str] = field(default_factory=list)
    title_matches: list[str] = field(default_factory=list)
    challenge_element_hits: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class HtmlAnalysis:
    html: str
    lowered_html: str
    soup: BeautifulSoup
    visible_text: str
    title_text: str


_BOT_VENDOR_HEADER_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("x-datadome",           "",          "datadome"),
    ("x-datadome-cid",       "",          "datadome"),
    ("server",               "datadome",  "datadome"),
    ("cf-mitigated",         "challenge", "cloudflare"),  # only when value = "challenge"
    ("x-sucuri-id",          "",          "sucuri"),
    ("x-sucuri-cache",       "",          "sucuri"),
    ("x-akamai-transformed", "",          "akamai"),
    ("akamai-grn",           "",          "akamai"),
    ("x-px-block",           "",          "perimeterx"),
)


def is_retryable_http_status(status_code: int) -> bool:
    return status_code in {403, 429} or 500 <= int(status_code or 0) <= 599


def is_non_retryable_http_status(status_code: int) -> bool:
    code = int(status_code or 0)
    if code == 401:
        return True
    return 400 <= code <= 499 and code not in {403, 429}


def is_blocked_html(html: str, status_code: int) -> bool:
    return classify_blocked_page(html, status_code).blocked


def classify_block_from_headers(headers: Any) -> str | None:
    if not headers:
        return None
    try:
        items = list(headers.items()) if hasattr(headers, "items") else list(headers)
    except Exception:
        return None
    normalized: dict[str, str] = {}
    for key, value in items:
        normalized[str(key or "").strip().lower()] = str(value or "").strip().lower()
    for header_name, must_contain, vendor in _BOT_VENDOR_HEADER_MARKERS:
        value = normalized.get(header_name)
        if value is None:
            continue
        if must_contain and must_contain not in value:
            continue
        return vendor
    return None


def classify_blocked_page(html: str, status_code: int) -> BlockPageClassification:
    code = int(status_code or 0)
    if code == 401:
        return BlockPageClassification(
            blocked=False,
            outcome="auth_wall",
            evidence=[f"http_status:{code}"],
        )
    if code == 429:
        return BlockPageClassification(
            blocked=True,
            outcome="rate_limited",
            evidence=[f"http_status:{code}"],
        )
    if code == 403:
        return BlockPageClassification(
            blocked=True,
            outcome="challenge_page",
            evidence=[f"http_status:{code}"],
        )
    lowered = str(html or "").lower()
    if not lowered.strip():
        return BlockPageClassification(blocked=False, outcome="empty")

    analysis = _analyze_html(html)
    soup = analysis.soup
    visible_text = analysis.visible_text.lower()
    title_text = analysis.title_text.lower()

    title_patterns = _string_sequence(BLOCK_SIGNATURES.get("title_regexes"))
    title_matches: list[str] = []
    for pattern in title_patterns:
        raw_pattern = str(pattern or "").strip()
        if not raw_pattern:
            continue
        try:
            if re.search(raw_pattern, title_text, re.IGNORECASE):
                title_matches.append(raw_pattern)
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
    active_provider_hits = {
        str(item.get("marker") or "").strip().lower()
        for item in _mapping_sequence(BLOCK_SIGNATURES.get("active_provider_markers"))
        if str(item.get("marker") or "").strip()
        and str(item.get("marker") or "").strip().lower() in lowered
    }
    challenge_element_hits = set(_challenge_element_hits(soup, lowered))
    evidence = [
        *sorted(f"title:{pattern}" for pattern in title_matches),
        *sorted(f"strong:{marker}" for marker in strong_hits),
        *sorted(f"weak:{marker}" for marker in weak_hits),
        *sorted(f"provider:{marker}" for marker in provider_hits),
        *sorted(f"active_provider:{marker}" for marker in active_provider_hits),
        *sorted(f"challenge_element:{marker}" for marker in challenge_element_hits),
    ]

    blocked = False
    if len(strong_hits) >= 2:
        blocked = True
    elif strong_hits and (
        provider_hits or active_provider_hits or challenge_element_hits or title_matches
    ):
        blocked = True
    elif "access denied" in strong_hits:
        blocked = True
    elif "just a moment" in strong_hits and (
        "cloudflare" in provider_hits
        or "cf-challenge" in provider_hits
        or "cf-browser-verification" in active_provider_hits
    ):
        blocked = True
    elif challenge_element_hits and (provider_hits or active_provider_hits):
        blocked = True
    elif title_matches and challenge_element_hits:
        blocked = True
    elif strong_hits and weak_hits and provider_hits:
        blocked = True
    return BlockPageClassification(
        blocked=blocked,
        outcome="challenge_page" if blocked else "ok",
        evidence=evidence,
        provider_hits=sorted(provider_hits),
        active_provider_hits=sorted(active_provider_hits),
        strong_hits=sorted(strong_hits),
        weak_hits=sorted(weak_hits),
        title_matches=title_matches,
        challenge_element_hits=sorted(challenge_element_hits),
    )


def should_escalate_to_browser(
    result: PageFetchResult,
    *,
    surface: str | None = None,
) -> bool:
    if is_non_retryable_http_status(result.status_code):
        return False
    if result.blocked or is_retryable_http_status(result.status_code):
        return True
    analysis = _analyze_html(result.html)
    has_detail_signals = _has_extractable_detail_signals(result.html, analysis=analysis)
    if _looks_like_js_shell(result.html, analysis=analysis) and not has_detail_signals:
        return True
    if "detail" in str(surface or "").lower() and not has_detail_signals:
        return True
    return False


async def is_blocked_html_async(html: str, status_code: int) -> bool:
    return await asyncio.to_thread(is_blocked_html, html, status_code)


async def classify_blocked_page_async(
    html: str,
    status_code: int,
) -> BlockPageClassification:
    return await asyncio.to_thread(classify_blocked_page, html, status_code)


async def should_escalate_to_browser_async(
    result: PageFetchResult,
    *,
    surface: str | None = None,
) -> bool:
    return await asyncio.to_thread(should_escalate_to_browser, result, surface=surface)


async def get_shared_http_client(
    *,
    proxy: str | None = None,
    force_ipv4: bool = False,
) -> httpx.AsyncClient:
    family_preference = address_family_preference()
    key = (str(proxy or "").strip() or None, family_preference, bool(force_ipv4))
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
                force_ipv4=bool(force_ipv4),
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
    headers = copy_headers(response.headers)
    vendor = classify_block_from_headers(headers)
    blocked = bool(vendor) or await blocked_html_checker(html, response.status_code)
    return PageFetchResult(
        url=url,
        final_url=str(response.url),
        html=html,
        status_code=response.status_code,
        method="httpx",
        content_type=response.headers.get("content-type", "text/html"),
        blocked=blocked,
        headers=headers,
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
        impersonate=crawler_runtime_settings.curl_impersonate_target,
        allow_redirects=True,
        timeout=timeout_seconds,
        proxy=proxy,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    html = response.text or ""
    headers = copy_headers(response.headers)
    vendor = classify_block_from_headers(headers)
    blocked = bool(vendor) or is_blocked_html(html, response.status_code)
    return PageFetchResult(
        url=url,
        final_url=str(response.url),
        html=html,
        status_code=response.status_code,
        method="curl_cffi",
        content_type=response.headers.get("content-type", "text/html"),
        blocked=blocked,
        headers=headers,
    )


def _looks_like_js_shell(html: str, *, analysis: HtmlAnalysis | None = None) -> bool:
    parsed = analysis or _analyze_html(html)
    if len(parsed.visible_text) > 120:
        return False
    root = parsed.soup.find(id=re.compile(r"root|app|__next", re.I))
    scripts = parsed.soup.find_all("script")
    return root is not None and len(scripts) >= 3


def _has_extractable_detail_signals(
    html: str,
    *,
    analysis: HtmlAnalysis | None = None,
) -> bool:
    parsed = analysis or _analyze_html(html)
    if not parsed.html:
        return False
    for payload in parse_json_ld(parsed.soup):
        if not isinstance(payload, dict):
            continue
        raw_type = payload.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        ).lower()
        if any(token in normalized_type for token in ("product", "productgroup", "jobposting")):
            return True
    js_states = harvest_js_state_objects(parsed.soup, parsed.html)
    if any(_state_payload_has_content(payload) for payload in js_states.values()):
        return True
    return any(
        token in parsed.lowered_html
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


def _analyze_html(html: str) -> HtmlAnalysis:
    text = str(html or "")
    soup = BeautifulSoup(text, "html.parser")
    return HtmlAnalysis(
        html=text,
        lowered_html=text.lower(),
        soup=soup,
        visible_text=_visible_text_from_soup(soup),
        title_text=clean_text(
            soup.title.get_text(" ", strip=True) if soup.title else ""
        ),
    )


def _visible_text_from_soup(soup: BeautifulSoup) -> str:
    pieces: list[str] = []
    for node in soup.find_all(string=True):
        if isinstance(node, Comment):
            continue
        parent_name = str(getattr(getattr(node, "parent", None), "name", "") or "").lower()
        if parent_name in {"script", "style", "noscript"}:
            continue
        text = clean_text(str(node))
        if text:
            pieces.append(text)
    return clean_text(" ".join(pieces))


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


def _challenge_element_hits(soup: BeautifulSoup, lowered_html: str) -> list[str]:
    hits: list[str] = []
    for iframe in list(soup.find_all("iframe")):
        src = str(iframe.get("src") or "").strip().lower()
        title = str(iframe.get("title") or "").strip().lower()
        if "captcha-delivery.com" in src:
            hits.append("captcha_delivery_iframe")
        if "captcha" in title:
            hits.append("captcha_titled_iframe")
        if "datadome" in title:
            hits.append("datadome_titled_iframe")
    for script in list(soup.find_all("script")):
        src = str(script.get("src") or "").strip().lower()
        if "captcha-delivery.com" in src:
            hits.append("captcha_delivery_script")
        if "datadome" in src:
            hits.append("datadome_script")
    if "geo.captcha-delivery.com" in lowered_html:
        hits.append("captcha_delivery_host")
    if "ct.captcha-delivery.com" in lowered_html:
        hits.append("captcha_delivery_bootstrap")
    if "title=\"datadome captcha\"" in lowered_html:
        hits.append("datadome_captcha_title")
    return hits


__all__ = [
    "BlockPageClassification",
    "NetworkPayloadReadResult",
    "classify_block_from_headers",
    "classify_blocked_page",
    "classify_blocked_page_async",
    "PageFetchResult",
    "close_shared_http_client",
    "copy_headers",
    "curl_fetch",
    "get_shared_http_client",
    "http_fetch",
    "is_blocked_html",
    "is_blocked_html_async",
    "is_non_retryable_http_status",
    "is_retryable_http_status",
    "should_escalate_to_browser",
    "should_escalate_to_browser_async",
]
