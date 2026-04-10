# Playwright browser acquisition client with optional proxy and network interception.
from __future__ import annotations

import logging

import asyncio
import ipaddress
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
import time
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from app.core.config import settings
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_runtime import BrowserRuntimeOptions
from app.services.acquisition.traversal import (
    TraversalResult,
    TraversalConfig,
    apply_traversal_mode as _apply_traversal_mode_shared,
    click_and_observe_next_page as _click_and_observe_next_page_shared,
    click_load_more as _click_load_more_shared,
    collect_paginated_html as _collect_paginated_html_shared,
    find_next_page_url_anchor_only as _find_next_page_url_anchor_only_shared,
    has_load_more_control as _has_load_more_control_shared,
    pagination_state_changed as _pagination_state_changed_shared,
    peek_next_page_signal as _peek_next_page_signal_shared,
    scroll_to_bottom as _scroll_to_bottom_shared,
    snapshot_pagination_state as _snapshot_pagination_state_shared,
)
from app.services.acquisition.cookie_store import (
    cookie_policy_for_domain,
    cookie_store_path,
    filter_persistable_cookies,
    load_cookies_for_context,
    save_cookies_payload,
)
from app.services.runtime_metrics import incr
from app.services.pipeline_config import (
    ACCORDION_EXPAND_WAIT_MS,
    BLOCK_MIN_HTML_LENGTH,
    BLOCK_BROWSER_CHALLENGE_STRONG_MARKERS,
    BLOCK_BROWSER_CHALLENGE_WEAK_MARKERS,
    BROWSER_ERROR_RETRY_ATTEMPTS,
    BROWSER_ERROR_RETRY_DELAY_MS,
    BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS,
    BROWSER_NAVIGATION_LOAD_TIMEOUT_MS,
    BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS,
    CHALLENGE_POLL_INTERVAL_MS,
    CHALLENGE_WAIT_MAX_SECONDS,
    COOKIE_CONSENT_POSTCLICK_WAIT_MS,
    COOKIE_CONSENT_SELECTORS,
    COOKIE_CONSENT_PREWAIT_MS,
    CARD_SELECTORS_COMMERCE,
    CARD_SELECTORS_JOBS,
    DEFAULT_MAX_SCROLLS,
    DOM_PATTERNS,
    INTERRUPTIBLE_WAIT_POLL_MS,
    LISTING_MIN_ITEMS,
    LISTING_READINESS_MAX_WAIT_MS,
    LISTING_READINESS_POLL_MS,
    LOAD_MORE_WAIT_MIN_MS,
    LOAD_MORE_SELECTORS,
    ORIGIN_WARM_PAUSE_MS,
    PAGINATION_NAVIGATION_TIMEOUT_MS,
    PAGINATION_NEXT_SELECTORS,
    SCROLL_WAIT_MIN_MS,
    SHADOW_DOM_FLATTEN_MAX_HOSTS,
    SURFACE_READINESS_MAX_WAIT_MS,
    SURFACE_READINESS_POLL_MS,
)
from app.services.url_safety import validate_public_target

logger = logging.getLogger(__name__)

_RETRYABLE_PAGE_CONTENT_ERROR_RE = re.compile(
    r"(page is navigating|changing the content)",
    re.IGNORECASE,
)
_BROWSER_POOL_MAX_SIZE = 6
_BROWSER_POOL_IDLE_TTL_SECONDS = 300
_BROWSER_POOL_HEALTHCHECK_INTERVAL_SECONDS = 60


def _traversal_config() -> TraversalConfig:
    return TraversalConfig(
        pagination_next_selectors=list(PAGINATION_NEXT_SELECTORS),
        load_more_selectors=list(LOAD_MORE_SELECTORS),
        scroll_wait_min_ms=SCROLL_WAIT_MIN_MS,
        load_more_wait_min_ms=LOAD_MORE_WAIT_MIN_MS,
        validate_public_target=validate_public_target,
    )


@dataclass
class _PooledBrowser:
    browser: object
    last_used_monotonic: float


_BROWSER_POOL: dict[str, _PooledBrowser] = {}
_BROWSER_POOL_LOCK = asyncio.Lock()
_BROWSER_POOL_TASK_LOCK = asyncio.Lock()
_BROWSER_POOL_CLEANUP_TASK: asyncio.Task | None = None


@dataclass
class BrowserResult:
    """Result from a Playwright render including intercepted payloads."""

    html: str = ""
    network_payloads: list[dict] = field(default_factory=list)
    frame_sources: list[dict] = field(default_factory=list)
    promoted_sources: list[dict] = field(default_factory=list)
    challenge_state: str = "none"
    origin_warmed: bool = False
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass
class ChallengeAssessment:
    state: str
    should_wait: bool
    reasons: list[str] = field(default_factory=list)


_STEALTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


async def fetch_rendered_html(
    url: str,
    proxy: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    prefer_stealth: bool = False,
    request_delay_ms: int = 0,
    runtime_options: BrowserRuntimeOptions | None = None,
    requested_fields: list[str] | None = None,
    requested_field_selectors: dict[str, list[dict]] | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
    run_id: int | None = None,
) -> BrowserResult:
    """Render a page with Playwright and intercept XHR/fetch responses.

    Args:
        url: Target URL.
        proxy: Optional proxy URL.
        traversal_mode: None, "paginate", "scroll", "load_more", or "auto".
        max_scrolls: Max scroll attempts (for scroll mode).
    """
    target = await validate_public_target(url)

    async with async_playwright() as pw:
        return await _fetch_rendered_html_with_fallback(
            pw,
            target=target,
            url=url,
            proxy=proxy,
            surface=surface,
            traversal_mode=traversal_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            prefer_stealth=prefer_stealth,
            request_delay_ms=request_delay_ms,
            runtime_options=runtime_options or BrowserRuntimeOptions(),
            requested_fields=requested_fields or [],
            requested_field_selectors=requested_field_selectors or {},
            checkpoint=checkpoint,
            run_id=run_id,
        )


async def _fetch_rendered_html_with_fallback(
    pw,
    *,
    target,
    url: str,
    proxy: str | None,
    surface: str | None = None,
    traversal_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    prefer_stealth: bool,
    request_delay_ms: int,
    runtime_options: BrowserRuntimeOptions | None,
    requested_fields: list[str],
    requested_field_selectors: dict[str, list[dict]],
    checkpoint: Callable[[], Awaitable[None]] | None = None,
    run_id: int | None = None,
) -> BrowserResult:
    last_error: Exception | None = None
    first_profile_failure_reason: str | None = None
    options = runtime_options or BrowserRuntimeOptions()
    profiles = _browser_launch_profiles(options)
    for index, profile in enumerate(profiles):
        navigation_strategies = (
            _shortened_navigation_strategies()
            if _should_shorten_navigation_after_profile_failure(first_profile_failure_reason)
            else _navigation_strategies(browser_channel=str(profile.get("channel") or "").strip() or None)
        )
        try:
            result = await _fetch_rendered_html_attempt(
                pw,
                target=target,
                url=url,
                proxy=proxy,
                surface=surface,
                traversal_mode=traversal_mode,
                max_pages=max_pages,
                max_scrolls=max_scrolls,
                prefer_stealth=prefer_stealth,
                request_delay_ms=request_delay_ms,
                runtime_options=options,
                requested_fields=requested_fields,
                requested_field_selectors=requested_field_selectors,
                launch_profile=profile,
                navigation_strategies=navigation_strategies,
                checkpoint=checkpoint,
                run_id=run_id,
            )
            result.diagnostics["browser_launch_profile"] = profile["label"]
            if index < len(profiles) - 1 and _should_retry_launch_profile(result, surface=surface):
                first_profile_failure_reason = "low_value_result"
                logger.info(
                    "Playwright %s produced a low-value result for %s; trying next launch profile",
                    profile["label"],
                    url,
                )
                continue
            return result
        except (PlaywrightError, RuntimeError, ValueError, TypeError, OSError) as exc:
            last_error = exc
            first_profile_failure_reason = _classify_profile_failure_reason(exc)
            logger.warning("Playwright %s failed for %s: %s", profile["label"], url, exc)
            continue
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Unable to render {url}")


async def _fetch_rendered_html_attempt(
    pw,
    *,
    target,
    url: str,
    proxy: str | None,
    surface: str | None,
    traversal_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    prefer_stealth: bool,
    request_delay_ms: int,
    runtime_options: BrowserRuntimeOptions,
    requested_fields: list[str],
    requested_field_selectors: dict[str, list[dict]],
    launch_profile: dict[str, str | None],
    navigation_strategies: list[tuple[str, int]] | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
    run_id: int | None = None,
) -> BrowserResult:
    result = BrowserResult()
    intercepted: list[dict] = []
    blocked_non_public_requests: list[dict[str, str]] = []
    timings_ms: dict[str, int] = {}
    browser_started_at = time.perf_counter()
    browser_type = getattr(pw, str(launch_profile.get("browser_type") or "chromium"))
    launch_kwargs = _build_launch_kwargs(
        proxy,
        target,
        browser_channel=str(launch_profile.get("channel") or "").strip() or None,
    )
    launch_started_at = time.perf_counter()
    browser, browser_reused = await _acquire_browser(
        browser_type=browser_type,
        launch_kwargs=launch_kwargs,
        browser_pool_key=_browser_pool_key(launch_profile, proxy),
    )
    timings_ms["browser_launch_ms"] = _elapsed_ms(launch_started_at)
    timings_ms["browser_reused"] = int(browser_reused)
    browser_channel = str(launch_profile.get("channel") or "").strip() or None
    try:
        # FIX: Wrap context creation in a strict timeout to prevent zombie browsers
        context = await asyncio.wait_for(
            browser.new_context(
                **_context_kwargs(
                    prefer_stealth,
                    browser_channel=browser_channel,
                    runtime_options=runtime_options,
                )
            ),
            timeout=15.0
        )
    except (PlaywrightError, asyncio.TimeoutError):
        # Browser in pool may have died or hung; evict and retry once.
        await _evict_browser(_browser_pool_key(launch_profile, proxy), browser)
        browser, _ = await _acquire_browser(
            browser_type=browser_type,
            launch_kwargs=launch_kwargs,
            browser_pool_key=_browser_pool_key(launch_profile, proxy),
            force_new=True,
        )
        context = await asyncio.wait_for(
            browser.new_context(
                **_context_kwargs(
                    prefer_stealth,
                    browser_channel=browser_channel,
                    runtime_options=runtime_options,
                )
            ),
            timeout=15.0
        )
        
    original_domain = _domain(url)
    try:
        await _load_cookies(context, original_domain)
        # FIX: Wrap page creation in timeout
        page = await asyncio.wait_for(context.new_page(), timeout=10.0)

        async def _guard_non_public_request(route, request) -> None:
            request_url = str(getattr(request, "url", "") or "").strip()
            allowed, reason = await _is_public_browser_request_target(request_url)
            if allowed:
                await route.continue_()
                return
            blocked_non_public_requests.append(
                {
                    "url": request_url,
                    "resource_type": str(getattr(request, "resource_type", "") or ""),
                    "reason": reason,
                }
            )
            try:
                await route.abort("blockedbyclient")
            except PlaywrightError:
                await route.abort()

        route_fn = getattr(page, "route", None)
        if callable(route_fn):
            await route_fn("**/*", _guard_non_public_request)

        async def _on_response(response):
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body = await response.json()
                    intercepted.append({
                        "url": response.url,
                        "status": response.status,
                        "body": body,
                    })
                except (PlaywrightError, ValueError):
                    logger.debug("Failed to parse intercepted JSON response from %s", response.url, exc_info=True)

        page.on("response", _on_response)

        if browser_channel:
            result.origin_warmed = False
            timings_ms["browser_origin_warm_ms"] = 0
        elif not runtime_options.warm_origin:
            # Skip origin warming for non-stealth requests to save 2s per domain.
            result.origin_warmed = False
            timings_ms["browser_origin_warm_ms"] = 0
        else:
            origin_warm_started_at = time.perf_counter()
            result.origin_warmed = await _maybe_warm_origin(page, url, checkpoint=checkpoint)
            timings_ms["browser_origin_warm_ms"] = _elapsed_ms(origin_warm_started_at)

        navigation_started_at = time.perf_counter()
        await _goto_with_fallback(
            page,
            url,
            surface=surface,
            strategies=navigation_strategies or _navigation_strategies(browser_channel=browser_channel),
            checkpoint=checkpoint,
        )
        timings_ms["browser_navigation_ms"] = _elapsed_ms(navigation_started_at)
        await _dismiss_cookie_consent(page, checkpoint=checkpoint)
        if runtime_options.wait_for_challenge:
            challenge_started_at = time.perf_counter()
            challenge_ok, challenge_state, reasons = await _wait_for_challenge_resolution(
                page,
                surface=surface,
                checkpoint=checkpoint,
            )
            timings_ms["browser_challenge_wait_ms"] = _elapsed_ms(challenge_started_at)
        else:
            challenge_ok, challenge_state, reasons = True, "skipped", []
            timings_ms["browser_challenge_wait_ms"] = 0
        result.challenge_state = challenge_state
        result.diagnostics["challenge_reasons"] = reasons
        result.diagnostics["challenge_ok"] = challenge_ok
        result.diagnostics["anti_bot_enabled"] = runtime_options.anti_bot_enabled
        if not challenge_ok:
            await _populate_result(result, page, intercepted, checkpoint=checkpoint)
            result.diagnostics["final_url"] = page.url or url
            result.diagnostics["html_length"] = len(result.html or "")
            result.diagnostics["blocked"] = detect_blocked_page(result.html).is_blocked
            timings_ms["browser_total_ms"] = _elapsed_ms(browser_started_at)
            result.diagnostics["timings_ms"] = timings_ms
            await _persist_context_cookies(context, page.url or url, original_domain)
            return result
        if runtime_options.wait_for_readiness and _is_listing_surface(surface):
            readiness_started_at = time.perf_counter()
            listing_readiness = await _wait_for_listing_readiness(page, surface, checkpoint=checkpoint)
            timings_ms["browser_listing_readiness_wait_ms"] = _elapsed_ms(readiness_started_at)
            if listing_readiness is not None:
                result.diagnostics["listing_readiness"] = listing_readiness
                result.diagnostics["surface_readiness"] = listing_readiness
            if listing_readiness and not bool(listing_readiness.get("ready")) and await _page_looks_low_value(page):
                await _populate_result(result, page, intercepted, checkpoint=checkpoint)
                timings_ms["browser_total_ms"] = _elapsed_ms(browser_started_at)
                result.diagnostics["timings_ms"] = timings_ms
                await _persist_context_cookies(context, page.url or url, original_domain)
                return result
        elif runtime_options.wait_for_readiness:
            readiness_started_at = time.perf_counter()
            surface_readiness = await _wait_for_surface_readiness(
                page,
                surface=surface,
                checkpoint=checkpoint,
            )
            timings_ms["browser_surface_readiness_wait_ms"] = _elapsed_ms(readiness_started_at)
            if surface_readiness is not None:
                result.diagnostics["surface_readiness"] = surface_readiness
        await _pause_after_navigation(request_delay_ms, checkpoint=checkpoint)
        interactive_expansion = await expand_all_interactive_elements(page, checkpoint=checkpoint)
        if interactive_expansion:
            result.diagnostics["interactive_expansion"] = interactive_expansion
        await _flatten_shadow_dom(page)

        traversal_started_at = time.perf_counter()
        try:
            traversal_result = await _apply_traversal_mode(
                page,
                surface,
                traversal_mode,
                max_scrolls,
                max_pages=max_pages,
                request_delay_ms=request_delay_ms,
                checkpoint=checkpoint,
            )
        except (
            PlaywrightError,
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
        ) as exc:
            logger.warning(
                "[traversal] fallback to single-page, reason=exception:%s, url=%s",
                type(exc).__name__,
                url,
            )
            result.diagnostics["traversal_fallback_used"] = True
            result.diagnostics["traversal_fallback_reason"] = (
                f"exception:{type(exc).__name__}"
            )
            traversal_result = TraversalResult(
                html=None,
                summary={
                    "mode": traversal_mode,
                    "attempted": True,
                    "fallback_used": True,
                    "stop_reason": f"exception:{type(exc).__name__}",
                },
            )
        timings_ms["browser_traversal_ms"] = _elapsed_ms(traversal_started_at)
        combined_html = traversal_result.html
        traversal_summary = _normalize_traversal_summary(
            traversal_result.summary if isinstance(traversal_result.summary, dict) else {},
            traversal_mode=traversal_mode,
            combined_html=combined_html,
        )
        if traversal_summary:
            result.diagnostics["traversal_summary"] = traversal_summary
            if traversal_summary.get("attempted"):
                incr("traversal_attempt_total")
                if int(traversal_summary.get("pages_collected", 0) or 0) > 0:
                    incr("traversal_success_total")
                if traversal_summary.get("fallback_used"):
                    incr("traversal_fallback_total")

        # Emit traversal progress as a crawl event (visible in UI)
        if run_id is not None and traversal_summary.get("attempted"):
            try:
                from app.services.crawl_events import append_log_event
                _ts_mode = traversal_summary.get("mode_used") or traversal_mode or "?"
                _ts_pages = traversal_summary.get("pages_collected", 0)
                _ts_stop = traversal_summary.get("stop_reason") or "unknown"
                _ts_ms = timings_ms.get("browser_traversal_ms", 0)
                _ts_iters = traversal_summary.get("scroll_iterations", 0)
                _ts_parts = [f"mode={_ts_mode}"]
                if _ts_iters:
                    _ts_parts.append(f"scroll_iterations={_ts_iters}")
                _ts_parts.extend([
                    f"pages_collected={_ts_pages}",
                    f"stop_reason={_ts_stop}",
                    f"time={_ts_ms}ms",
                ])
                await append_log_event(
                    run_id=run_id,
                    level="info",
                    message=f"[TRAVERSAL] {', '.join(_ts_parts)}",
                )
            except Exception:
                pass  # Don't fail the acquisition if logging fails

        # Only apply fallback detection for paginated modes (auto, paginate)
        # scroll/load_more mutate the page in-place and don't collect separate pages
        _paginated_modes = {"paginate", "auto"}
        if (
            traversal_mode in _paginated_modes
            and traversal_summary.get("attempted")
            and int(traversal_summary.get("pages_collected", 0) or 0) <= 0
            and combined_html is None
        ):
            fallback_reason = str(
                traversal_summary.get("stop_reason") or "no_pages_collected"
            )
            logger.warning(
                "[traversal] fallback to single-page, reason=%s, url=%s",
                fallback_reason,
                url,
            )
            result.diagnostics["traversal_fallback_used"] = True
            result.diagnostics["traversal_fallback_reason"] = fallback_reason
        
        # Always record traversal context when traversal was attempted
        if traversal_mode:
            result.diagnostics["traversal_mode"] = traversal_mode
            result.diagnostics["max_pages"] = max_pages
        
        if combined_html is not None:
            result.html = combined_html
            result.network_payloads = intercepted
            # FIX: Fetch frame sources but DO NOT append traversal_html to avoid duplication
            # combined_html already contains all pages stitched together
            _, frame_sources, promoted_sources = await _collect_frame_sources(page)
            result.frame_sources = frame_sources
            result.promoted_sources = promoted_sources
            stitched_page_count = (
                combined_html.count("<!-- PAGE BREAK:") if combined_html else 0
            )
            result.diagnostics["page_count"] = stitched_page_count
            result.diagnostics["pages_collected"] = stitched_page_count
            result.diagnostics["frame_sources"] = len(frame_sources)
            result.diagnostics["promoted_sources"] = len(promoted_sources)
            timings_ms["browser_total_ms"] = _elapsed_ms(browser_started_at)
            result.diagnostics["timings_ms"] = timings_ms
            await _persist_context_cookies(context, page.url or url, original_domain)
            return result

        # Scroll/load-more: page was mutated in-place; read current state
        await _populate_result(result, page, intercepted, checkpoint=checkpoint)
        timings_ms["browser_total_ms"] = _elapsed_ms(browser_started_at)
        result.diagnostics["timings_ms"] = timings_ms
        if blocked_non_public_requests:
            result.diagnostics["blocked_non_public_requests"] = blocked_non_public_requests[
                :10
            ]
            result.diagnostics["blocked_non_public_request_count"] = len(
                blocked_non_public_requests
            )
        await _persist_context_cookies(context, page.url or url, original_domain)
        return result
    finally:
        await context.close()


def _browser_pool_key(launch_profile: dict[str, str | None], proxy: str | None) -> str:
    browser_type = str(launch_profile.get("browser_type") or "chromium").strip()
    channel = str(launch_profile.get("channel") or "").strip() or "default"
    proxy_key = str(proxy or "").strip() or "direct"
    return f"{browser_type}|{channel}|{proxy_key}"


async def _is_public_browser_request_target(request_url: str) -> tuple[bool, str]:
    parsed = urlparse(str(request_url or "").strip())
    scheme = str(parsed.scheme or "").lower()
    if scheme in {"http", "https"}:
        try:
            await validate_public_target(request_url)
        except ValueError as exc:
            return False, f"non_public_target:{exc}"
        return True, "public_target"
    if scheme in {"data", "blob"}:
        return True, f"non_http_scheme:allowed_{scheme}"
    disallowed = scheme or "missing_scheme"
    return False, f"non_http_scheme:disallowed_{disallowed}_scheme"


def _browser_is_connected(browser: object) -> bool:
    checker = getattr(browser, "is_connected", None)
    if not callable(checker):
        return True
    try:
        return bool(checker())
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        return False


async def _close_browser_safe(browser: object) -> None:
    try:
        await browser.close()
    except PlaywrightError:
        logger.debug("Failed to close pooled browser", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Unexpected pooled browser close failure", exc_info=True)


async def _evict_idle_or_dead_browsers() -> None:
    now = time.monotonic()
    to_close: list[object] = []
    async with _BROWSER_POOL_LOCK:
        stale_keys = [
            key
            for key, entry in _BROWSER_POOL.items()
            if (now - entry.last_used_monotonic) >= _BROWSER_POOL_IDLE_TTL_SECONDS
            or not _browser_is_connected(entry.browser)
        ]
        for key in stale_keys:
            entry = _BROWSER_POOL.pop(key, None)
            if entry is not None:
                to_close.append(entry.browser)
    for browser in to_close:
        await _close_browser_safe(browser)


async def _shutdown_browser_pool() -> None:
    to_close: list[object] = []
    async with _BROWSER_POOL_LOCK:
        for entry in _BROWSER_POOL.values():
            to_close.append(entry.browser)
        _BROWSER_POOL.clear()
    for browser in to_close:
        await _close_browser_safe(browser)


async def _browser_pool_healthcheck_loop() -> None:
    while True:
        await asyncio.sleep(_BROWSER_POOL_HEALTHCHECK_INTERVAL_SECONDS)
        await _evict_idle_or_dead_browsers()


async def _ensure_browser_pool_maintenance_task() -> None:
    global _BROWSER_POOL_CLEANUP_TASK
    async with _BROWSER_POOL_TASK_LOCK:
        loop = asyncio.get_running_loop()
        if _BROWSER_POOL_CLEANUP_TASK is None or _BROWSER_POOL_CLEANUP_TASK.done():
            _BROWSER_POOL_CLEANUP_TASK = loop.create_task(_browser_pool_healthcheck_loop())


async def _acquire_browser(
    *,
    browser_type,
    launch_kwargs: dict[str, object],
    browser_pool_key: str,
    force_new: bool = False,
):
    await _ensure_browser_pool_maintenance_task()
    await _evict_idle_or_dead_browsers()
    to_close: list[object] = []
    browser = None
    now = time.monotonic()
    async with _BROWSER_POOL_LOCK:
        if not force_new:
            pooled = _BROWSER_POOL.get(browser_pool_key)
            if pooled is not None and _browser_is_connected(pooled.browser):
                pooled.last_used_monotonic = now
                return pooled.browser, True
            _BROWSER_POOL.pop(browser_pool_key, None)
    browser = await browser_type.launch(**launch_kwargs)
    async with _BROWSER_POOL_LOCK:
        now = time.monotonic()
        pooled = _BROWSER_POOL.get(browser_pool_key)
        if not force_new and pooled is not None and _browser_is_connected(pooled.browser):
            pooled.last_used_monotonic = now
            to_close.append(browser)
            browser = pooled.browser
            reused = True
        else:
            _BROWSER_POOL[browser_pool_key] = _PooledBrowser(
                browser=browser,
                last_used_monotonic=now,
            )
            reused = False
            if len(_BROWSER_POOL) > _BROWSER_POOL_MAX_SIZE:
                lru_key = min(
                    _BROWSER_POOL,
                    key=lambda key: _BROWSER_POOL[key].last_used_monotonic,
                )
                if lru_key != browser_pool_key:
                    entry = _BROWSER_POOL.pop(lru_key, None)
                    if entry is not None:
                        to_close.append(entry.browser)
    for stale_browser in to_close:
        await _close_browser_safe(stale_browser)
    return browser, reused


async def _evict_browser(browser_pool_key: str, browser) -> None:
    async with _BROWSER_POOL_LOCK:
        pooled = _BROWSER_POOL.get(browser_pool_key)
        if pooled is not None and pooled.browser is browser:
            _BROWSER_POOL.pop(browser_pool_key, None)
    await _close_browser_safe(browser)


def _browser_launch_profiles(runtime_options: BrowserRuntimeOptions) -> list[dict[str, str | None]]:
    # Make system_chrome the primary profile to avoid ERR_HTTP2_PROTOCOL_ERROR
    # and TLS fingerprinting blocks from CDNs like Akamai (Myntra/Target/etc).
    # If real Chrome is missing or fails, it will fall back to bundled_chromium.
    profiles = [
        {"label": "system_chrome", "browser_type": "chromium", "channel": "chrome"},
        {"label": "bundled_chromium", "browser_type": "chromium", "channel": None},
    ]
    
    # Always return both to ensure maximum resilience
    return profiles


def _is_listing_surface(surface: str | None) -> bool:
    return str(surface or "").strip().lower().endswith("listing")


def _should_retry_launch_profile(result: BrowserResult, *, surface: str | None) -> bool:
    result_html = str(getattr(result, "html", "") or "")
    diagnostics = (
        result.diagnostics if isinstance(getattr(result, "diagnostics", None), dict) else {}
    )
    if detect_blocked_page(result_html).is_blocked:
        return True
    if _is_listing_surface(surface):
        readiness = diagnostics.get("listing_readiness")
        if isinstance(readiness, dict) and (
            not bool(readiness.get("ready")) or bool(readiness.get("shell_like"))
        ) and _html_looks_low_value(result_html):
            return True
    return False


async def _page_looks_low_value(page) -> bool:
    try:
        html = await _page_content_with_retry(page)
    except PlaywrightError:
        logger.debug("Failed to inspect page content for low-value result detection", exc_info=True)
        return False
    return _html_looks_low_value(html)


async def _collect_frame_sources(page) -> tuple[str, list[dict], list[dict]]:
    try:
        main_html = await _page_content_with_retry(page)
    except PlaywrightError:
        logger.debug("Failed to read main page content while collecting frame sources", exc_info=True)
        return "", [], []

    main_origin = _origin_url(str(getattr(page, "url", "") or ""))
    frame_sources: list[dict] = []
    promoted_sources: list[dict] = []
    same_origin_fragments: list[str] = []
    for frame in list(getattr(page, "frames", []) or [])[1:]:
        frame_url = str(getattr(frame, "url", "") or "").strip()
        if not frame_url:
            continue
        frame_origin = _origin_url(frame_url)
        same_origin = bool(main_origin and frame_origin and main_origin == frame_origin)
        frame_entry = {"url": frame_url, "same_origin": same_origin}
        try:
            frame_html = await frame.content()
        except PlaywrightError:
            frame_html = ""
        if frame_html:
            frame_entry["html_length"] = len(frame_html)
        frame_sources.append(frame_entry)
        if same_origin and frame_html:
            same_origin_fragments.append(
                "\n".join([
                    f"<!-- FRAME START: {frame_url} -->",
                    frame_html,
                    f"<!-- FRAME END: {frame_url} -->",
                ])
            )
        if not same_origin or not frame_html:
            promoted_sources.append({
                "kind": "iframe",
                "url": frame_url,
                "same_origin": same_origin,
                "html_available": bool(frame_html),
            })
    combined_html = main_html
    if same_origin_fragments:
        combined_html = "\n".join([main_html, *same_origin_fragments])
    return combined_html, frame_sources, promoted_sources


def _html_looks_low_value(html: str) -> bool:
    if not html:
        return True
    if detect_blocked_page(html).is_blocked:
        return True
    html_lower = html.lower()
    visible = re.sub(r"<[^>]+>", " ", html_lower)
    visible = " ".join(visible.split())
    low_value_phrases = (
        "sorry, this page is not available",
        "this page is not available",
        "page not found",
        "not available",
        "just a moment",
    )
    return len(html_lower) < 1200 and any(phrase in visible for phrase in low_value_phrases)


def _build_launch_kwargs(proxy: str | None, target, *, browser_channel: str | None = None) -> dict:
    launch_kwargs: dict = {"headless": settings.playwright_headless}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    if browser_channel:
        launch_kwargs["channel"] = browser_channel
    # Disabled DNS pinning as it causes HTTP2 errors with some sites (e.g., Myntra)
    # if target.dns_resolved and target.resolved_ips and not browser_channel:
    #     pinned_ip = target.resolved_ips[0]
    #     launch_kwargs["args"] = [
    #         f"--host-resolver-rules=MAP {target.hostname} {_chromium_host_rule_ip(pinned_ip)}",
    #     ]
    
    # NOTE: --disable-http2 was removed as it triggers anti-bot detection
    # HTTP/2 multiplexing is a key browser fingerprint that anti-bot systems check
    
    return launch_kwargs


async def _maybe_warm_origin(
    page,
    url: str,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> bool:
    origin_url = _origin_url(url)
    if not origin_url or origin_url == url:
        return False
    await _warm_origin(page, origin_url, checkpoint=checkpoint)
    return True


async def _cooperative_sleep_ms(
    delay_ms: int,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    remaining_ms = max(0, int(delay_ms or 0))
    poll_ms = max(INTERRUPTIBLE_WAIT_POLL_MS, 50)
    while remaining_ms > 0:
        if checkpoint is not None:
            await checkpoint()
        current_ms = min(remaining_ms, poll_ms)
        await asyncio.sleep(current_ms / 1000.0)
        remaining_ms -= current_ms
    if checkpoint is not None:
        await checkpoint()


async def _cooperative_page_wait(
    page,
    delay_ms: int,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    remaining_ms = max(0, int(delay_ms or 0))
    poll_ms = max(INTERRUPTIBLE_WAIT_POLL_MS, 50)
    while remaining_ms > 0:
        if checkpoint is not None:
            await checkpoint()
        current_ms = min(remaining_ms, poll_ms)
        await page.wait_for_timeout(current_ms)
        remaining_ms -= current_ms
    if checkpoint is not None:
        await checkpoint()


async def _pause_after_navigation(
    request_delay_ms: int,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    delay_ms = request_delay_ms if request_delay_ms > 0 else 250
    await _cooperative_sleep_ms(delay_ms, checkpoint=checkpoint)


async def _apply_traversal_mode(
    page,
    surface: str | None,
    traversal_mode: str | None,
    max_scrolls: int,
    *,
    max_pages: int,
    request_delay_ms: int,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> TraversalResult:
    traversal_config = _traversal_config()

    return await _apply_traversal_mode_shared(
        page,
        surface,
        traversal_mode,
        max_scrolls,
        config=traversal_config,
        max_pages=max_pages,
        request_delay_ms=request_delay_ms,
        page_content_with_retry=_page_content_with_retry,
        wait_for_surface_readiness=_wait_for_surface_readiness,
        wait_for_listing_readiness=_wait_for_listing_readiness,
        peek_next_page_signal=_peek_next_page_signal,
        click_and_observe_next_page=_click_and_observe_next_page,
        has_load_more_control=lambda p, _cfg: _has_load_more_control(p),
        dismiss_cookie_consent=_dismiss_cookie_consent,
        pause_after_navigation=_pause_after_navigation,
        expand_all_interactive_elements=expand_all_interactive_elements,
        flatten_shadow_dom=_flatten_shadow_dom,
        cooperative_sleep_ms=_cooperative_sleep_ms,
        snapshot_listing_page_metrics=_snapshot_listing_page_metrics,
        checkpoint=checkpoint,
    )


@dataclass
class _PaginatedHtmlResult:
    html: str
    summary: dict[str, object]


async def _collect_paginated_html(
    page,
    *,
    surface: str | None = None,
    max_pages: int,
    request_delay_ms: int,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> _PaginatedHtmlResult:
    traversal_config = _traversal_config()
    traversal_result = await _collect_paginated_html_shared(
        page,
        config=traversal_config,
        surface=surface,
        max_pages=max_pages,
        request_delay_ms=request_delay_ms,
        page_content_with_retry=_page_content_with_retry,
        wait_for_surface_readiness=_wait_for_surface_readiness,
        wait_for_listing_readiness=_wait_for_listing_readiness,
        click_and_observe_next_page=_click_and_observe_next_page,
        dismiss_cookie_consent=_dismiss_cookie_consent,
        pause_after_navigation=_pause_after_navigation,
        expand_all_interactive_elements=expand_all_interactive_elements,
        flatten_shadow_dom=_flatten_shadow_dom,
        checkpoint=checkpoint,
    )
    html = traversal_result.html or ""
    return _PaginatedHtmlResult(
        html=html,
        summary=dict(traversal_result.summary or {}),
    )


async def _peek_next_page_signal(page) -> dict[str, object] | None:
    traversal_config = _traversal_config()
    return await _peek_next_page_signal_shared(page, config=traversal_config)


async def _wait_for_listing_readiness(
    page,
    surface: str | None,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, object] | None:
    from app.services.config.platform_readiness import resolve_listing_readiness_override
    
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_surface.endswith("listing"):
        return None
    selectors = (
        CARD_SELECTORS_JOBS
        if normalized_surface == "job_listing"
        else CARD_SELECTORS_COMMERCE
    )
    page_url = str(getattr(page, "url", "") or "").lower()
    
    # Apply platform overrides from config pattern matching.
    override = resolve_listing_readiness_override(page_url)
    if override is not None:
        selectors = [*selectors, *list(override.get("selectors") or [])]
    
    if not selectors:
        return None
    elapsed = 0
    poll_ms = max(100, LISTING_READINESS_POLL_MS)
    max_wait_ms = max(0, LISTING_READINESS_MAX_WAIT_MS)
    
    # Apply max_wait_ms override from configuration
    if override is not None:
        max_wait_ms = max(max_wait_ms, int(override.get("max_wait_ms", 0) or 0))
    
    best_selector = ""
    best_count = 0
    stable_windows = 0
    last_snapshot: dict[str, object] | None = None
    while elapsed <= max_wait_ms:
        page_metrics = await _snapshot_listing_page_metrics(page)
        current_best_selector = ""
        current_best_count = 0
        for selector in selectors:
            try:
                count = await page.locator(selector).count()
            except PlaywrightError:
                logger.debug("Listing readiness count failed for selector %s", selector, exc_info=True)
                continue
            if count > current_best_count:
                current_best_count = count
                current_best_selector = selector
            if count >= LISTING_MIN_ITEMS:
                return {
                    "ready": True,
                    "reason": "selector_match",
                    "selector": selector,
                    "count": count,
                    "link_count": int((page_metrics or {}).get("link_count", 0) or 0),
                    "waited_ms": elapsed,
                }
        if current_best_count > best_count:
            best_count = current_best_count
            best_selector = current_best_selector
        shell_like = _listing_metrics_look_shell_like(page_metrics)
        if _listing_metrics_stable(last_snapshot, page_metrics):
            stable_windows += 1
        else:
            stable_windows = 0
        last_snapshot = page_metrics
        if stable_windows >= 1 and page_metrics and not shell_like:
            return {
                "ready": True,
                "reason": "behavioral_stability",
                "selector": best_selector or None,
                "count": best_count,
                "link_count": int(page_metrics.get("link_count", 0) or 0),
                "waited_ms": elapsed,
                "shell_like": False,
            }
        if (
            page_metrics
            and not shell_like
            and int(page_metrics.get("link_count", 0) or 0) >= LISTING_MIN_ITEMS
            and elapsed >= poll_ms
        ):
            return {
                "ready": True,
                "reason": "behavioral_links",
                "selector": best_selector or None,
                "count": best_count,
                "link_count": int(page_metrics.get("link_count", 0) or 0),
                "waited_ms": elapsed,
                "shell_like": False,
            }
        if elapsed >= max_wait_ms:
            break
        await _cooperative_page_wait(page, poll_ms, checkpoint=checkpoint)
        elapsed += poll_ms
    return {
        "ready": False,
        "reason": "timeout",
        "selector": best_selector or None,
        "count": best_count,
        "link_count": int((last_snapshot or {}).get("link_count", 0) or 0),
        "shell_like": _listing_metrics_look_shell_like(last_snapshot),
        "waited_ms": elapsed,
    }


async def _snapshot_listing_page_metrics(page) -> dict[str, object]:
    try:
        return await page.evaluate(
            """
            () => {
                const body = document.body;
                const main = document.querySelector("main");
                const root = main || body;
                const linkCount = Array.from((root || document).querySelectorAll("a[href]")).length;
                const cardishCount = Array.from((root || document).querySelectorAll("[data-testid*='job' i], [class*='job'], [class*='career'], [class*='opening'], [class*='result'], article, li")).length;
                const text = ((root && root.innerText) || document.body?.innerText || "").trim();
                const loadingText = text.toLowerCase();
                const loading = /loading|searching|please wait|just a moment/.test(loadingText);
                const htmlLength = (root && root.innerHTML ? root.innerHTML.length : 0);
                const identities = Array.from((root || document).querySelectorAll("a[href], [data-job-id], [data-id], [data-testid], article, li"))
                    .map((node) => {
                        if (!(node instanceof Element)) return "";
                        const href = node.getAttribute("href") || node.querySelector("a[href]")?.getAttribute("href") || "";
                        const dataId = node.getAttribute("data-job-id")
                            || node.getAttribute("data-id")
                            || node.getAttribute("data-testid")
                            || "";
                        const heading = node.querySelector("h1, h2, h3, h4, [role='heading']")?.textContent || "";
                        const textSample = (heading || node.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 120);
                        const token = (href || dataId || textSample).trim().toLowerCase();
                        return token;
                    })
                    .filter((token, index, arr) => token && arr.indexOf(token) === index)
                    .slice(0, 200);
                const domSignature = JSON.stringify({
                    linkCount,
                    cardishCount,
                    htmlLength,
                    identities: identities.slice(0, 20),
                    textSample: text.slice(0, 240),
                });
                return {
                    link_count: linkCount,
                    cardish_count: cardishCount,
                    text_length: text.length,
                    html_length: htmlLength,
                    identity_count: identities.length,
                    identities: identities,
                    dom_signature: domSignature,
                    loading: loading,
                };
            }
            """
        )
    except PlaywrightError:
        logger.debug("Failed to snapshot listing page metrics", exc_info=True)
        return {}


def _listing_metrics_stable(previous: dict[str, object] | None, current: dict[str, object] | None) -> bool:
    if not previous or not current:
        return False
    keys = ("link_count", "cardish_count", "text_length")
    return all(int(previous.get(key, -1) or 0) == int(current.get(key, -2) or 0) for key in keys)


def _listing_metrics_look_shell_like(metrics: dict[str, object] | None) -> bool:
    if not metrics:
        return True
    if bool(metrics.get("loading")):
        return True
    link_count = int(metrics.get("link_count", 0) or 0)
    text_length = int(metrics.get("text_length", 0) or 0)
    return link_count < LISTING_MIN_ITEMS and text_length < 300


def _detail_readiness_selectors(surface: str | None) -> list[str]:
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface == "job_detail":
        selectors = [DOM_PATTERNS.get("title", ""), DOM_PATTERNS.get("company", ""), DOM_PATTERNS.get("salary", "")]
    elif normalized_surface == "ecommerce_detail":
        selectors = [DOM_PATTERNS.get("title", ""), DOM_PATTERNS.get("price", ""), DOM_PATTERNS.get("sku", "")]
    else:
        selectors = [DOM_PATTERNS.get("title", ""), DOM_PATTERNS.get("price", "")]
    return [selector for selector in selectors if str(selector).strip()]


async def _wait_for_surface_readiness(
    page,
    *,
    surface: str | None,
    max_wait_ms: int | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, object] | None:
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_surface:
        return None
    if normalized_surface.endswith("listing"):
        if max_wait_ms == 0:
            selectors = CARD_SELECTORS_JOBS if normalized_surface == "job_listing" else CARD_SELECTORS_COMMERCE
            for selector in selectors:
                try:
                    count = await page.locator(selector).count()
                except PlaywrightError:
                    continue
                if count >= LISTING_MIN_ITEMS:
                    return {"ready": True, "selector": selector, "count": count, "waited_ms": 0}
            return {"ready": False, "selector": None, "count": 0, "waited_ms": 0}
        return await _wait_for_listing_readiness(page, surface, checkpoint=checkpoint)
    selectors = _detail_readiness_selectors(surface)
    if not selectors:
        return None
    elapsed = 0
    poll_ms = max(100, SURFACE_READINESS_POLL_MS)
    max_wait_ms = max(0, SURFACE_READINESS_MAX_WAIT_MS if max_wait_ms is None else max_wait_ms)
    while elapsed <= max_wait_ms:
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count():
                    return {
                        "ready": True,
                        "selector": selector,
                        "waited_ms": elapsed,
                    }
            except PlaywrightError:
                logger.debug("Surface readiness check failed for selector %s", selector, exc_info=True)
                continue
        if elapsed >= max_wait_ms:
            break
        await _cooperative_page_wait(page, poll_ms, checkpoint=checkpoint)
        elapsed += poll_ms
    return {
        "ready": False,
        "selector": None,
        "waited_ms": elapsed,
    }


async def _find_next_page_url_anchor_only(page) -> str:
    traversal_config = _traversal_config()
    return await _find_next_page_url_anchor_only_shared(
        page,
        config=traversal_config,
    )


async def _find_next_page_url(page) -> str:
    return await _find_next_page_url_anchor_only(page)


async def _snapshot_pagination_state(page) -> dict[str, object]:
    return await _snapshot_pagination_state_shared(page)


def _pagination_state_changed(previous: dict[str, object] | None, current: dict[str, object] | None) -> bool:
    return _pagination_state_changed_shared(previous, current)


async def _click_and_observe_next_page(
    page,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> str:
    traversal_config = _traversal_config()
    return await _click_and_observe_next_page_shared(
        page,
        config=traversal_config,
        checkpoint=checkpoint,
    )


async def expand_all_interactive_elements(
    page,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, object]:
    try:
        # FIX: Added maxClicks limit (20) to prevent browser crashing on heavy DOMs
        expanded_count = await page.evaluate(
            """
            () => {
                let count = 0;
                const maxClicks = 20;
                const seen = new Set();
                const targets = [
                    ...document.querySelectorAll('details > summary'),
                    ...document.querySelectorAll('[aria-expanded="false"]:not([role="menuitem"])'),
                    ...document.querySelectorAll('button[data-toggle]:not([data-toggle="modal"]):not([role="menuitem"])'),
                ].filter((el) => {
                    if (!(el instanceof Element)) return false;
                    if (el.closest('nav, [role="navigation"], [role="menubar"]')) return false;
                    if (el.closest('[aria-modal="true"], [role="dialog"], .modal')) return false;
                    return true;
                });
                for (const el of targets) {
                    if (count >= maxClicks) break;
                    if (!(el instanceof Element) || seen.has(el)) continue;
                    seen.add(el);
                    try {
                        el.click();
                        count++;
                    } catch (error) {}
                }
                return count;
            }
            """,
        )
        if expanded_count:
            logger.debug("Expanded %d interactive elements", expanded_count)
            await _cooperative_sleep_ms(ACCORDION_EXPAND_WAIT_MS, checkpoint=checkpoint)
        return {
            "actions": ["expand_all_interactive_elements"],
            "expanded_count": int(expanded_count or 0),
        }
    except PlaywrightError:
        logger.debug("Interactive element expansion failed (non-critical)", exc_info=True)
    return {}


async def _flatten_shadow_dom(page) -> None:
    try:
        flattened_count = await page.evaluate(
            """
            (maxHosts) => {
                const hosts = [];
                const collectHosts = (root) => {
                    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
                    let current = walker.currentNode;
                    while (current) {
                        if (current.shadowRoot) {
                            hosts.push(current);
                            if (hosts.length >= maxHosts) {
                                return;
                            }
                            collectHosts(current.shadowRoot);
                            if (hosts.length >= maxHosts) {
                                return;
                            }
                        }
                        current = walker.nextNode();
                    }
                };
                const escapeHtml = (text) =>
                    String(text || "")
                        .replace(/&/g, "&amp;")
                        .replace(/</g, "&lt;")
                        .replace(/>/g, "&gt;");
                const escapeAttr = (text) => escapeHtml(text).replace(/"/g, "&quot;");
                const serializeNode = (node) => {
                    if (node.nodeType === Node.TEXT_NODE) {
                        return escapeHtml(node.textContent || "");
                    }
                    if (node.nodeType !== Node.ELEMENT_NODE) {
                        return "";
                    }
                    const element = node;
                    const tagName = (element.tagName || "div").toLowerCase();
                    const attrs = Array.from(element.attributes || [])
                        .map((attr) => ` ${attr.name}="${escapeAttr(attr.value)}"`)
                        .join("");
                    const children = Array.from(element.childNodes || []).map(serializeNode);
                    if (element.shadowRoot) {
                        children.push(
                            `<div data-shadow-dom-inline-root="${tagName}">` +
                                Array.from(element.shadowRoot.childNodes || []).map(serializeNode).join("") +
                            `</div>`
                        );
                    }
                    return `<${tagName}${attrs}>${children.join("")}</${tagName}>`;
                };

                collectHosts(document);
                let flattened = 0;
                for (const host of hosts.slice(0, maxHosts)) {
                    if (!host.shadowRoot) {
                        continue;
                    }
                    if (host.querySelector(":scope > [data-shadow-dom-clone='true']")) {
                        continue;
                    }
                    const container = document.createElement("div");
                    container.setAttribute("data-shadow-dom-clone", "true");
                    container.hidden = true;
                    container.innerHTML = Array.from(host.shadowRoot.childNodes || []).map(serializeNode).join("");
                    host.appendChild(container);
                    flattened += 1;
                }
                return flattened;
            }
            """,
            SHADOW_DOM_FLATTEN_MAX_HOSTS,
        )
        if flattened_count:
            logger.debug("Flattened %d shadow root hosts", flattened_count)
    except PlaywrightError:
        logger.debug("Shadow DOM flattening failed (non-critical)", exc_info=True)


async def _populate_result(
    result: BrowserResult,
    page,
    intercepted: list[dict],
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    result.html, result.frame_sources, result.promoted_sources = await _collect_frame_sources(page)
    result.network_payloads = intercepted
    result.diagnostics["final_url"] = str(page.url or "").strip() or None
    result.diagnostics["frame_sources"] = len(result.frame_sources)
    result.diagnostics["promoted_sources"] = len(result.promoted_sources)
    if result.html:
        result.diagnostics["html_length"] = len(result.html)
        result.diagnostics["blocked"] = detect_blocked_page(result.html).is_blocked


async def _page_content_with_retry(
    page,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
    attempts: int = 4,
    wait_ms: int = 400,
) -> str:
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return await page.content()
        except PlaywrightError as exc:
            last_error = exc
            retryable_playwright_error = isinstance(exc, PlaywrightError) and bool(
                _RETRYABLE_PAGE_CONTENT_ERROR_RE.search(str(exc))
            )
            if not retryable_playwright_error:
                raise
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=2000)
            except PlaywrightError:
                logger.debug("Timed out waiting for domcontentloaded before retrying page.content()", exc_info=True)
            if attempt + 1 >= max(1, attempts):
                break
            await _cooperative_page_wait(page, wait_ms, checkpoint=checkpoint)
    assert last_error is not None
    raise last_error


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((time.perf_counter() - started_at) * 1000)))


def _normalize_traversal_summary(
    summary: dict[str, object],
    *,
    traversal_mode: str | None,
    combined_html: str | None,
) -> dict[str, object]:
    normalized = dict(summary or {})
    mode_used = str(normalized.get("mode_used") or normalized.get("mode") or traversal_mode or "").strip() or None
    pages_collected = int(
        normalized.get("pages_collected", 0) or (
            str(combined_html or "").count("<!-- PAGE BREAK:") if combined_html else 0
        )
    )
    stop_reason = str(normalized.get("stop_reason") or "").strip() or None
    fallback_used = bool(normalized.get("fallback_used"))
    scroll_iterations = int(normalized.get("scroll_iterations") or normalized.get("attempt_count") or 0)
    normalized["mode_used"] = mode_used
    normalized["pages_collected"] = pages_collected
    normalized["scroll_iterations"] = scroll_iterations
    normalized["stop_reason"] = stop_reason
    normalized["fallback_used"] = fallback_used
    return {key: value for key, value in normalized.items() if value is not None}


async def _persist_context_cookies(context, final_url: str, original_domain: str) -> None:
    final_domain = _domain(final_url)
    await _save_cookies(context, final_domain)
    if final_domain != original_domain:
        await _save_cookies(context, original_domain)


def _navigation_strategies(*, browser_channel: str | None = None) -> list[tuple[str, int]]:
    if browser_channel:
        return [
            ("domcontentloaded", BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS),
            ("commit", BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS),
        ]
    return [
        ("load", BROWSER_NAVIGATION_LOAD_TIMEOUT_MS),
        ("domcontentloaded", BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS),
    ]


def _shortened_navigation_strategies() -> list[tuple[str, int]]:
    return [
        ("domcontentloaded", 12000),
        ("commit", 8000),
    ]


def _classify_profile_failure_reason(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, PlaywrightTimeoutError) or "timeout" in text:
        return "timeout"
    if "browser_navigation_error:" in text:
        return "navigation_error"
    return "generic_error"


def _should_shorten_navigation_after_profile_failure(reason: str | None) -> bool:
    return reason in {"timeout", "navigation_error"}


async def _goto_with_fallback(
    page,
    url: str,
    *,
    surface: str | None = None,
    strategies: list[tuple[str, int]] | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Navigate with progressively less strict wait conditions.

    Modern storefronts often keep background requests, beacons, or websocket
    connections active indefinitely. We therefore use `domcontentloaded` as the
    hard navigation boundary, then do a short best-effort `load` wait instead
    of waiting for network silence.

    Also handles non-timeout errors (e.g. ERR_HTTP2_PROTOCOL_ERROR) by
    retrying before giving up.
    """
    strategies = strategies or _navigation_strategies()
    last_error = None
    browser_error_retries = max(0, BROWSER_ERROR_RETRY_ATTEMPTS)

    for attempt in range(browser_error_retries + 1):
        try:
            if checkpoint is not None:
                await checkpoint()
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS,
            )
            browser_error_reason = await _retryable_browser_error_reason(page)
            if browser_error_reason is not None:
                if attempt >= browser_error_retries:
                    raise RuntimeError(f"browser_navigation_error:{browser_error_reason}")
                logger.debug(
                    "goto(%s) landed on transient browser error page (%s); retrying",
                    url,
                    browser_error_reason,
                )
                await _cooperative_page_wait(
                    page,
                    BROWSER_ERROR_RETRY_DELAY_MS,
                    checkpoint=checkpoint,
                )
                continue

            # Best-effort hydration window after DOM readiness.
            for wait_until, timeout in strategies:
                if wait_until == "load":
                    try:
                        await page.wait_for_load_state(
                            wait_until,
                            timeout=min(timeout, BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS),
                        )
                    except PlaywrightError:
                        pass
            return
        except PlaywrightError as exc:
            last_error = exc
            logger.debug("goto(%s, attempt=%d) failed: %s", url, attempt, exc)
            if attempt >= browser_error_retries:
                raise last_error


async def _retryable_browser_error_reason(page) -> str | None:
    page_url = str(getattr(page, "url", "") or "").strip().lower()
    if page_url.startswith("chrome-error://"):
        return "chrome_error_url"
    try:
        html = await page.content()
    except PlaywrightError:
        logger.debug("Failed to inspect page content for browser error markers", exc_info=True)
        return None
    text = (html or "")[:20_000].lower().replace("’", "'")
    markers = {
        "err_name_not_resolved": "dns_name_not_resolved",
        "dns_probe_finished_nxdomain": "dns_probe_finished_nxdomain",
        "dns_probe_finished_no_internet": "dns_probe_finished_no_internet",
        "this site can't be reached": "site_cannot_be_reached",
        "server ip address could not be found": "server_ip_not_found",
        "err_network_changed": "network_changed",
        "err_connection_reset": "connection_reset",
    }
    for marker, reason in markers.items():
        if marker in text:
            return reason
    return None


async def _warm_origin(
    page,
    origin_url: str,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    try:
        await page.goto(
            origin_url,
            wait_until="domcontentloaded",
            timeout=BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS,
        )
        await _cooperative_page_wait(page, ORIGIN_WARM_PAUSE_MS, checkpoint=checkpoint)
        try:
            await page.mouse.move(240, 180)
            await page.evaluate("window.scrollBy(0, 120)")
        except PlaywrightError:
            logger.debug("Origin warm mouse/scroll interaction failed", exc_info=True)
    except PlaywrightError:
        logger.debug("Origin warm navigation failed for %s", origin_url, exc_info=True)
        return


async def _scroll_to_bottom(
    page,
    max_scrolls: int,
    *,
    request_delay_ms: int,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, object]:
    traversal_config = _traversal_config()
    return await _scroll_to_bottom_shared(
        page,
        max_scrolls,
        config=traversal_config,
        request_delay_ms=request_delay_ms,
        cooperative_sleep_ms=_cooperative_sleep_ms,
        snapshot_listing_page_metrics=_snapshot_listing_page_metrics,
        checkpoint=checkpoint,
    )


async def _click_load_more(
    page,
    max_clicks: int,
    *,
    request_delay_ms: int,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, object]:
    traversal_config = _traversal_config()
    return await _click_load_more_shared(
        page,
        max_clicks,
        config=traversal_config,
        request_delay_ms=request_delay_ms,
        cooperative_sleep_ms=_cooperative_sleep_ms,
        snapshot_listing_page_metrics=_snapshot_listing_page_metrics,
        checkpoint=checkpoint,
    )


async def _has_load_more_control(page) -> bool:
    traversal_config = _traversal_config()
    return await _has_load_more_control_shared(
        page,
        config=traversal_config,
    )


async def _dismiss_cookie_consent(
    page,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    try:
        await _cooperative_page_wait(page, COOKIE_CONSENT_PREWAIT_MS, checkpoint=checkpoint)
    except PlaywrightError:
        logger.debug("Cookie consent pre-wait failed", exc_info=True)
        return
    for selector in COOKIE_CONSENT_SELECTORS:
        try:
            button = page.locator(selector).first
            if await button.is_visible():
                await button.click()
                await _cooperative_page_wait(
                    page,
                    COOKIE_CONSENT_POSTCLICK_WAIT_MS,
                    checkpoint=checkpoint,
                )
                return
        except PlaywrightError:
            logger.debug("Cookie consent click failed for selector %s", selector, exc_info=True)
            continue
    try:
        await page.keyboard.press("Escape")
    except PlaywrightError:
        logger.debug("Escape key press failed during cookie consent dismissal", exc_info=True)


async def _wait_for_challenge_resolution(
    page,
    max_wait_ms: int = CHALLENGE_WAIT_MAX_SECONDS * 1000,
    poll_interval_ms: int = CHALLENGE_POLL_INTERVAL_MS,
    surface: str | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> tuple[bool, str, list[str]]:
    try:
        html = await page.content()
    except PlaywrightError:
        logger.debug("Failed to read page content for challenge detection", exc_info=True)
        return True, "none", []

    assessment = _assess_challenge_signals(html)
    if assessment.state == "blocked_signal":
        return False, "blocked", assessment.reasons
    if not assessment.should_wait:
        return True, assessment.state, assessment.reasons

    elapsed = 0
    while elapsed < max_wait_ms:
        await _cooperative_page_wait(page, poll_interval_ms, checkpoint=checkpoint)
        elapsed += poll_interval_ms
        try:
            html = await page.content()
        except PlaywrightError:
            logger.debug("Failed to read page content during challenge polling", exc_info=True)
            break
        assessment = _assess_challenge_signals(html)
        if assessment.state == "blocked_signal":
            return False, "blocked", assessment.reasons
        if not assessment.should_wait:
            readiness = await _wait_for_surface_readiness(
                page,
                surface=surface,
                max_wait_ms=0,
                checkpoint=checkpoint,
            )
            if readiness and not bool(readiness.get("ready")):
                continue
            state = "waiting_resolved" if elapsed > 0 else "none"
            return True, state, assessment.reasons

    return False, "blocked", assessment.reasons


def _assess_challenge_signals(html: str) -> ChallengeAssessment:
    text = (html or "")[:40_000].lower()
    strong_markers = BLOCK_BROWSER_CHALLENGE_STRONG_MARKERS or {
        "captcha": "captcha",
        "verify you are human": "verification_text",
        "checking your browser": "browser_check",
        "cf-browser-verification": "cloudflare_verification",
        "challenge-platform": "challenge_platform",
        "just a moment": "interstitial_text",
        "access denied": "access_denied",
        "powered and protected by akamai": "akamai_banner",
    }
    weak_markers = BLOCK_BROWSER_CHALLENGE_WEAK_MARKERS or {
        "one more step": "generic_interstitial",
        "oops!! something went wrong": "generic_error_text",
        "error page": "error_page_text",
    }
    strong_hits = [label for marker, label in strong_markers.items() if marker in text]
    weak_hits = [label for marker, label in weak_markers.items() if marker in text]
    blocked_verdict = detect_blocked_page(html)
    challenge_like_hits = {
        "captcha",
        "verification_text",
        "browser_check",
        "cloudflare_verification",
        "challenge_platform",
        "interstitial_text",
        "datadome_marker",
    }
    short_html = len(html or "") < max(BLOCK_MIN_HTML_LENGTH, 2500)
    if blocked_verdict.is_blocked and challenge_like_hits & set(strong_hits):
        reasons = strong_hits or weak_hits or ["blocked_detector"]
        if short_html:
            reasons.append("short_html")
        return ChallengeAssessment(state="waiting_unresolved", should_wait=True, reasons=reasons)
    has_provider_signature = bool(blocked_verdict.provider)
    if blocked_verdict.is_blocked and short_html and has_provider_signature:
        reasons = strong_hits or weak_hits or [str(blocked_verdict.provider), "blocked_detector"]
        return ChallengeAssessment(state="waiting_unresolved", should_wait=True, reasons=reasons)
    if blocked_verdict.is_blocked:
        return ChallengeAssessment(state="blocked_signal", should_wait=False, reasons=strong_hits or weak_hits or ["blocked_detector"])
    if short_html and strong_hits:
        return ChallengeAssessment(state="blocked_signal", should_wait=False, reasons=strong_hits + ["short_html"])
    if len(strong_hits) >= 2:
        reasons = strong_hits[:]
        if short_html:
            reasons.append("short_html")
        return ChallengeAssessment(state="waiting_unresolved", should_wait=True, reasons=reasons)
    if strong_hits or weak_hits:
        reasons = (strong_hits + weak_hits)[:]
        if short_html:
            reasons.append("short_html")
        return ChallengeAssessment(state="weak_signal_ignored", should_wait=False, reasons=reasons)
    return ChallengeAssessment(state="none", should_wait=False, reasons=[])


def _context_kwargs(
    prefer_stealth: bool,
    *,
    browser_channel: str | None = None,
    runtime_options: BrowserRuntimeOptions | None = None,
) -> dict:
    options = runtime_options or BrowserRuntimeOptions()
    if browser_channel:
        kwargs = {
            "java_script_enabled": True,
            "ignore_https_errors": bool(options.ignore_https_errors),
            "viewport": {"width": 1365, "height": 900},
            "device_scale_factor": 1,
            "is_mobile": False,
            "has_touch": False,
            "color_scheme": "light",
            "user_agent": _STEALTH_USER_AGENT,
            "service_workers": "block",  # FIX: Prevent Service Worker SSRF bypasses
        }
        return kwargs
    kwargs = {
        "java_script_enabled": True,
        "ignore_https_errors": bool(options.ignore_https_errors),
        "locale": "en-US",
        "timezone_id": "UTC",
        "viewport": {"width": 1365, "height": 900},
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
        "color_scheme": "light",
        "service_workers": "block",  # FIX: Prevent Service Worker SSRF bypasses
    }
    if options.bypass_csp:
        kwargs["bypass_csp"] = True
    if prefer_stealth:
        kwargs["user_agent"] = _STEALTH_USER_AGENT
    return kwargs


def _origin_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))


async def _load_cookies(context, domain: str) -> bool:
    cookies = load_cookies_for_context(domain)
    if not cookies:
        return False
    try:
        await context.add_cookies(cookies)
    except PlaywrightError:
        logger.debug("Failed to add cookies to context for domain %s", domain, exc_info=True)
        return False
    return True


async def _save_cookies(context, domain: str) -> None:
    try:
        cookies = await context.cookies()
    except PlaywrightError:
        logger.debug("Failed to read cookies from context for domain %s", domain, exc_info=True)
        return
    save_cookies_payload(cookies, domain=domain)


def _cookie_store_path(domain: str) -> Path | None:
    return cookie_store_path(domain)


def _filter_persistable_cookies(payload: object, *, domain: str) -> list[dict]:
    return filter_persistable_cookies(payload, domain=domain)


def _is_persistable_cookie(cookie: dict, *, domain: str) -> bool:
    return cookie in filter_persistable_cookies([cookie], domain=domain)


def _cookie_name_allowed(name: str, policy: dict[str, object]) -> bool:
    normalized = str(name or "").strip().lower()
    allowed_names = {
        str(value).strip().lower()
        for value in policy.get("allowed_cookie_names", [])
        if str(value).strip()
    }
    harvest_names = {
        str(value).strip().lower()
        for value in policy.get("harvest_cookie_names", [])
        if str(value).strip()
    }
    if normalized in allowed_names or normalized in harvest_names:
        return True
    for prefix in policy.get("harvest_name_prefixes", []):
        if normalized.startswith(str(prefix).strip().lower()):
            return True
    for fragment in policy.get("harvest_name_contains", []):
        if str(fragment).strip().lower() in normalized:
            return True
    return False


def _cookie_name_blocked(name: str, policy: dict[str, object]) -> bool:
    normalized = str(name or "").strip().lower()
    if not normalized:
        return True
    blocked_prefixes = [str(value).strip().lower() for value in policy.get("blocked_name_prefixes", []) if str(value).strip()]
    for prefix in blocked_prefixes:
        if normalized.startswith(prefix):
            return True
    blocked_substrings = [str(value).strip().lower() for value in policy.get("blocked_name_contains", []) if str(value).strip()]
    for fragment in blocked_substrings:
        if fragment in normalized:
            return True
    return False


def _cookie_policy_for_domain(domain: str) -> dict[str, object]:
    return cookie_policy_for_domain(domain)


def _cookie_expiry(cookie: dict) -> float | None:
    raw_expires = cookie.get("expires")
    if raw_expires in (None, "", -1):
        return None
    try:
        return float(raw_expires)
    except (TypeError, ValueError):
        return None


def _cookie_domain_matches(cookie_domain: str, requested_domain: str) -> bool:
    cookie_host = str(cookie_domain or "").strip().lower().lstrip(".")
    requested_host = str(requested_domain or "").strip().lower().lstrip(".")
    if not cookie_host or not requested_host:
        return False
    return (
        cookie_host == requested_host
        or requested_host.endswith(f".{cookie_host}")
    )


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _chromium_host_rule_ip(ip_text: str) -> str:
    try:
        value = ipaddress.ip_address(ip_text)
    except ValueError:
        return ip_text
    return f"[{value.compressed}]" if value.version == 6 else value.compressed


async def shutdown_browser_pool() -> None:
    await _shutdown_browser_pool()
