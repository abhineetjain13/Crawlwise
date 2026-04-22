from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
import logging
import re
import time
from urllib.parse import urljoin, urlsplit

from app.services.acquisition.dom_runtime import get_page_html, wait_for_dom_mutation_settle
from app.services.acquisition.runtime import classify_blocked_page_async

try:
    from playwright.async_api import Error as _PlaywrightError
except ImportError:  # pragma: no cover
    class _PlaywrightError(Exception):  # type: ignore[no-redef]
        pass

from app.services.config.extraction_rules import (
    LISTING_FALLBACK_CONTAINER_SELECTOR,
    LISTING_STRUCTURE_NEGATIVE_HINTS,
    LISTING_STRUCTURE_POSITIVE_HINTS,
)
from app.services.platform_policy import (
    path_tenant_boundary_family,
    requires_path_tenant_boundary,
    url_host_matches_platform_family,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS, PAGINATION_SELECTORS
from selectolax.lexbor import LexborHTMLParser

logger = logging.getLogger(__name__)

_STRUCTURED_SCRIPT_TYPES = {
    "application/hal+json",
    "application/json",
    "application/ld+json",
    "application/vnd.api+json",
}
_STRUCTURED_SCRIPT_IDS = {
    "__next_data__",
    "__nuxt_data__",
}
_STRUCTURED_SCRIPT_TEXT_MARKERS = (
    "__apollo_state__",
    "__initial_state__",
    "__nuxt__",
    "__preloaded_state__",
    "__remixcontext",
    "shopifyanalytics.meta",
    "var meta =",
)
_PRICE_HINT_RE = re.compile(
    r"(?:rs\.?|inr|\$|£|€)\s*\d|\b\d[\d,]{2,}\b",
    re.I,
)
_LISTING_RECOVERY_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("clear_filters", r"(clear all|clear filters|reset|reset filters)", "Removing active filters"),
    ("view_all", r"(view all|see all|shop all|show all)", "Expanding the listing view"),
    ("next_page", r"(next|older|›|»|>)", "Advancing pagination"),
)
@dataclass(slots=True)
class TraversalResult:
    requested_mode: str | None
    selected_mode: str | None = None
    activated: bool = False
    stop_reason: str = "not_requested"
    iterations: int = 0
    scroll_iterations: int = 0
    load_more_clicks: int = 0
    pages_advanced: int = 0
    progress_events: int = 0
    card_count: int = 0
    overlays_dismissed: bool = False
    click_retries: int = 0
    html_fragments: list[tuple[str, bool]] = field(default_factory=list)
    events: list[tuple[str, str]] = field(default_factory=list)
    _seen_card_fragments: set[str] = field(default_factory=set, repr=False)
    _seen_structured_fragments: set[str] = field(default_factory=set, repr=False)

    def html_bytes(self) -> int:
        return sum(
            len(fragment.encode("utf-8"))
            for fragment, _is_fallback in self.html_fragments
            if fragment
        )

    def compose_html(self) -> str:
        texts = [str(fragment or "").strip() for fragment, _is_fallback in self.html_fragments if str(fragment or "").strip()]
        if not texts:
            return ""
        if not self.activated:
            return "\n".join(texts)
        sections = [
            (
                f'<section data-traversal-fragment="{index}">\n'
                f"{text}\n"
                "</section>"
            )
            for index, text in enumerate(texts, start=1)
        ]
        return "<html><body>\n" + "\n".join(sections) + "\n</body></html>"

    def diagnostics(self) -> dict[str, object]:
        return {
            "requested_traversal_mode": self.requested_mode,
            "selected_traversal_mode": self.selected_mode,
            "traversal_activated": self.activated,
            "traversal_stop_reason": self.stop_reason,
            "traversal_iterations": self.iterations,
            "scroll_iterations": self.scroll_iterations,
            "load_more_clicks": self.load_more_clicks,
            "pages_advanced": self.pages_advanced,
            "traversal_progress_events": self.progress_events,
            "listing_card_count": self.card_count,
            "traversal_fragment_count": len(self.html_fragments),
            "traversal_html_bytes": self.html_bytes(),
            "overlays_dismissed": self.overlays_dismissed,
            "click_retries": self.click_retries,
            "traversal_events": self.events,
        }


def _set_stop_reason(
    result: TraversalResult,
    reason: str,
    *,
    surface: str,
    traversal_mode: str | None = None,
) -> None:
    result.stop_reason = reason
    logger.info(
        "Traversal stop_reason=%s surface=%s requested_mode=%s selected_mode=%s iterations=%s progress_events=%s",
        reason,
        surface,
        traversal_mode or result.requested_mode,
        result.selected_mode,
        result.iterations,
        result.progress_events,
    )


def should_run_traversal(surface: str | None, traversal_mode: str | None) -> bool:
    normalized_mode = str(traversal_mode or "").strip().lower()
    if normalized_mode in {"single", "sitemap", "crawl"} or not normalized_mode:
        return False
    if normalized_mode in {"scroll", "load_more", "paginate"}:
        return True
    # "auto" mode: require listing surface
    normalized_surface = str(surface or "").strip().lower()
    return "listing" in normalized_surface


async def execute_listing_traversal(
    page,
    *,
    surface: str,
    traversal_mode: str,
    max_pages: int,
    max_scrolls: int,
    timeout_seconds: float | None = None,
    on_event=None,
) -> TraversalResult:
    normalized_mode = str(traversal_mode or "").strip().lower()
    result = TraversalResult(requested_mode=normalized_mode)
    if not should_run_traversal(surface, normalized_mode):
        _set_stop_reason(result, "not_listing_or_disabled", surface=surface, traversal_mode=normalized_mode)
        result.html_fragments = [(await get_page_html(page), True)]
        return result

    selected_mode: str | None = normalized_mode
    if normalized_mode == "auto":
        selected_mode = await _detect_auto_mode(page, surface=surface)
        if not selected_mode:
            if await _has_scroll_signals(page, surface=surface):
                selected_mode = "scroll"
                logger.info(
                    "auto mode: no controls found, falling back to scroll for surface=%s",
                    surface,
                )
            else:
                result.selected_mode = selected_mode
                _set_stop_reason(result, "no_mode_detected", surface=surface, traversal_mode=normalized_mode)
                result.card_count = (await _page_snapshot(page, surface=surface))["card_count"]
                result.html_fragments = [(await get_page_html(page), True)]
                return result
        result.selected_mode = selected_mode
    else:
        result.selected_mode = normalized_mode

    deadline_at = (
        time.monotonic() + float(timeout_seconds)
        if timeout_seconds is not None and float(timeout_seconds) > 0
        else None
    )
    result.activated = True
    if selected_mode == "scroll":
        await _run_scroll_traversal(
            page,
            surface=surface,
            max_scrolls=max_scrolls,
            result=result,
            deadline_at=deadline_at,
            on_event=on_event,
        )
    elif selected_mode == "load_more":
        await _run_load_more_traversal(
            page,
            surface=surface,
            max_clicks=max(1, int(max_pages)),
            result=result,
            deadline_at=deadline_at,
            on_event=on_event,
        )
    elif selected_mode == "paginate":
        await _run_paginate_traversal(
            page,
            surface=surface,
            max_pages=max_pages,
            result=result,
            deadline_at=deadline_at,
            on_event=on_event,
        )
    else:
        _set_stop_reason(result, "unsupported_mode", surface=surface, traversal_mode=normalized_mode)

    if not result.html_fragments:
        result.html_fragments = [(await get_page_html(page), True)]
    return result


async def _detect_auto_mode(page, *, surface: str) -> str | None:
    load_more_locator = await _find_actionable_locator(page, "load_more")
    next_page_locator = await _find_actionable_locator(page, "next_page")
    scroll_signals = await _has_scroll_signals(page, surface=surface)
    if load_more_locator is not None:
        return "load_more"
    if next_page_locator is not None:
        if await _looks_like_paginate_control(next_page_locator) or await _looks_like_next_page_control(next_page_locator):
            return "paginate"
        if not scroll_signals:
            return "paginate"
    if scroll_signals:
        return "scroll"
    return None


async def _run_scroll_traversal(
    page,
    *,
    surface: str,
    max_scrolls: int,
    result: TraversalResult,
    deadline_at: float | None,
    on_event,
) -> None:
    max_iterations = min(
        max(1, int(max_scrolls)),
        int(crawler_runtime_settings.traversal_max_iterations_cap),
    )
    weak_progress_streak = 0
    best_card_gain = 0
    marginal_gain_streak = 0
    await _append_html_fragment(page, result, surface=surface)
    previous = await _page_snapshot(page, surface=surface)
    await _emit_event(on_event, "info", "Detected listing layout, pagination: scroll")
    for _ in range(max_iterations):
        if _deadline_reached(deadline_at):
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        result.iterations += 1
        result.scroll_iterations += 1
        await page.evaluate(
            """
            () => {
              const root = document.scrollingElement || document.documentElement || document.body;
              root.scrollTo({ top: root.scrollHeight, behavior: "auto" });
            }
            """
        )
        wait_ms = _remaining_timeout_ms(
            deadline_at,
            int(crawler_runtime_settings.scroll_wait_min_ms),
        )
        if wait_ms <= 0:
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        await _settle_after_action(page, deadline_at=deadline_at, timeout_ms=wait_ms)
        current = await _page_snapshot(page, surface=surface)
        card_gain = max(
            0,
            int(current.get("card_count", 0)) - int(previous.get("card_count", 0)),
        )
        if card_gain > 0:
            best_card_gain = max(best_card_gain, card_gain)
        if _snapshot_progressed(previous, current):
            result.progress_events += 1
            message = (
                f"Scroll {result.iterations}/{max_iterations} - "
                f"{previous.get('card_count', 0)} -> {current.get('card_count', 0)} records"
            )
            result.events.append(("info", message))
            await _emit_event(on_event, "info", message)
            await _append_html_fragment(page, result, surface=surface)
            weak_progress_streak = 0
            if _is_marginal_card_gain(
                card_gain=card_gain,
                best_gain=best_card_gain,
                current_count=int(current.get("card_count", 0)),
            ):
                marginal_gain_streak += 1
            else:
                marginal_gain_streak = 0
        else:
            weak_progress_streak += 1
            marginal_gain_streak = 0
        previous = current
        if marginal_gain_streak > int(crawler_runtime_settings.traversal_weak_progress_streak_max):
            _set_stop_reason(result, "marginal_scroll_gain", surface=surface)
            break
        if weak_progress_streak > int(crawler_runtime_settings.traversal_weak_progress_streak_max):
            _set_stop_reason(result, "no_scroll_progress", surface=surface)
            break
    else:
        _set_stop_reason(result, "scroll_limit_reached", surface=surface)
    result.card_count = previous["card_count"]


async def _run_load_more_traversal(
    page,
    *,
    surface: str,
    max_clicks: int,
    result: TraversalResult,
    deadline_at: float | None,
    on_event,
) -> None:
    max_iterations = min(
        max(1, int(max_clicks)),
        int(crawler_runtime_settings.traversal_max_iterations_cap),
    )
    best_card_gain = 0
    marginal_gain_streak = 0
    await _append_html_fragment(page, result, surface=surface)
    previous = await _page_snapshot(page, surface=surface)
    await _emit_event(
        on_event,
        "info",
        "Detected listing layout, pagination: load_more",
    )
    for _ in range(max_iterations):
        if _deadline_reached(deadline_at):
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        locator = await _find_actionable_locator(page, "load_more")
        if locator is None:
            _set_stop_reason(result, "load_more_not_found", surface=surface)
            break
        result.iterations += 1
        result.load_more_clicks += 1
        current_url = page.url
        clicked = await _click_with_retry(
            page,
            locator,
            result=result,
            deadline_at=deadline_at,
        )
        if not clicked:
            _set_stop_reason(result, "load_more_click_failed", surface=surface)
            break
        wait_ms = _remaining_timeout_ms(
            deadline_at,
            int(crawler_runtime_settings.load_more_wait_min_ms),
        )
        if wait_ms <= 0:
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        await _wait_for_transition(
            page,
            previous_url=current_url,
            deadline_at=deadline_at,
            timeout_ms=wait_ms,
        )
        current = await _page_snapshot(page, surface=surface)
        card_gain = max(
            0,
            int(current.get("card_count", 0)) - int(previous.get("card_count", 0)),
        )
        if card_gain > 0:
            best_card_gain = max(best_card_gain, card_gain)
        if _snapshot_progressed(previous, current):
            result.progress_events += 1
            message = (
                f"Load more {result.iterations}/{max_iterations} - "
                f"{previous.get('card_count', 0)} -> {current.get('card_count', 0)} records"
            )
            result.events.append(("info", message))
            await _emit_event(on_event, "info", message)
            await _append_html_fragment(page, result, surface=surface)
            if _is_marginal_card_gain(
                card_gain=card_gain,
                best_gain=best_card_gain,
                current_count=int(current.get("card_count", 0)),
            ):
                marginal_gain_streak += 1
            else:
                marginal_gain_streak = 0
                previous = current
                continue
            if marginal_gain_streak > int(crawler_runtime_settings.traversal_weak_progress_streak_max):
                _set_stop_reason(result, "marginal_load_more_gain", surface=surface)
                previous = current
                break
            previous = current
            continue
        _set_stop_reason(result, "load_more_no_progress", surface=surface)
        previous = current
        break
    else:
        _set_stop_reason(result, "load_more_limit_reached", surface=surface)
    result.card_count = previous["card_count"]


async def _run_paginate_traversal(
    page,
    *,
    surface: str,
    max_pages: int,
    result: TraversalResult,
    deadline_at: float | None,
    on_event,
) -> None:
    previous = await _page_snapshot(page, surface=surface)
    best_card_gain = 0
    marginal_gain_streak = 0
    result.card_count = previous["card_count"]
    await _append_html_fragment(page, result, surface=surface)
    await _emit_event(
        on_event,
        "info",
        "Detected listing layout, pagination: paginate",
    )
    page_limit = max(1, int(max_pages))
    visited_urls: set[str] = {page.url}
    for _ in range(max(0, page_limit - 1)):
        if _deadline_reached(deadline_at):
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        locator = await _find_actionable_locator(page, "next_page")
        if locator is None:
            _set_stop_reason(result, "next_page_not_found", surface=surface)
            break
        result.iterations += 1
        current_url = page.url
        intended_url: str | None = None
        href = await locator.get_attribute("href")
        normalized_href = str(href or "").strip().lower()
        if href and not normalized_href.startswith(("#", "javascript:")):
            next_url = urljoin(current_url, href)
            if not _is_same_origin(current_url, next_url):
                _set_stop_reason(result, "paginate_off_domain", surface=surface)
                break
            if next_url in visited_urls:
                _set_stop_reason(result, "paginate_cycle_detected", surface=surface)
                break
            intended_url = next_url
            goto_timeout_ms = _remaining_timeout_ms(
                deadline_at,
                int(crawler_runtime_settings.pagination_navigation_timeout_ms),
                min_ms=5000,
            )
            if goto_timeout_ms <= 0:
                _set_stop_reason(result, "budget_exceeded", surface=surface)
                break
            await page.goto(
                next_url,
                wait_until="domcontentloaded",
                timeout=goto_timeout_ms,
            )
            await _wait_for_transition(
                page,
                previous_url=current_url,
                navigation_expected=True,
                deadline_at=deadline_at,
            )
        else:
            clicked = await _click_with_retry(
                page,
                locator,
                result=result,
                deadline_at=deadline_at,
            )
            if not clicked:
                _set_stop_reason(result, "paginate_click_failed", surface=surface)
                break
            await _wait_for_transition(
                page,
                previous_url=current_url,
                deadline_at=deadline_at,
                timeout_ms=int(crawler_runtime_settings.traversal_settle_networkidle_timeout_ms),
            )
        if await _page_matches_block_challenge(page):
            _set_stop_reason(result, "paginate_blocked", surface=surface)
            break
        resolved_url = page.url
        # Cycle detection: if the resolved URL is already visited, we've looped.
        # For href-based nav: a server redirect may send us back to a visited URL
        # (resolved_url != intended_url signals the redirect happened).
        # For click-based nav: only flag if the URL actually changed to a visited one
        # (SPAs often keep the same URL, which is not a cycle).
        if resolved_url in visited_urls:
            if intended_url is not None and resolved_url != intended_url:
                _set_stop_reason(result, "paginate_cycle_detected", surface=surface)
                break
            if intended_url is None and resolved_url != current_url:
                _set_stop_reason(result, "paginate_cycle_detected", surface=surface)
                break
        visited_urls.add(resolved_url)
        current = await _page_snapshot(page, surface=surface)
        card_gain = max(
            0,
            int(current.get("card_count", 0)) - int(previous.get("card_count", 0)),
        )
        if card_gain > 0:
            best_card_gain = max(best_card_gain, card_gain)
        if _paginate_snapshot_progressed(previous, current):
            await _append_html_fragment(page, result, surface=surface)
            result.progress_events += 1
            message = (
                f"Page {result.iterations + 1}/{page_limit} - "
                f"{previous.get('card_count', 0)} -> {current.get('card_count', 0)} records"
            )
            result.events.append(("info", message))
            await _emit_event(on_event, "info", message)
            result.pages_advanced += 1
            if _is_marginal_card_gain(
                card_gain=card_gain,
                best_gain=best_card_gain,
                current_count=int(current.get("card_count", 0)),
            ):
                marginal_gain_streak += 1
            else:
                marginal_gain_streak = 0
            previous = current
            if marginal_gain_streak > int(crawler_runtime_settings.traversal_weak_progress_streak_max):
                _set_stop_reason(result, "marginal_paginate_gain", surface=surface)
                break
            continue
        _set_stop_reason(result, "paginate_no_progress", surface=surface)
        break
    else:
        _set_stop_reason(result, "paginate_limit_reached", surface=surface)
    result.card_count = previous["card_count"]


async def _find_actionable_locator(page, selector_group: str):
    selectors = PAGINATION_SELECTORS.get(selector_group) if isinstance(PAGINATION_SELECTORS, dict) else []
    for selector in list(selectors or []):
        locator = page.locator(str(selector)).first
        try:
            if await locator.count() == 0:
                continue
            if not await locator.is_visible(timeout=250):
                continue
            if await locator.is_disabled():
                continue
            return locator
        except Exception:
            logger.debug(
                "Traversal locator check failed for selector_group=%s selector=%s",
                selector_group,
                selector,
                exc_info=True,
            )
            continue
    if selector_group == "next_page":
        generic_locator = await _find_generic_next_page_locator(page)
        if generic_locator is not None:
            return generic_locator
        return await _find_aom_actionable_locator(
            page,
            selector_group=selector_group,
            name_pattern=r"(next|older|›|»|>)",
        )
    if selector_group == "load_more":
        return await _find_aom_actionable_locator(
            page,
            selector_group=selector_group,
            name_pattern=r"(load more|show more|see more|view more)",
        )
    return None


async def _find_generic_next_page_locator(page):
    for selector in (
        "a[rel='next']",
        "link[rel='next']",
        ".pagination-next a",
        ".pagination-next",
        ".pagination-container a[rel='next']",
        ".pagination-container a[href*='?p=']",
        ".pagination-container a[href*='&p=']",
    ):
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0:
                continue
            if selector == "link[rel='next']":
                continue
            if not await locator.is_visible(timeout=250):
                continue
            if await locator.is_disabled():
                continue
            logger.info("Traversal generic next-page selector=%s url=%s", selector, page.url)
            return locator
        except Exception:
            logger.debug(
                "Traversal generic next-page lookup failed selector=%s url=%s",
                selector,
                page.url,
                exc_info=True,
            )
            continue
    return None


async def recover_listing_page_content(
    page,
    *,
    on_event=None,
) -> dict[str, object]:
    diagnostics: dict[str, object] = {
        "status": "attempted",
        "limit": int(crawler_runtime_settings.listing_recovery_max_actions),
    }
    clicked_count = 0
    actions_taken: list[str] = []
    max_actions = max(0, int(crawler_runtime_settings.listing_recovery_max_actions))
    if max_actions == 0:
        diagnostics["clicked_count"] = clicked_count
        diagnostics["actions_taken"] = actions_taken
        diagnostics["status"] = "disabled"
        return diagnostics

    helper_result = TraversalResult(requested_mode="recovery")
    wait_ms = max(0, int(crawler_runtime_settings.listing_recovery_post_action_wait_ms))
    for action_name, pattern, message in _LISTING_RECOVERY_ACTIONS:
        if clicked_count >= max_actions:
            diagnostics["status"] = "interaction_limit_reached"
            break
        locator = (
            await _find_actionable_locator(page, "next_page")
            if action_name == "next_page"
            else await _find_aom_actionable_locator(
                page,
                selector_group=action_name,
                name_pattern=pattern,
            )
        )
        if locator is None:
            continue
        await _emit_event(on_event, "info", f"{message}...")
        if not await _click_with_retry(page, locator, result=helper_result):
            continue
        clicked_count += 1
        actions_taken.append(action_name)
        if wait_ms > 0:
            await page.wait_for_timeout(wait_ms)
        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=int(
                    crawler_runtime_settings.traversal_settle_networkidle_timeout_ms
                ),
            )
        except Exception:
            logger.debug(
                "Listing recovery networkidle wait timed out for action=%s url=%s",
                action_name,
                getattr(page, "url", ""),
                exc_info=True,
            )
    if diagnostics["status"] == "attempted":
        diagnostics["status"] = (
            "recovered"
            if clicked_count > 0
            else "no_actionable_elements"
        )
    diagnostics["clicked_count"] = clicked_count
    diagnostics["actions_taken"] = actions_taken
    diagnostics["click_retries"] = helper_result.click_retries
    return diagnostics


async def _find_aom_actionable_locator(
    page,
    *,
    selector_group: str,
    name_pattern: str,
):
    compiled = re.compile(name_pattern, re.IGNORECASE)
    for role in ("button", "link"):
        locator = page.get_by_role(role, name=compiled)
        try:
            count = min(await locator.count(), 10)
        except Exception:
            logger.debug(
                "Traversal AOM locator count failed selector_group=%s role=%s url=%s",
                selector_group,
                role,
                page.url,
                exc_info=True,
            )
            continue
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if not await candidate.is_visible(timeout=250):
                    continue
                if await candidate.is_disabled():
                    continue
                logger.info(
                    "Traversal AOM fallback selector_group=%s role=%s index=%s url=%s",
                    selector_group,
                    role,
                    index,
                    page.url,
                )
                return candidate
            except Exception:
                logger.debug(
                    "Traversal AOM candidate probe failed selector_group=%s role=%s index=%s url=%s",
                    selector_group,
                    role,
                    index,
                    page.url,
                    exc_info=True,
                )
                continue
    return None



async def _click_with_retry(
    page,
    locator,
    *,
    result: TraversalResult,
    deadline_at: float | None = None,
) -> bool:
    """Attempt to click a locator with progressive fallbacks.

    Strategy:
    1. Scroll element to viewport center to escape sticky headers/footers.
    2. Normal click with configurable timeout.
    3. On interception/timeout: dismiss overlays and retry with force=True.
    4. Final fallback: JavaScript node.click().
    """
    click_timeout_ms = _remaining_timeout_ms(
        deadline_at,
        int(crawler_runtime_settings.traversal_click_timeout_ms),
    )
    if click_timeout_ms <= 0:
        return False
    # Step 1: Scroll element to center viewport to avoid sticky header overlap
    try:
        await locator.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        logger.debug("Traversal scroll_into_view failed", exc_info=True)
        if not await _locator_still_resolves(locator):
            return False
    try:
        await locator.evaluate(
            """(node) => {
                if (node instanceof Element) {
                    node.scrollIntoView({ block: 'center', behavior: 'instant' });
                }
            }"""
        )
    except Exception:
        logger.debug(
            "Traversal center-scroll evaluate failed url=%s",
            page.url,
            exc_info=True,
        )
        if not await _locator_still_resolves(locator):
            return False

    # Step 2: Normal click
    first_exc = None
    try:
        await locator.click(timeout=click_timeout_ms)
        return True
    except Exception as exc:
        first_exc = exc
        if not await _locator_still_resolves(locator):
            return False
        logger.debug(
            "Traversal normal click failed (%s); trying overlay dismissal + force",
            type(exc).__name__,
        )
        result.click_retries += 1

    # Step 3: Dismiss overlays then force-click (overlays are restored after)
    await dismiss_overlays_if_needed(page, locator=locator, result=result)
    force_exc = None
    try:
        await locator.click(timeout=click_timeout_ms, force=True)
        await _restore_overlays(page)
        return True
    except Exception as exc:
        force_exc = exc
        if not await _locator_still_resolves(locator):
            return False
        logger.debug(
            "Traversal force click failed (%s); trying JS click",
            type(exc).__name__,
        )
        result.click_retries += 1
    await _restore_overlays(page)

    # Step 4: JavaScript fallback
    try:
        await locator.evaluate(
            "(node) => node instanceof HTMLElement && node.click()"
        )
        await wait_for_dom_mutation_settle(
            page,
            quiet_window_ms=min(500, max(100, click_timeout_ms // 5)),
            timeout_ms=min(2000, click_timeout_ms),
        )
        return True
    except Exception as js_exc:
        logger.warning(
            "Traversal all click strategies failed: normal=%s force=%s js=%s",
            type(first_exc).__name__,
            type(force_exc).__name__,
            type(js_exc).__name__,
        )
        return False


async def _locator_still_resolves(locator) -> bool:
    counter = getattr(locator, "count", None)
    if not callable(counter):
        return True
    for attempt in range(2):
        try:
            if bool(await counter()):
                return True
        except Exception:
            pass
        if attempt == 0:
            await asyncio.sleep(0)
    return False


async def dismiss_overlays_if_needed(
    page,
    *,
    locator,
    result: TraversalResult,
) -> None:
    """Temporarily hide intercepting overlays and dismiss cookie banners.

    Only elements that actually sit above the click target are muted. This
    avoids the previous broad mutation of structural tags like `header` /
    `nav`, which can interfere with delegated SPA event handling.
    """
    dismissed_any = False
    try:
        muted_count = await locator.evaluate(
            """
            (target) => {
                if (!(target instanceof Element)) {
                    return 0;
                }
                const rect = target.getBoundingClientRect();
                if (!rect.width || !rect.height) {
                    return 0;
                }
                const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
                const cx = clamp(rect.left + (rect.width / 2), 1, Math.max(1, window.innerWidth - 1));
                const cy = clamp(rect.top + Math.min(rect.height / 2, 24), 1, Math.max(1, window.innerHeight - 1));
                const hints = ['cookie', 'consent', 'modal', 'overlay', 'dialog', 'popup', 'banner', 'interstitial', 'backdrop'];
                let muted = 0;
                for (const node of document.elementsFromPoint(cx, cy)) {
                    if (!(node instanceof Element)) {
                        continue;
                    }
                    if (node === target || node.contains(target)) {
                        break;
                    }
                    const style = window.getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    const zIndex = Number.parseInt(style.zIndex || '0', 10);
                    const signature = [
                        node.id || '',
                        node.className || '',
                        node.getAttribute('role') || '',
                        node.getAttribute('aria-label') || '',
                        node.getAttribute('aria-modal') || '',
                    ].join(' ').toLowerCase();
                    const overlayLike =
                        node.getAttribute('aria-modal') === 'true' ||
                        style.position === 'fixed' ||
                        style.position === 'sticky' ||
                        zIndex >= 100 ||
                        hints.some((hint) => signature.includes(hint));
                    const coversPoint =
                        rect.width > 0 &&
                        rect.height > 0 &&
                        cx >= rect.left &&
                        cx <= rect.right &&
                        cy >= rect.top &&
                        cy <= rect.bottom;
                    if (!overlayLike || !coversPoint) {
                        continue;
                    }
                    node.setAttribute('data-crawlwise-orig-pointer-events', node.style.pointerEvents || '');
                    node.setAttribute('data-crawlwise-orig-z-index', node.style.zIndex || '');
                    node.style.setProperty('pointer-events', 'none', 'important');
                    node.style.setProperty('z-index', '-1', 'important');
                    muted += 1;
                }
                return muted;
            }
            """
        )
        dismissed_any = int(muted_count or 0) > 0
    except Exception:
        logger.debug("Traversal overlay dismissal JS failed", exc_info=True)
    # Dismiss cookie consent banners
    from app.services.config.selectors import COOKIE_CONSENT_SELECTORS
    consent_selectors = (
        list(COOKIE_CONSENT_SELECTORS)
        if isinstance(COOKIE_CONSENT_SELECTORS, (list, tuple))
        else []
    )
    for selector in consent_selectors[:5]:
        try:
            btn = page.locator(str(selector)).first
            if await btn.count() > 0 and await btn.is_visible(timeout=200):
                await btn.click(timeout=1000, force=True)
                await wait_for_dom_mutation_settle(
                    page,
                    quiet_window_ms=150,
                    timeout_ms=750,
                )
                dismissed_any = True
                logger.info("Traversal dismissed cookie consent via %s", selector)
                break
        except Exception:
            logger.debug(
                "Traversal cookie consent dismissal probe failed selector=%s url=%s",
                selector,
                page.url,
                exc_info=True,
            )
            continue
    if dismissed_any:
        result.overlays_dismissed = True


async def _restore_overlays(page) -> None:
    """Restore overlay elements to their original inline styles after a click."""
    try:
        await page.evaluate(
            """
            () => {
                const all = document.querySelectorAll('[data-crawlwise-orig-pointer-events], [data-crawlwise-orig-z-index]');
                for (const node of all) {
                    try {
                        const origPE = node.getAttribute('data-crawlwise-orig-pointer-events');
                        const origZI = node.getAttribute('data-crawlwise-orig-z-index');
                        if (origPE !== undefined) {
                            if (origPE === '') {
                                node.style.removeProperty('pointer-events');
                            } else {
                                node.style.pointerEvents = origPE;
                            }
                            node.removeAttribute('data-crawlwise-orig-pointer-events');
                        }
                        if (origZI !== undefined) {
                            if (origZI === '') {
                                node.style.removeProperty('z-index');
                            } else {
                                node.style.zIndex = origZI;
                            }
                            node.removeAttribute('data-crawlwise-orig-z-index');
                        }
                    } catch (e) {
                        continue;
                    }
                }
            }
            """
        )
    except Exception:
        logger.debug("Traversal overlay restore JS failed", exc_info=True)


async def _append_html_fragment(
    page,
    result: TraversalResult,
    *,
    surface: str,
) -> None:
    html = await get_page_html(page)
    if not html:
        return
    fragment = _bounded_traversal_fragment_html(
        html,
        surface=surface,
        seen_cards=result._seen_card_fragments,
        seen_structured=result._seen_structured_fragments,
    )
    is_fallback = not fragment
    value = html if is_fallback else fragment
    # Dedup: compare against the last fragment of the same type
    for prev_value, prev_is_fallback in reversed(result.html_fragments):
        if prev_is_fallback == is_fallback:
            if prev_value == value:
                return
            break
    result.html_fragments.append((value, is_fallback))


async def _looks_like_paginate_control(locator) -> bool:
    href = ""
    try:
        href = str(await locator.get_attribute("href") or "").strip().lower()
    except Exception:
        logger.debug("Traversal next_page href inspection failed", exc_info=True)
    if href and not href.startswith(("#", "javascript:")):
        return True
    try:
        inspection = await locator.evaluate(
            """
            (node) => {
              if (!(node instanceof Element)) {
                return {};
              }
              const rawHref = String(node.getAttribute('href') || '').trim().toLowerCase();
              const label = [
                node.getAttribute('aria-label'),
                node.getAttribute('title'),
                node.textContent,
              ]
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim()
                .toLowerCase();
              const container = node.closest(
                "[aria-label*='pagination' i], [data-testid*='pagination' i], [class*='pagination' i], nav, [role='navigation']"
              );
              const containerText = String(container?.textContent || '')
                .replace(/\\s+/g, ' ')
                .trim()
                .toLowerCase();
              const datasetKeys = Object.keys(node.dataset || {});
              return {
                raw_href: rawHref,
                has_click_handler:
                  typeof node.onclick === 'function' ||
                  node.hasAttribute('onclick') ||
                  datasetKeys.some((key) => /(page|paginate|next|cursor)/i.test(key)),
                pagination_container: Boolean(container),
                pagination_text:
                  /\\b(next|previous|prev|page|older|newer)\\b/.test(label) ||
                  /\\b(next|previous|prev|page|older|newer)\\b/.test(containerText),
                sibling_page_numbers: /(?:^|\\s)\\d+(?:\\s|$)/.test(containerText),
                is_button_like:
                  String(node.tagName || '').toLowerCase() === 'button' ||
                  String(node.getAttribute('role') || '').trim().toLowerCase() === 'button',
              };
            }
            """
        )
    except Exception:
        logger.debug("Traversal next_page control inspection failed", exc_info=True)
        return False
    if not isinstance(inspection, dict):
        return False
    if bool(inspection.get("pagination_container")) and (
        bool(inspection.get("has_click_handler"))
        or bool(inspection.get("is_button_like"))
    ):
        return True
    if bool(inspection.get("pagination_text")) and (
        bool(inspection.get("has_click_handler"))
        or bool(inspection.get("sibling_page_numbers"))
        or bool(inspection.get("is_button_like"))
    ):
        return True
    return False


async def _looks_like_next_page_control(locator) -> bool:
    try:
        inspection = await locator.evaluate(
            """
            (node) => {
              if (!(node instanceof Element)) {
                return {};
              }
              const text = [
                node.textContent,
                node.getAttribute('aria-label'),
                node.getAttribute('title'),
                node.getAttribute('rel'),
                node.className,
              ]
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim()
                .toLowerCase();
              const disabled =
                node.hasAttribute('disabled') ||
                node.getAttribute('aria-disabled') === 'true' ||
                /disabled/.test(String(node.className || '').toLowerCase());
              return { text, disabled };
            }
            """
        )
    except Exception:
        return False
    if not isinstance(inspection, dict):
        return False
    if bool(inspection.get("disabled")):
        return False
    text = str(inspection.get("text") or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in ("next", "older", "more", "›", "»"))


async def _page_matches_block_challenge(page) -> bool:
    html = await get_page_html(page)
    if not html:
        return False
    classification = await classify_blocked_page_async(html, 200)
    return bool(classification.blocked)


def _bounded_traversal_fragment_html(
    html: str,
    *,
    surface: str,
    seen_cards: set[str],
    seen_structured: set[str],
) -> str:
    parser = LexborHTMLParser(html)
    max_bytes = max(8_192, int(crawler_runtime_settings.traversal_fragment_max_bytes))
    script_budget = max_bytes // 3
    structured_fragments = _collect_structured_script_fragments(
        parser,
        seen=seen_structured,
        byte_budget=script_budget,
    )
    card_budget = max_bytes - _fragments_bytes(structured_fragments)
    card_fragments = _collect_listing_card_fragments(
        parser,
        surface=surface,
        seen=seen_cards,
        byte_budget=card_budget,
    )
    if not card_fragments and not structured_fragments:
        return ""
    parts: list[str] = []
    if structured_fragments:
        parts.append('<div data-traversal-structured="true">')
        parts.extend(structured_fragments)
        parts.append("</div>")
    if card_fragments:
        parts.append('<div data-traversal-cards="true">')
        parts.extend(card_fragments)
        parts.append("</div>")
    return "\n".join(parts)


def _collect_structured_script_fragments(
    parser: LexborHTMLParser,
    *,
    seen: set[str],
    byte_budget: int,
) -> list[str]:
    if byte_budget <= 0:
        return []
    fragments: list[str] = []
    used_bytes = 0
    for node in parser.css("script"):
        attrs = getattr(node, "attributes", {}) or {}
        script_id = str(attrs.get("id") or "").strip().lower()
        script_type = str(attrs.get("type") or "").strip().lower()
        text = str(node.text(strip=True) or "")
        if not text:
            continue
        if not (
            script_type in _STRUCTURED_SCRIPT_TYPES
            or script_id in _STRUCTURED_SCRIPT_IDS
            or any(marker in text.lower() for marker in _STRUCTURED_SCRIPT_TEXT_MARKERS)
        ):
            continue
        fragment = str(node.html or "").strip()
        if not fragment or fragment in seen:
            continue
        fragment_bytes = len(fragment.encode("utf-8"))
        if used_bytes + fragment_bytes > byte_budget:
            continue
        seen.add(fragment)
        fragments.append(fragment)
        used_bytes += fragment_bytes
    return fragments


def _collect_listing_card_fragments(
    parser: LexborHTMLParser,
    *,
    surface: str,
    seen: set[str],
    byte_budget: int,
) -> list[str]:
    if byte_budget <= 0:
        return []
    selector_group = (
        "jobs" if str(surface or "").strip().lower().startswith("job_") else "ecommerce"
    )
    fragments = _collect_unique_node_html(
        parser,
        selectors=list(CARD_SELECTORS.get(selector_group) or []),
        seen=seen,
        byte_budget=byte_budget,
    )
    if fragments:
        return fragments
    return _collect_anchor_container_fragments(
        parser,
        seen=seen,
        byte_budget=byte_budget,
    )


def _collect_unique_node_html(
    parser: LexborHTMLParser,
    *,
    selectors: list[str],
    seen: set[str],
    byte_budget: int,
) -> list[str]:
    fragments: list[str] = []
    used_bytes = 0
    for selector in selectors:
        try:
            matches = parser.css(selector)
        except Exception:
            matches = []
        for node in matches:
            fragment = str(node.html or "").strip()
            if not fragment or fragment in seen:
                continue
            fragment_bytes = len(fragment.encode("utf-8"))
            if used_bytes + fragment_bytes > byte_budget:
                continue
            seen.add(fragment)
            fragments.append(fragment)
            used_bytes += fragment_bytes
    return fragments


def _collect_anchor_container_fragments(
    parser: LexborHTMLParser,
    *,
    seen: set[str],
    byte_budget: int,
) -> list[str]:
    scored_fragments: list[tuple[int, str]] = []
    used_bytes = 0
    for node in parser.css(LISTING_FALLBACK_CONTAINER_SELECTOR):
        score = _listing_fragment_score(node)
        if score <= 0:
            continue
        fragment = str(node.html or "").strip()
        if not fragment or fragment in seen:
            continue
        scored_fragments.append((score, fragment))
    scored_fragments.sort(key=lambda row: (-row[0], len(row[1])))
    fragments: list[str] = []
    for _score, fragment in scored_fragments:
        fragment_bytes = len(fragment.encode("utf-8"))
        if used_bytes + fragment_bytes > byte_budget:
            continue
        seen.add(fragment)
        fragments.append(fragment)
        used_bytes += fragment_bytes
    return fragments


def _listing_fragment_score(node) -> int:
    tag_name = str(getattr(node, "tag", "") or "").strip().lower()
    if tag_name in {"header", "nav", "footer"}:
        return -100
    attrs = getattr(node, "attributes", {}) or {}
    signature = " ".join(
        [
            str(attrs.get("class") or ""),
            str(attrs.get("id") or ""),
            str(attrs.get("role") or ""),
            str(attrs.get("aria-label") or ""),
        ]
    ).lower()
    if any(token in signature for token in LISTING_STRUCTURE_NEGATIVE_HINTS):
        return -10
    score = 0
    if any(token in signature for token in LISTING_STRUCTURE_POSITIVE_HINTS):
        score += 6
    try:
        link_count = len(node.css("a[href]"))
    except Exception:
        return -100
    if link_count == 0:
        return -100
    if link_count == 1:
        score += 4
    elif link_count <= 6:
        score += 2
    elif link_count <= 12:
        score -= 1
    else:
        score -= 6
    text = str(node.text(strip=True) or "").strip()
    text_len = len(text)
    if text_len < 12:
        score -= 3
    elif text_len <= 2000:
        score += 3
    else:
        score -= 3
    if _PRICE_HINT_RE.search(text):
        score += 3
    if tag_name in {"article", "li", "tr", "section"}:
        score += 2
    return score


def _fragments_bytes(fragments: list[str]) -> int:
    return sum(len(fragment.encode("utf-8")) for fragment in fragments if fragment)


async def _page_snapshot(page, *, surface: str) -> dict[str, int]:
    snapshot = await page.evaluate(
        """
        () => {
          const root = document.scrollingElement || document.documentElement || document.body;
          const normalize = (text, limit) =>
            String(text || '')
              .replace(/\\s+/g, ' ')
              .trim()
              .slice(0, limit);
          const visibleText = normalize(document.body?.innerText || '', 1600);
          const anchorSummary = Array.from(
            document.querySelectorAll('main a[href], article a[href], li a[href], tr a[href], section a[href], [role=\"row\"] a[href]')
          )
            .slice(0, 24)
            .map((node) =>
              `${normalize(node.getAttribute('href'), 140)}|${normalize(node.textContent, 80)}`
            )
            .join('||');
          const overflowContainers = Array.from(document.querySelectorAll('*')).filter((node) => {
            const style = window.getComputedStyle(node);
            return ['auto', 'scroll'].includes(style.overflowY) && node.scrollHeight - node.clientHeight > 150;
          }).length;
          return {
            scroll_height: Number(root?.scrollHeight || 0),
            client_height: Number(root?.clientHeight || window.innerHeight || 0),
            overflow_containers: overflowContainers,
            content_signature_source: `${location.href}::${visibleText}::${anchorSummary}`,
          };
        }
        """
    )
    if not isinstance(snapshot, dict):
        snapshot = {}
    return {
        "card_count": await _card_count(page, surface=surface),
        "content_signature": _content_signature(snapshot.pop("content_signature_source", "")),
        **snapshot,
    }


async def count_listing_cards(page, *, surface: str, allow_heuristic: bool = True) -> int:
    selector_group = "jobs" if str(surface or "").strip().lower().startswith("job_") else "ecommerce"
    selectors = CARD_SELECTORS.get(selector_group) if isinstance(CARD_SELECTORS, dict) else []
    normalized_selectors = [
        str(selector).strip() for selector in list(selectors or []) if str(selector).strip()
    ]
    if not normalized_selectors:
        return await _heuristic_card_count(page) if allow_heuristic else 0
    try:
        count = await page.evaluate(
            """
            (selectors) => {
              let highest = 0;
              for (const selector of selectors) {
                try {
                  highest = Math.max(highest, document.querySelectorAll(selector).length);
                } catch (error) {
                  continue;
                }
              }
              return highest;
            }
            """,
            normalized_selectors,
        )
    except _PlaywrightError:
        raise
    except Exception:
        logger.debug(
            "Traversal card counting via evaluate failed for surface=%s; falling back to locator counts",
            surface,
            exc_info=True,
        )
        highest = 0
        for selector in normalized_selectors:
            try:
                highest = max(highest, await page.locator(selector).count())
            except _PlaywrightError:
                raise
            except Exception:
                logger.debug(
                    "Traversal locator fallback failed for surface=%s selector=%s",
                    surface,
                    selector,
                    exc_info=True,
                )
                continue
        return highest
    try:
        resolved = max(0, int(count or 0))
    except (TypeError, ValueError):
        resolved = 0
    if resolved > 0:
        return resolved
    if allow_heuristic:
        return await _heuristic_card_count(page, surface=surface)
    return 0


async def _card_count(page, *, surface: str) -> int:
    return await count_listing_cards(page, surface=surface)


async def _heuristic_card_count(page, *, surface: str) -> int:
    html = await get_page_html(page)
    if not html:
        return 0
    parser = LexborHTMLParser(html)
    seen: set[str] = set()
    count = 0
    try:
        nodes = parser.css(LISTING_FALLBACK_CONTAINER_SELECTOR)
    except Exception:
        return 0
    for node in nodes:
        fragment = str(node.html or "").strip()
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        if _listing_fragment_score(node) <= 0:
            continue
        if _node_supports_listing_heuristic(node, surface=surface):
            if _node_contains_nested_listing_candidates(node, surface=surface):
                continue
            count += 1
    return count


def _node_supports_listing_heuristic(node, *, surface: str) -> bool:
    signature = _listing_node_signature(node)
    has_positive_signature = any(
        token in signature for token in LISTING_STRUCTURE_POSITIVE_HINTS
    )
    has_price = _node_text_has_price(node)
    has_detail_link = _node_has_detail_like_link(node, surface=surface)
    has_media = _node_has_listing_media(node)
    if has_detail_link:
        return True
    if has_price and (has_positive_signature or has_media):
        return True
    return has_positive_signature and has_media


def _node_contains_nested_listing_candidates(node, *, surface: str) -> bool:
    node_fragment = str(node.html or "").strip()
    try:
        descendants = node.css(LISTING_FALLBACK_CONTAINER_SELECTOR)
    except Exception:
        return False
    for descendant in descendants:
        if str(descendant.html or "").strip() == node_fragment:
            continue
        if _listing_fragment_score(descendant) <= 0:
            continue
        if _node_supports_listing_heuristic(descendant, surface=surface):
            return True
    return False


def _listing_node_signature(node) -> str:
    attrs = getattr(node, "attributes", {}) or {}
    return " ".join(
        [
            str(attrs.get("class") or ""),
            str(attrs.get("id") or ""),
            str(attrs.get("role") or ""),
            str(attrs.get("aria-label") or ""),
        ]
    ).lower()


def _node_text_has_price(node) -> bool:
    return bool(_PRICE_HINT_RE.search(str(node.text(strip=True) or "").strip()))


def _node_has_listing_media(node) -> bool:
    try:
        return bool(node.css("img, picture img, picture source"))
    except Exception:
        return False


def _node_has_detail_like_link(node, *, surface: str) -> bool:
    href_tokens = (
        ("/job/", "/jobs/", "/viewjob", "showjob=", "/careers/")
        if str(surface or "").strip().lower().startswith("job_")
        else ("/products/", "/product/", "/p/", "/dp/", "/item/")
    )
    try:
        anchors = node.css("a[href]")
    except Exception:
        return False
    for anchor in anchors[:6]:
        attrs = getattr(anchor, "attributes", {}) or {}
        href = str(attrs.get("href") or "").strip().lower()
        if not href or href.startswith(("#", "javascript:")):
            continue
        if any(token in href for token in href_tokens):
            return True
    return False


def _snapshot_progressed(previous: dict[str, int], current: dict[str, int]) -> bool:
    if int(current.get("card_count", 0)) > int(previous.get("card_count", 0)):
        return True
    if str(current.get("content_signature") or "") != str(
        previous.get("content_signature") or ""
    ):
        return True
    if int(current.get("scroll_height", 0)) >= int(previous.get("scroll_height", 0)) + int(
        crawler_runtime_settings.traversal_force_probe_min_advance_px
    ):
        return True
    return False


def _paginate_snapshot_progressed(previous: dict[str, int], current: dict[str, int]) -> bool:
    previous_count = int(previous.get("card_count", 0))
    current_count = int(current.get("card_count", 0))
    if current_count > previous_count:
        return True
    if previous_count <= 0 and current_count <= 0:
        return False
    return _snapshot_progressed(previous, current)


def _is_marginal_card_gain(*, card_gain: int, best_gain: int, current_count: int) -> bool:
    if card_gain <= 0:
        return False
    if current_count < max(6, int(crawler_runtime_settings.listing_min_items) * 3):
        return False
    if best_gain < max(2, int(crawler_runtime_settings.listing_min_items) * 2):
        return False
    return card_gain <= max(1, best_gain // 5)


def _content_signature(html: str) -> str:
    text = str(html or "").strip()
    if not text:
        return ""
    return hashlib.sha1(
        text.encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()


async def _has_scroll_signals(page, *, surface: str) -> bool:
    snapshot = await _page_snapshot(page, surface=surface)
    scroll_height = int(snapshot.get("scroll_height", 0))
    client_height = max(1, int(snapshot.get("client_height", 0)))
    overflow_containers = int(snapshot.get("overflow_containers", 0))
    if overflow_containers >= 1:
        return True
    return scroll_height >= (
        client_height * int(crawler_runtime_settings.infinite_scroll_tall_page_ratio)
    )


async def _settle_after_action(
    page,
    *,
    deadline_at: float | None,
    timeout_ms: int | None = None,
) -> None:
    wait_ms = _remaining_timeout_ms(
        deadline_at,
        int(timeout_ms or crawler_runtime_settings.traversal_min_settle_wait_ms),
    )
    if wait_ms <= 0:
        return
    try:
        await page.wait_for_load_state("networkidle", timeout=min(1500, wait_ms * 2))
    except Exception:
        logger.debug(
            "Traversal networkidle settle wait failed url=%s",
            page.url,
            exc_info=True,
        )
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=min(1500, wait_ms * 2))
    except Exception:
        logger.debug(
            "Traversal domcontentloaded settle wait failed url=%s",
            page.url,
            exc_info=True,
        )
    await wait_for_dom_mutation_settle(
        page,
        quiet_window_ms=min(500, max(100, wait_ms // 4)),
        timeout_ms=wait_ms,
    )


async def _wait_for_transition(
    page,
    *,
    previous_url: str,
    navigation_expected: bool = False,
    deadline_at: float | None = None,
    timeout_ms: int | None = None,
) -> None:
    await _wait_for_navigation_if_changed(
        page,
        previous_url=previous_url,
        navigation_expected=navigation_expected,
        deadline_at=deadline_at,
    )
    await _settle_after_action(page, deadline_at=deadline_at, timeout_ms=timeout_ms)


async def _wait_for_navigation_if_changed(
    page,
    *,
    previous_url: str,
    navigation_expected: bool,
    deadline_at: float | None,
) -> None:
    if navigation_expected or page.url != previous_url:
        await _wait_for_domcontentloaded(page, deadline_at=deadline_at)
        return
    poll_ms = max(1, int(crawler_runtime_settings.pagination_post_click_poll_ms))
    timeout_ms = _remaining_timeout_ms(
        deadline_at,
        int(crawler_runtime_settings.pagination_post_click_timeout_ms),
    )
    if timeout_ms <= 0:
        return
    waited_ms = 0
    while waited_ms < timeout_ms:
        step_ms = min(poll_ms, max(1, timeout_ms - waited_ms))
        await page.wait_for_timeout(step_ms)
        waited_ms += step_ms
        if page.url != previous_url:
            await _wait_for_domcontentloaded(page, deadline_at=deadline_at)
            return


async def _wait_for_domcontentloaded(page, *, deadline_at: float | None) -> None:
    timeout_ms = _remaining_timeout_ms(
        deadline_at,
        int(crawler_runtime_settings.pagination_post_click_domcontentloaded_timeout_ms),
    )
    if timeout_ms <= 0:
        return
    try:
        await page.wait_for_load_state(
            "domcontentloaded",
            timeout=timeout_ms,
        )
    except Exception:
        logger.debug("Traversal domcontentloaded wait failed", exc_info=True)
        return


def _deadline_reached(deadline_at: float | None) -> bool:
    return deadline_at is not None and time.monotonic() >= deadline_at


def _remaining_timeout_ms(deadline_at: float | None, default_ms: int, *, min_ms: int = 500) -> int:
    if deadline_at is None:
        return max(min_ms, int(default_ms))
    remaining_ms = int((deadline_at - time.monotonic()) * 1000)
    if remaining_ms <= 0:
        return 0
    return max(min_ms, min(int(default_ms), remaining_ms))


async def _emit_event(on_event, level: str, message: str) -> None:
    if on_event is None:
        return
    try:
        await on_event(level, message)
    except Exception:
        logger.debug("Traversal event callback failed", exc_info=True)


def _is_same_origin(current_url: str, next_url: str) -> bool:
    current = urlsplit(str(current_url or ""))
    next_value = urlsplit(str(next_url or ""))
    if (
        str(current.scheme or "").lower(),
        str(current.netloc or "").lower(),
    ) != (
        str(next_value.scheme or "").lower(),
        str(next_value.netloc or "").lower(),
    ):
        return False
    current_host = _host_without_port(current.netloc)
    next_host = _host_without_port(next_value.netloc)
    if current_host != next_host:
        return False
    # Also compare the first path segment to prevent cross-tenant bleed
    # on path-based multi-tenant architectures (e.g. myworkdayjobs.com/TenantA).
    if _requires_path_tenant_boundary(current_url, next_url):
        current_first = (str(current.path or "").strip("/").split("/") + [""])[0].lower()
        next_first = (str(next_value.path or "").strip("/").split("/") + [""])[0].lower()
        if current_first and next_first and current_first != next_first:
            return False
    return True


def _host_without_port(netloc: str) -> str:
    return str(netloc or "").split(":", 1)[0].lower()


def _requires_path_tenant_boundary(current_url: str, next_url: str) -> bool:
    current_family = path_tenant_boundary_family(current_url)
    next_family = path_tenant_boundary_family(next_url)
    if not current_family or current_family != next_family:
        return False
    return (
        requires_path_tenant_boundary(current_url)
        and requires_path_tenant_boundary(next_url)
        and url_host_matches_platform_family(current_url, current_family)
        and url_host_matches_platform_family(next_url, next_family)
    )
