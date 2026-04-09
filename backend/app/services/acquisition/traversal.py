from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin

from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from app.services.pipeline_config import (
    BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS,
    LISTING_MIN_ITEMS,
    LOAD_MORE_SELECTORS,
    LOAD_MORE_WAIT_MIN_MS,
    PAGINATION_NAVIGATION_TIMEOUT_MS,
    PAGINATION_NEXT_SELECTORS,
    SCROLL_WAIT_MIN_MS,
)
from app.services.url_safety import validate_public_target

logger = logging.getLogger(__name__)


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
    click_and_observe_next_page: Callable[..., Awaitable[str]],
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
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface.endswith("_detail"):
        return TraversalResult(
            summary={
                "mode": traversal_mode,
                "attempted": False,
                "stop_reason": "detail_surface",
            }
        )
    if traversal_mode == "scroll":
        summary = await scroll_to_bottom(
            page,
            max_scrolls,
            config=config,
            request_delay_ms=request_delay_ms,
            cooperative_sleep_ms=cooperative_sleep_ms,
            snapshot_listing_page_metrics=snapshot_listing_page_metrics,
            checkpoint=checkpoint,
        )
        return TraversalResult(summary=summary)
    if traversal_mode == "load_more":
        summary = await click_load_more(
            page,
            max_scrolls,
            config=config,
            request_delay_ms=request_delay_ms,
            cooperative_sleep_ms=cooperative_sleep_ms,
            snapshot_listing_page_metrics=snapshot_listing_page_metrics,
            checkpoint=checkpoint,
        )
        return TraversalResult(summary=summary)
    if traversal_mode == "paginate":
        return await collect_paginated_html(
            page,
            config=config,
            surface=surface,
            max_pages=max_pages,
            request_delay_ms=request_delay_ms,
            page_content_with_retry=page_content_with_retry,
            wait_for_surface_readiness=wait_for_surface_readiness,
            wait_for_listing_readiness=wait_for_listing_readiness,
            click_and_observe_next_page=click_and_observe_next_page,
            dismiss_cookie_consent=dismiss_cookie_consent,
            pause_after_navigation=pause_after_navigation,
            expand_all_interactive_elements=expand_all_interactive_elements,
            flatten_shadow_dom=flatten_shadow_dom,
            checkpoint=checkpoint,
        )
    if traversal_mode == "auto":
        auto_steps: list[dict[str, object]] = []
        scroll_summary = await scroll_to_bottom(
            page,
            max_scrolls,
            config=config,
            request_delay_ms=request_delay_ms,
            cooperative_sleep_ms=cooperative_sleep_ms,
            snapshot_listing_page_metrics=snapshot_listing_page_metrics,
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
                checkpoint=checkpoint,
            )
            auto_steps.append(load_more_summary)
        next_page_url = await click_and_observe_next_page(
            page,
            checkpoint=checkpoint,
        )
        if next_page_url:
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
                dismiss_cookie_consent=dismiss_cookie_consent,
                pause_after_navigation=pause_after_navigation,
                expand_all_interactive_elements=expand_all_interactive_elements,
                flatten_shadow_dom=flatten_shadow_dom,
                checkpoint=checkpoint,
            )
            paginated.summary.setdefault("steps", [])
            paginated.summary["steps"] = [
                *auto_steps,
                *list(paginated.summary.get("steps") or []),
            ]
            paginated.summary.setdefault("mode", "auto")
            return paginated
        return TraversalResult(
            summary={
                "mode": "auto",
                "attempted": True,
                "steps": auto_steps,
                "stop_reason": "no_pagination_after_scroll_or_load_more",
            }
        )
    return TraversalResult(
        summary={
            "mode": traversal_mode,
            "attempted": False,
            "stop_reason": "mode_not_enabled",
        }
    )


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
    click_and_observe_next_page: Callable[..., Awaitable[str]],
    dismiss_cookie_consent: Callable[..., Awaitable[None]],
    pause_after_navigation: Callable[..., Awaitable[None]],
    expand_all_interactive_elements: Callable[..., Awaitable[dict[str, object]]],
    flatten_shadow_dom: Callable[..., Awaitable[None]],
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> TraversalResult:
    config = _resolved_config(config)
    fragments: list[str] = []
    visited_urls: set[str] = set()
    stop_reason = "max_pages_reached"
    steps: list[dict[str, object]] = []
    current_url = str(page.url or "").strip()
    if current_url:
        visited_urls.add(current_url)

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
        next_page_url = await click_and_observe_next_page(page, checkpoint=checkpoint)
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
        if not page_advanced_in_place:
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
                    "in_place": True,
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
            "page_count": len(fragments),
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


async def click_and_observe_next_page(
    page,
    *,
    config: TraversalConfig | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> str:
    config = _resolved_config(config)
    next_page_url = await find_next_page_url_anchor_only(page, config=config)
    if next_page_url:
        return next_page_url

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

    click_selectors = [
        *config.pagination_next_selectors,
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
        except PlaywrightError:
            logger.debug(
                "Failed to inspect clickable pagination selector %s",
                selector,
                exc_info=True,
            )
    if target is None:
        return ""

    initial_url = str(page.url or "").strip()
    initial_state = await snapshot_pagination_state(page)
    initial_hash = await _container_hash()
    try:
        await target.click(timeout=1500)
    except PlaywrightError:
        logger.debug("Failed to click next-page control", exc_info=True)
        return ""
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
            return current_url
        current_state = await snapshot_pagination_state(page)
        if pagination_state_changed(initial_state, current_state):
            return current_url or initial_url
        if await _container_hash() != initial_hash:
            return current_url
    return ""


async def scroll_to_bottom(
    page,
    max_scrolls: int,
    *,
    config: TraversalConfig | None = None,
    request_delay_ms: int,
    cooperative_sleep_ms: Callable[..., Awaitable[None]],
    snapshot_listing_page_metrics: Callable[..., Awaitable[dict[str, object]]],
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, object]:
    config = _resolved_config(config)
    prev_height = 0
    previous_metrics: dict[str, object] | None = None
    steps: list[dict[str, object]] = []
    stop_reason = "max_scrolls_reached"
    forced_probe_used = False
    weak_progress_streak = 0
    max_iterations = min(max(0, int(max_scrolls or 0)), 50)
    for index in range(max_iterations):
        current_height = await current_scroll_height(page)
        current_metrics = await snapshot_listing_page_metrics(page)
        if current_height == prev_height and not listing_progressed(
            previous_metrics, current_metrics
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
        # FIX: Wait for network idle to ensure XHRs for new items complete,
        # falling back to the cooperative sleep if it times out.
        if hasattr(page, "wait_for_load_state"):
            try:
                from playwright.async_api import TimeoutError as PwTimeoutError
                await page.wait_for_load_state("networkidle", timeout=max(request_delay_ms, config.scroll_wait_min_ms))
            except (PwTimeoutError, Exception):
                await cooperative_sleep_ms(
                    max(request_delay_ms, config.scroll_wait_min_ms),
                    checkpoint=checkpoint,
                )
        else:
            await cooperative_sleep_ms(
                max(request_delay_ms, config.scroll_wait_min_ms),
                checkpoint=checkpoint,
            )
        next_height = await current_scroll_height(page)
        next_metrics = await snapshot_listing_page_metrics(page)
        progress_kind = classify_progress(
            previous=current_metrics,
            current=next_metrics,
            height_before=current_height,
            height_after=next_height,
        )
        progressed = progress_kind != "none"
        if not progressed:
            # One extra settle window for delayed/virtualized rendering pages.
            await cooperative_sleep_ms(500, checkpoint=checkpoint)
            settled_height = await current_scroll_height(page)
            settled_metrics = await snapshot_listing_page_metrics(page)
            settled_progress_kind = classify_progress(
                previous=current_metrics,
                current=settled_metrics,
                height_before=next_height,
                height_after=settled_height,
            )
            if settled_progress_kind != "none":
                progressed = True
                progress_kind = settled_progress_kind
                next_height = settled_height
                next_metrics = settled_metrics

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
                "progressed": progressed,
            }
        )
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
    previous: dict[str, object] | None, current: dict[str, object] | None
) -> bool:
    if not previous or not current:
        return False
    for key in ("link_count", "cardish_count", "text_length", "html_length"):
        if int(current.get(key, 0) or 0) > int(previous.get(key, 0) or 0):
            return True
    return False


def classify_progress(
    *,
    previous: dict[str, object] | None,
    current: dict[str, object] | None,
    height_before: int,
    height_after: int,
) -> str:
    if listing_progressed(previous, current):
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
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, object]:
    config = _resolved_config(config)
    steps: list[dict[str, object]] = []
    stop_reason = "max_clicks_reached"
    for index in range(max_clicks):
        clicked = False
        previous_metrics = await snapshot_listing_page_metrics(page)
        for selector in config.load_more_selectors:
            try:
                button = page.locator(selector).first
                if await button.is_visible():
                    await button.click()
                    # FIX: Wait for network idle to ensure XHRs for new items complete,
                    # falling back to the cooperative sleep if it times out.
                    if hasattr(page, "wait_for_load_state"):
                        try:
                            from playwright.async_api import TimeoutError as PwTimeoutError
                            await page.wait_for_load_state("networkidle", timeout=max(request_delay_ms, config.load_more_wait_min_ms))
                        except (PwTimeoutError, Exception):
                            await cooperative_sleep_ms(
                                max(request_delay_ms, config.load_more_wait_min_ms),
                                checkpoint=checkpoint,
                            )
                    else:
                        await cooperative_sleep_ms(
                            max(request_delay_ms, config.load_more_wait_min_ms),
                            checkpoint=checkpoint,
                        )
                    current_metrics = await snapshot_listing_page_metrics(page)
                    progressed = listing_progressed(previous_metrics, current_metrics)
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
