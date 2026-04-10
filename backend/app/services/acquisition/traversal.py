from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin

from app.services.pipeline_config import (
    BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS,
    CARD_SELECTORS_COMMERCE,
    CARD_SELECTORS_JOBS,
    LISTING_MIN_ITEMS,
    LOAD_MORE_SELECTORS,
    LOAD_MORE_WAIT_MIN_MS,
    PAGINATION_NAVIGATION_TIMEOUT_MS,
    PAGINATION_NEXT_SELECTORS,
    SCROLL_WAIT_MIN_MS,
)
from app.services.runtime_metrics import incr
from app.services.url_safety import validate_public_target
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

logger = logging.getLogger(__name__)
_MAX_TRAVERSAL_FRAGMENTS = 50
_MAX_TRAVERSAL_FRAGMENT_BYTES = 2_000_000
_MAX_TRAVERSAL_TOTAL_BYTES = 6_000_000


def _card_selectors_for_surface(surface: str | None) -> list[str]:
    """Return the appropriate CARD_SELECTORS list based on the crawl surface."""
    normalized = str(surface or "").strip().lower()
    if "job" in normalized:
        return list(CARD_SELECTORS_JOBS)
    return list(CARD_SELECTORS_COMMERCE)


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
    const container = document.querySelector(
        'main, [role="main"], [role="feed"], .products, .product-grid, .results, .search-results'
    ) || document.body;
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
    const container = document.querySelector(
        'main, [role="main"], [role="feed"], .products, .product-grid, .results, .search-results'
    ) || document.body;
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


async def apply_traversal_mode(
    page,
    surface: str | None,
    traversal_mode: str | None,
    max_scrolls: int,
    *,
    config: TraversalConfig | None = None,
    max_pages: int,
    request_delay_ms: int,
    page_content_with_retry: Callable[..., Awaitable[str]],
    wait_for_surface_readiness: Callable[..., Awaitable[dict[str, object] | None]],
    wait_for_listing_readiness: Callable[..., Awaitable[dict[str, object] | None]],
    peek_next_page_signal: Callable[..., Awaitable[dict[str, object] | None]],
    click_and_observe_next_page: Callable[..., Awaitable[str | AdvanceResult]] | None = None,
    advance_next_page_fn: Callable[..., Awaitable[AdvanceResult]] | None = None,
    has_load_more_control: Callable[..., Awaitable[bool]],
    dismiss_cookie_consent: Callable[..., Awaitable[None]],
    pause_after_navigation: Callable[..., Awaitable[None]],
    expand_all_interactive_elements: Callable[..., Awaitable[dict[str, object]]],
    flatten_shadow_dom: Callable[..., Awaitable[None]],
    cooperative_sleep_ms: Callable[..., Awaitable[None]],
    snapshot_listing_page_metrics: Callable[..., Awaitable[dict[str, object]]],
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> TraversalResult:
    config = _resolved_config(config)
    logger.info("[traversal] starting mode=%s surface=%s", traversal_mode, surface)

    def _log_and_return(result: TraversalResult) -> TraversalResult:
        logger.info(
            "[traversal] done mode=%s html_len=%s stop_reason=%s",
            result.summary.get("mode", traversal_mode),
            len(result.html or "") if result.html else 0,
            result.summary.get("stop_reason"),
        )
        return result

    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface.endswith("_detail"):
        return _log_and_return(TraversalResult(
            summary={
                "mode": traversal_mode,
                "attempted": False,
                "stop_reason": "detail_surface",
            }
        ))
    collected_fragments: list[str] = []
    seen_fragment_hashes: set[str] = set()
    captured_fragment_bytes = 0
    # Card-level dedup: identity string → True.  Prevents virtualized grids
    # from producing duplicate cards across scroll steps.
    seen_card_identities: set[str] = set()
    # Container child signatures seen so far, used for DOM-diff fallback
    # when CARD_SELECTORS match 0 elements.
    known_container_sigs: list[str] = []

    card_selectors = _card_selectors_for_surface(surface)

    async def _capture_fragment(page, marker: str) -> None:
        """Capture only card-level HTML instead of full page content.

        Strategy:
        1. Run JS with CARD_SELECTORS to extract matching card outerHTML,
           deduplicating by stable identity (href / data-id).
        2. If selectors match nothing, fall back to a DOM diff of the listing
           container (new children since the last step).
        3. Only if both produce nothing, fall back to full page.content() —
           but this path should be rare.
        """
        nonlocal captured_fragment_bytes
        if len(collected_fragments) >= _MAX_TRAVERSAL_FRAGMENTS:
            return

        fragment_parts: list[str] = []
        try:
            result = await page.evaluate(_JS_EXTRACT_CARDS, card_selectors)
            cards = result.get("cards", []) if isinstance(result, dict) else []
            for card in cards:
                identity = card.get("identity", "")
                card_html = card.get("html", "")
                if not card_html:
                    continue
                if identity and identity in seen_card_identities:
                    continue
                if identity:
                    seen_card_identities.add(identity)
                fragment_parts.append(card_html)
        except (PlaywrightError, Exception):
            logger.debug("Card-selector extraction failed at %s", marker, exc_info=True)
            cards = []

        # Fallback: DOM diff of listing container when selectors matched nothing.
        if not fragment_parts:
            try:
                diff_items = await page.evaluate(
                    _JS_CONTAINER_DIFF, known_container_sigs
                )
                if isinstance(diff_items, list):
                    for item in diff_items:
                        item_html = item.get("html", "") if isinstance(item, dict) else ""
                        item_sig = item.get("sig", "") if isinstance(item, dict) else ""
                        if not item_html:
                            continue
                        fragment_parts.append(item_html)
                        if item_sig:
                            known_container_sigs.append(item_sig)
            except (PlaywrightError, Exception):
                logger.debug("Container-diff fallback failed at %s", marker, exc_info=True)

        # Last resort: full page content (original behavior).
        if not fragment_parts:
            html = await page_content_with_retry(page, checkpoint=checkpoint)
            if not isinstance(html, str) or not html:
                return
            encoded_size = len(html.encode("utf-8", errors="ignore"))
            if encoded_size > _MAX_TRAVERSAL_FRAGMENT_BYTES:
                return
            if captured_fragment_bytes + encoded_size > _MAX_TRAVERSAL_TOTAL_BYTES:
                return
            fingerprint = hashlib.sha1(
                html.encode("utf-8", errors="ignore")
            ).hexdigest()
            if fingerprint in seen_fragment_hashes:
                return
            seen_fragment_hashes.add(fingerprint)
            captured_fragment_bytes += encoded_size
            collected_fragments.append(
                f"<!-- PAGE BREAK:traversal:{marker}:{getattr(page, 'url', '')} -->\n{html}"
            )
            return

        # Assemble targeted fragment from card parts.
        html = "\n".join(fragment_parts)
        encoded_size = len(html.encode("utf-8", errors="ignore"))
        if captured_fragment_bytes + encoded_size > _MAX_TRAVERSAL_TOTAL_BYTES:
            return
        captured_fragment_bytes += encoded_size
        collected_fragments.append(
            f"<!-- PAGE BREAK:traversal:{marker}:{getattr(page, 'url', '')} -->\n{html}"
        )

    async def _capture_initial_fragment(page, marker: str) -> None:
        if collected_fragments:
            return
        await _capture_fragment(page, marker)

    if traversal_mode == "scroll":
        await _capture_initial_fragment(page, "scroll-initial")
        summary = await scroll_to_bottom(
            page,
            max_scrolls,
            config=config,
            request_delay_ms=request_delay_ms,
            cooperative_sleep_ms=cooperative_sleep_ms,
            snapshot_listing_page_metrics=snapshot_listing_page_metrics,
            capture_dom_fragment=lambda current_page, index: _capture_fragment(
                current_page, f"scroll-{index}"
            ),
            checkpoint=checkpoint,
        )
        await _capture_fragment(page, "scroll-final")
        summary["pages_collected"] = len(collected_fragments)
        summary["captured_fragment_bytes"] = captured_fragment_bytes
        return _log_and_return(TraversalResult(
            html="\n".join(collected_fragments) if collected_fragments else await page_content_with_retry(page, checkpoint=checkpoint),
            summary=summary,
        ))

    if traversal_mode == "load_more":
        await _capture_initial_fragment(page, "load-more-initial")
        summary = await click_load_more(
            page,
            max_scrolls,
            config=config,
            request_delay_ms=request_delay_ms,
            cooperative_sleep_ms=cooperative_sleep_ms,
            snapshot_listing_page_metrics=snapshot_listing_page_metrics,
            capture_dom_fragment=lambda current_page, index: _capture_fragment(
                current_page, f"load-more-{index}"
            ),
            checkpoint=checkpoint,
        )
        await _capture_fragment(page, "load-more-final")
        summary["pages_collected"] = len(collected_fragments)
        summary["captured_fragment_bytes"] = captured_fragment_bytes
        return _log_and_return(TraversalResult(
            html="\n".join(collected_fragments) if collected_fragments else await page_content_with_retry(page, checkpoint=checkpoint),
            summary=summary,
        ))

    if traversal_mode == "paginate":
        return _log_and_return(await collect_paginated_html(
            page,
            config=config,
            surface=surface,
            max_pages=max_pages,
            request_delay_ms=request_delay_ms,
            page_content_with_retry=page_content_with_retry,
            wait_for_surface_readiness=wait_for_surface_readiness,
            wait_for_listing_readiness=wait_for_listing_readiness,
            click_and_observe_next_page=click_and_observe_next_page,
            advance_next_page_fn=advance_next_page_fn,
            dismiss_cookie_consent=dismiss_cookie_consent,
            pause_after_navigation=pause_after_navigation,
            expand_all_interactive_elements=expand_all_interactive_elements,
            flatten_shadow_dom=flatten_shadow_dom,
            checkpoint=checkpoint,
        ))
    if traversal_mode == "auto":
        auto_steps: list[dict[str, object]] = []
        await _capture_initial_fragment(page, "auto-initial")

        scroll_summary = await scroll_to_bottom(
            page,
            max_scrolls,
            config=config,
            request_delay_ms=request_delay_ms,
            cooperative_sleep_ms=cooperative_sleep_ms,
            snapshot_listing_page_metrics=snapshot_listing_page_metrics,
            capture_dom_fragment=lambda current_page, index: _capture_fragment(
                current_page, f"auto-scroll-{index}"
            ),
            checkpoint=checkpoint,
        )
        auto_steps.append(scroll_summary)
        if await has_load_more_control(page, config):
            load_more_summary = await click_load_more(
                page,
                max_scrolls,
                config=config,
                request_delay_ms=request_delay_ms,
                cooperative_sleep_ms=cooperative_sleep_ms,
                snapshot_listing_page_metrics=snapshot_listing_page_metrics,
                capture_dom_fragment=lambda current_page, index: _capture_fragment(
                    current_page, f"auto-load-more-{index}"
                ),
                checkpoint=checkpoint,
            )
            auto_steps.append(load_more_summary)
        
        await _capture_fragment(page, "auto-pre-pagination")
        pre_pagination_html = "\n".join(collected_fragments) if collected_fragments else await page_content_with_retry(page, checkpoint=checkpoint)
        
        next_page_signal = await peek_next_page_signal(page)
        if next_page_signal:
            paginated = await collect_paginated_html(
                page,
                config=config,
                surface=surface,
                max_pages=max_pages,
                request_delay_ms=request_delay_ms,
                page_content_with_retry=page_content_with_retry,
                wait_for_surface_readiness=wait_for_surface_readiness,
                wait_for_listing_readiness=wait_for_listing_readiness,
                click_and_observe_next_page=click_and_observe_next_page,
                advance_next_page_fn=advance_next_page_fn,
                dismiss_cookie_consent=dismiss_cookie_consent,
                pause_after_navigation=pause_after_navigation,
                expand_all_interactive_elements=expand_all_interactive_elements,
                flatten_shadow_dom=flatten_shadow_dom,
                checkpoint=checkpoint,
            )
            if pre_pagination_html:
                paginated.html = f"<!-- PAGE BREAK: auto pre-pagination -->\n{pre_pagination_html}\n" + (paginated.html or "")
            
            paginated.summary.setdefault("steps", [])
            paginated.summary["steps"] = [
                *auto_steps,
                *list(paginated.summary.get("steps") or []),
            ]
            paginated.summary.setdefault("mode", "auto")
            paginated.summary["pages_collected"] = int(
                paginated.summary.get("pages_collected", 0) or 0
            ) + len(collected_fragments)
            paginated.summary["captured_fragment_bytes"] = captured_fragment_bytes
            return _log_and_return(paginated)

        return _log_and_return(TraversalResult(
            html=pre_pagination_html,
            summary={
                "mode": "auto",
                "attempted": True,
                "steps": auto_steps,
                "pages_collected": len(collected_fragments),
                "captured_fragment_bytes": captured_fragment_bytes,
                "stop_reason": "no_pagination_after_scroll_or_load_more",
            }
        ))
    return _log_and_return(TraversalResult(
        summary={
            "mode": traversal_mode,
            "attempted": False,
            "stop_reason": "mode_not_enabled",
        }
    ))


async def collect_paginated_html(
    page,
    *,
    config: TraversalConfig | None = None,
    surface: str | None = None,
    max_pages: int,
    request_delay_ms: int,
    page_content_with_retry: Callable[..., Awaitable[str]],
    wait_for_surface_readiness: Callable[..., Awaitable[dict[str, object] | None]],
    wait_for_listing_readiness: Callable[..., Awaitable[dict[str, object] | None]],
    click_and_observe_next_page: Callable[..., Awaitable[str | AdvanceResult]] | None = None,
    advance_next_page_fn: Callable[..., Awaitable[AdvanceResult]] | None = None,
    dismiss_cookie_consent: Callable[..., Awaitable[None]],
    pause_after_navigation: Callable[..., Awaitable[None]],
    expand_all_interactive_elements: Callable[..., Awaitable[dict[str, object]]],
    flatten_shadow_dom: Callable[..., Awaitable[None]],
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> TraversalResult:
    config = _resolved_config(config)
    if advance_next_page_fn is None and click_and_observe_next_page is None:
        raise ValueError("no pagination callback provided")

    fragments: list[str] = []
    visited_urls: set[str] = set()
    stop_reason = "max_pages_reached"
    steps: list[dict[str, object]] = []
    current_url = str(page.url or "").strip()
    if current_url:
        visited_urls.add(current_url)

    # Resolve the advance callback.  Prefer advance_next_page_fn (aware of
    # already_navigated); fall back to the legacy click_and_observe_next_page
    # wrapper for backward compatibility.
    async def _legacy_advance(pg, *, checkpoint=None) -> AdvanceResult:
        if click_and_observe_next_page is None:
            raise ValueError("no pagination callback provided")
        result = await click_and_observe_next_page(pg, checkpoint=checkpoint)  # type: ignore[misc]
        if isinstance(result, AdvanceResult):
            return AdvanceResult(
                url=result.url,
                already_navigated=result.already_navigated,
            )
        return AdvanceResult(url=result, already_navigated=False)

    _advance = advance_next_page_fn if advance_next_page_fn is not None else _legacy_advance

    page_limit = max(1, int(max_pages or 1))
    for page_index in range(page_limit):
        page_html = await page_content_with_retry(page, checkpoint=checkpoint)
        fragments.append(
            f"<!-- PAGE BREAK:{page_index + 1}:{page.url} -->\n{page_html}"
        )
        steps.append(
            {
                "action": "capture_page",
                "page_index": page_index + 1,
                "url": str(page.url or "").strip() or None,
                "html_length": len(page_html or ""),
            }
        )
        if page_index + 1 >= page_limit:
            break
        current_url = str(page.url or "").strip()
        advance_result = await _advance(page, checkpoint=checkpoint)
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
            logger.warning(
                "Rejected pagination URL %s from %s: %s", next_page_url, page.url, exc
            )
            stop_reason = "rejected_next_page"
            break
        visited_urls.add(next_page_url)
        # Only navigate when the advance step did not already mutate the page
        # (e.g. it returned an <a href> URL but did not click).
        needs_goto = not advance_result.already_navigated and not page_advanced_in_place
        if needs_goto:
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
            await wait_for_surface_readiness(
                page,
                surface=surface,
                checkpoint=checkpoint,
            )
            steps.append(
                {
                    "action": "goto_next_page",
                    "page_index": page_index + 2,
                    "url": next_page_url,
                    "in_place": False,
                }
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
        await dismiss_cookie_consent(page, checkpoint=checkpoint)
        await pause_after_navigation(request_delay_ms, checkpoint=checkpoint)
        await expand_all_interactive_elements(page, checkpoint=checkpoint)
        await flatten_shadow_dom(page)
        await wait_for_listing_readiness(page, surface, checkpoint=checkpoint)
    return TraversalResult(
        html="\n".join(fragments),
        summary={
            "mode": "paginate",
            "attempted": True,
            "pages_collected": len(fragments),
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
        await target.click(timeout=1500)
    except PlaywrightError:
        logger.debug("Failed to click next-page control", exc_info=True)
        return AdvanceResult()
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except PlaywrightTimeoutError:
        logger.debug(
            "Timed out waiting for domcontentloaded after pagination click",
            exc_info=True,
        )

    waited_ms = 0
    poll_ms = 250
    while waited_ms < 3000:
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
) -> dict[str, object]:
    config = _resolved_config(config)
    prev_height = 0
    previous_metrics: dict[str, object] | None = None
    steps: list[dict[str, object]] = []
    stop_reason = "max_scrolls_reached"
    forced_probe_used = False
    weak_progress_streak = 0
    seen_identities: set[str] = set()
    max_iterations = min(max(0, int(max_scrolls or 0)), 50)
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
        
        # FIX: Force a mandatory sleep so the browser's JS has time to trigger the API fetch
        # before we check for networkidle, avoiding instant 0ms returns.
        await cooperative_sleep_ms(max(500, request_delay_ms), checkpoint=checkpoint)
        
        # FIX: Wait for network idle to ensure XHRs for new items complete,
        # falling back to the cooperative sleep if it times out.
        if hasattr(page, "wait_for_load_state"):
            try:
                from playwright.async_api import TimeoutError as PwTimeoutError
                await page.wait_for_load_state("networkidle", timeout=config.scroll_wait_min_ms)
            except (PwTimeoutError, PlaywrightError):
                # FIX: Do nothing! The time has already elapsed during wait_for_load_state timeout
                pass
            except (BrokenPipeError, ConnectionResetError) as exc:
                logger.warning("Ignoring transient OS error during scroll wait_for_load_state: %s", exc)
        else:
            await cooperative_sleep_ms(
                config.scroll_wait_min_ms,
                checkpoint=checkpoint,
            )
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
            await cooperative_sleep_ms(500, checkpoint=checkpoint)
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
        steps.append(
            {
                "action": "scroll",
                "index": index + 1,
                "height_before": current_height,
                "height_after": next_height,
                "target": scroll_result.get("target"),
                "forced_probe": forced_probe_used,
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
        if weak_progress_streak >= 2:
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
                """
            ({ currentHeight, forceProbe }) => {
                const candidates = [
                    document.querySelector("main"),
                    ...Array.from(document.querySelectorAll("[role='main'], [role='feed'], [role='list'], .products, .product-grid, .product-list, .results, .search-results, .items, .list, .listing"))
                ].filter(Boolean);
                const score = (el) => {
                    const links = el.querySelectorAll("a[href]").length;
                    const cards = el.querySelectorAll("article, li, [class*='product'], [class*='result'], [class*='item']").length;
                    const scrollable = Math.max(0, (el.scrollHeight || 0) - (el.clientHeight || 0));
                    return (links * 2) + cards + (scrollable > 150 ? 10 : 0);
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
                    target.scrollHeight > (target.clientHeight + 150)
                        ? target
                        : root;
                const label = activeTarget === root
                    ? "window"
                    : (activeTarget.getAttribute("data-testid") || activeTarget.getAttribute("id") || activeTarget.className || activeTarget.tagName || "container").toString().slice(0, 120);
                if (activeTarget === root) {
                    const nextTop = forceProbe
                        ? Math.max((window.scrollY || 0) + Math.max(window.innerHeight || 0, 600), currentHeight || 0)
                        : (currentHeight || root.scrollHeight || 0);
                    window.scrollTo(0, nextTop);
                } else {
                    const nextTop = forceProbe
                        ? Math.max((activeTarget.scrollTop || 0) + Math.max(activeTarget.clientHeight || 0, 600), currentHeight || 0)
                        : Math.max(currentHeight || 0, activeTarget.scrollTop || 0);
                    activeTarget.scrollTo(0, nextTop || activeTarget.scrollHeight || 0);
                }
                return { target: label };
            }
            """,
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
                    
                    # FIX: Force mandatory sleep so browser's JS has time to trigger API fetch
                    await cooperative_sleep_ms(max(500, request_delay_ms), checkpoint=checkpoint)
                    
                    # FIX: Wait for network idle to ensure XHRs for new items complete,
                    # falling back to the cooperative sleep if it times out.
                    if hasattr(page, "wait_for_load_state"):
                        try:
                            from playwright.async_api import TimeoutError as PwTimeoutError
                            await page.wait_for_load_state("networkidle", timeout=config.load_more_wait_min_ms)
                        except (PwTimeoutError, PlaywrightError):
                            # FIX: Do nothing! The time has already elapsed during wait_for_load_state timeout
                            pass
                        except (BrokenPipeError, ConnectionResetError) as exc:
                            logger.warning("Ignoring transient OS error during load-more wait_for_load_state: %s", exc)
                    else:
                        await cooperative_sleep_ms(
                            config.load_more_wait_min_ms,
                            checkpoint=checkpoint,
                        )
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
                            "progressed": progressed,
                        }
                    )
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
