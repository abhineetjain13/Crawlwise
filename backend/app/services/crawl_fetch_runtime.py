from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.acquisition.browser_identity import build_playwright_context_options
from app.services.acquisition.traversal import (
    execute_listing_traversal,
    should_run_traversal,
)
from app.services.config.block_signatures import BLOCK_SIGNATURES
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_value_utils import clean_text, hostname
from app.services.platform_policy import resolve_platform_runtime_policy
from app.services.structured_sources import harvest_js_state_objects, parse_json_ld

logger = logging.getLogger(__name__)
_MAX_CAPTURED_NETWORK_PAYLOADS = 25
_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES = 500_000
_NETWORK_PAYLOAD_NOISE_URL_RE = re.compile(
    r"geolocation|geoip|geo/|/geo\b|\banalytics\b|tracking|telemetry|"
    r"klarna\.com|affirm\.com|afterpay\.com|olapic-cdn\.com|livechat|"
    r"zendesk\.com|intercom\.io|facebook\.com|google-analytics|"
    r"googletagmanager|sentry\.io|datadome|px\.ads|cdn-cgi/|captcha",
    re.I,
)

_BROWSER_PREFERRED_HOST_TTL_SECONDS = 1800.0
_BROWSER_PREFERRED_HOSTS: dict[str, float] = {}
_SHARED_HTTP_CLIENT: httpx.AsyncClient | None = None
_SHARED_HTTP_CLIENT_LOCK = asyncio.Lock()
_BROWSER_RUNTIME: SharedBrowserRuntime | None = None
_BROWSER_RUNTIME_LOCK = asyncio.Lock()
_DETAIL_EXPAND_SELECTORS = (
    "button, summary, details summary, "
    "[role='button'], [aria-expanded='false'], "
    "[data-testid*='expand'], [data-testid*='accordion']"
)
_DETAIL_EXPAND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ecommerce": (
        "about",
        "compatibility",
        "description",
        "details",
        "dimensions",
        "more",
        "product",
        "read more",
        "show more",
        "spec",
        "view more",
    ),
    "job": (
        "benefits",
        "compensation",
        "description",
        "more",
        "qualifications",
        "requirements",
        "responsibilities",
        "salary",
        "see more",
        "show all",
    ),
}

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright


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


class SharedBrowserRuntime:
    def __init__(self, *, max_contexts: int) -> None:
        self.max_contexts = max(1, int(max_contexts))
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(self.max_contexts)
        self._lock = asyncio.Lock()
        self._active_contexts = 0

    async def _ensure(self) -> None:
        if self._browser is not None and getattr(
            self._browser,
            "is_connected",
            lambda: True,
        )():
            return
        async with self._lock:
            if self._browser is not None and getattr(
                self._browser,
                "is_connected",
                lambda: True,
            )():
                return
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=settings.playwright_headless,
            )

    @asynccontextmanager
    async def page(self):
        await self._ensure()
        await self._semaphore.acquire()
        if self._browser is None:
            self._semaphore.release()
            raise RuntimeError("Browser runtime failed to initialize")
        context: BrowserContext | None = None
        page: Page | None = None
        self._active_contexts += 1
        try:
            context = await self._browser.new_context(
                **build_playwright_context_options()
            )
            page = await context.new_page()
            yield page
        finally:
            self._active_contexts = max(0, self._active_contexts - 1)
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    logger.debug("Failed to close browser context", exc_info=True)
            self._semaphore.release()

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    logger.debug("Failed to close browser", exc_info=True)
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    logger.debug("Failed to stop playwright", exc_info=True)
            self._browser = None
            self._playwright = None

    def snapshot(self) -> dict[str, int | bool]:
        queued = max(0, -int(getattr(self._semaphore, "_value", 0)))
        return {
            "ready": self._browser is not None,
            "size": self._active_contexts,
            "max_size": self.max_contexts,
            "active": self._active_contexts,
            "queued": queued,
            "capacity": self.max_contexts,
        }


def is_blocked_html(html: str, status_code: int) -> bool:
    if status_code in {401, 403, 429, 503}:
        return True
    lowered = str(html or "").lower()
    if not lowered.strip():
        return False

    for item in _mapping_sequence(BLOCK_SIGNATURES.get("active_provider_markers")):
        marker = str(item.get("marker") or "").strip().lower()
        if marker and marker in lowered:
            return True

    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    visible_text = clean_text(soup.get_text(" ", strip=True)).lower()
    title_text = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "").lower()

    title_patterns = _string_sequence(BLOCK_SIGNATURES.get("title_regexes"))
    for pattern in title_patterns:
        raw_pattern = str(pattern or "").strip()
        if raw_pattern and re.search(raw_pattern, title_text, re.IGNORECASE):
            return True

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

    strong_hits = {marker for marker in strong_markers if marker in visible_text or marker in title_text}
    weak_hits = {marker for marker in weak_markers if marker in visible_text or marker in title_text}
    provider_hits = {marker for marker in provider_markers if marker in lowered}

    if len(strong_hits) >= 2:
        return True
    if strong_hits and provider_hits:
        return True
    if "access denied" in strong_hits:
        return True
    if "just a moment" in strong_hits and ("cloudflare" in provider_hits or "cf-challenge" in lowered):
        return True
    return bool(strong_hits and weak_hits and provider_hits)


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
            and str(key or "").strip().lower()
            not in {"config", "env", "locale"}
        }
        if meaningful_keys:
            return True
        return any(_state_payload_has_content(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_state_payload_has_content(item) for item in payload[:10])
    return payload not in (None, "")


def _should_escalate_to_browser(result: PageFetchResult) -> bool:
    if result.blocked:
        return True
    if _looks_like_js_shell(result.html) and not _has_extractable_detail_signals(result.html):
        return True
    return False


def _remember_browser_host(url: str) -> None:
    host = hostname(url)
    if not host:
        return
    _BROWSER_PREFERRED_HOSTS[host] = (
        time.monotonic() + _BROWSER_PREFERRED_HOST_TTL_SECONDS
    )


def _host_prefers_browser(url: str) -> bool:
    host = hostname(url)
    if not host:
        return False
    expires_at = _BROWSER_PREFERRED_HOSTS.get(host)
    if expires_at is None:
        return False
    if expires_at <= time.monotonic():
        _BROWSER_PREFERRED_HOSTS.pop(host, None)
        return False
    return True


async def _get_shared_http_client() -> httpx.AsyncClient:
    global _SHARED_HTTP_CLIENT
    if _SHARED_HTTP_CLIENT is not None and not _SHARED_HTTP_CLIENT.is_closed:
        return _SHARED_HTTP_CLIENT
    async with _SHARED_HTTP_CLIENT_LOCK:
        if _SHARED_HTTP_CLIENT is None or _SHARED_HTTP_CLIENT.is_closed:
            _SHARED_HTTP_CLIENT = httpx.AsyncClient(
                follow_redirects=True,
                timeout=settings.http_timeout_seconds,
                limits=httpx.Limits(
                    max_connections=settings.http_max_connections,
                    max_keepalive_connections=settings.http_max_keepalive_connections,
                ),
            )
        return _SHARED_HTTP_CLIENT


async def close_shared_http_client() -> None:
    global _SHARED_HTTP_CLIENT
    async with _SHARED_HTTP_CLIENT_LOCK:
        if _SHARED_HTTP_CLIENT is not None and not _SHARED_HTTP_CLIENT.is_closed:
            await _SHARED_HTTP_CLIENT.aclose()
        _SHARED_HTTP_CLIENT = None


async def _get_browser_runtime() -> SharedBrowserRuntime:
    global _BROWSER_RUNTIME
    if _BROWSER_RUNTIME is not None:
        return _BROWSER_RUNTIME
    async with _BROWSER_RUNTIME_LOCK:
        if _BROWSER_RUNTIME is None:
            _BROWSER_RUNTIME = SharedBrowserRuntime(
                max_contexts=settings.browser_pool_size
            )
        return _BROWSER_RUNTIME


async def shutdown_browser_runtime() -> None:
    global _BROWSER_RUNTIME
    async with _BROWSER_RUNTIME_LOCK:
        runtime = _BROWSER_RUNTIME
        _BROWSER_RUNTIME = None
    if runtime is not None:
        await runtime.close()


def browser_runtime_snapshot() -> dict[str, int | bool]:
    if _BROWSER_RUNTIME is None:
        max_size = max(1, int(settings.browser_pool_size))
        return {
            "ready": False,
            "size": 0,
            "max_size": max_size,
            "active": 0,
            "queued": 0,
            "capacity": max_size,
        }
    return _BROWSER_RUNTIME.snapshot()


async def reset_fetch_runtime_state() -> None:
    _BROWSER_PREFERRED_HOSTS.clear()
    await shutdown_browser_runtime()
    await close_shared_http_client()


async def _http_fetch(url: str, timeout_seconds: float) -> PageFetchResult:
    client = await _get_shared_http_client()
    response = await client.get(url, timeout=timeout_seconds)
    html = response.text or ""
    return PageFetchResult(
        url=url,
        final_url=str(response.url),
        html=html,
        status_code=response.status_code,
        method="httpx",
        content_type=response.headers.get("content-type", "text/html"),
        blocked=is_blocked_html(html, response.status_code),
        headers=_copy_headers(response.headers),
    )


def _curl_fetch_sync(url: str, timeout_seconds: float) -> PageFetchResult:
    from curl_cffi import requests as curl_requests

    response = curl_requests.get(
        url,
        impersonate="chrome124",
        allow_redirects=True,
        timeout=timeout_seconds,
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
        headers=_copy_headers(response.headers),
    )


async def _curl_fetch(url: str, timeout_seconds: float) -> PageFetchResult:
    return await asyncio.to_thread(_curl_fetch_sync, url, timeout_seconds)


async def _browser_fetch(
    url: str,
    timeout_seconds: float,
    *,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
) -> PageFetchResult:
    runtime = await _get_browser_runtime()
    async with runtime.page() as page:
        network_payloads: list[dict[str, object]] = []
        network_payload_lock = asyncio.Lock()
        capture_tasks: list[asyncio.Task[None]] = []
        malformed_payloads = 0
        normalized_surface = str(surface or "")

        async def _capture_response(response) -> None:
            content_type = str(response.headers.get("content-type", "") or "").lower()
            if not _should_capture_network_payload(
                url=response.url,
                content_type=content_type,
                headers=response.headers,
                captured_count=len(network_payloads),
            ):
                return
            try:
                body_bytes = await _read_network_payload_body(response)
            except Exception:
                logger.debug(
                    "Failed to read intercepted response body from %s",
                    response.url,
                    exc_info=True,
                )
                return
            if body_bytes is None:
                return
            try:
                payload = json.loads(body_bytes.decode("utf-8", errors="replace"))
            except Exception:
                nonlocal malformed_payloads
                malformed_payloads += 1
                logger.debug(
                    "Failed to decode intercepted JSON response from %s",
                    response.url,
                    exc_info=True,
                )
                return
            endpoint_info = _classify_network_endpoint(
                response_url=response.url,
                surface=normalized_surface,
            )
            async with network_payload_lock:
                if not _should_capture_network_payload(
                    url=response.url,
                    content_type=content_type,
                    headers=response.headers,
                    captured_count=len(network_payloads),
                ):
                    return
                network_payloads.append(
                    {
                        "url": response.url,
                        "method": getattr(response.request, "method", "GET"),
                        "status": int(getattr(response, "status", 0) or 0),
                        "content_type": content_type,
                        "endpoint_type": endpoint_info["type"],
                        "endpoint_family": endpoint_info["family"],
                        "body": payload,
                    }
                )

        def _schedule_capture(response) -> None:
            capture_tasks.append(asyncio.create_task(_capture_response(response)))

        page.on("response", _schedule_capture)
        response = None
        networkidle_timed_out = False
        goto_timeout_ms = min(
            int(timeout_seconds * 1000),
            int(crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms),
        )
        fallback_timeout_ms = min(
            int(timeout_seconds * 1000),
            int(crawler_runtime_settings.browser_navigation_min_final_commit_timeout_ms),
        )
        navigation_strategy = "domcontentloaded"
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=goto_timeout_ms,
            )
        except Exception:
            navigation_strategy = "commit"
            response = await page.goto(
                url,
                wait_until="commit",
                timeout=fallback_timeout_ms,
            )
        wait_ms = min(
            int(timeout_seconds * 1000),
            int(crawler_runtime_settings.browser_navigation_optimistic_wait_ms),
        )
        if wait_ms > 0:
            await page.wait_for_timeout(wait_ms)
        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=min(
                    int(timeout_seconds * 1000),
                    int(crawler_runtime_settings.browser_navigation_networkidle_timeout_ms),
                ),
            )
        except Exception:
            networkidle_timed_out = True
        expansion_diagnostics: dict[str, object] = {}
        if surface and "detail" in str(surface).lower():
            expansion_diagnostics = await expand_all_interactive_elements(
                page,
                surface=str(surface or ""),
            )
        traversal_result = None
        html_fragments: list[str]
        if should_run_traversal(surface, traversal_mode):
            traversal_result = await execute_listing_traversal(
                page,
                surface=str(surface or ""),
                traversal_mode=str(traversal_mode or ""),
                max_pages=max_pages,
                max_scrolls=max_scrolls,
            )
            html_fragments = list(traversal_result.html_fragments or [])
        else:
            html_fragments = [await page.content()]
        html = "\n".join(fragment for fragment in html_fragments if fragment)
        status_code = response.status if response is not None else 200
        if capture_tasks:
            await asyncio.gather(*capture_tasks, return_exceptions=True)
        diagnostics = {
            "navigation_strategy": navigation_strategy,
            "networkidle_timed_out": networkidle_timed_out,
            "network_payload_count": len(network_payloads),
            "malformed_network_payloads": malformed_payloads,
            "detail_expansion": expansion_diagnostics,
        }
        if traversal_result is not None:
            diagnostics.update(traversal_result.diagnostics())
        return PageFetchResult(
            url=url,
            final_url=page.url,
            html=html,
            status_code=status_code,
            method="browser",
            content_type=(
                response.headers.get("content-type", "text/html")
                if response is not None
                else "text/html"
            ),
            blocked=is_blocked_html(html, status_code),
            headers=(
                _copy_headers(response.headers)
                if response is not None
                else httpx.Headers()
            ),
            network_payloads=network_payloads[:_MAX_CAPTURED_NETWORK_PAYLOADS],
            browser_diagnostics=diagnostics,
        )


async def _call_browser_fetch(
    url: str,
    timeout_seconds: float,
    *,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
) -> PageFetchResult:
    try:
        return await _browser_fetch(
            url,
            timeout_seconds,
            surface=surface,
            traversal_mode=traversal_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
        )
    except TypeError as exc:
        message = str(exc)
        if (
            "unexpected keyword argument" not in message
            or not _is_browser_fetch_signature_error(exc)
        ):
            raise
        logger.info(
            "Falling back to legacy _browser_fetch signature without traversal parameters for %s; dropped surface=%r traversal_mode=%r max_pages=%r max_scrolls=%r; error=%s",
            url,
            surface,
            traversal_mode,
            max_pages,
            max_scrolls,
            message,
        )
        return await _browser_fetch(url, timeout_seconds)


def _is_browser_fetch_signature_error(exc: TypeError) -> bool:
    frames = traceback.extract_tb(exc.__traceback__)
    return any(
        frame.name in {"_call_browser_fetch", "_browser_fetch"}
        for frame in frames
    )


def _copy_headers(headers: Any) -> httpx.Headers:
    if isinstance(headers, httpx.Headers):
        return httpx.Headers(list(headers.multi_items()))
    if hasattr(headers, "multi_items"):
        return httpx.Headers(list(headers.multi_items()))
    if isinstance(headers, dict):
        return httpx.Headers(headers)
    return httpx.Headers(list(getattr(headers, "items", lambda: [])()))


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


def _should_capture_network_payload(
    *,
    url: str,
    content_type: str,
    headers: dict[str, object] | Any,
    captured_count: int,
) -> bool:
    lowered_url = str(url or "").lower()
    if "json" not in content_type and not lowered_url.endswith(".json"):
        return False
    if captured_count >= _MAX_CAPTURED_NETWORK_PAYLOADS:
        return False
    if _NETWORK_PAYLOAD_NOISE_URL_RE.search(lowered_url):
        return False
    content_length = _coerce_content_length(headers)
    if (
        content_length is not None
        and content_length > _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES
    ):
        return False
    return True


def _classify_network_endpoint(
    *,
    response_url: str,
    surface: str,
) -> dict[str, str]:
    lowered_url = str(response_url or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    family = "generic"
    if "greenhouse" in lowered_url:
        family = "greenhouse"
    elif "workday" in lowered_url:
        family = "workday"
    elif "lever.co" in lowered_url or "/lever/" in lowered_url:
        family = "lever"
    elif "shopify" in lowered_url:
        family = "shopify"
    elif "__next" in lowered_url or "_next/data" in lowered_url:
        family = "nextjs"

    endpoint_type = "generic_json"
    if "/graphql" in lowered_url or "graphql?" in lowered_url:
        endpoint_type = "graphql"
    elif normalized_surface == "job_detail" and any(
        token in lowered_url
        for token in (
            "/jobs/",
            "/job_posts/",
            "/postings/",
            "/positions/",
            "/requisition/",
            "/careers/",
        )
    ):
        endpoint_type = "job_api"
    elif normalized_surface == "ecommerce_detail" and any(
        token in lowered_url
        for token in (
            "/products/",
            "/product/",
            "product.js",
            "/variants/",
            "/cart.js",
        )
    ):
        endpoint_type = "product_api"
    return {"type": endpoint_type, "family": family}


async def expand_all_interactive_elements(
    page: Any,
    *,
    surface: str = "",
    checkpoint: Any = None,
) -> dict[str, object]:
    del checkpoint
    diagnostics: dict[str, object] = {
        "buttons_found": 0,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
        "limit": int(crawler_runtime_settings.detail_expand_max_interactions),
    }
    try:
        candidates = await page.locator(_DETAIL_EXPAND_SELECTORS).element_handles()
    except Exception as exc:
        diagnostics["interaction_failures"] = [f"locator_failed:{exc}"]
        return diagnostics

    keywords = _detail_expansion_keywords(surface)
    expanded_elements: list[str] = []
    interaction_failures: list[str] = []
    diagnostics["buttons_found"] = len(candidates)
    max_interactions = max(
        0,
        min(
            int(crawler_runtime_settings.detail_expand_max_interactions),
            int(crawler_runtime_settings.accordion_expand_max),
        ),
    )
    clicked_count = 0
    for handle in candidates:
        if clicked_count >= max_interactions:
            break
        try:
            label = await _interactive_label(handle)
            if keywords and label and not any(keyword in label for keyword in keywords):
                continue
            await handle.scroll_into_view_if_needed()
            try:
                await handle.click(timeout=1_000)
            except Exception:
                await handle.evaluate(
                    "(node) => node instanceof HTMLElement && node.click()"
                )
            if int(crawler_runtime_settings.accordion_expand_wait_ms) > 0:
                await page.wait_for_timeout(
                    int(crawler_runtime_settings.accordion_expand_wait_ms)
                )
            clicked_count += 1
            if label:
                expanded_elements.append(label)
        except Exception as exc:
            interaction_failures.append(str(exc))
    diagnostics["clicked_count"] = clicked_count
    diagnostics["expanded_elements"] = expanded_elements
    diagnostics["interaction_failures"] = interaction_failures
    return diagnostics


def _detail_expansion_keywords(surface: str) -> tuple[str, ...]:
    lowered = str(surface or "").strip().lower()
    if "ecommerce" in lowered:
        return _DETAIL_EXPAND_KEYWORDS["ecommerce"]
    if "job" in lowered:
        return _DETAIL_EXPAND_KEYWORDS["job"]
    return ()


async def _interactive_label(handle: Any) -> str:
    value = await handle.evaluate(
        """(node) => {
            const pieces = [
                node.innerText,
                node.textContent,
                node.getAttribute('aria-label'),
                node.getAttribute('title'),
                node.getAttribute('data-testid'),
            ];
            return pieces.find((item) => item && item.trim()) || '';
        }"""
    )
    return " ".join(str(value or "").split()).strip().lower()


def _coerce_content_length(headers: dict[str, object] | Any) -> int | None:
    if not headers:
        return None
    raw_value = headers.get("content-length")
    try:
        parsed = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


async def _read_network_payload_body(response) -> bytes | None:
    body_bytes = await response.body()
    if len(body_bytes) > _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES:
        return None
    return body_bytes


async def fetch_page(
    url: str,
    *,
    timeout_seconds: float | None = None,
    proxy_list: list[str] | None = None,
    prefer_browser: bool = False,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
    sleep_ms: int = 0,
) -> PageFetchResult:
    del proxy_list, sleep_ms
    resolved_timeout = float(timeout_seconds or settings.http_timeout_seconds)
    runtime_policy = resolve_platform_runtime_policy(url)
    browser_first = (
        prefer_browser
        or _host_prefers_browser(url)
        or bool(runtime_policy.get("requires_browser"))
        or should_run_traversal(surface, traversal_mode)
    )
    if browser_first:
        browser_result = await _call_browser_fetch(
            url,
            resolved_timeout,
            surface=surface,
            traversal_mode=traversal_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
        )
        _remember_browser_host(browser_result.final_url)
        return browser_result

    last_error: Exception | None = None
    for fetcher in (_curl_fetch, _http_fetch):
        try:
            result = await fetcher(url, resolved_timeout)
            if _should_escalate_to_browser(result):
                browser_result = await _call_browser_fetch(
                    url,
                    resolved_timeout,
                    surface=surface,
                    traversal_mode=traversal_mode,
                    max_pages=max_pages,
                    max_scrolls=max_scrolls,
                )
                _remember_browser_host(browser_result.final_url)
                return browser_result
            return result
        except Exception as exc:
            last_error = exc
            logger.debug(
                "Fetch failed for %s via %s",
                url,
                fetcher.__name__,
                exc_info=True,
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")
