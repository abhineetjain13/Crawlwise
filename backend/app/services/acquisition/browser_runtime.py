from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx
from bs4 import BeautifulSoup, Comment

from app.core.config import settings
from app.services.acquisition.browser_capture import (
    _MAX_CAPTURED_NETWORK_PAYLOADS,
    BrowserNetworkCapture as _BrowserNetworkCapture,
    _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES,
    _NETWORK_CAPTURE_QUEUE_SIZE,
    _NETWORK_CAPTURE_WORKERS,
    capture_browser_screenshot,
    classify_network_endpoint,
    read_network_payload_body,
    should_capture_network_payload,
)
from app.services.acquisition.browser_identity import (
    build_playwright_context_options,
    clear_browser_identity_cache,
)
from app.services.acquisition.runtime import (
    BlockPageClassification,
    NetworkPayloadReadResult,
    classify_blocked_page_async,
    PageFetchResult,
    copy_headers,
    is_blocked_html_async,
)
from app.services.acquisition.traversal import (
    count_listing_cards,
    execute_listing_traversal,
    should_run_traversal,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS
from app.services.field_value_core import clean_text
from app.services.field_value_core import hostname
from app.services.platform_policy import (
    resolve_browser_readiness_policy,
    resolve_listing_readiness_override,
    resolve_platform_runtime_policy,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)

try:
    from playwright_stealth import Stealth as _PlaywrightStealth
    _STEALTH_APPLIER = _PlaywrightStealth().apply_stealth_async
except Exception:  # pragma: no cover - optional dep missing
    _STEALTH_APPLIER = None


async def _apply_stealth(page: Any) -> None:
    if _STEALTH_APPLIER is None:
        return
    try:
        await _STEALTH_APPLIER(page)
    except Exception:
        logger.debug("Failed to apply playwright-stealth", exc_info=True)
_BROWSER_PREFERRED_HOST_TTL_SECONDS = 1800.0
_BROWSER_PREFERRED_HOSTS: dict[str, float] = {}
_BROWSER_PREFERRED_HOST_SUCCESSES: dict[str, tuple[int, float]] = {}
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
_DETAIL_READINESS_HINTS: dict[str, tuple[str, ...]] = {
    "ecommerce": (
        "add to cart",
        "description",
        "features",
        "materials",
        "price",
        "product details",
        "reviews",
        "shipping",
        "size",
        "specifications",
    ),
    "job": (
        "apply",
        "benefits",
        "job description",
        "qualifications",
        "remote",
        "requirements",
        "responsibilities",
        "salary",
        "skills",
    ),
}
_AOM_EXPAND_ROLES = {"button", "tab"}


class _BrowserHtmlAnalysis:
    __slots__ = ("h1_present", "html", "lowered_html", "normalized_text", "soup", "visible_text")

    def __init__(self, html: str) -> None:
        text = str(html or "")
        self.html = text
        self.lowered_html = text.lower()
        self.soup = BeautifulSoup(text, "html.parser")
        self.visible_text = _visible_text_from_soup(self.soup)
        self.normalized_text = " ".join(self.visible_text.split())
        self.h1_present = bool(self.soup.find("h1"))


class SharedBrowserRuntime:
    def __init__(self, *, max_contexts: int) -> None:
        self.max_contexts = max(1, int(max_contexts))
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(self.max_contexts)
        self._lock = asyncio.Lock()
        self._counter_lock = asyncio.Lock()
        self._stats_lock = asyncio.Lock()
        self._active_contexts = 0
        self._queued_count = 0
        self._total_contexts_created = 0
        self._browser_launched_at: float = 0.0

    def _should_recycle_browser(self) -> bool:
        if self._browser is None:
            return False
        if not getattr(self._browser, "is_connected", lambda: True)():
            return True
        max_contexts = int(
            crawler_runtime_settings.browser_max_contexts_before_recycle
        )
        if max_contexts > 0 and self._total_contexts_created >= max_contexts:
            return True
        max_lifetime = int(crawler_runtime_settings.browser_max_lifetime_seconds)
        if max_lifetime > 0 and self._browser_launched_at > 0:
            if time.monotonic() - self._browser_launched_at >= max_lifetime:
                return True
        return False

    async def _ensure(self) -> None:
        if self._browser is not None and not self._should_recycle_browser():
            return
        async with self._lock:
            if self._should_recycle_browser():
                logger.info(
                    "Recycling browser instance (contexts=%d, lifetime=%.0fs)",
                    self._total_contexts_created,
                    time.monotonic() - self._browser_launched_at
                    if self._browser_launched_at
                    else 0,
                )
                await self.close()
            if self._browser is not None:
                return
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=settings.playwright_headless,
            )
            self._browser_launched_at = time.monotonic()
            async with self._counter_lock:
                self._total_contexts_created = 0

    def _build_context_options(self, *, run_id: int | None = None) -> dict[str, object]:
        return build_playwright_context_options(run_id=run_id)

    @asynccontextmanager
    async def page(self, *, proxy: str | None = None, run_id: int | None = None):
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
            context_options = self._build_context_options(run_id=run_id)
            if proxy:
                context_options["proxy"] = {"server": proxy}
            context = await self._browser.new_context(**context_options)
            async with self._counter_lock:
                self._total_contexts_created += 1
            page = await context.new_page()
            await _apply_stealth(page)
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
            self._browser_launched_at = 0.0

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
            "total_contexts_created": self._total_contexts_created,
            "browser_lifetime_seconds": int(
                time.monotonic() - self._browser_launched_at
            )
            if self._browser_launched_at
            else 0,
            "preferred_hosts": len(_BROWSER_PREFERRED_HOSTS),
        }


@asynccontextmanager
async def temporary_browser_page(*, proxy: str, run_id: int | None = None):
    runtime = await get_browser_runtime()
    async with runtime.page(proxy=proxy, run_id=run_id) as page:
        yield page


def remember_browser_host_if_good(
    url: str,
    *,
    browser_outcome: str | None,
    blocked: bool,
) -> bool:
    prune_browser_preferred_hosts()
    host = hostname(url)
    if not host:
        return False
    if not browser_host_preference_eligible(
        browser_outcome=browser_outcome,
        blocked=blocked,
    ):
        _BROWSER_PREFERRED_HOST_SUCCESSES.pop(host, None)
        _BROWSER_PREFERRED_HOSTS.pop(host, None)
        return False
    threshold = max(1, int(crawler_runtime_settings.browser_preference_min_successes))
    expires_at = time.monotonic() + _BROWSER_PREFERRED_HOST_TTL_SECONDS
    prior_count, prior_expiry = _BROWSER_PREFERRED_HOST_SUCCESSES.get(host, (0, 0.0))
    count = prior_count + 1 if prior_expiry > time.monotonic() else 1
    _BROWSER_PREFERRED_HOST_SUCCESSES[host] = (count, expires_at)
    if count < threshold:
        _BROWSER_PREFERRED_HOSTS.pop(host, None)
        return False
    _BROWSER_PREFERRED_HOSTS[host] = expires_at
    return True


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
    expired_successes = [
        host
        for host, (_, expires_at) in list(_BROWSER_PREFERRED_HOST_SUCCESSES.items())
        if expires_at <= current
    ]
    for host in expired_successes:
        _BROWSER_PREFERRED_HOST_SUCCESSES.pop(host, None)
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
    clear_browser_identity_cache()


def shutdown_browser_runtime_sync() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(shutdown_browser_runtime())
        return
    try:
        loop_thread_id = getattr(loop, "_thread_id")
    except Exception:
        loop_thread_id = None
    if loop_thread_id is not None and loop_thread_id != threading.get_ident():
        future = asyncio.run_coroutine_threadsafe(shutdown_browser_runtime(), loop)
        try:
            future.result(timeout=10)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "Timed out waiting for browser runtime shutdown to complete"
            )
        except Exception:
            logger.exception("Browser runtime shutdown task failed")
        return
    # When called from the event loop thread, waiting synchronously would deadlock
    # the loop, so shutdown remains best-effort and logs completion asynchronously.
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
    run_id: int | None = None,
    proxy: str | None = None,
    browser_reason: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
    on_event=None,
    runtime_provider=get_browser_runtime,
    proxied_page_factory=temporary_browser_page,
    blocked_html_checker=is_blocked_html_async,
) -> PageFetchResult:
    if proxy:
        page_context = proxied_page_factory(proxy=proxy, run_id=run_id)
    else:
        runtime = await runtime_provider()
        page_context = runtime.page(run_id=run_id)
    async with page_context as page:
        await _emit_browser_event(
            on_event,
            "info",
            f"Launched headless browser (chromium, proxy: {proxy or 'direct'})",
        )
        started_at = time.perf_counter()
        deadline = started_at + float(timeout_seconds)

        def _remaining() -> float:
            return max(2.0, deadline - time.perf_counter())

        phase_timings_ms: dict[str, int] = {}
        normalized_surface = str(surface or "")
        payload_capture = _BrowserNetworkCapture(
            surface=normalized_surface,
            should_capture_payload=should_capture_network_payload,
            classify_endpoint=classify_network_endpoint,
            read_payload_body=read_network_payload_body,
        )
        payload_capture.attach(page)
        traversal_active = should_run_traversal(surface, traversal_mode)
        readiness_policy = resolve_browser_readiness_policy(
            url,
            traversal_active=traversal_active,
        )
        readiness_override = readiness_policy.get("listing_override")
        try:
            response, navigation_strategy = await _navigate_browser_page(
                page, url=url, timeout_seconds=_remaining(), phase_timings_ms=phase_timings_ms,
            )
            page_title = ""
            try:
                page_title = clean_text(await page.title())
            except Exception:
                page_title = ""
            await _emit_browser_event(
                on_event,
                "info",
                (
                    f"Page loaded in {phase_timings_ms.get('navigation', 0)}ms"
                    + (f' - title="{page_title}"' if page_title else "")
                ),
            )
            (
                current_probe,
                readiness_probes,
                networkidle_timed_out,
                networkidle_skip_reason,
                readiness_diagnostics,
                expansion_diagnostics,
            ) = await _settle_browser_page(
                page,
                url=url,
                surface=normalized_surface,
                timeout_seconds=_remaining(),
                readiness_override=readiness_override,
                readiness_policy=readiness_policy,
                phase_timings_ms=phase_timings_ms,
            )
            html, traversal_result = await _serialize_browser_page_content(
                page,
                surface=surface,
                traversal_mode=traversal_mode,
                traversal_active=traversal_active,
                timeout_seconds=_remaining(),
                max_pages=max_pages,
                max_scrolls=max_scrolls,
                phase_timings_ms=phase_timings_ms,
                on_event=on_event,
            )
            response_missing = response is None
            status_code = response.status if response is not None else 0
            if response_missing:
                logger.warning(
                    "Browser navigation returned no response for %s using %s strategy",
                    url,
                    navigation_strategy,
                )
            payload_capture_started_at = time.perf_counter()
            capture_summary = await payload_capture.close(page)
            phase_timings_ms["payload_capture"] = _elapsed_ms(
                payload_capture_started_at
            )
            blocked_classification = await classify_blocked_page_async(html, status_code)
            blocked = bool(
                blocked_classification.blocked
                or await blocked_html_checker(html, status_code)
            )
            html_bytes = len(html.encode("utf-8"))
            challenge_evidence = list(blocked_classification.evidence or [])
            low_content_reason = classify_low_content_reason(html, html_bytes=html_bytes)
            browser_outcome = classify_browser_outcome(
                html=html,
                html_bytes=html_bytes,
                blocked=blocked,
                block_classification=blocked_classification,
                traversal_result=traversal_result,
            )
            if traversal_result is not None and traversal_result.activated:
                await _emit_browser_event(
                    on_event,
                    "info",
                    (
                        f"Traversal complete - {int(traversal_result.card_count or 0)} records, "
                        f"stop reason: {traversal_result.stop_reason}"
                    ),
                )
            if blocked:
                await _emit_browser_event(
                    on_event,
                    "warning",
                    f"Acquisition detected rate limiting or bot protection for {url}",
                )
            screenshot_path = ""
            if browser_outcome != "usable_content":
                screenshot_started_at = time.perf_counter()
                screenshot_path = await capture_browser_screenshot(page)
                phase_timings_ms["screenshot_capture"] = _elapsed_ms(
                    screenshot_started_at
                )
            else:
                phase_timings_ms["screenshot_capture"] = 0
            phase_timings_ms["total"] = _elapsed_ms(started_at)
            diagnostics = {
                "browser_attempted": True,
                "browser_reason": str(browser_reason or "").strip().lower() or None,
                "browser_outcome": browser_outcome,
                "navigation_strategy": navigation_strategy,
                "response_missing": response_missing,
                "networkidle_timed_out": networkidle_timed_out,
                "networkidle_wait_reason": readiness_policy.get("networkidle_reason"),
                "networkidle_skip_reason": networkidle_skip_reason,
                "html_bytes": html_bytes,
                "phase_timings_ms": phase_timings_ms,
                "challenge_evidence": challenge_evidence,
                "challenge_provider_hits": list(blocked_classification.provider_hits or []),
                "challenge_element_hits": list(
                    blocked_classification.challenge_element_hits or []
                ),
                "low_content_reason": low_content_reason,
                "readiness_probes": readiness_probes,
                "network_payload_count": capture_summary.network_payload_count,
                "malformed_network_payloads": capture_summary.malformed_network_payloads,
                "network_payload_read_failures": (
                    capture_summary.network_payload_read_failures
                ),
                "closed_network_payloads": capture_summary.closed_network_payloads,
                "skipped_oversized_network_payloads": (
                    capture_summary.skipped_oversized_network_payloads
                ),
                "dropped_network_payload_events": capture_summary.dropped_payload_events,
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
                platform_family=resolve_platform_runtime_policy(
                    page.url,
                    html,
                    surface=surface,
                ).get("family"),
                headers=(
                    copy_headers(response.headers)
                    if response is not None
                    else httpx.Headers()
                ),
                network_payloads=capture_summary.payloads,
                browser_diagnostics=diagnostics,
                artifacts=(
                    {"browser_screenshot_path": screenshot_path}
                    if screenshot_path
                    else {}
                ),
            )
        finally:
            await payload_capture.close(page)


def _append_readiness_probe(
    readiness_probes: list[dict[str, object]],
    *,
    stage: str,
    probe: dict[str, object],
) -> None:
    readiness_probes.append({"stage": stage, **probe})


async def _navigate_browser_page(
    page: Any,
    *,
    url: str,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
):
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
    navigation_started_at = time.perf_counter()
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
        try:
            response = await page.goto(
                url,
                wait_until="commit",
                timeout=fallback_timeout_ms,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            phase_timings_ms["navigation"] = _elapsed_ms(navigation_started_at)
            setattr(exc, "browser_phase_timings_ms", dict(phase_timings_ms))
            setattr(exc, "browser_navigation_strategy", navigation_strategy)
            raise
    finally:
        phase_timings_ms["navigation"] = _elapsed_ms(navigation_started_at)
    return response, navigation_strategy


async def _settle_browser_page(
    page: Any,
    *,
    url: str,
    surface: str,
    timeout_seconds: float,
    readiness_override: dict[str, object] | None,
    readiness_policy: dict[str, object],
    phase_timings_ms: dict[str, int],
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    bool,
    str | None,
    dict[str, object],
    dict[str, object],
]:
    readiness_probes: list[dict[str, object]] = []
    cached_html: str | None = None

    async def _cached_probe(*, refresh_html: bool = False) -> dict[str, object]:
        nonlocal cached_html
        if refresh_html or cached_html is None:
            cached_html = await page.content()
        return await probe_browser_readiness(
            page,
            url=url,
            surface=surface,
            listing_override=readiness_override,
            html=cached_html,
        )

    current_probe = await _cached_probe(refresh_html=True)
    _append_readiness_probe(
        readiness_probes,
        stage="after_navigation",
        probe=current_probe,
    )
    wait_ms = min(
        int(timeout_seconds * 1000),
        int(crawler_runtime_settings.browser_navigation_optimistic_wait_ms),
    )
    if wait_ms > 0 and not current_probe["is_ready"]:
        optimistic_wait_started_at = time.perf_counter()
        await page.wait_for_timeout(wait_ms)
        phase_timings_ms["optimistic_wait"] = _elapsed_ms(optimistic_wait_started_at)
        current_probe = await _cached_probe(refresh_html=True)
        _append_readiness_probe(
            readiness_probes,
            stage="after_optimistic_wait",
            probe=current_probe,
        )
    else:
        phase_timings_ms["optimistic_wait"] = 0

    networkidle_timed_out = False
    networkidle_skip_reason = None
    if not current_probe["is_ready"] and bool(readiness_policy.get("require_networkidle")):
        networkidle_wait_started_at = time.perf_counter()
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
        phase_timings_ms["networkidle_wait"] = _elapsed_ms(networkidle_wait_started_at)
        current_probe = await _cached_probe(refresh_html=True)
        _append_readiness_probe(
            readiness_probes,
            stage="after_networkidle",
            probe=current_probe,
        )
    else:
        phase_timings_ms["networkidle_wait"] = 0
        networkidle_skip_reason = (
            "fast_path_ready" if current_probe["is_ready"] else "not_required"
        )

    if not current_probe["is_ready"] and readiness_override is not None:
        readiness_started_at = time.perf_counter()
        readiness_diagnostics = await wait_for_listing_readiness(
            page,
            url,
            override=readiness_override,
        )
        phase_timings_ms["readiness_wait"] = _elapsed_ms(readiness_started_at)
        current_probe = await _cached_probe(refresh_html=True)
        _append_readiness_probe(
            readiness_probes,
            stage="after_platform_readiness",
            probe=current_probe,
        )
    else:
        phase_timings_ms["readiness_wait"] = 0
        readiness_diagnostics = {
            "status": "skipped",
            "reason": (
                "fast_path_ready" if current_probe["is_ready"] else "no_platform_override"
            ),
        }

    expansion_started_at = time.perf_counter()
    expansion_diagnostics = await expand_detail_content_if_needed(
        page,
        surface=surface,
        readiness_probe=current_probe,
    )
    phase_timings_ms["expansion"] = _elapsed_ms(expansion_started_at)
    if expansion_diagnostics.get("clicked_count", 0):
        current_probe = await _cached_probe(refresh_html=True)
        _append_readiness_probe(
            readiness_probes,
            stage="after_detail_expansion",
            probe=current_probe,
        )
    return (
        current_probe,
        readiness_probes,
        networkidle_timed_out,
        networkidle_skip_reason,
        readiness_diagnostics,
        expansion_diagnostics,
    )


async def _serialize_browser_page_content(
    page: Any,
    *,
    surface: str | None,
    traversal_mode: str | None,
    traversal_active: bool,
    timeout_seconds: float,
    max_pages: int,
    max_scrolls: int,
    phase_timings_ms: dict[str, int],
    on_event=None,
):
    traversal_result = None
    traversal_started_at = time.perf_counter()
    if traversal_active:
        traversal_result = await execute_listing_traversal(
            page,
            surface=str(surface or ""),
            traversal_mode=str(traversal_mode or ""),
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            timeout_seconds=timeout_seconds,
            on_event=on_event,
        )
        html = traversal_result.compose_html()
    else:
        html = ""
    phase_timings_ms["traversal"] = _elapsed_ms(traversal_started_at)

    serialization_started_at = time.perf_counter()
    if traversal_result is None:
        html = await page.content()
    phase_timings_ms["content_serialization"] = _elapsed_ms(
        serialization_started_at
    )
    return html, traversal_result


async def wait_for_listing_readiness(
    page: Any,
    page_url: str,
    *,
    override: dict[str, object] | None = None,
) -> dict[str, object]:
    override = override or resolve_listing_readiness_override(page_url)
    return await _wait_for_listing_readiness(page, override=override)


async def _wait_for_listing_readiness(
    page: Any,
    *,
    override: dict[str, object] | None,
) -> dict[str, object]:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

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
    except asyncio.CancelledError:
        raise
    except PlaywrightTimeoutError as exc:
        return {
            "platform": str(override.get("platform") or ""),
            "max_wait_ms": max_wait_ms,
            "status": "timed_out",
            "attempted_selectors": selectors,
            "failures": [f"{combined_selector}:{type(exc).__name__}"],
        }
    matched_selector = None
    for selector in selectors:
        if await page.locator(selector).count():
            matched_selector = selector
            break
    return {
        "platform": str(override.get("platform") or ""),
        "combined_selector": combined_selector,
        "max_wait_ms": max_wait_ms,
        "matched_selector": matched_selector or combined_selector,
        "status": "matched",
    }


async def probe_browser_readiness(
    page: Any,
    *,
    url: str,
    surface: str,
    listing_override: dict[str, object] | None = None,
    html: str | None = None,
) -> dict[str, object]:
    html_text = html if html is not None else await page.content()
    analysis = _BrowserHtmlAnalysis(html_text or "")
    visible_text_length = len(analysis.normalized_text)
    structured_data_present = any(
        token in analysis.lowered_html
        for token in (
            '"@type":"product"',
            '"@type":"jobposting"',
            "application/ld+json",
            "__next_data__",
            "__nuxt__",
            "shopifyanalytics.meta",
        )
    )
    detail_hints = detail_readiness_hint_count(surface, analysis.visible_text.lower())
    detail_like = analysis.h1_present or structured_data_present or detail_hints > 0
    listing_card_count = await listing_card_signal_count(page, surface=surface)
    matched_listing_selectors = await count_matching_selectors(
        page,
        selectors=list(listing_override.get("selectors") or [])
        if isinstance(listing_override, dict)
        else [],
    )
    is_detail = "detail" in surface
    is_listing = "listing" in surface
    if is_detail:
        is_ready = bool(
            structured_data_present
            or (
                detail_like
                and detail_hints >= int(crawler_runtime_settings.detail_field_signal_min_count)
                and visible_text_length >= int(crawler_runtime_settings.browser_readiness_visible_text_min)
            )
        )
    elif is_listing:
        is_ready = bool(
            listing_card_count >= int(crawler_runtime_settings.listing_min_items)
            or matched_listing_selectors > 0
        )
    else:
        is_ready = visible_text_length >= int(
            crawler_runtime_settings.browser_readiness_visible_text_min
        )
    return {
        "url": url,
        "surface": surface,
        "is_ready": is_ready,
        "detail_like": detail_like,
        "structured_data_present": structured_data_present,
        "visible_text_length": visible_text_length,
        "detail_hint_count": detail_hints,
        "listing_card_count": listing_card_count,
        "matched_listing_selectors": matched_listing_selectors,
        "h1_present": analysis.h1_present,
    }


async def listing_card_signal_count(page: Any, *, surface: str) -> int:
    selector_group = "jobs" if str(surface or "").strip().lower().startswith("job_") else "ecommerce"
    selectors = CARD_SELECTORS.get(selector_group) if isinstance(CARD_SELECTORS, dict) else []
    normalized_selectors = [
        str(selector).strip() for selector in list(selectors or []) if str(selector).strip()
    ]
    if not normalized_selectors:
        return 0
    return await count_listing_cards(
        page,
        surface=surface,
        allow_heuristic=False,
    )


async def count_matching_selectors(page: Any, *, selectors: list[str]) -> int:
    from playwright.async_api import Error as PlaywrightError

    matches = 0
    for selector in selectors:
        normalized = str(selector or "").strip()
        if not normalized:
            continue
        try:
            matches += int(await page.locator(normalized).count())
        except PlaywrightError:
            raise
        except Exception:
            continue
    return matches


def detail_readiness_hint_count(surface: str, visible_text: str) -> int:
    lowered_surface = str(surface or "").strip().lower()
    if "ecommerce" in lowered_surface:
        hints = _DETAIL_READINESS_HINTS["ecommerce"]
    elif "job" in lowered_surface:
        hints = _DETAIL_READINESS_HINTS["job"]
    else:
        hints = ()
    return sum(1 for hint in hints if hint in visible_text)


async def expand_detail_content_if_needed(
    page: Any,
    *,
    surface: str,
    readiness_probe: dict[str, object],
) -> dict[str, object]:
    current_probe = dict(readiness_probe or {})
    if "detail" not in str(surface or "").lower():
        return _detail_expansion_skip("non_detail_surface")
    if current_probe.get("is_ready"):
        return _detail_expansion_skip("already_ready")
    if readiness_probe and not current_probe.get("detail_like"):
        return _detail_expansion_skip("not_detail_like")
    dom = await expand_all_interactive_elements(
        page,
        surface=surface,
        max_elapsed_ms=int(crawler_runtime_settings.detail_expand_max_elapsed_ms),
    )
    if dom.get("clicked_count", 0):
        current_probe = await probe_browser_readiness(
            page,
            url=str(getattr(page, "url", "") or ""),
            surface=surface,
        )
    aom = {
        "status": "skipped",
        "reason": "not_needed",
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
        "limit": int(crawler_runtime_settings.detail_aom_expand_max_interactions),
        "max_elapsed_ms": int(crawler_runtime_settings.detail_aom_expand_max_elapsed_ms),
        "attempted": False,
    }
    if not current_probe.get("is_ready"):
        aom = await expand_interactive_elements_via_accessibility(
            page,
            surface=surface,
            max_elapsed_ms=int(crawler_runtime_settings.detail_aom_expand_max_elapsed_ms),
        )
    return {
        "status": "expanded"
        if dom.get("clicked_count", 0) or aom.get("clicked_count", 0)
        else "attempted",
        "reason": "missing_detail_content",
        "clicked_count": int(dom.get("clicked_count", 0) or 0)
        + int(aom.get("clicked_count", 0) or 0),
        "expanded_elements": [
            *list(dom.get("expanded_elements") or []),
            *list(aom.get("expanded_elements") or []),
        ],
        "interaction_failures": [
            *list(dom.get("interaction_failures") or []),
            *list(aom.get("interaction_failures") or []),
        ],
        "dom": dom,
        "aom": aom,
    }
async def expand_all_interactive_elements(
    page: Any,
    *,
    surface: str = "",
    checkpoint: Any = None,
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    del checkpoint
    started_at = time.perf_counter()
    diagnostics: dict[str, object] = {
        "status": "attempted",
        "buttons_found": 0,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
        "limit": int(crawler_runtime_settings.detail_expand_max_interactions),
        "max_elapsed_ms": max_elapsed_ms,
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
            diagnostics["status"] = "interaction_limit_reached"
            break
        if max_elapsed_ms is not None and _elapsed_ms(started_at) >= int(max_elapsed_ms):
            diagnostics["status"] = "time_budget_reached"
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
    if diagnostics["status"] == "attempted":
        diagnostics["status"] = "expanded" if clicked_count > 0 else "no_matches"
    diagnostics["clicked_count"] = clicked_count
    diagnostics["expanded_elements"] = expanded_elements
    diagnostics["interaction_failures"] = interaction_failures
    diagnostics["elapsed_ms"] = _elapsed_ms(started_at)
    return diagnostics


async def expand_interactive_elements_via_accessibility(
    page: Any,
    *,
    surface: str = "",
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    started_at = time.perf_counter()
    diagnostics: dict[str, object] = {
        "status": "attempted",
        "attempted": False,
        "limit": int(crawler_runtime_settings.detail_aom_expand_max_interactions),
        "max_elapsed_ms": max_elapsed_ms,
        "buttons_found": 0,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
    }
    accessibility = getattr(page, "accessibility", None)
    snapshot_fn = getattr(accessibility, "snapshot", None)
    if snapshot_fn is None:
        diagnostics["status"] = "skipped"
        diagnostics["reason"] = "accessibility_unavailable"
        diagnostics["elapsed_ms"] = _elapsed_ms(started_at)
        return diagnostics
    diagnostics["attempted"] = True
    try:
        snapshot = await snapshot_fn()
    except Exception as exc:
        diagnostics["status"] = "snapshot_failed"
        diagnostics["interaction_failures"] = [f"snapshot_failed:{exc}"]
        diagnostics["elapsed_ms"] = _elapsed_ms(started_at)
        return diagnostics
    candidates = accessibility_expand_candidates(snapshot, surface=surface)
    diagnostics["buttons_found"] = len(candidates)
    max_interactions = max(0, int(crawler_runtime_settings.detail_aom_expand_max_interactions))
    if len(candidates) > max_interactions:
        keywords = detail_expansion_keywords(surface)
        if keywords:
            prioritized = [
                item for item in candidates if any(keyword in item[1] for keyword in keywords)
            ]
            prioritized_set = set(prioritized)
            candidates = prioritized + [
                item for item in candidates if item not in prioritized_set
            ]
        diagnostics["skipped_count"] = len(candidates) - max_interactions
    for role, name in candidates[:max_interactions]:
        if max_elapsed_ms is not None and _elapsed_ms(started_at) >= int(max_elapsed_ms):
            diagnostics["status"] = "time_budget_reached"
            break
        try:
            locator_factory = getattr(page, "get_by_role", None)
            if locator_factory is None:
                diagnostics["interaction_failures"].append("get_by_role_unavailable")
                diagnostics["status"] = "locator_unavailable"
                break
            locator = locator_factory(role, name=name, exact=True)
            locator = getattr(locator, "first", locator)
            if hasattr(locator, "count") and await locator.count() == 0:
                continue
            if hasattr(locator, "is_visible") and not await locator.is_visible(timeout=250):
                continue
            if hasattr(locator, "is_disabled") and await locator.is_disabled():
                continue
            await locator.click(timeout=1_000)
            if int(crawler_runtime_settings.accordion_expand_wait_ms) > 0:
                await page.wait_for_timeout(
                    int(crawler_runtime_settings.accordion_expand_wait_ms)
                )
            diagnostics["clicked_count"] += 1
            diagnostics["expanded_elements"].append(name)
        except Exception as exc:
            diagnostics["interaction_failures"].append(str(exc))
    if diagnostics["status"] == "attempted":
        diagnostics["status"] = (
            "expanded" if diagnostics["clicked_count"] > 0 else "no_matches"
        )
    diagnostics["elapsed_ms"] = _elapsed_ms(started_at)
    return diagnostics


def _detail_expansion_skip(reason: str) -> dict[str, object]:
    return {
        "status": "skipped",
        "reason": reason,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
        "dom": {},
        "aom": {},
    }


def accessibility_expand_candidates(
    snapshot: dict[str, object] | None,
    *,
    surface: str,
) -> list[tuple[str, str]]:
    keywords = detail_expansion_keywords(surface)
    if not snapshot:
        return []
    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _walk(node: dict[str, object]) -> None:
        role = str(node.get("role") or "").strip().lower()
        name = " ".join(str(node.get("name") or "").split()).strip().lower()
        candidate = (role, name)
        if (
            role in _AOM_EXPAND_ROLES
            and name
            and (not keywords or any(keyword in name for keyword in keywords))
            and candidate not in seen
        ):
            seen.add(candidate)
            results.append(candidate)
        for child in list(node.get("children") or []):
            if isinstance(child, dict):
                _walk(child)

    _walk(snapshot)
    return results


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
def classify_browser_outcome(
    *,
    html: str,
    html_bytes: int,
    blocked: bool,
    block_classification: BlockPageClassification | None = None,
    traversal_result: Any = None,
) -> str:
    classification = block_classification or BlockPageClassification(
        blocked=blocked,
        outcome="challenge_page" if blocked else "ok",
    )
    if classification.blocked or blocked:
        return "challenge_page"
    if traversal_result is not None and bool(getattr(traversal_result, "activated", False)):
        progress_events = int(getattr(traversal_result, "progress_events", 0) or 0)
        stop_reason = str(getattr(traversal_result, "stop_reason", "") or "").strip()
        if progress_events == 0 and stop_reason.endswith(("_not_found", "_no_progress")):
            return "traversal_failed"
    if looks_like_low_content_shell(html, html_bytes=html_bytes):
        return "low_content_shell"
    return "usable_content"


def browser_host_preference_eligible(
    *,
    browser_outcome: str | None,
    blocked: bool,
) -> bool:
    if blocked:
        return False
    return str(browser_outcome or "").strip().lower() == "usable_content"


def looks_like_low_content_shell(html: str, *, html_bytes: int) -> bool:
    return classify_low_content_reason(html, html_bytes=html_bytes) is not None


def classify_low_content_reason(html: str, *, html_bytes: int) -> str | None:
    analysis = _BrowserHtmlAnalysis(html)
    if not analysis.html.strip():
        return "empty_html"
    lowered_text = analysis.normalized_text.lower()
    if any(
        phrase in lowered_text
        for phrase in (
            "empty category",
            "no products found",
            "no jobs found",
            "0 results",
            "there are no items",
        )
    ):
        return "empty_terminal_page"
    if len(analysis.normalized_text) >= 120:
        return None
    if any(
        token in analysis.lowered_html
        for token in ("product", "jobposting", "__next_data__", "__nuxt__", "application/ld+json")
    ):
        return None
    if html_bytes <= 8_000:
        return "low_visible_text"
    return None


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
def build_failed_browser_diagnostics(
    *,
    browser_reason: str | None,
    exc: Exception,
) -> dict[str, object]:
    outcome = "render_timeout" if _is_timeout_error(exc) else "navigation_failed"
    failure_kind = _browser_failure_kind(exc)
    return {
        "browser_attempted": True,
        "browser_reason": str(browser_reason or "").strip().lower() or None,
        "browser_outcome": outcome,
        "failure_kind": failure_kind,
        "failure_stage": "navigation",
        "error": f"{type(exc).__name__}: {exc}",
        "navigation_strategy": getattr(exc, "browser_navigation_strategy", None),
        "phase_timings_ms": dict(
            getattr(exc, "browser_phase_timings_ms", {}) or {}
        ),
    }


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


async def _emit_browser_event(on_event, level: str, message: str) -> None:
    if on_event is None:
        return
    try:
        await on_event(level, message)
    except Exception:
        logger.debug("Browser event callback failed", exc_info=True)


def _is_timeout_error(exc: Exception) -> bool:
    class_name = type(exc).__name__.lower()
    message = str(exc or "").lower()
    return "timeout" in class_name or "timeout" in message


def _browser_failure_kind(exc: Exception) -> str:
    class_name = type(exc).__name__.lower()
    message = str(exc or "").lower()
    if "targetclosed" in class_name or "target closed" in message:
        return "page_closed"
    if "page closed" in message or "browser has been closed" in message:
        return "page_closed"
    if _is_timeout_error(exc):
        return "timeout"
    return "navigation_error"


__all__ = [
    "SharedBrowserRuntime",
    "_BROWSER_PREFERRED_HOSTS",
    "_BROWSER_PREFERRED_HOST_SUCCESSES",
    "_MAX_CAPTURED_NETWORK_PAYLOADS",
    "_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES",
    "_NETWORK_CAPTURE_QUEUE_SIZE",
    "_NETWORK_CAPTURE_WORKERS",
    "NetworkPayloadReadResult",
    "browser_fetch",
    "browser_runtime_snapshot",
    "build_failed_browser_diagnostics",
    "browser_host_preference_eligible",
    "capture_browser_screenshot",
    "classify_network_endpoint",
    "classify_browser_outcome",
    "expand_all_interactive_elements",
    "get_browser_runtime",
    "host_prefers_browser",
    "looks_like_low_content_shell",
    "prune_browser_preferred_hosts",
    "read_network_payload_body",
    "remember_browser_host_if_good",
    "should_capture_network_payload",
    "shutdown_browser_runtime",
    "shutdown_browser_runtime_sync",
    "temporary_browser_page",
]
