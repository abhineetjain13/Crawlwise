from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin
from typing import Protocol

from app.services.acquisition.policy import (
    AcquisitionPlan,
    decide_initial_auto_traversal,
    decide_post_progress_auto_traversal,
)
from app.services.config.crawl_runtime import (
    BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS,
    INFINITE_SCROLL_CONTAINER_OVERFLOW_THRESHOLD_PX,
    INFINITE_SCROLL_POSITIVE_SIGNAL_MIN,
    INFINITE_SCROLL_TALL_PAGE_RATIO,
    LISTING_MIN_ITEMS,
    LOAD_MORE_WAIT_MIN_MS,
    PAGINATION_NAVIGATION_TIMEOUT_MS,
    PAGINATION_POST_CLICK_DOMCONTENTLOADED_TIMEOUT_MS,
    PAGINATION_POST_CLICK_POLL_MS,
    PAGINATION_POST_CLICK_SETTLE_TIMEOUT_MS,
    PAGINATION_POST_CLICK_TIMEOUT_MS,
    PAGINATION_PAGE_SIZE_ANOMALY_RATIO,
    SCROLL_WAIT_MIN_MS,
    TRAVERSAL_ACTIVE_LINK_WEIGHT,
    TRAVERSAL_ACTIVE_SCROLLABLE_BONUS,
    TRAVERSAL_ACTIVE_SCROLLABLE_THRESHOLD_PX,
    TRAVERSAL_ACTIVE_TARGET_LABEL_MAX_LEN,
    TRAVERSAL_FORCE_PROBE_MIN_ADVANCE_PX,
    TRAVERSAL_MAX_ITERATIONS_CAP,
    TRAVERSAL_MIN_SETTLE_WAIT_MS,
    TRAVERSAL_WEAK_PROGRESS_STREAK_MAX,
)
from app.services.config.selectors import PAGINATION_SELECTORS
from app.services.runtime_metrics import incr
from app.services.url_safety import validate_public_target
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

logger = logging.getLogger(__name__)
PAGINATION_NEXT_SELECTORS = list(PAGINATION_SELECTORS.get("next_page", []))
LOAD_MORE_SELECTORS = list(PAGINATION_SELECTORS.get("load_more", []))
_MAX_TRAVERSAL_FRAGMENTS = 50
_MAX_TRAVERSAL_FRAGMENT_BYTES = 2_000_000
_MAX_TRAVERSAL_TOTAL_BYTES = 6_000_000


# ---------------------------------------------------------------------------
# JS snippet: extract only card outerHTML + identity keys from the live DOM.
# Returns {cards: [{html, identity}], container_signature: str}.
# ---------------------------------------------------------------------------
_JS_EXTRACT_CARDS = """
(selectors) => {
    const seen = new Set();
    const cards = [];
    for (const sel of selectors) {
        let nodes;
        try { nodes = document.querySelectorAll(sel); } catch { continue; }
        for (const node of nodes) {
            const identity =
                (node.getAttribute('href') || '').trim() ||
                (node.querySelector('a[href]')?.getAttribute('href') || '').trim() ||
                (node.getAttribute('data-id') || '').trim() ||
                (node.getAttribute('data-product-id') || '').trim() ||
                (node.getAttribute('data-job-id') || '').trim() ||
                '';
            const key = identity || node.outerHTML.slice(0, 200);
            if (seen.has(key)) continue;
            seen.add(key);
            cards.push({html: node.outerHTML, identity: identity});
        }
    }
    // Container signature for DOM-diff fallback when selectors match nothing.
    let container = document.querySelector(
        '[data-testid*="grid"], [data-test-id*="grid"], [class*="product-list"], [class*="product-grid"], ul.products, .products, .product-grid, .results, .search-results'
    );
    if (!container) {
        container = document.querySelector('main, [role="main"], [role="feed"]') || document.body;
    }
    const childCount = container ? container.children.length : 0;
    const sig = container ? (container.tagName + ':' + childCount) : '';
    return {cards, container_signature: sig};
}
"""

# JS snippet: DOM-diff fallback — returns outerHTML of new children added to
# the listing container since the last capture.  Caller passes the set of
# child signatures already seen (first 200 chars of outerHTML).
_JS_CONTAINER_DIFF = """
(knownSigs) => {
    let container = document.querySelector(
        '[data-testid*="grid"], [data-test-id*="grid"], [class*="product-list"], [class*="product-grid"], ul.products, .products, .product-grid, .results, .search-results'
    );
    if (!container) {
        container = document.querySelector('main, [role="main"], [role="feed"]') || document.body;
    }
    if (!container) return [];
    const news = [];
    for (const child of container.children) {
        const sig = child.outerHTML.slice(0, 200);
        if (knownSigs.includes(sig)) continue;
        news.push({html: child.outerHTML, sig});
    }
    return news;
}
"""

# ---------------------------------------------------------------------------
# JS snippet: detect infinite scroll signals in the live DOM.
# Returns a dict of boolean signals.
# ---------------------------------------------------------------------------
_JS_DETECT_INFINITE_SCROLL = r"""
() => {
    // 1. Sentinel / trigger elements used by infinite scroll libraries
    const sentinelSelectors = [
        '[data-infinite-scroll]', '[data-lazy-load]',
        '.infinite-scroll-component', '.infinite-scroll-sentinel',
        '.infinite-loader', '[data-infinite]',
        '.lazy-load-trigger', '.scroll-sentinel',
        '.load-on-scroll', '[data-load-more-auto]',
    ];
    let hasSentinel = false;
    for (const sel of sentinelSelectors) {
        try { if (document.querySelector(sel)) { hasSentinel = true; break; } } catch {}
    }

    // 2. Offset-based pagination params in current URL
    const currentUrl = window.location.href;
    const hasOffsetParam = /[?&](offset|start|from)=\\d/i.test(currentUrl);

    // 3. rel=next link that only adds an offset param (SEO fallback pattern)
    const relNext = document.querySelector("link[rel='next'][href]");
    let relNextIsOffsetOnly = false;
    if (relNext) {
        try {
            const nextUrl = new URL(relNext.href, window.location.origin);
            const baseUrl = new URL(window.location.href);
            relNextIsOffsetOnly = nextUrl.pathname === baseUrl.pathname &&
                /^(offset|page|start|from|p|pg)$/i.test(
                    [...nextUrl.searchParams.keys()].find(k => {
                        return nextUrl.searchParams.get(k) !== baseUrl.searchParams.get(k);
                    }) || ''
                );
        } catch {}
    }

    // 4. Large inner scrollable containers (overflow scroll/auto)
    let hasScrollableContainer = false;
    const containers = document.querySelectorAll(
        'main, [role="main"], [role="feed"], .products, .product-grid, .results'
    );
    for (const el of containers) {
        try {
            const style = getComputedStyle(el);
            const ov = style.overflowY || '';
            if ((ov === 'auto' || ov === 'scroll') &&
                (el.scrollHeight - el.clientHeight) > __OVERFLOW_THRESHOLD__) {
                hasScrollableContainer = true;
                break;
            }
        } catch {}
    }

    // 5. Page height >>> viewport (strong infinite scroll hint)
    const docH = Math.max(
        document.body?.scrollHeight || 0,
        document.documentElement?.scrollHeight || 0
    );
    const vpH = window.innerHeight || 0;
    const tallPage = docH > vpH * __TALL_PAGE_RATIO__;

    return {
        has_sentinel: hasSentinel,
        has_offset_param: hasOffsetParam,
        rel_next_is_offset_only: relNextIsOffsetOnly,
        has_scrollable_container: hasScrollableContainer,
        tall_page: tallPage,
        doc_height: docH,
        viewport_height: vpH,
    };
}
"""
_JS_DETECT_INFINITE_SCROLL = _JS_DETECT_INFINITE_SCROLL.replace(
    "__OVERFLOW_THRESHOLD__", str(INFINITE_SCROLL_CONTAINER_OVERFLOW_THRESHOLD_PX)
).replace("__TALL_PAGE_RATIO__", str(INFINITE_SCROLL_TALL_PAGE_RATIO))

_JS_PERFORM_SCROLL = """
            ({ currentHeight, forceProbe }) => {
                const candidates = [
                    document.querySelector("main"),
                    ...Array.from(document.querySelectorAll("[role='main'], [role='feed'], [role='list'], .products, .product-grid, .product-list, .results, .search-results, .items, .list, .listing"))
                ].filter(Boolean);
                const score = (el) => {
                    const links = el.querySelectorAll("a[href]").length;
                    const cards = el.querySelectorAll("article, li, [class*='product'], [class*='result'], [class*='item']").length;
                    const scrollable = Math.max(0, (el.scrollHeight || 0) - (el.clientHeight || 0));
                    return (links * __LINK_WEIGHT__) + cards + (scrollable > __SCROLLABLE_THRESHOLD__ ? __SCROLLABLE_BONUS__ : 0);
                };
                let target = null;
                for (const candidate of candidates) {
                    if (!candidate || !(candidate instanceof Element)) continue;
                    if (!target || score(candidate) > score(target)) {
                        target = candidate;
                    }
                }
                const root = document.scrollingElement || document.documentElement || document.body;
                const activeTarget =
                    target instanceof HTMLElement &&
                    target.scrollHeight > (target.clientHeight + __SCROLLABLE_THRESHOLD__)
                        ? target
                        : root;
                const label = activeTarget === root
                    ? "window"
                    : (activeTarget.getAttribute("data-testid") || activeTarget.getAttribute("id") || activeTarget.className || activeTarget.tagName || "container").toString().slice(0, __LABEL_MAX_LEN__);
                if (activeTarget === root) {
                    const nextTop = forceProbe
                        ? Math.max((window.scrollY || 0) + Math.max(window.innerHeight || 0, __FORCE_PROBE_MIN_ADVANCE__), currentHeight || 0)
                        : (currentHeight || root.scrollHeight || 0);
                    window.scrollTo(0, nextTop);
                } else {
                    const nextTop = forceProbe
                        ? Math.max((activeTarget.scrollTop || 0) + Math.max(activeTarget.clientHeight || 0, __FORCE_PROBE_MIN_ADVANCE__), currentHeight || 0)
                        : Math.max(currentHeight || 0, activeTarget.scrollTop || 0);
                    activeTarget.scrollTo(0, nextTop || activeTarget.scrollHeight || 0);
                }
                return { target: label };
            }
"""
_JS_PERFORM_SCROLL = (
    _JS_PERFORM_SCROLL.replace("__LINK_WEIGHT__", str(TRAVERSAL_ACTIVE_LINK_WEIGHT))
    .replace(
        "__SCROLLABLE_THRESHOLD__", str(TRAVERSAL_ACTIVE_SCROLLABLE_THRESHOLD_PX)
    )
    .replace("__SCROLLABLE_BONUS__", str(TRAVERSAL_ACTIVE_SCROLLABLE_BONUS))
    .replace(
        "__LABEL_MAX_LEN__", str(TRAVERSAL_ACTIVE_TARGET_LABEL_MAX_LEN)
    )
    .replace(
        "__FORCE_PROBE_MIN_ADVANCE__", str(TRAVERSAL_FORCE_PROBE_MIN_ADVANCE_PX)
    )
)


async def _detect_infinite_scroll_signals(page) -> dict[str, object]:
    """Evaluate the live DOM for signals that indicate infinite scroll.

    Returns a dict of individual boolean signals plus a composite
    ``is_likely_infinite_scroll`` flag.  When True the caller should
    prefer scroll traversal even if pagination anchor links are present
    (they are likely SEO fallbacks).
    """
    try:
        raw = await page.evaluate(_JS_DETECT_INFINITE_SCROLL)
    except (PlaywrightError, Exception):
        logger.debug("Infinite scroll detection probe failed", exc_info=True)
        return {"is_likely_infinite_scroll": False, "error": True}

    if not isinstance(raw, dict):
        return {"is_likely_infinite_scroll": False, "error": True}

    # Composite: two or more positive signals → infinite scroll.
    positive = sum([
        bool(raw.get("has_sentinel")),
        bool(raw.get("rel_next_is_offset_only")),
        bool(raw.get("has_scrollable_container")),
        bool(raw.get("tall_page")),
        bool(raw.get("has_offset_param")),
    ])
    raw["positive_signal_count"] = positive
    raw["is_likely_infinite_scroll"] = (
        positive >= INFINITE_SCROLL_POSITIVE_SIGNAL_MIN
    )
    return raw


def _identity_tokens(metrics: dict[str, object] | None) -> set[str]:
    if not metrics:
        return set()
    raw = metrics.get("identities")
    if not isinstance(raw, list):
        return set()
    return {
        str(token).strip().lower()
        for token in raw
        if str(token).strip()
    }


def _identity_growth(
    seen_identities: set[str],
    metrics: dict[str, object] | None,
) -> int:
    current = _identity_tokens(metrics)
    before = len(seen_identities)
    seen_identities.update(current)
    return max(0, len(seen_identities) - before)


def _traversal_wait_error(exc: Exception) -> dict[str, str]:
    error_type = type(exc).__name__
    if isinstance(exc, PlaywrightError):
        error_type = "PlaywrightError"
    return {
        "type": error_type,
        "message": str(exc or "").strip()[:300],
    }


@dataclass
class TraversalResult:
    html: str | None = None
    summary: dict[str, object] = field(default_factory=dict)


@dataclass
class TraversalConfig:
    pagination_next_selectors: list[str] = field(
        default_factory=lambda: PAGINATION_NEXT_SELECTORS
    )
    load_more_selectors: list[str] = field(default_factory=lambda: LOAD_MORE_SELECTORS)
    scroll_wait_min_ms: int = SCROLL_WAIT_MIN_MS
    load_more_wait_min_ms: int = LOAD_MORE_WAIT_MIN_MS
    validate_public_target: object = validate_public_target


def _resolved_config(config: TraversalConfig | None) -> TraversalConfig:
    return config if config is not None else TraversalConfig()


def _log_traversal_result(
    traversal_mode: str | None,
    result: TraversalResult,
) -> TraversalResult:
    logger.info(
        "[traversal] done mode=%s html_len=%s stop_reason=%s",
        result.summary.get("mode", traversal_mode),
        len(result.html or "") if result.html else 0,
        result.summary.get("stop_reason"),
    )
    return result


@dataclass(slots=True)
class TraversalRuntime:
    page_content_with_retry: Callable[..., Awaitable[str]]
    wait_for_surface_readiness: Callable[..., Awaitable[dict[str, object] | None]]
    wait_for_listing_readiness: Callable[..., Awaitable[dict[str, object] | None]]
    peek_next_page_signal: Callable[..., Awaitable[dict[str, object] | None]]
    has_load_more_control: Callable[..., Awaitable[bool]]
    dismiss_cookie_consent: Callable[..., Awaitable[None]]
    pause_after_navigation: Callable[..., Awaitable[None]]
    expand_all_interactive_elements: Callable[..., Awaitable[dict[str, object]]]
    flatten_shadow_dom: Callable[..., Awaitable[None]]
    cooperative_sleep_ms: Callable[..., Awaitable[None]]
    snapshot_listing_page_metrics: Callable[..., Awaitable[dict[str, object]]]
    click_and_observe_next_page: Callable[..., Awaitable[str | AdvanceResult]] | None = None
    advance_next_page_fn: Callable[..., Awaitable[AdvanceResult]] | None = None
    ensure_memory_available: Callable[[], None] | None = None
    run_id: int | None = None
    traversal_artifact_dir: Path | None = None
    checkpoint: Callable[[], Awaitable[None]] | None = None
    progress_logger: Callable[[str], Awaitable[None]] | None = None
    goto_page: Callable[..., Awaitable[None]] | None = None


@dataclass(slots=True)
class TraversalRequest:
    page: object
    plan: AcquisitionPlan
    surface: str | None
    traversal_mode: str | None
    max_scrolls: int
    max_pages: int
    request_delay_ms: int
    runtime: TraversalRuntime
    config: TraversalConfig | None = None


@dataclass(slots=True)
class PaginationTraversalRequest:
    page: object
    plan: AcquisitionPlan
    surface: str | None
    max_pages: int
    request_delay_ms: int
    runtime: TraversalRuntime
    config: TraversalConfig | None = None


@dataclass
class _TraversalContext:
    page: object
    surface: str | None
    plan: AcquisitionPlan
    traversal_mode: str | None
    config: TraversalConfig
    max_scrolls: int
    max_pages: int
    request_delay_ms: int
    runtime: TraversalRuntime

    @property
    def page_content_with_retry(self) -> Callable[..., Awaitable[str]]:
        return self.runtime.page_content_with_retry

    @property
    def wait_for_surface_readiness(
        self,
    ) -> Callable[..., Awaitable[dict[str, object] | None]]:
        return self.runtime.wait_for_surface_readiness

    @property
    def wait_for_listing_readiness(
        self,
    ) -> Callable[..., Awaitable[dict[str, object] | None]]:
        return self.runtime.wait_for_listing_readiness

    @property
    def peek_next_page_signal(
        self,
    ) -> Callable[..., Awaitable[dict[str, object] | None]]:
        return self.runtime.peek_next_page_signal

    @property
    def click_and_observe_next_page(
        self,
    ) -> Callable[..., Awaitable[str | AdvanceResult]] | None:
        return self.runtime.click_and_observe_next_page

    @property
    def advance_next_page_fn(self) -> Callable[..., Awaitable[AdvanceResult]] | None:
        return self.runtime.advance_next_page_fn

    @property
    def has_load_more_control(self) -> Callable[..., Awaitable[bool]]:
        return self.runtime.has_load_more_control

    @property
    def dismiss_cookie_consent(self) -> Callable[..., Awaitable[None]]:
        return self.runtime.dismiss_cookie_consent

    @property
    def pause_after_navigation(self) -> Callable[..., Awaitable[None]]:
        return self.runtime.pause_after_navigation

    @property
    def expand_all_interactive_elements(
        self,
    ) -> Callable[..., Awaitable[dict[str, object]]]:
        return self.runtime.expand_all_interactive_elements

    @property
    def flatten_shadow_dom(self) -> Callable[..., Awaitable[None]]:
        return self.runtime.flatten_shadow_dom

    @property
    def cooperative_sleep_ms(self) -> Callable[..., Awaitable[None]]:
        return self.runtime.cooperative_sleep_ms

    @property
    def snapshot_listing_page_metrics(
        self,
    ) -> Callable[..., Awaitable[dict[str, object]]]:
        return self.runtime.snapshot_listing_page_metrics

    @property
    def ensure_memory_available(self) -> Callable[[], None] | None:
        return self.runtime.ensure_memory_available

    @property
    def run_id(self) -> int | None:
        return self.runtime.run_id

    @property
    def traversal_artifact_dir(self) -> Path | None:
        return self.runtime.traversal_artifact_dir

    @property
    def checkpoint(self) -> Callable[[], Awaitable[None]] | None:
        return self.runtime.checkpoint

    @property
    def progress_logger(self) -> Callable[[str], Awaitable[None]] | None:
        return self.runtime.progress_logger

    @property
    def goto_page(self) -> Callable[..., Awaitable[None]] | None:
        return self.runtime.goto_page


class TraversalStrategy(Protocol):
    async def traverse(self) -> TraversalResult:
        ...


@dataclass
class _FragmentCaptureState:
    page_content_with_retry: Callable[..., Awaitable[str]]
    checkpoint: Callable[[], Awaitable[None]] | None
    card_selectors: list[str]
    collected_fragments: list[str] = field(default_factory=list)
    seen_fragment_hashes: set[str] = field(default_factory=set)
    captured_fragment_bytes: int = 0
    seen_card_identities: set[str] = field(default_factory=set)
    known_container_sigs: list[str] = field(default_factory=list)

    async def capture_fragment(self, page, marker: str) -> None:
        """Capture only card-level HTML instead of full page content.

        Strategy:
        1. Run JS with CARD_SELECTORS to extract matching card outerHTML,
           deduplicating by stable identity (href / data-id).
        2. If selectors match nothing, fall back to a DOM diff of the listing
           container (new children since the last step).
        3. Only if both produce nothing, fall back to full page.content() —
           but this path should be rare.
        """
        if len(self.collected_fragments) >= _MAX_TRAVERSAL_FRAGMENTS:
            return

        fragment_parts: list[str] = []
        try:
            result = await page.evaluate(_JS_EXTRACT_CARDS, self.card_selectors)
            cards = result.get("cards", []) if isinstance(result, dict) else []
            for card in cards:
                identity = card.get("identity", "")
                card_html = card.get("html", "")
                if not card_html:
                    continue
                if identity and identity in self.seen_card_identities:
                    continue
                if identity:
                    self.seen_card_identities.add(identity)
                fragment_parts.append(card_html)
        except (PlaywrightError, Exception):
            logger.debug("Card-selector extraction failed at %s", marker, exc_info=True)

        if not fragment_parts:
            try:
                diff_items = await page.evaluate(
                    _JS_CONTAINER_DIFF, self.known_container_sigs
                )
                if isinstance(diff_items, list):
                    for item in diff_items:
                        item_html = item.get("html", "") if isinstance(item, dict) else ""
                        item_sig = item.get("sig", "") if isinstance(item, dict) else ""
                        if not item_html:
                            continue
                        fragment_parts.append(item_html)
                        if item_sig:
                            self.known_container_sigs.append(item_sig)
            except (PlaywrightError, Exception):
                logger.debug("Container-diff fallback failed at %s", marker, exc_info=True)

        if not fragment_parts:
            html = await self.page_content_with_retry(page, checkpoint=self.checkpoint)
            if not isinstance(html, str) or not html:
                return
            encoded_size = len(html.encode("utf-8", errors="ignore"))
            if encoded_size > _MAX_TRAVERSAL_FRAGMENT_BYTES:
                return
            if self.captured_fragment_bytes + encoded_size > _MAX_TRAVERSAL_TOTAL_BYTES:
                return
            fingerprint = hashlib.sha1(
                html.encode("utf-8", errors="ignore")
            ).hexdigest()
            if fingerprint in self.seen_fragment_hashes:
                return
            self.seen_fragment_hashes.add(fingerprint)
            self.captured_fragment_bytes += encoded_size
            self.collected_fragments.append(
                f"<!-- PAGE BREAK:traversal:{marker}:{getattr(page, 'url', '')} -->\n{html}"
            )
            return

        html = "\n".join(fragment_parts)
        encoded_size = len(html.encode("utf-8", errors="ignore"))
        if self.captured_fragment_bytes + encoded_size > _MAX_TRAVERSAL_TOTAL_BYTES:
            return
        self.captured_fragment_bytes += encoded_size
        self.collected_fragments.append(
            f"<!-- PAGE BREAK:traversal:{marker}:{getattr(page, 'url', '')} -->\n{html}"
        )

    async def capture_initial_fragment(self, page, marker: str) -> None:
        if self.collected_fragments:
            return
        await self.capture_fragment(page, marker)

    async def render_html(self, page) -> str:
        if self.collected_fragments:
            return "\n".join(self.collected_fragments)
        return await self.page_content_with_retry(page, checkpoint=self.checkpoint)


def _new_fragment_capture_state(
    context: _TraversalContext,
) -> _FragmentCaptureState:
    return _FragmentCaptureState(
        page_content_with_retry=context.page_content_with_retry,
        checkpoint=context.checkpoint,
        card_selectors=list(context.plan.traversal_card_selectors),
    )


async def _run_fragment_progress_traversal(
    *,
    context: _TraversalContext,
    fragments: _FragmentCaptureState,
    initial_marker: str,
    progress_marker_prefix: str,
    final_marker: str,
    progress_runner: Callable[
        [Callable[[object, int], Awaitable[None]]],
        Awaitable[dict[str, object]],
    ],
) -> TraversalResult:
    page = context.page
    await fragments.capture_initial_fragment(page, initial_marker)
    summary = await progress_runner(
        lambda current_page, index: fragments.capture_fragment(
            current_page,
            f"{progress_marker_prefix}-{index}",
        )
    )
    await fragments.capture_fragment(page, final_marker)
    summary["pages_collected"] = len(fragments.collected_fragments)
    summary["captured_fragment_bytes"] = fragments.captured_fragment_bytes
    return TraversalResult(
        html=await fragments.render_html(page),
        summary=summary,
    )


class _TraversalStrategyBase:
    def __init__(self, context: _TraversalContext) -> None:
        self.context = context

    def _log_and_return(self, result: TraversalResult) -> TraversalResult:
        return _log_traversal_result(self.context.traversal_mode, result)


class ScrollStrategy(_TraversalStrategyBase):
    async def traverse(self) -> TraversalResult:
        async def _run_progress(
            capture_dom_fragment: Callable[[object, int], Awaitable[None]],
        ) -> dict[str, object]:
            kwargs = {
                "config": self.context.config,
                "request_delay_ms": self.context.request_delay_ms,
                "cooperative_sleep_ms": self.context.cooperative_sleep_ms,
                "snapshot_listing_page_metrics": self.context.snapshot_listing_page_metrics,
                "capture_dom_fragment": capture_dom_fragment,
                "checkpoint": self.context.checkpoint,
            }
            if self.context.progress_logger is not None:
                kwargs["progress_logger"] = self.context.progress_logger
            return await scroll_to_bottom(
                self.context.page,
                self.context.max_scrolls,
                **kwargs,
            )

        return self._log_and_return(
            await _run_fragment_progress_traversal(
                context=self.context,
                fragments=_new_fragment_capture_state(self.context),
                initial_marker="scroll-initial",
                progress_marker_prefix="scroll",
                final_marker="scroll-final",
                progress_runner=_run_progress,
            )
        )


class LoadMoreStrategy(_TraversalStrategyBase):
    async def traverse(self) -> TraversalResult:
        async def _run_progress(
            capture_dom_fragment: Callable[[object, int], Awaitable[None]],
        ) -> dict[str, object]:
            kwargs = {
                "config": self.context.config,
                "request_delay_ms": self.context.request_delay_ms,
                "cooperative_sleep_ms": self.context.cooperative_sleep_ms,
                "snapshot_listing_page_metrics": self.context.snapshot_listing_page_metrics,
                "capture_dom_fragment": capture_dom_fragment,
                "checkpoint": self.context.checkpoint,
            }
            if self.context.progress_logger is not None:
                kwargs["progress_logger"] = self.context.progress_logger
            return await click_load_more(
                self.context.page,
                self.context.max_scrolls,
                **kwargs,
            )

        return self._log_and_return(
            await _run_fragment_progress_traversal(
                context=self.context,
                fragments=_new_fragment_capture_state(self.context),
                initial_marker="load-more-initial",
                progress_marker_prefix="load-more",
                final_marker="load-more-final",
                progress_runner=_run_progress,
            )
        )


class PaginationStrategy(_TraversalStrategyBase):
    async def traverse(self) -> TraversalResult:
        result = await collect_paginated_html(
            PaginationTraversalRequest(
                page=self.context.page,
                plan=self.context.plan,
                config=self.context.config,
                surface=self.context.surface,
                max_pages=self.context.max_pages,
                request_delay_ms=self.context.request_delay_ms,
                runtime=self.context.runtime,
            )
        )
        return self._log_and_return(result)


class AutoTraversalStrategy(_TraversalStrategyBase):
    def __init__(self, context: _TraversalContext) -> None:
        super().__init__(context)
        self._fragments = _new_fragment_capture_state(context)

    async def traverse(self) -> TraversalResult:
        page = self.context.page

        async def _maybe_log_progress(message: str) -> None:
            if self.context.progress_logger is not None:
                await self.context.progress_logger(message)

        async def _paginate_with_decision(
            *,
            decision: str,
            steps: list[dict[str, object]],
            pre_pagination_html: str | None = None,
        ) -> TraversalResult:
            paginated = await collect_paginated_html(
                PaginationTraversalRequest(
                    page=page,
                    plan=self.context.plan,
                    config=self.context.config,
                    surface=self.context.surface,
                    max_pages=self.context.max_pages,
                    request_delay_ms=self.context.request_delay_ms,
                    runtime=self.context.runtime,
                )
            )
            if pre_pagination_html:
                paginated.html = (
                    "<!-- PAGE BREAK:auto:pre-pagination: -->\n"
                    f"{pre_pagination_html}\n"
                    f"{paginated.html or ''}"
                )
                paginated.summary["pages_collected"] = int(
                    paginated.summary.get("pages_collected", 0) or 0
                ) + len(self._fragments.collected_fragments)
            paginated.summary["decision"] = decision
            paginated.summary["steps"] = [
                *steps,
                *list(paginated.summary.get("steps") or []),
            ]
            paginated.summary["captured_fragment_bytes"] = (
                self._fragments.captured_fragment_bytes
            )
            return paginated

        next_page_signal = await self.context.peek_next_page_signal(page)
        if next_page_signal:
            await _maybe_log_progress("auto:paginate_first next_page_signal_detected")
            await self._fragments.capture_initial_fragment(page, "auto-initial")
            infinite_scroll_signals = await _detect_infinite_scroll_signals(page)
            initial_decision = decide_initial_auto_traversal(
                next_page_signal,
                infinite_scroll_signals,
            )
            if not initial_decision.should_paginate_now:
                logger.info(
                    "[TRAVERSAL] auto:hybrid_detected — pagination signal present "
                    "but infinite scroll signals stronger, skipping pagination. "
                    "signals=%s",
                    infinite_scroll_signals,
                )
                # Fall through to scroll logic below
            else:
                return self._log_and_return(
                    await _paginate_with_decision(
                        decision=initial_decision.decision,
                        steps=[],
                    )
                )

        scroll_summary = await scroll_to_bottom(
            page,
            self.context.max_scrolls,
            config=self.context.config,
            request_delay_ms=self.context.request_delay_ms,
            cooperative_sleep_ms=self.context.cooperative_sleep_ms,
            snapshot_listing_page_metrics=self.context.snapshot_listing_page_metrics,
            capture_dom_fragment=lambda current_page, index: self._fragments.capture_fragment(
                current_page, f"auto-scroll-{index}"
            ),
            checkpoint=self.context.checkpoint,
            progress_logger=self.context.progress_logger,
        )
        progress_steps: list[dict[str, object]] = [scroll_summary]
        if await self.context.has_load_more_control(page, self.context.config):
            load_more_summary = await click_load_more(
                page,
                self.context.max_scrolls,
                config=self.context.config,
                request_delay_ms=self.context.request_delay_ms,
                cooperative_sleep_ms=self.context.cooperative_sleep_ms,
                snapshot_listing_page_metrics=self.context.snapshot_listing_page_metrics,
                capture_dom_fragment=lambda current_page, index: self._fragments.capture_fragment(
                    current_page, f"auto-load-more-{index}"
                ),
                checkpoint=self.context.checkpoint,
                progress_logger=self.context.progress_logger,
            )
            progress_steps.append(load_more_summary)

        await self._fragments.capture_fragment(page, "auto-pre-pagination")
        pre_pagination_html = await self._fragments.render_html(page)

        next_page_signal = await self.context.peek_next_page_signal(page)
        if next_page_signal:
            await _maybe_log_progress(
                "auto:progress_then_paginate next_page_signal_detected"
            )
            return self._log_and_return(
                await _paginate_with_decision(
                    decision=decide_post_progress_auto_traversal(next_page_signal),
                    steps=progress_steps,
                    pre_pagination_html=pre_pagination_html,
                )
            )

        final_decision = decide_post_progress_auto_traversal(next_page_signal)
        return self._log_and_return(
            TraversalResult(
                html=pre_pagination_html,
                summary={
                    "mode": "auto",
                    "attempted": True,
                    "steps": progress_steps,
                    "pages_collected": len(self._fragments.collected_fragments),
                    "captured_fragment_bytes": self._fragments.captured_fragment_bytes,
                    "decision": final_decision,
                    "stop_reason": "no_pagination_after_scroll_or_load_more",
                },
            )
        )


class _NoOpTraversalStrategy(_TraversalStrategyBase):
    async def traverse(self) -> TraversalResult:
        return self._log_and_return(
            TraversalResult(
                summary={
                    "mode": self.context.traversal_mode,
                    "attempted": False,
                    "stop_reason": "mode_not_enabled",
                }
            )
        )


def _traversal_strategy_for_mode(context: _TraversalContext) -> TraversalStrategy:
    normalized_mode = str(context.traversal_mode or "").strip().lower()
    strategy_map: dict[str, type[_TraversalStrategyBase]] = {
        "scroll": ScrollStrategy,
        "load_more": LoadMoreStrategy,
        "paginate": PaginationStrategy,
        "auto": AutoTraversalStrategy,
    }
    strategy_factory = strategy_map.get(normalized_mode, _NoOpTraversalStrategy)
    return strategy_factory(context)


async def apply_traversal_mode(request: TraversalRequest) -> TraversalResult:
    config = _resolved_config(request.config)
    logger.info(
        "[traversal] starting mode=%s surface=%s",
        request.traversal_mode,
        request.surface,
    )

    if not request.plan.traversal_enabled:
        return _log_traversal_result(
            request.traversal_mode,
            TraversalResult(
                summary={
                    "mode": request.traversal_mode,
                    "attempted": False,
                    "stop_reason": "detail_surface",
                }
            ),
        )

    context = _TraversalContext(
        page=request.page,
        surface=request.surface,
        plan=request.plan,
        traversal_mode=request.traversal_mode,
        config=config,
        max_scrolls=request.max_scrolls,
        max_pages=request.max_pages,
        request_delay_ms=request.request_delay_ms,
        runtime=request.runtime,
    )
    return await _traversal_strategy_for_mode(context).traverse()

def _log_for_pytest(level: int, message: str, *args: object) -> None:
    logger.log(level, message, *args)
    root_logger = logging.getLogger()
    if any(type(handler).__name__ == "LogCaptureHandler" for handler in root_logger.handlers):
        root_logger.log(level, message, *args)


async def collect_paginated_html(
    request: PaginationTraversalRequest,
) -> TraversalResult:
    config = _resolved_config(request.config)
    runtime = request.runtime
    if runtime.advance_next_page_fn is None and runtime.click_and_observe_next_page is None:
        raise ValueError("no pagination callback provided")
    if runtime.ensure_memory_available is not None:
        runtime.ensure_memory_available()

    fragments: list[str] = []
    page_files: list[Path] = []
    visited_urls: set[str] = set()
    stop_reason = "max_pages_reached"
    _first_page_size: int = 0
    steps: list[dict[str, object]] = []
    page = request.page
    current_url = str(page.url or "").strip()
    if current_url:
        visited_urls.add(current_url)
    seen_card_identities: set[str] = set()
    card_selectors = list(request.plan.traversal_card_selectors)

    async def _capture_page_html(
        current_page,
        *,
        page_number: int,
    ) -> tuple[str, int, str]:
        full_html = await runtime.page_content_with_retry(
            current_page,
            checkpoint=runtime.checkpoint,
        )
        capture_html = full_html
        capture_mode = "full_page"
        if request.plan.is_listing_surface:
            fragment_parts: list[str] = []
            try:
                result = await current_page.evaluate(_JS_EXTRACT_CARDS, card_selectors)
                cards = result.get("cards", []) if isinstance(result, dict) else []
                for card in cards:
                    identity = (
                        str(card.get("identity", "")).strip()
                        if isinstance(card, dict)
                        else ""
                    )
                    card_html = (
                        str(card.get("html", ""))
                        if isinstance(card, dict)
                        else ""
                    )
                    if not card_html:
                        continue
                    if identity and identity in seen_card_identities:
                        continue
                    if identity:
                        seen_card_identities.add(identity)
                    fragment_parts.append(card_html)
            except (PlaywrightError, Exception):
                logger.debug(
                    "Paginated card extraction failed for page %s",
                    page_number,
                    exc_info=True,
                )
            if fragment_parts:
                capture_html = "\n".join(fragment_parts)
                capture_mode = "targeted_fragment"
        if runtime.progress_logger is not None:
            await runtime.progress_logger(
                f"paginate:capture page={page_number} mode={capture_mode} html_length={len(capture_html or '')}"
            )
        return capture_html, len(full_html or ""), capture_mode

    # Resolve the advance callback.  Prefer advance_next_page_fn (aware of
    # already_navigated); fall back to the legacy click_and_observe_next_page
    # wrapper for backward compatibility.
    async def _legacy_advance(pg, *, checkpoint=None) -> AdvanceResult:
        if runtime.click_and_observe_next_page is None:
            raise ValueError("no pagination callback provided")
        result = await runtime.click_and_observe_next_page(  # type: ignore[misc]
            pg,
            checkpoint=checkpoint,
        )
        if isinstance(result, AdvanceResult):
            return AdvanceResult(
                url=result.url,
                already_navigated=result.already_navigated,
            )
        return AdvanceResult(url=result, already_navigated=False)

    _advance = (
        runtime.advance_next_page_fn
        if runtime.advance_next_page_fn is not None
        else _legacy_advance
    )

    page_limit = max(1, int(request.max_pages or 1))
    for page_index in range(page_limit):
        page_html, full_page_size, capture_mode = await _capture_page_html(
            page,
            page_number=page_index + 1,
        )
        current_page_size = full_page_size
        if page_index == 0:
            _first_page_size = current_page_size
        if runtime.traversal_artifact_dir is not None:
            await asyncio.to_thread(
                runtime.traversal_artifact_dir.mkdir,
                parents=True,
                exist_ok=True,
            )
            file_prefix = str(runtime.run_id) if runtime.run_id is not None else "adhoc"
            page_path = runtime.traversal_artifact_dir / f"{file_prefix}_page_{page_index + 1}.html"
            await asyncio.to_thread(
                page_path.write_text,
                f"<!-- PAGE BREAK:{page_index + 1}:{page.url} -->\n{page_html}",
                encoding="utf-8",
            )
            page_files.append(page_path)
        else:
            fragments.append(
                f"<!-- PAGE BREAK:{page_index + 1}:{page.url} -->\n{page_html}"
            )
        steps.append(
            {
                "action": "capture_page",
                "page_index": page_index + 1,
                "url": str(page.url or "").strip() or None,
                "html_length": len(page_html or ""),
                "capture_mode": capture_mode,
                "html_path": str(page_files[-1]) if page_files else None,
            }
        )
        if (
            page_index > 0
            and _first_page_size > 0
            and current_page_size
            >= _first_page_size * PAGINATION_PAGE_SIZE_ANOMALY_RATIO
        ):
            logger.warning(
                "[TRAVERSAL] paginate:page_size_anomaly page=%s "
                "first_page=%s current_page=%s ratio=%.1f — aborting",
                page_index + 1,
                _first_page_size,
                current_page_size,
                current_page_size / _first_page_size,
            )
            stop_reason = "page_size_anomaly"
            break
        if page_index + 1 >= page_limit:
            break
        current_url = str(page.url or "").strip()
        advance_result = await _advance(page, checkpoint=runtime.checkpoint)
        next_page_url = advance_result.url
        page_advanced_in_place = (
            bool(next_page_url)
            and str(page.url or "").strip() == current_url
            and next_page_url == current_url
        )
        if not next_page_url or (
            next_page_url in visited_urls and not page_advanced_in_place
        ):
            stop_reason = "no_next_page"
            break
        try:
            await config.validate_public_target(next_page_url)
        except ValueError as exc:
            _log_for_pytest(
                logging.WARNING,
                "Rejected pagination URL %s from %s: %s", next_page_url, page.url, exc
            )
            stop_reason = "rejected_next_page"
            break
        visited_urls.add(next_page_url)
        # Only navigate when the advance step did not already mutate the page
        # (e.g. it returned an <a href> URL but did not click).
        needs_goto = not advance_result.already_navigated and not page_advanced_in_place
        if needs_goto:
            if runtime.goto_page is not None:
                await runtime.goto_page(
                    page,
                    next_page_url,
                    surface=request.surface,
                    checkpoint=runtime.checkpoint,
                )
            else:
                await page.goto(
                    next_page_url,
                    wait_until="domcontentloaded",
                    timeout=PAGINATION_NAVIGATION_TIMEOUT_MS,
                )
            if hasattr(page, "wait_for_load_state"):
                try:
                    await page.wait_for_load_state(
                        "load",
                        timeout=BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS,
                    )
                except PlaywrightTimeoutError:
                    pass
            await runtime.wait_for_surface_readiness(
                page,
                plan=request.plan,
                checkpoint=runtime.checkpoint,
            )
            steps.append(
                {
                    "action": "goto_next_page",
                    "page_index": page_index + 2,
                    "url": next_page_url,
                    "in_place": False,
                }
            )
            if runtime.progress_logger is not None:
                await runtime.progress_logger(
                    f"paginate:advance_goto page={page_index + 2} url={next_page_url}"
                )
        else:
            steps.append(
                {
                    "action": "goto_next_page",
                    "page_index": page_index + 2,
                    "url": next_page_url,
                    "in_place": page_advanced_in_place or advance_result.already_navigated,
                }
            )
            if runtime.progress_logger is not None:
                await runtime.progress_logger(
                    f"paginate:advance_in_place page={page_index + 2} url={next_page_url}"
                )
        await runtime.dismiss_cookie_consent(page, checkpoint=runtime.checkpoint)
        await runtime.pause_after_navigation(
            request.request_delay_ms,
            checkpoint=runtime.checkpoint,
        )
        await runtime.expand_all_interactive_elements(
            page,
            checkpoint=runtime.checkpoint,
        )
        await runtime.flatten_shadow_dom(page)
        await runtime.wait_for_listing_readiness(
            page,
            plan=request.plan,
            checkpoint=runtime.checkpoint,
        )
    if page_files:
        fragments = await asyncio.gather(
            *[
                asyncio.to_thread(page_path.read_text, encoding="utf-8")
                for page_path in page_files
            ]
        )

    return TraversalResult(
        html="\n".join(fragments),
        summary={
            "mode": "paginate",
            "attempted": True,
            "pages_collected": len(page_files) or len(fragments),
            "visited_urls": len(visited_urls),
            "steps": steps,
            "stop_reason": stop_reason,
        },
    )


async def find_next_page_url_anchor_only(
    page,
    *,
    config: TraversalConfig | None = None,
) -> str:
    config = _resolved_config(config)
    try:
        href = await page.evaluate(
            """
            () => {
              const link = document.querySelector("link[rel='next'][href], link[rel='Next'][href]");
              return link ? link.href : '';
            }
            """
        )
        if href:
            return str(href or "").strip()
    except PlaywrightError:
        logger.debug("Failed to inspect document-level rel=next link", exc_info=True)

    for selector in config.pagination_next_selectors:
        try:
            locator = page.locator(selector).first
            if not await locator.count():
                continue
            href = await locator.get_attribute("href")
            if href:
                return urljoin(page.url, href)
        except PlaywrightError:
            logger.debug(
                "Failed to inspect pagination selector %s", selector, exc_info=True
            )
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
    except PlaywrightError:
        logger.debug("Failed to evaluate DOM for next-page link", exc_info=True)
        return ""
    return str(href or "").strip()


async def _find_clickable_pagination_target(page, *, config: TraversalConfig | None = None):
    config = _resolved_config(config)
    click_selectors = [
        *config.pagination_next_selectors,
        '[aria-label*="next" i]',
        'button[class*="next"]',
        '[role="button"][class*="next"]',
        'button:has-text("Next")',
        '[data-testid*="next"]',
    ]
    for selector in click_selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count():
                return selector, locator
        except PlaywrightError:
            logger.debug(
                "Failed to inspect clickable pagination selector %s",
                selector,
                exc_info=True,
            )
    return None, None


async def peek_next_page_signal(
    page,
    *,
    config: TraversalConfig | None = None,
) -> dict[str, object] | None:
    config = _resolved_config(config)
    next_page_url = await find_next_page_url_anchor_only(page, config=config)
    if next_page_url:
        return {"kind": "url", "next_page_url": next_page_url}
    selector, target = await _find_clickable_pagination_target(page, config=config)
    if target is None:
        return None
    return {"kind": "click", "selector": selector}


async def snapshot_pagination_state(page) -> dict[str, object]:
    try:
        return await page.evaluate(
            """
            () => {
                const root = document.querySelector("main") || document.body || document.documentElement;
                const listingLinks = Array.from((root || document).querySelectorAll("a[href]"))
                    .map((anchor) => {
                        const text = (anchor.textContent || anchor.getAttribute("aria-label") || "").replace(/\\s+/g, " ").trim();
                        const href = (anchor.getAttribute("href") || "").trim();
                        if (!text || !href) return null;
                        const loweredHref = href.toLowerCase();
                        const loweredText = text.toLowerCase();
                        const looksLikeListingHref =
                            loweredHref.includes("/job/") ||
                            loweredHref.includes("/jobs/") ||
                            loweredHref.includes("/career") ||
                            loweredHref.includes("/position");
                        const withinLikelyCard = !!anchor.closest(
                            "article, li, tr, [role='listitem'], [data-automation-id], [class*='job'], [class*='career'], [class*='opening'], [class*='result']"
                        );
                        const looksLikeListing =
                            (looksLikeListingHref || withinLikelyCard) &&
                            text.length >= 8 &&
                            !/apply|read more|save job|learn more|search/.test(loweredText);
                        if (!looksLikeListing) return null;
                        return `${text}@@${href}`;
                    })
                    .filter(Boolean)
                    .slice(0, 8);
                const activePaginationNode =
                    document.querySelector("[aria-current='page']") ||
                    document.querySelector("[aria-current='true']") ||
                    document.querySelector("[aria-selected='true']") ||
                    Array.from(document.querySelectorAll("button, a, [role='button']")).find((node) => {
                        const classes = (node.className || "").toString().toLowerCase();
                        const ariaPressed = (node.getAttribute("aria-pressed") || "").toLowerCase();
                        return classes.includes("active") || classes.includes("current") || ariaPressed === "true";
                    });
                const paginationMarker = activePaginationNode
                    ? ((activePaginationNode.getAttribute("aria-label") || activePaginationNode.textContent || "").replace(/\\s+/g, " ").trim())
                    : "";
                return {
                    url: window.location.href,
                    pagination_marker: paginationMarker,
                    listing_signature: listingLinks.join("\\n"),
                    listing_link_count: listingLinks.length,
                    root_text_length: ((root && root.innerText) || "").trim().length,
                };
            }
            """
        )
    except PlaywrightError:
        logger.debug("Failed to snapshot pagination state", exc_info=True)
        return {}


def pagination_state_changed(
    previous: dict[str, object] | None, current: dict[str, object] | None
) -> bool:
    if not previous or not current:
        return False
    previous_marker = str(previous.get("pagination_marker") or "").strip()
    current_marker = str(current.get("pagination_marker") or "").strip()
    if previous_marker and current_marker and previous_marker != current_marker:
        return True
    previous_signature = str(previous.get("listing_signature") or "").strip()
    current_signature = str(current.get("listing_signature") or "").strip()
    if (
        previous_signature
        and current_signature
        and previous_signature != current_signature
    ):
        return True
    previous_count = int(previous.get("listing_link_count", 0) or 0)
    current_count = int(current.get("listing_link_count", 0) or 0)
    if (
        previous_count != current_count
        and max(previous_count, current_count) >= LISTING_MIN_ITEMS
    ):
        return True
    return False


@dataclass
class AdvanceResult:
    """Result of advance_next_page.

    - ``url``: the URL of the next page (empty string if advance failed).
    - ``already_navigated``: True when a button click already changed the page
      state, so the caller must NOT do a redundant ``page.goto()``.
    """
    url: str = ""
    already_navigated: bool = False


async def advance_next_page(
    page,
    *,
    config: TraversalConfig | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> AdvanceResult:
    """Advance to the next page by clicking the pagination control.

    First checks for an ``<a href>`` next-page link (non-mutating).  If found,
    returns the URL with ``already_navigated=False`` so the caller can
    ``page.goto()`` itself.

    If no anchor is found, clicks the first matching pagination button and
    waits for the page to settle, returning ``already_navigated=True`` so the
    caller skips ``goto``.
    """
    config = _resolved_config(config)
    next_page_url = await find_next_page_url_anchor_only(page, config=config)
    if next_page_url:
        return AdvanceResult(url=next_page_url, already_navigated=False)

    async def _container_hash() -> int | None:
        selector = '[class*="product"], [class*="result"], ul.products, main'
        try:
            locator = page.locator(selector).first
            if not await locator.count():
                return None
            return hash((await locator.inner_html())[:2000])
        except PlaywrightError:
            logger.debug(
                "Failed to inspect listing container before/after pagination click",
                exc_info=True,
            )
            return None

    _selector, target = await _find_clickable_pagination_target(page, config=config)
    if target is None:
        return AdvanceResult()

    initial_url = str(page.url or "").strip()
    initial_state = await snapshot_pagination_state(page)
    initial_hash = await _container_hash()
    try:
        await target.click(timeout=PAGINATION_POST_CLICK_TIMEOUT_MS)
    except PlaywrightError:
        logger.debug("Failed to click next-page control", exc_info=True)
        return AdvanceResult()
    try:
        await page.wait_for_load_state(
            "domcontentloaded",
            timeout=PAGINATION_POST_CLICK_DOMCONTENTLOADED_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        logger.debug(
            "Timed out waiting for domcontentloaded after pagination click",
            exc_info=True,
        )

    waited_ms = 0
    poll_ms = PAGINATION_POST_CLICK_POLL_MS
    while waited_ms < PAGINATION_POST_CLICK_SETTLE_TIMEOUT_MS:
        if hasattr(page, "wait_for_timeout"):
            try:
                await page.wait_for_timeout(poll_ms)
            except PlaywrightError:
                logger.debug("Pagination wait_for_timeout failed", exc_info=True)
        if checkpoint:
            await checkpoint()
        waited_ms += poll_ms
        current_url = str(page.url or "").strip()
        if current_url != initial_url:
            return AdvanceResult(url=current_url, already_navigated=True)
        current_state = await snapshot_pagination_state(page)
        if pagination_state_changed(initial_state, current_state):
            return AdvanceResult(
                url=current_url or initial_url, already_navigated=True,
            )
        if await _container_hash() != initial_hash:
            return AdvanceResult(url=current_url, already_navigated=True)
    return AdvanceResult()


async def click_and_observe_next_page(
    page,
    *,
    config: TraversalConfig | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> str:
    """Legacy wrapper — delegates to advance_next_page and returns just the URL.

    Existing callers that only need the URL string continue to work unchanged.
    """
    result = await advance_next_page(
        page, config=config, checkpoint=checkpoint,
    )
    return result.url


async def scroll_to_bottom(
    page,
    max_scrolls: int,
    *,
    config: TraversalConfig | None = None,
    request_delay_ms: int,
    cooperative_sleep_ms: Callable[..., Awaitable[None]],
    snapshot_listing_page_metrics: Callable[..., Awaitable[dict[str, object]]],
    capture_dom_fragment: Callable[..., Awaitable[None]] | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
    progress_logger: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, object]:
    config = _resolved_config(config)
    prev_height = 0
    previous_metrics: dict[str, object] | None = None
    steps: list[dict[str, object]] = []
    stop_reason = "max_scrolls_reached"
    forced_probe_used = False
    weak_progress_streak = 0
    seen_identities: set[str] = set()
    max_iterations = min(max(0, int(max_scrolls or 0)), TRAVERSAL_MAX_ITERATIONS_CAP)
    for index in range(max_iterations):
        current_height = await current_scroll_height(page)
        current_metrics = await snapshot_listing_page_metrics(page)
        current_identity_growth = _identity_growth(seen_identities, current_metrics)
        if current_height == prev_height and not listing_progressed(
            previous_metrics,
            current_metrics,
            identity_growth=current_identity_growth,
        ):
            if steps and not forced_probe_used:
                forced_probe_used = True
            else:
                stop_reason = "no_progress_before_scroll"
                break
        scroll_result = await perform_scroll(
            page,
            current_height=current_height,
            force_probe=forced_probe_used,
        )

        await cooperative_sleep_ms(
            max(TRAVERSAL_MIN_SETTLE_WAIT_MS, request_delay_ms),
            checkpoint=checkpoint,
        )
        network_wait_status = "skipped"
        if hasattr(page, "wait_for_load_state"):
            try:
                await page.wait_for_load_state("networkidle", timeout=config.scroll_wait_min_ms)
                network_wait_status = "completed"
            except PlaywrightTimeoutError:
                network_wait_status = "timeout"
            except PlaywrightError as exc:
                wait_error = _traversal_wait_error(exc)
                steps.append(
                    {
                        "action": "scroll",
                        "index": index + 1,
                        "target": scroll_result.get("target"),
                        "forced_probe": forced_probe_used,
                        "network_wait_status": "failed",
                        "network_wait_error": wait_error,
                    }
                )
                return {
                    "mode": "scroll",
                    "attempted": True,
                    "attempt_count": len(steps),
                    "steps": steps,
                    "stop_reason": "network_wait_failed",
                    "network_wait_error": wait_error,
                }
            except (BrokenPipeError, ConnectionResetError) as exc:
                wait_error = _traversal_wait_error(exc)
                steps.append(
                    {
                        "action": "scroll",
                        "index": index + 1,
                        "target": scroll_result.get("target"),
                        "forced_probe": forced_probe_used,
                        "network_wait_status": "connection_lost",
                        "network_wait_error": wait_error,
                    }
                )
                return {
                    "mode": "scroll",
                    "attempted": True,
                    "attempt_count": len(steps),
                    "steps": steps,
                    "stop_reason": "network_wait_connection_lost",
                    "network_wait_error": wait_error,
                }
        else:
            await cooperative_sleep_ms(
                config.scroll_wait_min_ms,
                checkpoint=checkpoint,
            )
            network_wait_status = "sleep_only"
        next_height = await current_scroll_height(page)
        next_metrics = await snapshot_listing_page_metrics(page)
        identity_growth = _identity_growth(seen_identities, next_metrics)
        progress_kind = classify_progress(
            previous=current_metrics,
            current=next_metrics,
            height_before=current_height,
            height_after=next_height,
            identity_growth=identity_growth,
        )
        progressed = progress_kind != "none"
        if not progressed:
            # One extra settle window for delayed/virtualized rendering pages.
            await cooperative_sleep_ms(
                TRAVERSAL_MIN_SETTLE_WAIT_MS,
                checkpoint=checkpoint,
            )
            settled_height = await current_scroll_height(page)
            settled_metrics = await snapshot_listing_page_metrics(page)
            settled_identity_growth = _identity_growth(seen_identities, settled_metrics)
            settled_progress_kind = classify_progress(
                previous=current_metrics,
                current=settled_metrics,
                height_before=next_height,
                height_after=settled_height,
                identity_growth=settled_identity_growth,
            )
            if settled_progress_kind != "none":
                progressed = True
                progress_kind = settled_progress_kind
                next_height = settled_height
                next_metrics = settled_metrics
                identity_growth = settled_identity_growth

        if progress_kind == "height_only":
            weak_progress_streak += 1
        else:
            weak_progress_streak = 0
        logger.info(
            "[scroll] iteration=%s, height_before=%s, height_after=%s, stable=%s",
            index + 1,
            current_height,
            next_height,
            not progressed,
        )
        if progress_logger is not None:
            await progress_logger(f"scroll:iteration index={index + 1} height_before={current_height} height_after={next_height} progressed={progressed}")
        steps.append(
            {
                "action": "scroll",
                "index": index + 1,
                "height_before": current_height,
                "height_after": next_height,
                "target": scroll_result.get("target"),
                "forced_probe": forced_probe_used,
                "network_wait_status": network_wait_status,
                "progress_kind": progress_kind,
                "link_count_before": int(
                    (current_metrics or {}).get("link_count", 0) or 0
                ),
                "link_count_after": int((next_metrics or {}).get("link_count", 0) or 0),
                "cardish_count_before": int(
                    (current_metrics or {}).get("cardish_count", 0) or 0
                ),
                "cardish_count_after": int(
                    (next_metrics or {}).get("cardish_count", 0) or 0
                ),
                "identity_count_before": int(
                    (current_metrics or {}).get("identity_count", 0) or 0
                ),
                "identity_count_after": int(
                    (next_metrics or {}).get("identity_count", 0) or 0
                ),
                "identity_growth": identity_growth,
                "progressed": progressed,
            }
        )
        # Capture DOM fragment after each scroll to preserve items that
        # virtualized grids may remove from the DOM on subsequent scrolls.
        if capture_dom_fragment and progressed:
            try:
                await capture_dom_fragment(page, index + 1)
            except Exception:
                incr("traversal_dom_fragment_capture_failures_total")
                logger.debug("DOM fragment capture failed at scroll %s", index + 1, exc_info=True)
        prev_height = next_height
        previous_metrics = next_metrics
        if not progressed:
            stop_reason = "no_progress_after_scroll"
            break
        if weak_progress_streak >= TRAVERSAL_WEAK_PROGRESS_STREAK_MAX:
            stop_reason = "height_only_progress_exhausted"
            break
        forced_probe_used = False
    return {
        "mode": "scroll",
        "attempted": True,
        "attempt_count": len(steps),
        "steps": steps,
        "stop_reason": stop_reason,
    }


async def perform_scroll(
    page, *, current_height: int, force_probe: bool
) -> dict[str, object]:
    try:
        return (
            await page.evaluate(
                _JS_PERFORM_SCROLL,
                {"currentHeight": current_height, "forceProbe": force_probe},
            )
            or {}
        )
    except (PlaywrightError, TypeError, ValueError):
        try:
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
            return {"target": "window"}
        except PlaywrightError:
            logger.debug("Failed to perform scroll step", exc_info=True)
            return {}


async def current_scroll_height(page) -> int:
    try:
        return int(
            await page.evaluate(
                """
            () => {
                const root = document.scrollingElement || document.documentElement || document.body;
                if (!root) return 0;
                return Math.max(root.scrollHeight || 0, document.body?.scrollHeight || 0, document.documentElement?.scrollHeight || 0);
            }
            """
            )
            or 0
        )
    except PlaywrightError:
        logger.debug("Failed to read current scroll height", exc_info=True)
        return 0


def listing_progressed(
    previous: dict[str, object] | None,
    current: dict[str, object] | None,
    *,
    identity_growth: int = 0,
    dom_mutated: bool = False,
) -> bool:
    if identity_growth > 0 or dom_mutated:
        return True
    if not previous or not current:
        return False
    for key in ("identity_count", "link_count", "cardish_count", "text_length", "html_length"):
        if int(current.get(key, 0) or 0) > int(previous.get(key, 0) or 0):
            return True
    return False


def classify_progress(
    *,
    previous: dict[str, object] | None,
    current: dict[str, object] | None,
    height_before: int,
    height_after: int,
    identity_growth: int = 0,
) -> str:
    dom_mutated = bool(
        previous
        and current
        and previous.get("dom_signature") != current.get("dom_signature")
    )
    if listing_progressed(
        previous,
        current,
        identity_growth=identity_growth,
        dom_mutated=dom_mutated,
    ):
        return "content"
    if height_after > height_before:
        return "height_only"
    return "none"


async def click_load_more(
    page,
    max_clicks: int,
    *,
    config: TraversalConfig | None = None,
    request_delay_ms: int,
    cooperative_sleep_ms: Callable[..., Awaitable[None]],
    snapshot_listing_page_metrics: Callable[..., Awaitable[dict[str, object]]],
    capture_dom_fragment: Callable[..., Awaitable[None]] | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
    progress_logger: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, object]:
    config = _resolved_config(config)
    steps: list[dict[str, object]] = []
    stop_reason = "max_clicks_reached"
    seen_identities: set[str] = set()
    for index in range(max_clicks):
        clicked = False
        previous_metrics = await snapshot_listing_page_metrics(page)
        _identity_growth(seen_identities, previous_metrics)
        for selector in config.load_more_selectors:
            try:
                button = page.locator(selector).first
                if await button.is_visible():
                    await button.click()
                    await cooperative_sleep_ms(
                        max(TRAVERSAL_MIN_SETTLE_WAIT_MS, request_delay_ms),
                        checkpoint=checkpoint,
                    )
                    network_wait_status = "skipped"
                    if hasattr(page, "wait_for_load_state"):
                        try:
                            await page.wait_for_load_state("networkidle", timeout=config.load_more_wait_min_ms)
                            network_wait_status = "completed"
                        except PlaywrightTimeoutError:
                            network_wait_status = "timeout"
                        except PlaywrightError as exc:
                            wait_error = _traversal_wait_error(exc)
                            steps.append(
                                {
                                    "action": "load_more",
                                    "index": index + 1,
                                    "selector": selector,
                                    "network_wait_status": "failed",
                                    "network_wait_error": wait_error,
                                }
                            )
                            return {
                                "mode": "load_more",
                                "attempted": True,
                                "attempt_count": len(steps),
                                "steps": steps,
                                "stop_reason": "network_wait_failed",
                                "network_wait_error": wait_error,
                            }
                        except (BrokenPipeError, ConnectionResetError) as exc:
                            wait_error = _traversal_wait_error(exc)
                            steps.append(
                                {
                                    "action": "load_more",
                                    "index": index + 1,
                                    "selector": selector,
                                    "network_wait_status": "connection_lost",
                                    "network_wait_error": wait_error,
                                }
                            )
                            return {
                                "mode": "load_more",
                                "attempted": True,
                                "attempt_count": len(steps),
                                "steps": steps,
                                "stop_reason": "network_wait_connection_lost",
                                "network_wait_error": wait_error,
                            }
                    else:
                        await cooperative_sleep_ms(
                            config.load_more_wait_min_ms,
                            checkpoint=checkpoint,
                        )
                        network_wait_status = "sleep_only"
                    current_metrics = await snapshot_listing_page_metrics(page)
                    identity_growth = _identity_growth(seen_identities, current_metrics)
                    button_still_visible = await button.is_visible()
                    dom_mutated = bool(
                        previous_metrics
                        and current_metrics
                        and previous_metrics.get("dom_signature") != current_metrics.get("dom_signature")
                    )
                    progressed = listing_progressed(
                        previous_metrics,
                        current_metrics,
                        identity_growth=identity_growth,
                        dom_mutated=dom_mutated or not button_still_visible,
                    )
                    steps.append(
                        {
                            "action": "load_more",
                            "index": index + 1,
                            "selector": selector,
                            "link_count_before": int(
                                (previous_metrics or {}).get("link_count", 0) or 0
                            ),
                            "link_count_after": int(
                                (current_metrics or {}).get("link_count", 0) or 0
                            ),
                            "cardish_count_before": int(
                                (previous_metrics or {}).get("cardish_count", 0) or 0
                            ),
                            "cardish_count_after": int(
                                (current_metrics or {}).get("cardish_count", 0) or 0
                            ),
                            "identity_count_before": int(
                                (previous_metrics or {}).get("identity_count", 0) or 0
                            ),
                            "identity_count_after": int(
                                (current_metrics or {}).get("identity_count", 0) or 0
                            ),
                            "identity_growth": identity_growth,
                            "button_disappeared": not button_still_visible,
                            "dom_mutated": dom_mutated,
                            "network_wait_status": network_wait_status,
                            "progressed": progressed,
                        }
                    )
                    if progress_logger is not None:
                        await progress_logger(f"load_more:click index={index + 1} selector={selector} progressed={progressed}")
                    clicked = True
                    if not progressed:
                        stop_reason = "no_progress_after_click"
                        return {
                            "mode": "load_more",
                            "attempted": True,
                            "attempt_count": len(steps),
                            "steps": steps,
                            "stop_reason": stop_reason,
                        }
                    # Capture DOM fragment after each successful load-more
                    # to preserve items that may be replaced on next click.
                    if capture_dom_fragment:
                        try:
                            await capture_dom_fragment(page, index + 1)
                        except Exception:
                            incr("traversal_dom_fragment_capture_failures_total")
                            logger.debug("DOM fragment capture failed at load_more %s", index + 1, exc_info=True)
                    break
            except PlaywrightError:
                logger.debug(
                    "Load-more click failed for selector %s", selector, exc_info=True
                )
                continue
        if not clicked:
            stop_reason = "no_load_more_control"
            break
    return {
        "mode": "load_more",
        "attempted": True,
        "attempt_count": len(steps),
        "steps": steps,
        "stop_reason": stop_reason,
    }


async def has_load_more_control(
    page,
    config: TraversalConfig | None = None,
) -> bool:
    config = _resolved_config(config)
    for selector in config.load_more_selectors:
        try:
            button = page.locator(selector).first
            if await button.is_visible():
                return True
        except PlaywrightError:
            logger.debug(
                "Load-more visibility check failed for selector %s",
                selector,
                exc_info=True,
            )
    return False
