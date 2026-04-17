# Playwright browser acquisition client with optional proxy and network interception.
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

import psutil  # Hard dependency — zombie browser cleanup requires psutil

from app.core.config import settings
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_challenge import (
    _html_looks_low_value,
    _page_looks_low_value,
    _wait_for_challenge_resolution,
)
from app.services.acquisition.browser_stealth import (
    apply_browser_stealth,
    probe_browser_automation_surfaces,
)
from app.services.acquisition.browser_navigation import (
    _classify_profile_failure_reason,
    _goto_with_fallback,
    _navigation_strategies,
    _shortened_navigation_strategies,
    _should_shorten_navigation_after_profile_failure,
    _warm_origin,
)
from app.services.acquisition.browser_pool import (
    BrowserPool as _BrowserPoolExport,
    _acquire_browser,
    _browser_pool_key,
    _evict_browser,
    browser_pool_snapshot as _browser_pool_snapshot_export,
    prepare_browser_pool_for_worker_process as _prepare_browser_pool_for_worker_process_export,
    reset_browser_pool_state as _reset_browser_pool_state_export,
    shutdown_browser_pool as _shutdown_browser_pool_export,
    shutdown_browser_pool_sync as _shutdown_browser_pool_sync_export,
)
from app.services.acquisition.browser_readiness import (
    _cooperative_page_wait,
    _cooperative_sleep_ms,
    _is_listing_surface,
    _pause_after_navigation,
    _snapshot_listing_page_metrics,
    _wait_for_listing_readiness,
    _wait_for_surface_readiness,
)
from app.services.acquisition.browser_runtime import BrowserRuntimeOptions
from app.services.acquisition.cookie_store import (
    load_cookies_for_context,
    load_session_cookies_for_context,
    save_session_cookies_payload,
)
from app.services.acquisition.traversal import (
    AdvanceResult,
    TraversalConfig,
    TraversalRequest,
    TraversalResult,
    TraversalRuntime,
    advance_next_page as _advance_next_page_shared,
    apply_traversal_mode,
    click_and_observe_next_page as _click_and_observe_next_page_shared,
    click_load_more as _click_load_more_shared,
    find_next_page_url_anchor_only as _find_next_page_url_anchor_only_shared,
    has_load_more_control as _has_load_more_control_shared,
    pagination_state_changed as _pagination_state_changed_shared,
    peek_next_page_signal as _peek_next_page_signal_shared,
    scroll_to_bottom as _scroll_to_bottom_shared,
    snapshot_pagination_state as _snapshot_pagination_state_shared,
)
from app.services.exceptions import BrowserError
from app.services.resource_monitor import MemoryPressureLevel, get_memory_pressure_level
from app.services.config.crawl_runtime import (
    ACCORDION_EXPAND_WAIT_MS,
    BROWSER_CLOSE_TIMEOUT_MS,
    BROWSER_CONTEXT_TIMEOUT_MS,
    BROWSER_NEW_PAGE_TIMEOUT_MS,
    COOKIE_CONSENT_POSTCLICK_WAIT_MS,
    COOKIE_CONSENT_PREWAIT_MS,
    DEFAULT_MAX_SCROLLS,
    LOAD_MORE_WAIT_MIN_MS,
    SCROLL_WAIT_MIN_MS,
    SHADOW_DOM_FLATTEN_MAX_HOSTS,
)
from app.services.config.selectors import (
    CARD_SELECTORS,
    COOKIE_CONSENT_SELECTORS,
    PAGINATION_SELECTORS,
)
from app.services.runtime_metrics import incr
from app.services.url_safety import validate_public_target
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from playwright.async_api import (
    async_playwright,
)

if TYPE_CHECKING:
    from app.services.acquisition.session_context import SessionContext

logger = logging.getLogger(__name__)
CARD_SELECTORS_COMMERCE = list(CARD_SELECTORS.get("ecommerce", []))
CARD_SELECTORS_JOBS = list(CARD_SELECTORS.get("jobs", []))
PAGINATION_NEXT_SELECTORS = list(PAGINATION_SELECTORS.get("next_page", []))
LOAD_MORE_SELECTORS = list(PAGINATION_SELECTORS.get("load_more", []))

_RETRYABLE_PAGE_CONTENT_ERROR_RE = re.compile(
    r"(page is navigating|changing the content)",
    re.IGNORECASE,
)
_MIN_TRAVERSAL_MEMORY_BYTES = 500 * 1024 * 1024

# Resource types blocked in degraded (memory-pressure) mode to reduce
# per-page memory footprint.  Fonts/images/media are the heaviest
# resources and rarely affect extraction quality.
_DEGRADED_BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})
_DEGRADED_VIEWPORT = {"width": 1024, "height": 768}

BrowserPool = _BrowserPoolExport
browser_pool_snapshot = _browser_pool_snapshot_export
prepare_browser_pool_for_worker_process = (
    _prepare_browser_pool_for_worker_process_export
)
reset_browser_pool_state = _reset_browser_pool_state_export
shutdown_browser_pool = _shutdown_browser_pool_export
shutdown_browser_pool_sync = _shutdown_browser_pool_sync_export


def _traversal_config() -> TraversalConfig:
    return TraversalConfig(
        pagination_next_selectors=list(PAGINATION_NEXT_SELECTORS),
        load_more_selectors=list(LOAD_MORE_SELECTORS),
        scroll_wait_min_ms=SCROLL_WAIT_MIN_MS,
        load_more_wait_min_ms=LOAD_MORE_WAIT_MIN_MS,
        validate_public_target=validate_public_target,
    )


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


@dataclass(slots=True)
class BrowserRenderRequest:
    target: object
    url: str
    proxy: str | None
    surface: str | None
    traversal_mode: str | None
    max_pages: int
    max_scrolls: int
    prefer_stealth: bool
    request_delay_ms: int
    runtime_options: BrowserRuntimeOptions
    requested_fields: list[str] = field(default_factory=list)
    requested_field_selectors: dict[str, list[dict]] = field(default_factory=dict)
    checkpoint: Callable[[], Awaitable[None]] | None = None
    run_id: int | None = None
    session_context: SessionContext | None = None


@dataclass(slots=True)
class _BrowserRenderAttempt:
    request: BrowserRenderRequest
    launch_profile: dict[str, str | None]
    navigation_strategies: list[tuple[str, int]] | None = None


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
    session_context: SessionContext | None = None,
) -> BrowserResult:
    """Render a page with Playwright and intercept XHR/fetch responses.

    Args:
        url: Target URL.
        proxy: Optional proxy URL.
        traversal_mode: None, "paginate", "scroll", "load_more", or "auto".
        max_scrolls: Max scroll attempts (for scroll mode).
    """
    target = await validate_public_target(url)
    request = BrowserRenderRequest(
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
        requested_fields=list(requested_fields or []),
        requested_field_selectors=dict(requested_field_selectors or {}),
        checkpoint=checkpoint,
        run_id=run_id,
        session_context=session_context,
    )

    async with async_playwright() as pw:
        return await _fetch_rendered_html_with_fallback(pw, request)


async def _fetch_rendered_html_with_fallback(
    pw,
    request: BrowserRenderRequest,
) -> BrowserResult:
    last_error: Exception | None = None
    first_profile_failure_reason: str | None = None
    options = request.runtime_options or BrowserRuntimeOptions()
    profiles = _browser_launch_profiles(options, target=request.target)
    attempted_profiles: list[str] = []
    if not options.retry_launch_profiles:
        profiles = profiles[:1]
    for index, profile in enumerate(profiles):
        attempted_profiles.append(str(profile["label"]))
        navigation_strategies = (
            _shortened_navigation_strategies()
            if _should_shorten_navigation_after_profile_failure(
                first_profile_failure_reason
            )
            else _navigation_strategies(
                browser_channel=str(profile.get("channel") or "").strip() or None
            )
        )
        try:
            result = await _fetch_rendered_html_attempt(
                pw,
                _BrowserRenderAttempt(
                    request=request,
                    launch_profile=profile,
                    navigation_strategies=navigation_strategies,
                ),
            )
            result.diagnostics["browser_launch_profile"] = profile["label"]
            result.diagnostics["attempted_browser_profiles"] = attempted_profiles[:]
            result.diagnostics["system_chrome_attempted"] = "system_chrome" in attempted_profiles
            result.diagnostics["bundled_chromium_attempted"] = "bundled_chromium" in attempted_profiles
            if index < len(profiles) - 1 and _should_retry_launch_profile(
                result, surface=request.surface
            ):
                first_profile_failure_reason = "low_value_result"
                result.diagnostics["fallback_profile_used"] = str(profiles[index + 1]["label"])
                logger.info(
                    "Playwright %s produced a low-value result for %s; trying next launch profile",
                    profile["label"],
                    request.url,
                )
                continue
            return result
        except (
            TimeoutError,
            PlaywrightTimeoutError,
            PlaywrightError,
            RuntimeError,
            OSError,
            NotImplementedError,
        ) as exc:
            last_error = exc
            first_profile_failure_reason = _classify_profile_failure_reason(exc)
            logger.warning(
                "Playwright %s failed for %s: %s",
                profile["label"],
                request.url,
                exc,
            )
            continue
    if last_error is not None:
        raise last_error
    raise BrowserError(f"Unable to render {request.url}")


async def _fetch_rendered_html_attempt(
    pw,
    attempt: _BrowserRenderAttempt,
) -> BrowserResult:
    request = attempt.request
    launch_profile = attempt.launch_profile
    navigation_strategies = attempt.navigation_strategies
    url = request.url
    proxy = request.proxy
    target = request.target
    surface = request.surface
    traversal_mode = request.traversal_mode
    max_pages = request.max_pages
    max_scrolls = request.max_scrolls
    prefer_stealth = request.prefer_stealth
    request_delay_ms = request.request_delay_ms
    runtime_options = request.runtime_options
    run_id = request.run_id
    checkpoint = request.checkpoint
    session_context = request.session_context
    result = BrowserResult()
    intercepted: list[dict] = []
    blocked_non_public_requests: list[dict[str, str]] = []
    timings_ms: dict[str, int] = {}

    # Check memory pressure once per attempt — cheap psutil call.
    pressure = get_memory_pressure_level()
    degraded = pressure is not MemoryPressureLevel.NORMAL
    if degraded:
        logger.info(
            "Browser acquisition running in degraded mode (pressure=%s) for %s",
            pressure.value,
            url,
        )

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
    ctx_kwargs = _context_kwargs(
        prefer_stealth,
        browser_channel=browser_channel,
        runtime_options=runtime_options,
        session_context=session_context,
    )
    if degraded:
        ctx_kwargs["viewport"] = _DEGRADED_VIEWPORT
    try:
        # FIX: Wrap context creation in a strict timeout to prevent zombie browsers
        browser, context, stealth_applied = await _new_context_with_recovery(
            browser=browser,
            browser_type=browser_type,
            launch_kwargs=launch_kwargs,
            launch_profile=launch_profile,
            proxy=proxy,
            ctx_kwargs=ctx_kwargs,
            session_context=session_context,
        )
    except (TimeoutError, PlaywrightError):
        raise

    original_domain = _domain(url)
    page = None
    try:
        await _load_cookies(
            context,
            original_domain,
            session_context=session_context,
        )
        # FIX: Wrap page creation in timeout
        page = await asyncio.wait_for(
            context.new_page(), timeout=BROWSER_NEW_PAGE_TIMEOUT_MS / 1000
        )

        async def _route_request(route, request) -> None:
            request_url = str(getattr(request, "url", "") or "").strip()
            allowed, reason = await _is_public_browser_request_target(request_url)
            if not allowed:
                blocked_non_public_requests.append(
                    {
                        "url": request_url,
                        "resource_type": str(
                            getattr(request, "resource_type", "") or ""
                        ),
                        "reason": reason,
                    }
                )
                try:
                    await _abort_route(route, "blockedbyclient")
                except PlaywrightError:
                    await _abort_route(route)
                return

            if degraded:
                resource_type = str(getattr(request, "resource_type", "") or "")
                if resource_type in _DEGRADED_BLOCKED_RESOURCE_TYPES:
                    try:
                        await _abort_route(route, "blockedbyclient")
                    except PlaywrightError:
                        await _abort_route(route)
                    return

            await _continue_route(route)

        route_fn = getattr(page, "route", None)
        if callable(route_fn):
            await route_fn("**/*", _route_request)

        # DEBT-07: Cap intercepted payload accumulation to prevent
        # unbounded memory growth on analytics-heavy pages.
        _MAX_INTERCEPTED_PAYLOADS = 100
        _MAX_INTERCEPTED_BYTES = 5_000_000
        _intercepted_bytes = 0

        async def _on_response(response):
            nonlocal _intercepted_bytes
            if len(intercepted) >= _MAX_INTERCEPTED_PAYLOADS:
                return
            if _intercepted_bytes >= _MAX_INTERCEPTED_BYTES:
                return
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body = await response.json()
                    body_size = len(str(body))
                    if _intercepted_bytes + body_size > _MAX_INTERCEPTED_BYTES:
                        return
                    _intercepted_bytes += body_size
                    intercepted.append(
                        {
                            "url": response.url,
                            "status": response.status,
                            "body": body,
                        }
                    )
                except (PlaywrightError, ValueError):
                    logger.debug(
                        "Failed to parse intercepted JSON response from %s",
                        response.url,
                        exc_info=True,
                    )

        page.on("response", _on_response)

        if degraded:
            result.origin_warmed = False
            timings_ms["browser_origin_warm_ms"] = 0
        elif browser_channel:
            result.origin_warmed = False
            timings_ms["browser_origin_warm_ms"] = 0
        elif not runtime_options.warm_origin:
            # Skip origin warming for non-stealth requests to save 2s per domain.
            result.origin_warmed = False
            timings_ms["browser_origin_warm_ms"] = 0
        else:
            origin_warm_started_at = time.perf_counter()
            result.origin_warmed = await _maybe_warm_origin(
                page, url, checkpoint=checkpoint
            )
            timings_ms["browser_origin_warm_ms"] = _elapsed_ms(origin_warm_started_at)

        navigation_started_at = time.perf_counter()
        await _goto_with_fallback(
            page,
            url,
            surface=surface,
            strategies=navigation_strategies
            or _navigation_strategies(browser_channel=browser_channel),
            checkpoint=checkpoint,
        )
        timings_ms["browser_navigation_ms"] = _elapsed_ms(navigation_started_at)
        await _dismiss_cookie_consent(page, checkpoint=checkpoint)
        if degraded:
            challenge_ok, challenge_state, reasons = True, "degraded_skipped", []
            timings_ms["browser_challenge_wait_ms"] = 0
        elif runtime_options.wait_for_challenge:
            challenge_started_at = time.perf_counter()
            (
                challenge_ok,
                challenge_state,
                reasons,
            ) = await _wait_for_challenge_resolution(
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
        result.diagnostics["browser_runtime_hardened"] = runtime_options.hardened_mode
        result.diagnostics["browser_runtime_reason"] = (
            runtime_options.hardened_mode_reason
        )
        result.diagnostics["playwright_stealth_applied"] = stealth_applied
        if not challenge_ok:
            await _populate_result(result, page, intercepted, checkpoint=checkpoint)
            result.diagnostics["final_url"] = page.url or url
            result.diagnostics["html_length"] = len(result.html or "")
            result.diagnostics["blocked"] = detect_blocked_page(result.html).is_blocked
            timings_ms["browser_total_ms"] = _elapsed_ms(browser_started_at)
            result.diagnostics["timings_ms"] = timings_ms
            await _persist_context_cookies(
                context,
                page.url or url,
                original_domain,
                session_context=session_context,
            )
            return result
        if runtime_options.wait_for_readiness and _is_listing_surface(surface):
            readiness_started_at = time.perf_counter()
            listing_readiness = await _wait_for_listing_readiness(
                page, surface, checkpoint=checkpoint
            )
            timings_ms["browser_listing_readiness_wait_ms"] = _elapsed_ms(
                readiness_started_at
            )
            if listing_readiness is not None:
                result.diagnostics["listing_readiness"] = listing_readiness
                result.diagnostics["surface_readiness"] = listing_readiness
            if (
                listing_readiness
                and not bool(listing_readiness.get("ready"))
                and await _page_looks_low_value(
                    page,
                    _page_content_with_retry,
                )
            ):
                await _populate_result(result, page, intercepted, checkpoint=checkpoint)
                timings_ms["browser_total_ms"] = _elapsed_ms(browser_started_at)
                result.diagnostics["timings_ms"] = timings_ms
                await _persist_context_cookies(
                    context,
                    page.url or url,
                    original_domain,
                    session_context=session_context,
                )
                return result
        elif runtime_options.wait_for_readiness:
            readiness_started_at = time.perf_counter()
            surface_readiness = await _wait_for_surface_readiness(
                page,
                surface=surface,
                checkpoint=checkpoint,
            )
            timings_ms["browser_surface_readiness_wait_ms"] = _elapsed_ms(
                readiness_started_at
            )
            if surface_readiness is not None:
                result.diagnostics["surface_readiness"] = surface_readiness
        await _pause_after_navigation(request_delay_ms, checkpoint=checkpoint)
        interactive_expansion = await expand_all_interactive_elements(
            page, checkpoint=checkpoint
        )
        if interactive_expansion:
            result.diagnostics["interactive_expansion"] = interactive_expansion
        shadow_dom_flatten = await _flatten_shadow_dom(page)
        if shadow_dom_flatten:
            result.diagnostics["shadow_dom_flatten"] = shadow_dom_flatten

        traversal_result = TraversalResult()
        traversal_fallback_reused_initial_page = False
        traversal_started_at = time.perf_counter()
        if traversal_mode:
            try:
                progress_logger = None
                if run_id is not None:
                    async def _progress_logger(message: str) -> None:
                        from app.services.crawl_events import append_log_event

                        await append_log_event(
                            run_id=run_id,
                            level="info",
                            message=f"[TRAVERSAL] {message}",
                        )

                    progress_logger = _progress_logger
                traversal_runtime = TraversalRuntime(
                    page_content_with_retry=_page_content_with_retry,
                    wait_for_surface_readiness=_wait_for_surface_readiness,
                    wait_for_listing_readiness=_wait_for_listing_readiness,
                    peek_next_page_signal=_peek_next_page_signal,
                    click_and_observe_next_page=_click_and_observe_next_page,
                    advance_next_page_fn=_advance_next_page,
                    has_load_more_control=lambda p, _cfg: _has_load_more_control(p),
                    dismiss_cookie_consent=_dismiss_cookie_consent,
                    pause_after_navigation=_pause_after_navigation,
                    expand_all_interactive_elements=expand_all_interactive_elements,
                    flatten_shadow_dom=_flatten_shadow_dom,
                    cooperative_sleep_ms=_cooperative_sleep_ms,
                    snapshot_listing_page_metrics=_snapshot_listing_page_metrics,
                    ensure_memory_available=_check_memory_available,
                    run_id=run_id,
                    traversal_artifact_dir=_traversal_artifact_dir(run_id),
                    checkpoint=checkpoint,
                    progress_logger=progress_logger,
                    goto_page=lambda pg, next_url, *, surface=None, checkpoint=None: _goto_with_fallback(
                        pg,
                        next_url,
                        surface=surface,
                        checkpoint=checkpoint,
                    ),
                )
                traversal_result = await apply_traversal_mode(
                    TraversalRequest(
                        page=page,
                        surface=surface,
                        traversal_mode=traversal_mode,
                        max_scrolls=max_scrolls,
                        max_pages=max_pages,
                        request_delay_ms=request_delay_ms,
                        runtime=traversal_runtime,
                        config=_traversal_config(),
                    )
                )
            except (
                asyncio.TimeoutError,
                PlaywrightTimeoutError,
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
                traversal_fallback_reused_initial_page = True
                result.diagnostics["traversal_exception"] = {
                    "type": type(exc).__name__,
                    "message": str(exc or "").strip()[:300],
                }
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
        traversal_summary = (
            _normalize_traversal_summary(
                traversal_result.summary
                if isinstance(traversal_result.summary, dict)
                else {},
                traversal_mode=traversal_mode,
                combined_html=combined_html,
            )
            if traversal_mode
            or bool(getattr(traversal_result, "summary", None))
            or combined_html is not None
            else {}
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
                _ts_parts.extend(
                    [
                        f"pages_collected={_ts_pages}",
                        f"stop_reason={_ts_stop}",
                        f"time={_ts_ms}ms",
                    ]
                )
                await append_log_event(
                    run_id=run_id,
                    level="info",
                    message=f"[TRAVERSAL] {', '.join(_ts_parts)}",
                )
            except Exception:
                incr("acquisition_log_event_failures_total")
                logger.debug(
                    "Failed to append traversal crawl event for %s",
                    url,
                    exc_info=True,
                )

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
            traversal_fallback_reused_initial_page = True
            result.diagnostics["traversal_fallback_used"] = True
            result.diagnostics["traversal_fallback_reason"] = fallback_reason
        if traversal_fallback_reused_initial_page:
            result.diagnostics["traversal_reused_initial_page"] = True

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
            result.diagnostics["blocked_non_public_requests"] = (
                blocked_non_public_requests[:10]
            )
            result.diagnostics["blocked_non_public_request_count"] = len(
                blocked_non_public_requests
            )
        await _persist_context_cookies(
            context,
            page.url or url,
            original_domain,
            session_context=session_context,
        )
        return result
    finally:
        await _teardown_page_session(page, context)


def _is_closed_target_playwright_error(exc: Exception) -> bool:
    text = str(exc or "").strip().lower()
    return "target page, context or browser has been closed" in text


async def _abort_route(route, error_code: str | None = None) -> None:
    try:
        if error_code:
            await route.abort(error_code)
        else:
            await route.abort()
    except PlaywrightError as exc:
        if _is_closed_target_playwright_error(exc):
            logger.debug("Ignoring route.abort on closed Playwright target")
            return
        raise


async def _continue_route(route) -> None:
    try:
        await route.continue_()
    except PlaywrightError as exc:
        if _is_closed_target_playwright_error(exc):
            logger.debug("Ignoring route.continue_ on closed Playwright target")
            return
        raise


async def _teardown_page_session(page, context) -> None:
    cancelled = False
    if page is not None:
        unroute_all = getattr(page, "unroute_all", None)
        if callable(unroute_all):
            try:
                await unroute_all(behavior="ignoreErrors")
            except asyncio.CancelledError:
                logger.debug("Playwright page unroute cancelled during teardown")
                cancelled = True
            except TypeError:
                try:
                    await unroute_all()
                except asyncio.CancelledError:
                    logger.debug("Playwright page unroute cancelled during teardown")
                    cancelled = True
            except PlaywrightError as exc:
                if not _is_closed_target_playwright_error(exc):
                    logger.debug("Failed to unroute Playwright page", exc_info=True)
    try:
        await asyncio.wait_for(
            context.close(),
            timeout=BROWSER_CLOSE_TIMEOUT_MS / 1000,
        )
    except asyncio.CancelledError:
        logger.debug("Playwright context close cancelled during teardown")
        cancelled = True
    except TimeoutError:
        logger.debug("Timed out while closing Playwright context")
    except PlaywrightError as exc:
        if not _is_closed_target_playwright_error(exc):
            logger.debug("Failed to close Playwright context", exc_info=True)
    if cancelled:
        raise asyncio.CancelledError()


async def _new_context_with_recovery(
    *,
    browser,
    browser_type,
    launch_kwargs: dict,
    launch_profile: dict[str, str | None],
    proxy: str | None,
    ctx_kwargs: dict,
    session_context: SessionContext | None,
):
    try:
        context = await asyncio.wait_for(
            browser.new_context(**ctx_kwargs),
            timeout=BROWSER_CONTEXT_TIMEOUT_MS / 1000,
        )
    except (TimeoutError, PlaywrightError, NotImplementedError):
        await _evict_browser(_browser_pool_key(launch_profile, proxy), browser)
        browser, _ = await _acquire_browser(
            browser_type=browser_type,
            launch_kwargs=launch_kwargs,
            browser_pool_key=_browser_pool_key(launch_profile, proxy),
            force_new=True,
        )
        context = await asyncio.wait_for(
            browser.new_context(**ctx_kwargs),
            timeout=BROWSER_CONTEXT_TIMEOUT_MS / 1000,
        )
    stealth_applied = await _apply_browser_stealth_with_fallback(
        context,
        session_context=session_context,
    )
    return browser, context, stealth_applied


async def _apply_browser_stealth_with_fallback(
    context,
    *,
    session_context: SessionContext | None,
) -> bool:
    try:
        return await apply_browser_stealth(
            context,
            session_context=session_context,
        )
    except (PlaywrightError, RuntimeError, ValueError, TypeError):
        logger.debug("Failed to apply Playwright stealth init scripts", exc_info=True)
        return False
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


def _browser_launch_profiles(
    runtime_options: BrowserRuntimeOptions,
    *,
    target=None,
) -> list[dict[str, str | None]]:
    # DNS-pinned targets must stay on bundled Chromium because system Chrome
    # ignores --host-resolver-rules and would bypass the SSRF hardening.
    if bool(getattr(target, "dns_resolved", False)) and bool(
        getattr(target, "resolved_ips", None)
    ):
        return [
            {"label": "bundled_chromium", "browser_type": "chromium", "channel": None}
        ]

    # Make system_chrome the primary profile to avoid ERR_HTTP2_PROTOCOL_ERROR
    # and TLS fingerprinting blocks from CDNs like Akamai (Myntra/Target/etc).
    # If real Chrome is missing or fails, it will fall back to bundled_chromium.
    profiles = [
        {"label": "system_chrome", "browser_type": "chromium", "channel": "chrome"},
        {"label": "bundled_chromium", "browser_type": "chromium", "channel": None},
    ]

    # Always return both to ensure maximum resilience
    return profiles


def _should_retry_launch_profile(result: BrowserResult, *, surface: str | None) -> bool:
    result_html = str(getattr(result, "html", "") or "")
    diagnostics = (
        result.diagnostics
        if isinstance(getattr(result, "diagnostics", None), dict)
        else {}
    )
    if detect_blocked_page(result_html).is_blocked:
        return True
    if _is_listing_surface(surface):
        readiness = diagnostics.get("listing_readiness")
        if (
            isinstance(readiness, dict)
            and (not bool(readiness.get("ready")) or bool(readiness.get("shell_like")))
            and _html_looks_low_value(result_html)
        ):
            return True
    return False


async def _collect_frame_sources(page) -> tuple[str, list[dict], list[dict]]:
    try:
        main_html = await _page_content_with_retry(page)
    except PlaywrightError:
        logger.debug(
            "Failed to read main page content while collecting frame sources",
            exc_info=True,
        )
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
                "\n".join(
                    [
                        f"<!-- FRAME START: {frame_url} -->",
                        frame_html,
                        f"<!-- FRAME END: {frame_url} -->",
                    ]
                )
            )
        if not same_origin or not frame_html:
            promoted_sources.append(
                {
                    "kind": "iframe",
                    "url": frame_url,
                    "same_origin": same_origin,
                    "html_available": bool(frame_html),
                }
            )
    combined_html = main_html
    if same_origin_fragments:
        combined_html = "\n".join([main_html, *same_origin_fragments])
    return combined_html, frame_sources, promoted_sources


def _build_launch_kwargs(
    proxy: str | None, target, *, browser_channel: str | None = None
) -> dict:
    launch_kwargs: dict = {"headless": settings.playwright_headless}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    if browser_channel:
        launch_kwargs["channel"] = browser_channel
    # DNS pinning: prevent TOCTOU SSRF where Playwright re-resolves to a
    # different (internal) IP after Python validated it as public.
    # System Chrome (browser_channel set) does not support --host-resolver-rules.
    if target.dns_resolved and target.resolved_ips and not browser_channel:
        pinned_ip = target.resolved_ips[0]
        args = [
            f"--host-resolver-rules=MAP {target.hostname} {_chromium_host_rule_ip(pinned_ip)}",
            # HTTP/2 with resolver-rule pinning can cause TLS SNI/ALPN mismatches
            # on some hosts (e.g. Myntra). Disable H2 at the Chromium level for
            # pinned contexts so TLS negotiation stays on HTTP/1.1.
            "--disable-http2",
        ]
        launch_kwargs.setdefault("args", []).extend(args)
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


async def _peek_next_page_signal(page) -> dict[str, object] | None:
    traversal_config = _traversal_config()
    return await _peek_next_page_signal_shared(page, config=traversal_config)


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


def _pagination_state_changed(
    previous: dict[str, object] | None, current: dict[str, object] | None
) -> bool:
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


async def _advance_next_page(
    page,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> AdvanceResult:
    traversal_config = _traversal_config()
    return await _advance_next_page_shared(
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
        logger.debug(
            "Interactive element expansion failed (non-critical)", exc_info=True
        )
    return {}


async def _flatten_shadow_dom(page) -> dict[str, object]:
    try:
        host_count = await page.evaluate(
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
                collectHosts(document);
                return hosts.slice(0, maxHosts).filter((host) => Boolean(host.shadowRoot)).length;
            }
            """,
            SHADOW_DOM_FLATTEN_MAX_HOSTS,
        )
        flattened = int(host_count or 0)
        if flattened:
            logger.debug("Detected %d shadow root hosts", flattened)
        return {"attempted": True, "flattened_count": flattened, "mutated": False}
    except PlaywrightError as exc:
        logger.debug("Shadow DOM flattening failed (non-critical)", exc_info=True)
        return {
            "attempted": True,
            "flattened_count": 0,
            "mutated": False,
            "error": {
                "type": "PlaywrightError",
                "message": str(exc or "").strip()[:300] or "shadow_dom_flatten_failed",
            },
        }


async def _populate_result(
    result: BrowserResult,
    page,
    intercepted: list[dict],
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    (
        result.html,
        result.frame_sources,
        result.promoted_sources,
    ) = await _collect_frame_sources(page)
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
                logger.debug(
                    "Timed out waiting for domcontentloaded before retrying page.content()",
                    exc_info=True,
                )
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
    mode_used = (
        str(
            normalized.get("mode_used")
            or normalized.get("mode")
            or traversal_mode
            or ""
        ).strip()
        or None
    )
    pages_collected = int(
        normalized.get("pages_collected", 0)
        or (str(combined_html or "").count("<!-- PAGE BREAK:") if combined_html else 0)
    )
    stop_reason = str(normalized.get("stop_reason") or "").strip() or None
    fallback_used = bool(normalized.get("fallback_used"))
    scroll_iterations = int(
        normalized.get("scroll_iterations") or normalized.get("attempt_count") or 0
    )
    normalized["mode_used"] = mode_used
    normalized["pages_collected"] = pages_collected
    normalized["scroll_iterations"] = scroll_iterations
    normalized["stop_reason"] = stop_reason
    normalized["fallback_used"] = fallback_used
    return {key: value for key, value in normalized.items() if value is not None}


async def _persist_context_cookies(
    context,
    final_url: str,
    original_domain: str,
    *,
    session_context: SessionContext | None = None,
) -> None:
    final_domain = _domain(final_url)
    await _save_cookies(context, final_domain, session_context=session_context)
    if final_domain != original_domain:
        await _save_cookies(
            context,
            original_domain,
            session_context=session_context,
        )


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
        await _cooperative_page_wait(
            page, COOKIE_CONSENT_PREWAIT_MS, checkpoint=checkpoint
        )
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
            logger.debug(
                "Cookie consent click failed for selector %s", selector, exc_info=True
            )
            continue
    try:
        await page.keyboard.press("Escape")
    except PlaywrightError:
        logger.debug(
            "Escape key press failed during cookie consent dismissal", exc_info=True
        )


def _context_kwargs(
    prefer_stealth: bool,
    *,
    browser_channel: str | None = None,
    runtime_options: BrowserRuntimeOptions | None = None,
    session_context: SessionContext | None = None,
) -> dict:
    options = runtime_options or BrowserRuntimeOptions()

    # When a SessionContext is provided, delegate to its fingerprint-based
    # kwargs generator for full proxy-fingerprint-cookie affinity.
    if session_context is not None:
        kwargs = session_context.playwright_context_kwargs(
            browser_channel=browser_channel,
            ignore_https_errors=bool(options.ignore_https_errors),
            bypass_csp=bool(options.bypass_csp),
        )
        kwargs["service_workers"] = "block"
        return kwargs

    # Legacy path: static fingerprint.
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


async def _load_cookies(
    context,
    domain: str,
    *,
    session_context: SessionContext | None = None,
) -> bool:
    cookies: list[dict]
    if session_context is not None:
        session_context.remember_domain(domain)
        cookies = []
        if session_context.playwright_cookies:
            cookies = list(session_context.playwright_cookies)
        if not cookies:
            cookies = load_session_cookies_for_context(domain, session_context.identity_key)
            if cookies:
                session_context.merge_playwright_cookies(cookies)
    else:
        cookies = load_cookies_for_context(domain)
    if not cookies:
        return False
    try:
        await context.add_cookies(cookies)
    except PlaywrightError:
        logger.debug(
            "Failed to add cookies to context for domain %s", domain, exc_info=True
        )
        return False
    return True


async def _save_cookies(
    context,
    domain: str,
    *,
    session_context: SessionContext | None = None,
) -> None:
    try:
        cookies = await context.cookies()
    except PlaywrightError:
        logger.debug(
            "Failed to read cookies from context for domain %s", domain, exc_info=True
        )
        return
    if session_context is not None:
        session_context.remember_domain(domain)
        session_context.merge_playwright_cookies(cookies)
        await asyncio.to_thread(
            save_session_cookies_payload,
            cookies,
            domain=domain,
            session_identity=session_context.identity_key,
        )
        return
    logger.debug(
        "Skipping cookie persistence for non-session browser context on %s",
        domain,
    )


def _check_memory_available() -> None:
    mem = psutil.virtual_memory()
    if int(mem.available) < _MIN_TRAVERSAL_MEMORY_BYTES:
        raise MemoryError("Insufficient memory for traversal")


def _traversal_artifact_dir(run_id: int | None) -> Path:
    run_token = (
        str(run_id) if run_id is not None else f"adhoc-{os.getpid()}-{time.time_ns()}"
    )
    return settings.acquisition_cache_dir / "traversal_html" / run_token


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _chromium_host_rule_ip(ip_text: str) -> str:
    try:
        value = ipaddress.ip_address(ip_text)
    except ValueError:
        return ip_text
    return f"[{value.compressed}]" if value.version == 6 else value.compressed
