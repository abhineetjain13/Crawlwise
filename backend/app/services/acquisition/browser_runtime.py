from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx
from bs4 import BeautifulSoup

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
from app.services.acquisition.browser_detail import (
    accessibility_expand_candidates_impl,
    detail_expansion_skip,
    expand_all_interactive_elements_impl,
    expand_detail_content_if_needed_impl,
    expand_interactive_elements_via_accessibility_impl,
)
from app.services.acquisition.browser_identity import (
    build_playwright_context_options,
    clear_browser_identity_cache,
)
from app.services.acquisition.browser_page_flow import (
    BrowserFinalizeInput,
    append_readiness_probe,
    finalize_browser_fetch,
    navigate_browser_page_impl,
    remaining_timeout_factory,
    resolve_browser_fetch_policy as resolve_browser_fetch_policy_impl,
    serialize_browser_page_content_impl,
    settle_browser_page_impl,
)
from app.services.acquisition.browser_readiness import (
    classify_browser_outcome_impl,
    classify_low_content_reason_impl,
    count_matching_selectors,
    probe_browser_readiness_impl,
    visible_text_from_soup as visible_text_from_soup_impl,
    wait_for_listing_readiness_impl,
)
from app.services.acquisition.runtime import (
    BlockPageClassification,
    NetworkPayloadReadResult,
    classify_blocked_page_async,
    PageFetchResult,
    is_blocked_html_async,
)
from app.services.acquisition.traversal import (
    count_listing_cards,
    execute_listing_traversal,
    should_run_traversal,
)
from app.services.config.extraction_rules import (
    BROWSER_DETAIL_EXPAND_KEYWORDS,
    BROWSER_DETAIL_READINESS_HINTS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS
from app.services.field_value_core import clean_text
from app.services.field_value_core import hostname
from app.services.platform_policy import resolve_listing_readiness_override

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)

_BLOCKED_RESOURCE_TYPES = {"font", "image", "media", "stylesheet"}
_BLOCKED_TRACKER_TOKENS = (
    "doubleclick",
    "facebook",
    "google-analytics",
    "googletagmanager",
)

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
    str(key): tuple(str(item) for item in list(value or []))
    for key, value in dict(BROWSER_DETAIL_EXPAND_KEYWORDS or {}).items()
}
_DETAIL_READINESS_HINTS: dict[str, tuple[str, ...]] = {
    str(key): tuple(str(item) for item in list(value or []))
    for key, value in dict(BROWSER_DETAIL_READINESS_HINTS or {}).items()
}
_AOM_EXPAND_ROLES = {"button", "tab"}


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
            await _configure_context_routes(context)
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
        }


async def _configure_context_routes(context: Any) -> None:
    try:
        await context.route("**/*", _block_unneeded_route)
    except Exception:
        logger.debug("Failed to install browser request blocking", exc_info=True)


async def _block_unneeded_route(route: Any) -> None:
    request = getattr(route, "request", None)
    resource_type = str(getattr(request, "resource_type", "") or "").lower()
    request_url = str(getattr(request, "url", "") or "").lower()
    should_abort = (
        resource_type in _BLOCKED_RESOURCE_TYPES
        or any(token in request_url for token in _BLOCKED_TRACKER_TOKENS)
    )
    if should_abort:
        try:
            await route.abort()
            return
        except Exception:
            logger.debug(
                "Browser request abort failed for resource_type=%s url=%s; attempting continue",
                resource_type,
                request_url,
                exc_info=True,
            )
            try:
                await route.continue_()
                return
            except Exception:
                logger.debug(
                    "Browser request continue failed after abort failure for resource_type=%s url=%s",
                    resource_type,
                    request_url,
                    exc_info=True,
                )
                return
    try:
        await route.continue_()
    except Exception:
        logger.debug(
            "Browser request continue failed for resource_type=%s url=%s",
            resource_type,
            request_url,
            exc_info=True,
        )


@asynccontextmanager
async def temporary_browser_page(*, proxy: str, run_id: int | None = None):
    runtime = await get_browser_runtime()
    async with runtime.page(proxy=proxy, run_id=run_id) as page:
        yield page

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


def _log_shutdown_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.debug("Browser runtime shutdown task was cancelled")
    except Exception:
        logger.exception("Browser runtime shutdown task failed")


def _build_payload_capture(*, surface: str) -> _BrowserNetworkCapture:
    return _BrowserNetworkCapture(
        surface=surface,
        should_capture_payload=should_capture_network_payload,
        classify_endpoint=classify_network_endpoint,
        read_payload_body=read_network_payload_body,
    )


def _resolve_browser_fetch_policy(
    *,
    url: str,
    surface: str,
    traversal_mode: str | None,
) -> tuple[bool, dict[str, object], dict[str, object] | None]:
    return resolve_browser_fetch_policy_impl(
        url=url,
        surface=surface,
        traversal_mode=traversal_mode,
        should_run_traversal=should_run_traversal,
    )


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
        _remaining = remaining_timeout_factory(started_at + float(timeout_seconds))
        phase_timings_ms: dict[str, int] = {}
        normalized_surface = str(surface or "")
        payload_capture = _build_payload_capture(surface=normalized_surface)
        payload_capture.attach(page)
        traversal_active, readiness_policy, readiness_override = _resolve_browser_fetch_policy(
            url=url,
            surface=normalized_surface,
            traversal_mode=traversal_mode,
        )
        try:
            response, navigation_strategy = await _navigate_browser_page(
                page,
                url=url,
                timeout_seconds=_remaining(),
                phase_timings_ms=phase_timings_ms,
                readiness_policy=readiness_policy,
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
            html, traversal_result, rendered_html = await _serialize_browser_page_content(
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
            finalized = await finalize_browser_fetch(
                BrowserFinalizeInput(
                    page=page,
                    url=url,
                    surface=surface,
                    browser_reason=browser_reason,
                    on_event=on_event,
                    response=response,
                    navigation_strategy=navigation_strategy,
                    readiness_probes=readiness_probes,
                    networkidle_timed_out=networkidle_timed_out,
                    networkidle_skip_reason=networkidle_skip_reason,
                    readiness_policy=readiness_policy,
                    readiness_diagnostics=readiness_diagnostics,
                    expansion_diagnostics=expansion_diagnostics,
                    payload_capture=payload_capture,
                    html=html,
                    traversal_result=traversal_result,
                    rendered_html=rendered_html,
                    phase_timings_ms=phase_timings_ms,
                    started_at=started_at,
                ),
                blocked_html_checker=blocked_html_checker,
                classify_blocked_page_async=classify_blocked_page_async,
                classify_low_content_reason=classify_low_content_reason,
                classify_browser_outcome=classify_browser_outcome,
                capture_browser_screenshot=capture_browser_screenshot,
                emit_browser_event=_emit_browser_event,
                elapsed_ms=_elapsed_ms,
            )
            return PageFetchResult(
                url=url,
                final_url=page.url,
                html=html,
                status_code=int(finalized["status_code"]),
                method="browser",
                content_type=str(finalized["content_type"]),
                blocked=bool(finalized["blocked"]),
                platform_family=finalized["platform_family"],
                headers=finalized["page_headers"],
                network_payloads=list(finalized["network_payloads"]),
                browser_diagnostics=dict(finalized["diagnostics"]),
                artifacts=dict(finalized["artifacts"]),
            )
        finally:
            await payload_capture.close(page)


async def _navigate_browser_page(
    page: Any,
    *,
    url: str,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
    readiness_policy: dict[str, object] | None = None,
):
    return await navigate_browser_page_impl(
        page,
        url=url,
        timeout_seconds=timeout_seconds,
        phase_timings_ms=phase_timings_ms,
        readiness_policy=readiness_policy,
        crawler_runtime_settings=crawler_runtime_settings,
        elapsed_ms=_elapsed_ms,
    )


async def _settle_browser_page(
    page: Any,
    *,
    url: str,
    surface: str,
    timeout_seconds: float,
    readiness_override: dict[str, object] | None,
    readiness_policy: dict[str, object],
    phase_timings_ms: dict[str, int],
):
    return await settle_browser_page_impl(
        page,
        url=url,
        surface=surface,
        timeout_seconds=timeout_seconds,
        readiness_override=readiness_override,
        readiness_policy=readiness_policy,
        phase_timings_ms=phase_timings_ms,
        crawler_runtime_settings=crawler_runtime_settings,
        probe_browser_readiness=probe_browser_readiness,
        wait_for_listing_readiness=wait_for_listing_readiness,
        expand_detail_content_if_needed=expand_detail_content_if_needed,
        append_readiness_probe=append_readiness_probe,
        elapsed_ms=_elapsed_ms,
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
    return await serialize_browser_page_content_impl(
        page,
        surface=surface,
        traversal_mode=traversal_mode,
        traversal_active=traversal_active,
        timeout_seconds=timeout_seconds,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        phase_timings_ms=phase_timings_ms,
        execute_listing_traversal=execute_listing_traversal,
        elapsed_ms=_elapsed_ms,
        on_event=on_event,
    )


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
    return await wait_for_listing_readiness_impl(page, override=override)


async def probe_browser_readiness(
    page: Any,
    *,
    url: str,
    surface: str,
    listing_override: dict[str, object] | None = None,
    html: str | None = None,
) -> dict[str, object]:
    return await probe_browser_readiness_impl(
        page,
        url=url,
        surface=surface,
        listing_override=listing_override,
        html=html,
        detail_readiness_hint_count=detail_readiness_hint_count,
    )


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
    return await expand_detail_content_if_needed_impl(
        page,
        surface=surface,
        readiness_probe=readiness_probe,
        expand_all_interactive_elements=expand_all_interactive_elements,
        probe_browser_readiness=probe_browser_readiness,
        expand_interactive_elements_via_accessibility=expand_interactive_elements_via_accessibility,
    )


async def expand_all_interactive_elements(
    page: Any,
    *,
    surface: str = "",
    checkpoint: Any = None,
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    del checkpoint
    return await expand_all_interactive_elements_impl(
        page,
        surface=surface,
        detail_expand_selectors=_DETAIL_EXPAND_SELECTORS,
        detail_expansion_keywords=detail_expansion_keywords,
        interactive_label=interactive_label,
        is_actionable_interactive_handle=is_actionable_interactive_handle,
        elapsed_ms=_elapsed_ms,
        max_elapsed_ms=max_elapsed_ms,
    )


async def expand_interactive_elements_via_accessibility(
    page: Any,
    *,
    surface: str = "",
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    return await expand_interactive_elements_via_accessibility_impl(
        page,
        surface=surface,
        accessibility_expand_candidates=accessibility_expand_candidates,
        detail_expansion_keywords=detail_expansion_keywords,
        elapsed_ms=_elapsed_ms,
        max_elapsed_ms=max_elapsed_ms,
    )


def accessibility_expand_candidates(
    snapshot: dict[str, object] | None,
    *,
    surface: str,
) -> list[tuple[str, str]]:
    return accessibility_expand_candidates_impl(
        snapshot,
        surface=surface,
        aom_expand_roles=_AOM_EXPAND_ROLES,
        detail_expansion_keywords=detail_expansion_keywords,
    )


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
    return classify_browser_outcome_impl(
        html=html,
        html_bytes=html_bytes,
        blocked=blocked,
        block_classification=classification,
        traversal_result=traversal_result,
        looks_like_low_content_shell=looks_like_low_content_shell,
    )

def looks_like_low_content_shell(html: str, *, html_bytes: int) -> bool:
    return classify_low_content_reason(html, html_bytes=html_bytes) is not None


def classify_low_content_reason(html: str, *, html_bytes: int) -> str | None:
    return classify_low_content_reason_impl(html, html_bytes=html_bytes)


def _visible_text_from_soup(soup: BeautifulSoup) -> str:
    return visible_text_from_soup_impl(soup)
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
    "_MAX_CAPTURED_NETWORK_PAYLOADS",
    "_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES",
    "_NETWORK_CAPTURE_QUEUE_SIZE",
    "_NETWORK_CAPTURE_WORKERS",
    "NetworkPayloadReadResult",
    "browser_fetch",
    "browser_runtime_snapshot",
    "build_failed_browser_diagnostics",
    "capture_browser_screenshot",
    "classify_network_endpoint",
    "classify_browser_outcome",
    "expand_all_interactive_elements",
    "get_browser_runtime",
    "looks_like_low_content_shell",
    "read_network_payload_body",
    "should_capture_network_payload",
    "shutdown_browser_runtime",
    "shutdown_browser_runtime_sync",
    "temporary_browser_page",
]
