from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx

from app.core.config import settings
from app.services.acquisition.browser_identity import build_playwright_context_options
from app.services.acquisition.runtime import (
    NetworkPayloadReadResult,
    PageFetchResult,
    copy_headers,
    is_blocked_html_async,
)
from app.services.acquisition.traversal import (
    execute_listing_traversal,
    should_run_traversal,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_value_utils import hostname
from app.services.platform_policy import (
    classify_network_endpoint_family,
    resolve_listing_readiness_override,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

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


class SharedBrowserRuntime:
    def __init__(self, *, max_contexts: int) -> None:
        self.max_contexts = max(1, int(max_contexts))
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(self.max_contexts)
        self._lock = asyncio.Lock()
        self._stats_lock = asyncio.Lock()
        self._active_contexts = 0
        self._queued_count = 0

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

    def _build_context_options(self) -> dict[str, object]:
        return build_playwright_context_options()

    @asynccontextmanager
    async def page(self):
        await self._ensure()
        await self._update_queue_count(1)
        try:
            await self._semaphore.acquire()
        except Exception:
            await self._update_queue_count(-1)
            raise
        await self._update_queue_count(-1)
        if self._browser is None:
            self._semaphore.release()
            raise RuntimeError("Browser runtime failed to initialize")
        context: BrowserContext | None = None
        await self._update_active_contexts(1)
        try:
            context = await self._browser.new_context(**self._build_context_options())
            page = await context.new_page()
            yield page
        finally:
            await self._update_active_contexts(-1)
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

    async def _update_active_contexts(self, delta: int) -> None:
        async with self._stats_lock:
            self._active_contexts = max(0, self._active_contexts + delta)

    async def _update_queue_count(self, delta: int) -> None:
        async with self._stats_lock:
            self._queued_count = max(0, self._queued_count + delta)

    def snapshot(self) -> dict[str, int | bool]:
        prune_browser_preferred_hosts()
        return {
            "ready": self._browser is not None,
            "size": self._active_contexts,
            "max_size": self.max_contexts,
            "active": self._active_contexts,
            "queued": self._queued_count,
            "capacity": self.max_contexts,
            "preferred_hosts": len(_BROWSER_PREFERRED_HOSTS),
        }


@asynccontextmanager
async def temporary_browser_page(*, proxy: str):
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = None
    context = None
    try:
        browser = await playwright.chromium.launch(
            headless=settings.playwright_headless,
            proxy={"server": proxy},
        )
        context = await browser.new_context(**build_playwright_context_options())
        page = await context.new_page()
        yield page
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                logger.debug("Failed to close proxied browser context", exc_info=True)
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                logger.debug("Failed to close proxied browser", exc_info=True)
        try:
            await playwright.stop()
        except Exception:
            logger.debug("Failed to stop proxied playwright runtime", exc_info=True)


def remember_browser_host(url: str) -> None:
    prune_browser_preferred_hosts()
    host = hostname(url)
    if not host:
        return
    _BROWSER_PREFERRED_HOSTS[host] = (
        time.monotonic() + _BROWSER_PREFERRED_HOST_TTL_SECONDS
    )


def host_prefers_browser(url: str) -> bool:
    prune_browser_preferred_hosts()
    host = hostname(url)
    if not host:
        return False
    return host in _BROWSER_PREFERRED_HOSTS


def prune_browser_preferred_hosts(now: float | None = None) -> int:
    current = float(now if now is not None else time.monotonic())
    expired = [
        host for host, expires_at in list(_BROWSER_PREFERRED_HOSTS.items()) if expires_at <= current
    ]
    for host in expired:
        _BROWSER_PREFERRED_HOSTS.pop(host, None)
    return len(expired)


async def get_browser_runtime() -> SharedBrowserRuntime:
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


def shutdown_browser_runtime_sync() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(shutdown_browser_runtime())
        return
    task = loop.create_task(shutdown_browser_runtime())
    task.add_done_callback(_log_shutdown_task_result)


def browser_runtime_snapshot() -> dict[str, int | bool]:
    prune_browser_preferred_hosts()
    if _BROWSER_RUNTIME is None:
        max_size = max(1, int(settings.browser_pool_size))
        return {
            "ready": False,
            "size": 0,
            "max_size": max_size,
            "active": 0,
            "queued": 0,
            "capacity": max_size,
            "preferred_hosts": len(_BROWSER_PREFERRED_HOSTS),
        }
    return _BROWSER_RUNTIME.snapshot()


def _log_shutdown_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.debug("Browser runtime shutdown task was cancelled")
    except Exception:
        logger.exception("Browser runtime shutdown task failed")


async def browser_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
    runtime_provider=get_browser_runtime,
    proxied_page_factory=temporary_browser_page,
    blocked_html_checker=is_blocked_html_async,
) -> PageFetchResult:
    if proxy:
        page_context = proxied_page_factory(proxy=proxy)
    else:
        runtime = await runtime_provider()
        page_context = runtime.page()
    async with page_context as page:
        network_payloads: list[dict[str, object]] = []
        network_payload_lock = asyncio.Lock()
        capture_tasks: list[asyncio.Task[None]] = []
        malformed_payloads = 0
        payload_read_failures = 0
        payload_closed_failures = 0
        oversized_payloads = 0
        normalized_surface = str(surface or "")

        async def _capture_response(response) -> None:
            content_type = str(response.headers.get("content-type", "") or "").lower()
            if not should_capture_network_payload(
                url=response.url,
                content_type=content_type,
                headers=response.headers,
                captured_count=len(network_payloads),
            ):
                return
            body_result = await read_network_payload_body(response)
            if body_result.outcome == "response_closed":
                nonlocal payload_closed_failures
                async with network_payload_lock:
                    payload_closed_failures += 1
                return
            if body_result.outcome == "too_large":
                nonlocal oversized_payloads
                async with network_payload_lock:
                    oversized_payloads += 1
                return
            if body_result.outcome == "read_error":
                nonlocal payload_read_failures
                async with network_payload_lock:
                    payload_read_failures += 1
                return
            body_bytes = body_result.body
            if body_bytes is None:
                return
            try:
                payload = json.loads(body_bytes.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                nonlocal malformed_payloads
                async with network_payload_lock:
                    malformed_payloads += 1
                return
            endpoint_info = classify_network_endpoint(
                response_url=response.url,
                surface=normalized_surface,
            )
            async with network_payload_lock:
                if not should_capture_network_payload(
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
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        navigation_strategy = "domcontentloaded"
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=goto_timeout_ms,
            )
        except asyncio.CancelledError:
            raise
        except (PlaywrightTimeoutError, PlaywrightError):
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
        readiness_diagnostics = await wait_for_listing_readiness(page, url)
        expansion_diagnostics: dict[str, object] = {}
        if surface and "detail" in str(surface).lower():
            expansion_diagnostics = await expand_all_interactive_elements(
                page,
                surface=str(surface or ""),
            )
        traversal_result = None
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
        response_missing = response is None
        status_code = response.status if response is not None else 0
        if response_missing:
            logger.warning(
                "Browser navigation returned no response for %s using %s strategy",
                url,
                navigation_strategy,
            )
        if capture_tasks:
            await asyncio.gather(*capture_tasks, return_exceptions=True)
        async with network_payload_lock:
            network_payload_count = len(network_payloads)
            malformed_network_payloads = malformed_payloads
            network_payload_read_failures = payload_read_failures
            closed_network_payloads = payload_closed_failures
            skipped_oversized_network_payloads = oversized_payloads
        blocked = await blocked_html_checker(html, status_code)
        diagnostics = {
            "navigation_strategy": navigation_strategy,
            "response_missing": response_missing,
            "networkidle_timed_out": networkidle_timed_out,
            "network_payload_count": network_payload_count,
            "malformed_network_payloads": malformed_network_payloads,
            "network_payload_read_failures": network_payload_read_failures,
            "closed_network_payloads": closed_network_payloads,
            "skipped_oversized_network_payloads": skipped_oversized_network_payloads,
            "listing_readiness": readiness_diagnostics,
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
            blocked=blocked,
            headers=(copy_headers(response.headers) if response is not None else httpx.Headers()),
            network_payloads=network_payloads[:_MAX_CAPTURED_NETWORK_PAYLOADS],
            browser_diagnostics=diagnostics,
        )


async def wait_for_listing_readiness(page: Any, page_url: str) -> dict[str, object]:
    override = resolve_listing_readiness_override(page_url)
    if not override:
        return {}
    selectors = [
        str(selector or "").strip()
        for selector in list(override.get("selectors") or [])
        if str(selector or "").strip()
    ]
    if not selectors:
        return {}
    max_wait_ms = int(
        override.get("max_wait_ms")
        or crawler_runtime_settings.listing_readiness_max_wait_ms
        or 0
    )
    if max_wait_ms <= 0:
        return {}
    combined_selector = ", ".join(selectors)
    try:
        await page.wait_for_selector(
            combined_selector,
            state="attached",
            timeout=max_wait_ms,
        )
    except Exception as exc:
        return {
            "platform": str(override.get("platform") or ""),
            "max_wait_ms": max_wait_ms,
            "status": "timed_out",
            "attempted_selectors": selectors,
            "failures": [f"{combined_selector}:{type(exc).__name__}"],
        }
    matched_selector = None
    for selector in selectors:
        try:
            if await page.locator(selector).count():
                matched_selector = selector
                break
        except Exception:
            continue
    return {
        "platform": str(override.get("platform") or ""),
        "combined_selector": combined_selector,
        "max_wait_ms": max_wait_ms,
        "matched_selector": matched_selector or combined_selector,
        "status": "matched",
    }


def should_capture_network_payload(
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
    content_length = coerce_content_length(headers)
    if content_length is not None and content_length > _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES:
        return False
    return True


def classify_network_endpoint(*, response_url: str, surface: str) -> dict[str, str]:
    lowered_url = str(response_url or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    family = classify_network_endpoint_family(response_url)

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


async def read_network_payload_body(response) -> NetworkPayloadReadResult:
    try:
        body_bytes = await response.body()
    except Exception as exc:
        if is_response_closed_error(exc):
            return NetworkPayloadReadResult(
                body=None,
                outcome="response_closed",
                error=f"{type(exc).__name__}: {exc}",
            )
        return NetworkPayloadReadResult(
            body=None,
            outcome="read_error",
            error=f"{type(exc).__name__}: {exc}",
        )
    if len(body_bytes) > _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES:
        return NetworkPayloadReadResult(body=None, outcome="too_large")
    return NetworkPayloadReadResult(body=body_bytes, outcome="read")


def is_response_closed_error(exc: Exception) -> bool:
    class_name = type(exc).__name__.lower()
    message = str(exc or "").lower()
    return (
        "targetclosed" in class_name
        or "target closed" in message
        or "page closed" in message
        or "browser has been closed" in message
    )


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

    keywords = detail_expansion_keywords(surface)
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
            label = await interactive_label(handle)
            if keywords and label and not any(keyword in label for keyword in keywords):
                continue
            if not await is_actionable_interactive_handle(handle):
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


def detail_expansion_keywords(surface: str) -> tuple[str, ...]:
    lowered = str(surface or "").strip().lower()
    if "ecommerce" in lowered:
        return _DETAIL_EXPAND_KEYWORDS["ecommerce"]
    if "job" in lowered:
        return _DETAIL_EXPAND_KEYWORDS["job"]
    return ()


async def interactive_label(handle: Any) -> str:
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


async def is_actionable_interactive_handle(handle: Any) -> bool:
    state = await handle.evaluate(
        """(node) => {
            if (!(node instanceof HTMLElement) || !node.isConnected) {
                return { actionable: false };
            }
            const style = window.getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            const disabled = Boolean(
                node.hasAttribute('disabled') ||
                node.getAttribute('aria-disabled') === 'true' ||
                node.inert
            );
            const hidden = Boolean(
                node.hidden ||
                node.getAttribute('aria-hidden') === 'true' ||
                style.display === 'none' ||
                style.visibility === 'hidden' ||
                style.pointerEvents === 'none'
            );
            const collapsed = rect.width <= 0 || rect.height <= 0;
            return { actionable: !(disabled || hidden || collapsed) };
        }"""
    )
    if not isinstance(state, dict):
        return False
    return bool(state.get("actionable"))


def coerce_content_length(headers: dict[str, object] | Any) -> int | None:
    if not headers:
        return None
    raw_value = headers.get("content-length")
    try:
        parsed = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


__all__ = [
    "SharedBrowserRuntime",
    "_BROWSER_PREFERRED_HOSTS",
    "_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES",
    "browser_fetch",
    "browser_runtime_snapshot",
    "classify_network_endpoint",
    "expand_all_interactive_elements",
    "get_browser_runtime",
    "host_prefers_browser",
    "prune_browser_preferred_hosts",
    "read_network_payload_body",
    "remember_browser_host",
    "should_capture_network_payload",
    "shutdown_browser_runtime",
    "shutdown_browser_runtime_sync",
    "temporary_browser_page",
]
