from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_value_utils import clean_text, hostname
from app.services.structured_sources import harvest_js_state_objects, parse_json_ld

logger = logging.getLogger(__name__)

BLOCKED_TERMS = (
    "access denied",
    "are you human",
    "bot detection",
    "captcha",
    "cf-chl",
    "cloudflare",
    "forbidden",
    "temporarily unavailable",
)
_BROWSER_PREFERRED_HOST_TTL_SECONDS = 1800.0
_BROWSER_PREFERRED_HOSTS: dict[str, float] = {}
_SHARED_HTTP_CLIENT: httpx.AsyncClient | None = None
_SHARED_HTTP_CLIENT_LOCK = asyncio.Lock()
_BROWSER_RUNTIME = None
_BROWSER_RUNTIME_LOCK = asyncio.Lock()


@dataclass(slots=True)
class PageFetchResult:
    url: str
    final_url: str
    html: str
    status_code: int
    method: str
    content_type: str = "text/html"
    blocked: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    network_payloads: list[dict[str, object]] = field(default_factory=list)
    browser_diagnostics: dict[str, object] = field(default_factory=dict)


class SharedBrowserRuntime:
    def __init__(self, *, max_contexts: int) -> None:
        self.max_contexts = max(1, int(max_contexts))
        self._playwright = None
        self._browser = None
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
        context = None
        page = None
        self._active_contexts += 1
        try:
            context = await self._browser.new_context()
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
    lowered = html.lower()
    return any(term in lowered for term in BLOCKED_TERMS)


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
        headers=dict(response.headers),
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
        headers=dict(response.headers),
    )


async def _curl_fetch(url: str, timeout_seconds: float) -> PageFetchResult:
    return await asyncio.to_thread(_curl_fetch_sync, url, timeout_seconds)


async def _browser_fetch(url: str, timeout_seconds: float) -> PageFetchResult:
    runtime = await _get_browser_runtime()
    async with runtime.page() as page:
        network_payloads: list[dict[str, object]] = []
        capture_tasks: list[asyncio.Task[None]] = []

        async def _capture_response(response) -> None:
            content_type = str(response.headers.get("content-type", "") or "").lower()
            if "json" not in content_type and not response.url.lower().endswith(".json"):
                return
            try:
                payload = await response.json()
            except Exception:
                return
            network_payloads.append(
                {
                    "url": response.url,
                    "method": getattr(response.request, "method", "GET"),
                    "status": int(getattr(response, "status", 0) or 0),
                    "content_type": content_type,
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
        html = await page.content()
        status_code = response.status if response is not None else 200
        if capture_tasks:
            await asyncio.gather(*capture_tasks, return_exceptions=True)
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
            network_payloads=network_payloads[:25],
            browser_diagnostics={
                "navigation_strategy": navigation_strategy,
                "networkidle_timed_out": networkidle_timed_out,
                "network_payload_count": len(network_payloads),
            },
        )


async def fetch_page(
    url: str,
    *,
    timeout_seconds: float | None = None,
    prefer_browser: bool = False,
) -> PageFetchResult:
    resolved_timeout = float(timeout_seconds or settings.http_timeout_seconds)
    if prefer_browser or _host_prefers_browser(url):
        browser_result = await _browser_fetch(url, resolved_timeout)
        _remember_browser_host(browser_result.final_url)
        return browser_result

    last_error: Exception | None = None
    for fetcher in (_curl_fetch, _http_fetch):
        try:
            result = await fetcher(url, resolved_timeout)
            if _should_escalate_to_browser(result):
                browser_result = await _browser_fetch(url, resolved_timeout)
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
