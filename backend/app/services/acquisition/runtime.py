from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
import re
from typing import Any, cast

import httpx
from bs4 import BeautifulSoup

from app.services.acquisition.browser_readiness import HtmlAnalysis, analyze_html
from app.core.config import settings
from app.services.config.block_signatures import BLOCK_SIGNATURES
from app.services.config.extraction_rules import (
    ACTION_BUY_NOW,
    BROWSER_DETAIL_READINESS_HINTS,
    DETAIL_SHELL_FRAMEWORK_TOKENS,
    DETAIL_SHELL_PRODUCT_DATA_TOKENS,
    DETAIL_SHELL_STATE_TOKENS,
    JS_REQUIRED_PLACEHOLDER_PHRASES,
    LISTING_DETAIL_URL_MARKERS,
    LISTING_CLIENT_RENDERED_SHELL_HINTS,
    LISTING_SHELL_FRAMEWORK_TOKENS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.db_utils import mapping_or_empty
from app.services.field_value_core import clean_text
from app.services.network_resolution import (
    address_family_preference,
    build_async_http_client,
    default_request_headers,
)
from app.services.platform_policy import resolve_platform_runtime_policy
from app.services.structured_sources import harvest_js_state_objects, parse_json_ld

logger = logging.getLogger(__name__)

_SHARED_HTTP_CLIENTS: dict[tuple[str | None, str], httpx.AsyncClient] = {}
_SHARED_HTTP_CLIENT_LOCK = asyncio.Lock()
_ECOMMERCE_DETAIL_READINESS_HINTS = tuple(
    str(item).strip().lower()
    for item in list(
        (
            BROWSER_DETAIL_READINESS_HINTS.get("ecommerce")
            if isinstance(BROWSER_DETAIL_READINESS_HINTS, Mapping)
            else []
        )
        or []
    )
    if str(item).strip()
)


@dataclass(slots=True)
class PageFetchResult:
    url: str
    final_url: str
    html: str
    status_code: int
    method: str
    content_type: str = "text/html"
    blocked: bool = False
    platform_family: str | None = None
    headers: httpx.Headers = field(default_factory=httpx.Headers)
    network_payloads: list[dict[str, object]] = field(default_factory=list)
    browser_diagnostics: dict[str, object] = field(default_factory=dict)
    artifacts: dict[str, object] = field(default_factory=dict)
    page_markdown: str = ""


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
    forced_blocked = False
    forced_outcome = ""
    base_evidence: list[str] = []
    if code == 401:
        return BlockPageClassification(
            blocked=False,
            outcome="auth_wall",
            evidence=[f"http_status:{code}"],
        )
    if code == 429:
        forced_blocked = True
        forced_outcome = "rate_limited"
        base_evidence.append(f"http_status:{code}")
    if code == 403:
        forced_blocked = True
        forced_outcome = "challenge_page"
        base_evidence.append(f"http_status:{code}")
    lowered = str(html or "").lower()
    if not lowered.strip():
        if forced_blocked:
            return BlockPageClassification(
                blocked=True,
                outcome=forced_outcome,
                evidence=base_evidence,
            )
        return BlockPageClassification(blocked=False, outcome="empty")

    analysis = analyze_html(html)
    soup = analysis.soup
    visible_text = analysis.visible_text.lower()
    title_text = analysis.title_text.lower()
    has_extractable_content = _has_extractable_detail_signals(
        html,
        analysis=analysis,
    ) or _has_extractable_listing_signals(
        html,
        analysis=analysis,
    )

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
        for marker in mapping_or_empty(
            BLOCK_SIGNATURES.get("browser_challenge_strong_markers")
        ).keys()
        if str(marker or "").strip()
    ]
    weak_markers = [
        str(marker or "").strip().lower()
        for marker in mapping_or_empty(
            BLOCK_SIGNATURES.get("browser_challenge_weak_markers")
        ).keys()
        if str(marker or "").strip()
    ]
    content_tolerant_strong_markers = {
        str(marker or "").strip().lower()
        for marker in _string_sequence(BLOCK_SIGNATURES.get("content_tolerant_strong_markers"))
        if str(marker or "").strip()
    }
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
    hard_strong_hits = strong_hits - content_tolerant_strong_markers
    evidence = [
        *base_evidence,
        *sorted(f"title:{pattern}" for pattern in title_matches),
        *sorted(f"strong:{marker}" for marker in strong_hits),
        *sorted(f"weak:{marker}" for marker in weak_hits),
        *sorted(f"provider:{marker}" for marker in provider_hits),
        *sorted(f"active_provider:{marker}" for marker in active_provider_hits),
        *sorted(f"challenge_element:{marker}" for marker in challenge_element_hits),
    ]

    blocked = forced_blocked
    if forced_blocked:
        blocked = True
    elif len(hard_strong_hits) >= 2:
        blocked = True
    elif hard_strong_hits and (
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
    elif hard_strong_hits and weak_hits and provider_hits:
        blocked = True
    elif (
        "captcha" in strong_hits
        and provider_hits
        and not has_extractable_content
    ):
        blocked = True
    elif "captcha" in strong_hits and provider_hits and title_matches:
        blocked = True
    if (
        blocked
        and has_extractable_content
        and not title_matches
        and "captcha" not in strong_hits
        and (
            not hard_strong_hits
            or hard_strong_hits <= {"captcha"}
        )
    ):
        blocked = False
    return BlockPageClassification(
        blocked=blocked,
        outcome=(
            forced_outcome
            if blocked and forced_blocked
            else "challenge_page" if blocked else "ok"
        ),
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
    runtime_policy: Mapping[str, Any] | None = None,
) -> bool:
    non_retryable_http_status = is_non_retryable_http_status(result.status_code)
    if result.blocked or is_retryable_http_status(result.status_code):
        return True
    resolved_policy = (
        runtime_policy
        if runtime_policy is not None
        else resolve_platform_runtime_policy(
            result.final_url or result.url,
            result.html,
            surface=surface,
        )
    )
    escalation_policy = resolved_policy.get("http_browser_escalation")
    if not isinstance(escalation_policy, Mapping):
        escalation_policy = {}
    analysis = analyze_html(result.html)
    has_detail_signals = _has_extractable_detail_signals(result.html, analysis=analysis)
    has_listing_signals = _has_extractable_listing_signals(result.html, analysis=analysis)
    if (
        bool(escalation_policy.get("js_shell_without_detail_signals", True))
        and _looks_like_js_shell(result.html, analysis=analysis)
        and not has_detail_signals
    ):
        return True
    if (
        bool(escalation_policy.get("listing_shell_without_listing_signals"))
        and not has_listing_signals
        and _looks_like_listing_shell(result, analysis=analysis)
    ):
        return True
    if non_retryable_http_status:
        return False
    if bool(escalation_policy.get("missing_detail_signals")) and not has_detail_signals:
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
    runtime_policy: Mapping[str, Any] | None = None,
) -> bool:
    return await asyncio.to_thread(
        should_escalate_to_browser,
        result,
        surface=surface,
        runtime_policy=runtime_policy,
    )


async def get_shared_http_client(
    *,
    proxy: str | None = None,
) -> httpx.AsyncClient:
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
    client_builder=None,
    blocked_html_checker=is_blocked_html_async,
) -> PageFetchResult:
    if client_builder is not None:
        get_client = client_builder
    client = await get_client(proxy=proxy)
    response = await client.get(url, timeout=timeout_seconds)
    html = response.text or ""
    headers = copy_headers(response.headers)
    vendor = classify_block_from_headers(headers)
    blocked_result = blocked_html_checker(html, response.status_code)
    if inspect.isawaitable(blocked_result):
        blocked_result = await blocked_result
    blocked = bool(vendor) or bool(blocked_result)
    runtime_policy = resolve_platform_runtime_policy(str(response.url), html)
    return PageFetchResult(
        url=url,
        final_url=str(response.url),
        html=html,
        status_code=response.status_code,
        method="httpx",
        content_type=response.headers.get("content-type", "text/html"),
        blocked=blocked,
        platform_family=runtime_policy.get("family"),
        headers=headers,
    )


async def curl_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
    cookie_header: str | None = None,
) -> PageFetchResult:
    return await asyncio.to_thread(
        _curl_fetch_sync,
        url,
        timeout_seconds,
        proxy=proxy,
        cookie_header=cookie_header,
    )


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
    cookie_header: str | None = None,
) -> PageFetchResult:
    from curl_cffi import requests as curl_requests

    raw_impersonate_target = str(
        ""
        if crawler_runtime_settings.curl_impersonate_target is None
        else crawler_runtime_settings.curl_impersonate_target
    ).strip()
    impersonate_target = cast(Any, raw_impersonate_target or None)
    request_headers = default_request_headers()
    normalized_cookie_header = str(cookie_header or "").strip()
    if normalized_cookie_header:
        request_headers["Cookie"] = normalized_cookie_header
    response = curl_requests.get(
        url,
        impersonate=impersonate_target,
        allow_redirects=True,
        timeout=timeout_seconds,
        proxy=proxy,
        headers=request_headers,
    )
    html = response.text or ""
    response_headers = copy_headers(response.headers)
    vendor = classify_block_from_headers(response_headers)
    blocked = bool(vendor) or is_blocked_html(html, response.status_code)
    runtime_policy = resolve_platform_runtime_policy(str(response.url), html)
    return PageFetchResult(
        url=url,
        final_url=str(response.url),
        html=html,
        status_code=response.status_code,
        method="curl_cffi",
        content_type=response.headers.get("content-type", "text/html"),
        blocked=blocked,
        platform_family=runtime_policy.get("family"),
        headers=response_headers,
    )


def _looks_like_js_shell(html: str, *, analysis: HtmlAnalysis | None = None) -> bool:
    parsed = analysis or analyze_html(html)
    if _looks_like_js_required_placeholder(parsed):
        return True
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
    parsed = analysis or analyze_html(html)
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
    if _has_extractable_dom_detail_signals(parsed):
        return True
    lowered_html = parsed.lowered_html
    if any(token in lowered_html for token in DETAIL_SHELL_STATE_TOKENS):
        return True
    return any(token in lowered_html for token in DETAIL_SHELL_FRAMEWORK_TOKENS) and any(
        token in lowered_html for token in DETAIL_SHELL_PRODUCT_DATA_TOKENS
    )


def _has_extractable_dom_detail_signals(analysis: HtmlAnalysis) -> bool:
    if not analysis.h1_present:
        return False
    lowered_text = analysis.normalized_text.lower()
    detail_hint_hits = sum(
        1 for hint in _ECOMMERCE_DETAIL_READINESS_HINTS if hint in lowered_text
    )
    if ACTION_BUY_NOW.strip().lower() in lowered_text:
        detail_hint_hits += 1
    has_product_anchor = bool(
        analysis.soup.find(
            attrs={
                "content": re.compile(r"\bproduct\b", re.I),
                "property": re.compile(r"og:type", re.I),
            }
        )
    )
    has_price_anchor = bool(
        analysis.soup.find(
            attrs={
                "content": re.compile(
                    r"(?:[$€£₹]\s*)?\d{1,3}(?:,\d{3})*(?:[.,]\d{1,2})?|(?:[$€£₹]\s*)?\d+(?:[.,]\d{1,2})?",
                    re.I,
                ),
                "property": re.compile(r"(?:product:)?price", re.I),
            }
        )
        or analysis.soup.find(attrs={"itemprop": re.compile(r"price", re.I)})
        or re.search(r"(?:[$€£₹]\s*)\d+(?:[.,]\d{2})?", analysis.normalized_text)
    )
    if (
        "load in the app" in lowered_text
        or "loads in the app" in lowered_text
    ) and not (has_product_anchor or has_price_anchor):
        return False
    if detail_hint_hits >= int(crawler_runtime_settings.detail_field_signal_min_count):
        if analysis.soup.select_one("main h1, article h1, [role='main'] h1"):
            return True
        return has_product_anchor or has_price_anchor
    return detail_hint_hits > 0 and has_product_anchor


def _has_extractable_listing_signals(
    html: str,
    *,
    analysis: HtmlAnalysis | None = None,
) -> bool:
    parsed = analysis or analyze_html(html)
    if not parsed.html:
        return False
    typed_listing_count = 0
    for payload in parse_json_ld(parsed.soup):
        if not isinstance(payload, dict):
            continue
        raw_type = payload.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        ).lower()
        if "itemlist" in normalized_type:
            return True
        if any(token in normalized_type for token in ("product", "jobposting")):
            typed_listing_count += 1
    if typed_listing_count >= max(2, int(crawler_runtime_settings.listing_min_items)):
        return True
    detail_like_anchor_count = 0
    for anchor in parsed.soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip().lower()
        if any(marker in href for marker in LISTING_DETAIL_URL_MARKERS):
            detail_like_anchor_count += 1
            if detail_like_anchor_count >= 3:
                return True
    return False


def _looks_like_listing_shell(
    result: PageFetchResult,
    *,
    analysis: HtmlAnalysis | None = None,
) -> bool:
    parsed = analysis or analyze_html(result.html)
    if _looks_like_js_required_placeholder(parsed):
        return True
    lowered_surface = str(result.final_url or result.url or "").strip().lower()
    lowered_html = parsed.lowered_html
    if "#/" in lowered_surface:
        return True
    if int(result.status_code or 0) == 202:
        return True
    root = parsed.soup.find(id=re.compile(r"root|app|__next", re.I))
    script_count = len(parsed.soup.find_all("script"))
    if len(parsed.visible_text) > 400:
        return any(token in lowered_html for token in LISTING_CLIENT_RENDERED_SHELL_HINTS)
    if root is None and script_count < 3:
        return False
    return any(token in lowered_html for token in LISTING_SHELL_FRAMEWORK_TOKENS)


def _looks_like_js_required_placeholder(parsed: HtmlAnalysis) -> bool:
    combined_text = clean_text(f"{parsed.title_text} {parsed.visible_text}").lower()
    if not combined_text:
        return False
    if not any(phrase in combined_text for phrase in JS_REQUIRED_PLACEHOLDER_PHRASES):
        return False
    return bool(parsed.soup.find("noscript")) or len(parsed.visible_text) <= 400


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


def _mapping_sequence(value: object) -> list[dict[object, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_sequence(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _challenge_element_hits(soup: BeautifulSoup, lowered_html: str) -> list[str]:
    challenge_elements = mapping_or_empty(BLOCK_SIGNATURES.get("challenge_elements"))
    iframe_src_markers = _marker_map_from_config(challenge_elements, "iframe_src_markers")
    iframe_title_markers = _marker_map_from_config(
        challenge_elements,
        "iframe_title_markers",
    )
    script_src_markers = _marker_map_from_config(challenge_elements, "script_src_markers")
    html_markers = _marker_map_from_config(challenge_elements, "html_markers")
    hits: list[str] = []
    for iframe in list(soup.find_all("iframe")):
        src = str(iframe.get("src") or "").strip().lower()
        title = str(iframe.get("title") or "").strip().lower()
        for marker, hit in iframe_src_markers.items():
            if marker in src:
                hits.append(hit)
        for marker, hit in iframe_title_markers.items():
            if marker in title:
                hits.append(hit)
    for script in list(soup.find_all("script")):
        src = str(script.get("src") or "").strip().lower()
        for marker, hit in script_src_markers.items():
            if marker in src:
                hits.append(hit)
    for marker, hit in html_markers.items():
        if marker in lowered_html:
            hits.append(hit)
    return hits


def _marker_map_from_config(
    source: Mapping[str, object],
    key: str,
) -> dict[str, str]:
    return {
        str(marker or "").strip().lower(): str(hit or "").strip()
        for marker, hit in mapping_or_empty(source.get(key)).items()
        if str(marker or "").strip() and str(hit or "").strip()
    }


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
