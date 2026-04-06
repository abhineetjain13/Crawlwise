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

from playwright.async_api import Error as PlaywrightError, async_playwright

from app.core.config import settings
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_runtime import BrowserRuntimeOptions
from app.services.acquisition.cookie_store import (
    cookie_policy_for_domain,
    cookie_store_path,
    filter_persistable_cookies,
    load_cookies_for_context,
    save_cookies_payload,
)
from app.services.pipeline_config import (
    ACCORDION_EXPAND_MAX,
    ACCORDION_EXPAND_WAIT_MS,
    BLOCK_MIN_HTML_LENGTH,
    BLOCK_BROWSER_CHALLENGE_STRONG_MARKERS,
    BLOCK_BROWSER_CHALLENGE_WEAK_MARKERS,
    BROWSER_ERROR_RETRY_ATTEMPTS,
    BROWSER_ERROR_RETRY_DELAY_MS,
    BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS,
    BROWSER_NAVIGATION_LOAD_TIMEOUT_MS,
    BROWSER_NAVIGATION_NETWORKIDLE_TIMEOUT_MS,
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
from app.services.requested_field_policy import requested_field_terms
from app.services.url_safety import validate_public_target

logger = logging.getLogger(__name__)

_RETRYABLE_PAGE_CONTENT_ERROR_RE = re.compile(
    r"(page is navigating|changing the content)",
    re.IGNORECASE,
)


@dataclass
class BrowserResult:
    """Result from a Playwright render including intercepted payloads."""

    html: str = ""
    network_payloads: list[dict] = field(default_factory=list)
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
) -> BrowserResult:
    last_error: Exception | None = None
    first_profile_failed = False
    options = runtime_options or BrowserRuntimeOptions()
    profiles = _browser_launch_profiles(options)
    for index, profile in enumerate(profiles):
        navigation_strategies = (
            _shortened_navigation_strategies()
            if first_profile_failed
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
            )
            result.diagnostics["browser_launch_profile"] = profile["label"]
            if index < len(profiles) - 1 and _should_retry_launch_profile(result, surface=surface):
                first_profile_failed = True
                logger.info(
                    "Playwright %s produced a low-value result for %s; trying next launch profile",
                    profile["label"],
                    url,
                )
                continue
            return result
        except Exception as exc:
            last_error = exc
            first_profile_failed = True
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
) -> BrowserResult:
    result = BrowserResult()
    intercepted: list[dict] = []
    timings_ms: dict[str, int] = {}
    browser_started_at = time.perf_counter()
    browser_type = getattr(pw, str(launch_profile.get("browser_type") or "chromium"))
    launch_kwargs = _build_launch_kwargs(
        proxy,
        target,
        browser_channel=str(launch_profile.get("channel") or "").strip() or None,
    )
    launch_started_at = time.perf_counter()
    browser = await browser_type.launch(**launch_kwargs)
    timings_ms["browser_launch_ms"] = _elapsed_ms(launch_started_at)
    browser_channel = str(launch_profile.get("channel") or "").strip() or None
    context = await browser.new_context(**_context_kwargs(prefer_stealth, browser_channel=browser_channel))
    original_domain = _domain(url)
    try:
        await _load_cookies(context, original_domain)
        page = await context.new_page()

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
                except Exception:
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
        await _expand_accordions(page, checkpoint=checkpoint)
        field_trigger_selectors = await _open_requested_field_sections(
            page,
            requested_fields=requested_fields,
            requested_field_selectors=requested_field_selectors,
            checkpoint=checkpoint,
        )
        if field_trigger_selectors:
            result.diagnostics["field_trigger_selectors"] = field_trigger_selectors
        await _flatten_shadow_dom(page)

        traversal_started_at = time.perf_counter()
        combined_html = await _apply_traversal_mode(
            page,
            surface,
            traversal_mode,
            max_scrolls,
            max_pages=max_pages,
            request_delay_ms=request_delay_ms,
            checkpoint=checkpoint,
        )
        timings_ms["browser_traversal_ms"] = _elapsed_ms(traversal_started_at)
        if combined_html is not None:
            result.html = combined_html
            result.network_payloads = intercepted
            result.diagnostics["traversal_mode"] = traversal_mode
            result.diagnostics["max_pages"] = max_pages
            result.diagnostics["page_count"] = combined_html.count("<!-- PAGE BREAK:") if combined_html else 0
            timings_ms["browser_total_ms"] = _elapsed_ms(browser_started_at)
            result.diagnostics["timings_ms"] = timings_ms
            await _persist_context_cookies(context, page.url or url, original_domain)
            return result

        await _populate_result(result, page, intercepted, checkpoint=checkpoint)
        timings_ms["browser_total_ms"] = _elapsed_ms(browser_started_at)
        result.diagnostics["timings_ms"] = timings_ms
        await _persist_context_cookies(context, page.url or url, original_domain)
        return result
    finally:
        await context.close()
        await browser.close()


def _browser_launch_profiles(runtime_options: BrowserRuntimeOptions) -> list[dict[str, str | None]]:
    profiles = [
        {"label": "bundled_chromium", "browser_type": "chromium", "channel": None},
        {"label": "system_chrome", "browser_type": "chromium", "channel": "chrome"},
    ]
    if runtime_options.retry_launch_profiles:
        return profiles
    return profiles[:1]


def _is_listing_surface(surface: str | None) -> bool:
    return str(surface or "").strip().lower().endswith("listing")


def _should_retry_launch_profile(result: BrowserResult, *, surface: str | None) -> bool:
    if detect_blocked_page(result.html or "").is_blocked:
        return True
    if _is_listing_surface(surface):
        readiness = result.diagnostics.get("listing_readiness")
        if isinstance(readiness, dict) and not bool(readiness.get("ready")) and _html_looks_low_value(result.html):
            return True
    return False


async def _page_looks_low_value(page) -> bool:
    try:
        html = await _page_content_with_retry(page)
    except Exception:
        logger.debug("Failed to inspect page content for low-value result detection", exc_info=True)
        return False
    return _html_looks_low_value(html)


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
    if target.dns_resolved and target.resolved_ips and not browser_channel:
        pinned_ip = target.resolved_ips[0]
        launch_kwargs["args"] = [
            f"--host-resolver-rules=MAP {target.hostname} {_chromium_host_rule_ip(pinned_ip)}",
        ]
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
) -> str | None:
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface.endswith("_detail"):
        return None
    if traversal_mode == "scroll":
        await _scroll_to_bottom(
            page,
            max_scrolls,
            request_delay_ms=request_delay_ms,
            checkpoint=checkpoint,
        )
        return None
    if traversal_mode == "load_more":
        await _click_load_more(
            page,
            max_scrolls,
            request_delay_ms=request_delay_ms,
            checkpoint=checkpoint,
        )
        return None
    if traversal_mode == "paginate":
        return await _collect_paginated_html(
            page,
            surface=surface,
            max_pages=max_pages,
            request_delay_ms=request_delay_ms,
            checkpoint=checkpoint,
        )
    if traversal_mode == "auto":
        await _scroll_to_bottom(
            page,
            max_scrolls,
            request_delay_ms=request_delay_ms,
            checkpoint=checkpoint,
        )
        if await _has_load_more_control(page):
            await _click_load_more(
                page,
                max_scrolls,
                request_delay_ms=request_delay_ms,
                checkpoint=checkpoint,
            )
        next_page_url = await _click_and_observe_next_page(page, checkpoint=checkpoint)
        if next_page_url:
            return await _collect_paginated_html(
                page,
                surface=surface,
                max_pages=max_pages,
                request_delay_ms=request_delay_ms,
                checkpoint=checkpoint,
            )
    return None


async def _collect_paginated_html(
    page,
    *,
    surface: str | None = None,
    max_pages: int,
    request_delay_ms: int,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> str:
    fragments: list[str] = []
    visited_urls: set[str] = set()
    current_url = str(page.url or "").strip()
    if current_url:
        visited_urls.add(current_url)

    page_limit = max(1, int(max_pages or 1))
    for page_index in range(page_limit):
        page_html = await _page_content_with_retry(page, checkpoint=checkpoint)
        fragments.append(f"<!-- PAGE BREAK:{page_index + 1}:{page.url} -->\n{page_html}")
        if page_index + 1 >= page_limit:
            break
        current_url = str(page.url or "").strip()
        next_page_url = await _click_and_observe_next_page(page, checkpoint=checkpoint)
        page_advanced_in_place = bool(next_page_url) and str(page.url or "").strip() == current_url and next_page_url == current_url
        if not next_page_url or (next_page_url in visited_urls and not page_advanced_in_place):
            break
        try:
            await validate_public_target(next_page_url)
        except ValueError as exc:
            logger.warning("Rejected pagination URL %s from %s: %s", next_page_url, page.url, exc)
            break
        visited_urls.add(next_page_url)
        if not page_advanced_in_place:
            await page.goto(
                next_page_url,
                wait_until="domcontentloaded",
                timeout=PAGINATION_NAVIGATION_TIMEOUT_MS,
            )
            try:
                await page.wait_for_load_state(
                    "load",
                    timeout=BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS,
                )
            except Exception:
                pass
            await _wait_for_surface_readiness(
                page,
                surface=surface,
                checkpoint=checkpoint,
            )
        await _dismiss_cookie_consent(page, checkpoint=checkpoint)
        await _pause_after_navigation(request_delay_ms, checkpoint=checkpoint)
        await _expand_accordions(page, checkpoint=checkpoint)
        await _open_requested_field_sections(
            page,
            requested_fields=[],
            requested_field_selectors={},
            checkpoint=checkpoint,
        )
        await _flatten_shadow_dom(page)
        await _wait_for_listing_readiness(page, surface, checkpoint=checkpoint)
    return "\n".join(fragments)


async def _wait_for_listing_readiness(
    page,
    surface: str | None,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, object] | None:
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_surface.endswith("listing"):
        return None
    selectors = (
        CARD_SELECTORS_JOBS
        if normalized_surface == "job_listing"
        else CARD_SELECTORS_COMMERCE
    )
    if not selectors:
        return None
    elapsed = 0
    poll_ms = max(100, LISTING_READINESS_POLL_MS)
    max_wait_ms = max(0, LISTING_READINESS_MAX_WAIT_MS)
    best_selector = ""
    best_count = 0
    while elapsed <= max_wait_ms:
        current_best_selector = ""
        current_best_count = 0
        for selector in selectors:
            try:
                count = await page.locator(selector).count()
            except Exception:
                logger.debug("Listing readiness count failed for selector %s", selector, exc_info=True)
                continue
            if count > current_best_count:
                current_best_count = count
                current_best_selector = selector
            if count >= LISTING_MIN_ITEMS:
                return {
                    "ready": True,
                    "selector": selector,
                    "count": count,
                    "waited_ms": elapsed,
                }
        if current_best_count > best_count:
            best_count = current_best_count
            best_selector = current_best_selector
        if elapsed >= max_wait_ms:
            break
        await _cooperative_page_wait(page, poll_ms, checkpoint=checkpoint)
        elapsed += poll_ms
    return {
        "ready": False,
        "selector": best_selector or None,
        "count": best_count,
        "waited_ms": elapsed,
    }


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
                except Exception:
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
            except Exception:
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
    for selector in PAGINATION_NEXT_SELECTORS:
        try:
            locator = page.locator(selector).first
            if not await locator.count():
                continue
            href = await locator.get_attribute("href")
            if href:
                return urljoin(page.url, href)
        except Exception:
            logger.debug("Failed to inspect pagination selector %s", selector, exc_info=True)
            continue

    try:
        href = await page.evaluate(
            """
            () => {
              const anchors = Array.from(document.querySelectorAll('a[href]'));
              const match = anchors.find((anchor) => {
                const text = (anchor.textContent || '').trim().toLowerCase();
                const aria = (anchor.getAttribute('aria-label') || '').trim().toLowerCase();
                const title = (anchor.getAttribute('title') || '').trim().toLowerCase();
                return text === 'next' || text === 'next >' || text === '>' || aria.includes('next') || title.includes('next');
              });
              return match ? match.href : '';
            }
            """
        )
    except Exception:
        logger.debug("Failed to evaluate DOM for next-page link", exc_info=True)
        return ""
    return str(href or "").strip()


async def _find_next_page_url(page) -> str:
    return await _find_next_page_url_anchor_only(page)


async def _click_and_observe_next_page(
    page,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> str:
    next_page_url = await _find_next_page_url_anchor_only(page)
    if next_page_url:
        return next_page_url

    async def _container_hash() -> int | None:
        selector = '[class*="product"], [class*="result"], ul.products, main'
        try:
            locator = page.locator(selector).first
            if not await locator.count():
                return None
            return hash((await locator.inner_html())[:2000])
        except Exception:
            logger.debug("Failed to inspect listing container before/after pagination click", exc_info=True)
            return None

    click_selectors = [
        *PAGINATION_NEXT_SELECTORS,
        '[aria-label*="next" i]',
        'button[class*="next"]',
        '[role="button"][class*="next"]',
        'button:has-text("Next")',
        '[data-testid*="next"]',
    ]
    target = None
    for selector in click_selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count():
                target = locator
                break
        except Exception:
            logger.debug("Failed to inspect clickable pagination selector %s", selector, exc_info=True)
    if target is None:
        return ""

    initial_url = str(page.url or "").strip()
    initial_hash = await _container_hash()
    try:
        await target.click(timeout=1500)
    except Exception:
        logger.debug("Failed to click next-page control", exc_info=True)
        return ""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        logger.debug("Timed out waiting for domcontentloaded after pagination click", exc_info=True)

    waited_ms = 0
    poll_ms = 250
    while waited_ms < 3000:
        await _cooperative_page_wait(page, poll_ms, checkpoint=checkpoint)
        waited_ms += poll_ms
        current_url = str(page.url or "").strip()
        if current_url != initial_url:
            return current_url
        if await _container_hash() != initial_hash:
            return current_url
    return ""


async def _expand_accordions(
    page,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    try:
        expanded_count = await page.evaluate(
            """
            (maxExpand) => {
                let count = 0;
                const collapsed = document.querySelectorAll(
                    '[aria-expanded="false"], ' +
                    'details:not([open]), ' +
                    '[data-accordion-heading]:not([aria-expanded="true"]), ' +
                    '[role="tab"][aria-selected="false"]'
                );
                for (const el of collapsed) {
                    if (el.tagName === 'DETAILS') {
                        el.setAttribute('open', '');
                        count++;
                    } else {
                        try { el.click(); count++; } catch (error) {}
                    }
                    if (count >= maxExpand) break;
                }
                return count;
            }
            """,
            ACCORDION_EXPAND_MAX,
        )
        if expanded_count:
            logger.debug("Expanded %d accordion/tab sections", expanded_count)
            await _cooperative_sleep_ms(ACCORDION_EXPAND_WAIT_MS, checkpoint=checkpoint)
    except Exception:
        logger.debug("Accordion expansion failed (non-critical)", exc_info=True)


async def _open_requested_field_sections(
    page,
    *,
    requested_fields: list[str],
    requested_field_selectors: dict[str, list[dict]],
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, list[dict]]:
    plans: list[dict[str, object]] = []
    for field_name in requested_fields:
        normalized_field = str(field_name or "").strip().lower()
        if not normalized_field:
            continue
        plans.append({
            "field_name": normalized_field,
            "terms": requested_field_terms(normalized_field),
            "selectors": [
                {
                    "css_selector": str(row.get("css_selector") or "").strip() or None,
                    "xpath": str(row.get("xpath") or "").strip() or None,
                }
                for row in (requested_field_selectors.get(normalized_field) or [])
                if isinstance(row, dict)
            ],
        })
    if not plans:
        return {}

    try:
        clicked_rows = await page.evaluate(
            """
            (fieldPlans) => {
                const normalize = (value) =>
                    String(value || '')
                        .toLowerCase()
                        .replace(/&/g, ' and ')
                        .replace(/[_-]+/g, ' ')
                        .replace(/\\s+/g, ' ')
                        .trim();
                const roots = [document];
                const queue = [document];
                const seen = new Set([document]);
                while (queue.length) {
                    const root = queue.shift();
                    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
                    let current = walker.currentNode;
                    while (current) {
                        if (current.shadowRoot && !seen.has(current.shadowRoot)) {
                            roots.push(current.shadowRoot);
                            queue.push(current.shadowRoot);
                            seen.add(current.shadowRoot);
                        }
                        current = walker.nextNode();
                    }
                }
                const gatherBySelector = (selector, xpath) => {
                    const matches = [];
                    if (xpath) {
                        for (const root of roots) {
                            try {
                                const doc = root.ownerDocument || document;
                                const result = doc.evaluate(xpath, root, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                                for (let i = 0; i < result.snapshotLength; i += 1) {
                                    const node = result.snapshotItem(i);
                                    if (node && node.nodeType === Node.ELEMENT_NODE) matches.push(node);
                                }
                            } catch (error) {}
                        }
                    }
                    if (selector) {
                        for (const root of roots) {
                            try { matches.push(...Array.from(root.querySelectorAll(selector))); } catch (error) {}
                        }
                    }
                    return matches;
                };
                const selectableNodes = () => {
                    const nodes = [];
                    const selectors = [
                        '[aria-controls]',
                        '[role="tab"]',
                        '[role="button"]',
                        'button',
                        'summary',
                        '[data-accordion-heading]',
                        '[data-tab-heading]',
                        'a',
                        'li',
                        'div',
                    ];
                    for (const root of roots) {
                        for (const selector of selectors) {
                            try { nodes.push(...Array.from(root.querySelectorAll(selector))); } catch (error) {}
                        }
                    }
                    return nodes;
                };
                const clicked = [];
                const seenNodes = new Set();
                for (const plan of fieldPlans) {
                    const terms = Array.isArray(plan.terms) ? plan.terms.map(normalize).filter(Boolean) : [];
                    let targets = [];
                    for (const selectorPlan of (Array.isArray(plan.selectors) ? plan.selectors : [])) {
                        targets.push(...gatherBySelector(selectorPlan.css_selector, selectorPlan.xpath));
                    }
                    if (!targets.length && terms.length) {
                        const candidates = selectableNodes();
                        targets = candidates.filter((node) => {
                            const text = normalize(node.textContent || node.getAttribute('aria-label') || node.getAttribute('title') || '');
                            return terms.some((term) => term && text.includes(term));
                        });
                    }
                    for (const node of targets) {
                        if (!(node instanceof Element) || seenNodes.has(node)) continue;
                        seenNodes.add(node);
                        try { node.click(); } catch (error) { continue; }
                        clicked.push({
                            field_name: plan.field_name,
                            css_selector: null,
                            xpath: null,
                            regex: null,
                            status: 'clicked',
                            sample_value: normalize(node.textContent || ''),
                            source: 'requested_field_section',
                        });
                        break;
                    }
                }
                return clicked;
            }
            """,
            plans,
        )
        if clicked_rows:
            await _cooperative_sleep_ms(ACCORDION_EXPAND_WAIT_MS, checkpoint=checkpoint)
        selectors: dict[str, list[dict]] = {}
        for row in clicked_rows or []:
            if not isinstance(row, dict):
                continue
            field_name = str(row.get("field_name") or "").strip().lower()
            if not field_name:
                continue
            selectors.setdefault(field_name, []).append(row)
        return selectors
    except Exception:
        logger.debug("Requested field section expansion failed (non-critical)", exc_info=True)
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
    except Exception:
        logger.debug("Shadow DOM flattening failed (non-critical)", exc_info=True)


async def _populate_result(
    result: BrowserResult,
    page,
    intercepted: list[dict],
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    result.html = await _page_content_with_retry(page, checkpoint=checkpoint)
    result.network_payloads = intercepted
    result.diagnostics["final_url"] = str(page.url or "").strip() or None
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
        except Exception as exc:
            last_error = exc
            retryable_playwright_error = isinstance(exc, PlaywrightError) and bool(
                _RETRYABLE_PAGE_CONTENT_ERROR_RE.search(str(exc))
            )
            if not retryable_playwright_error:
                raise
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                logger.debug("Timed out waiting for domcontentloaded before retrying page.content()", exc_info=True)
            if attempt + 1 >= max(1, attempts):
                break
            await _cooperative_page_wait(page, wait_ms, checkpoint=checkpoint)
    assert last_error is not None
    raise last_error


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((time.perf_counter() - started_at) * 1000)))


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
                    except Exception:
                        pass
            return
        except Exception as exc:
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
    except Exception:
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
        except Exception:
            logger.debug("Origin warm mouse/scroll interaction failed", exc_info=True)
    except Exception:
        logger.debug("Origin warm navigation failed for %s", origin_url, exc_info=True)
        return


async def _scroll_to_bottom(
    page,
    max_scrolls: int,
    *,
    request_delay_ms: int,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Scroll to bottom repeatedly until no new content appears."""
    prev_height = 0
    for _ in range(max_scrolls):
        current_height = await page.evaluate(
            """
            () => {
                const root = document.scrollingElement || document.documentElement || document.body;
                if (!root) return 0;
                return Math.max(root.scrollHeight || 0, document.body?.scrollHeight || 0, document.documentElement?.scrollHeight || 0);
            }
            """
        )
        if current_height == prev_height:
            break
        prev_height = current_height
        await page.evaluate(
            """
            (height) => {
                const root = document.scrollingElement || document.documentElement || document.body;
                if (!root) return;
                window.scrollTo(0, height || root.scrollHeight || 0);
            }
            """,
            current_height,
        )
        await _cooperative_sleep_ms(
            max(request_delay_ms, SCROLL_WAIT_MIN_MS),
            checkpoint=checkpoint,
        )


async def _click_load_more(
    page,
    max_clicks: int,
    *,
    request_delay_ms: int,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Click load-more/show-all buttons until exhausted."""
    for _ in range(max_clicks):
        clicked = False
        for sel in LOAD_MORE_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible():
                    await btn.click()
                    await _cooperative_sleep_ms(
                        max(request_delay_ms, LOAD_MORE_WAIT_MIN_MS),
                        checkpoint=checkpoint,
                    )
                    clicked = True
                    break
            except Exception:
                logger.debug("Load-more click failed for selector %s", sel, exc_info=True)
                continue
        if not clicked:
            break


async def _has_load_more_control(page) -> bool:
    for selector in LOAD_MORE_SELECTORS:
        try:
            button = page.locator(selector).first
            if await button.is_visible():
                return True
        except Exception:
            logger.debug("Load-more visibility check failed for selector %s", selector, exc_info=True)
    return False


async def _dismiss_cookie_consent(
    page,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    try:
        await _cooperative_page_wait(page, COOKIE_CONSENT_PREWAIT_MS, checkpoint=checkpoint)
    except Exception:
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
        except Exception:
            logger.debug("Cookie consent click failed for selector %s", selector, exc_info=True)
            continue
    try:
        await page.keyboard.press("Escape")
    except Exception:
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
    except Exception:
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
        except Exception:
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


def _context_kwargs(prefer_stealth: bool, *, browser_channel: str | None = None) -> dict:
    if browser_channel:
        kwargs = {
            "java_script_enabled": True,
            "ignore_https_errors": True,
            "viewport": {"width": 1365, "height": 900},
            "device_scale_factor": 1,
            "is_mobile": False,
            "has_touch": False,
            "color_scheme": "light",
            "user_agent": _STEALTH_USER_AGENT,
        }
        return kwargs
    kwargs = {
        "java_script_enabled": True,
        "ignore_https_errors": True,
        "bypass_csp": True,
        "locale": "en-US",
        "timezone_id": "UTC",
        "viewport": {"width": 1365, "height": 900},
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
        "color_scheme": "light",
    }
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
    except Exception:
        logger.debug("Failed to add cookies to context for domain %s", domain, exc_info=True)
        return False
    return True


async def _save_cookies(context, domain: str) -> None:
    try:
        cookies = await context.cookies()
    except Exception:
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
