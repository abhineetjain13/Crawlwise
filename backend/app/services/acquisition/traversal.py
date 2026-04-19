from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
import logging
from urllib.parse import urljoin, urlsplit

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
    html_fragments: list[tuple[str, bool]] = field(default_factory=list)
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
    normalized_surface = str(surface or "").strip().lower()
    normalized_mode = str(traversal_mode or "").strip().lower()
    if normalized_mode in {"single", "sitemap", "crawl"}:
        return False
    return "listing" in normalized_surface and normalized_mode in {
        "auto",
        "scroll",
        "load_more",
        "paginate",
    }


async def execute_listing_traversal(
    page,
    *,
    surface: str,
    traversal_mode: str,
    max_pages: int,
    max_scrolls: int,
) -> TraversalResult:
    normalized_mode = str(traversal_mode or "").strip().lower()
    result = TraversalResult(requested_mode=normalized_mode)
    if not should_run_traversal(surface, normalized_mode):
        _set_stop_reason(result, "not_listing_or_disabled", surface=surface, traversal_mode=normalized_mode)
        result.html_fragments = [(await page.content(), True)]
        return result

    selected_mode: str | None = normalized_mode
    if normalized_mode == "auto":
        selected_mode = await _detect_auto_mode(page, surface=surface)
        result.selected_mode = selected_mode
        if not selected_mode:
            _set_stop_reason(result, "no_mode_detected", surface=surface, traversal_mode=normalized_mode)
            result.card_count = (await _page_snapshot(page, surface=surface))["card_count"]
            result.html_fragments = [(await page.content(), True)]
            return result
    else:
        result.selected_mode = normalized_mode

    result.activated = True
    if selected_mode == "scroll":
        await _run_scroll_traversal(
            page,
            surface=surface,
            max_scrolls=max_scrolls,
            result=result,
        )
    elif selected_mode == "load_more":
        await _run_load_more_traversal(
            page,
            surface=surface,
            max_clicks=max(1, int(max_pages)),
            result=result,
        )
    elif selected_mode == "paginate":
        await _run_paginate_traversal(
            page,
            surface=surface,
            max_pages=max_pages,
            result=result,
        )
    else:
        _set_stop_reason(result, "unsupported_mode", surface=surface, traversal_mode=normalized_mode)

    if not result.html_fragments:
        result.html_fragments = [(await page.content(), True)]
    return result


async def _detect_auto_mode(page, *, surface: str) -> str | None:
    if await _find_actionable_locator(page, "next_page") is not None:
        return "paginate"
    if await _find_actionable_locator(page, "load_more") is not None:
        return "load_more"
    if await _has_scroll_signals(page, surface=surface):
        return "scroll"
    return None


async def _run_scroll_traversal(
    page,
    *,
    surface: str,
    max_scrolls: int,
    result: TraversalResult,
) -> None:
    max_iterations = min(
        max(1, int(max_scrolls)),
        int(crawler_runtime_settings.traversal_max_iterations_cap),
    )
    weak_progress_streak = 0
    await _append_html_fragment(page, result, surface=surface)
    previous = await _page_snapshot(page, surface=surface)
    for _ in range(max_iterations):
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
        await page.wait_for_timeout(int(crawler_runtime_settings.scroll_wait_min_ms))
        await _settle_after_action(page)
        current = await _page_snapshot(page, surface=surface)
        if _snapshot_progressed(previous, current):
            result.progress_events += 1
            await _append_html_fragment(page, result, surface=surface)
            weak_progress_streak = 0
        else:
            weak_progress_streak += 1
        previous = current
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
) -> None:
    max_iterations = min(
        max(1, int(max_clicks)),
        int(crawler_runtime_settings.traversal_max_iterations_cap),
    )
    await _append_html_fragment(page, result, surface=surface)
    previous = await _page_snapshot(page, surface=surface)
    for _ in range(max_iterations):
        locator = await _find_actionable_locator(page, "load_more")
        if locator is None:
            _set_stop_reason(result, "load_more_not_found", surface=surface)
            break
        result.iterations += 1
        result.load_more_clicks += 1
        current_url = page.url
        await locator.click(timeout=1000)
        await page.wait_for_timeout(int(crawler_runtime_settings.load_more_wait_min_ms))
        await _wait_for_transition(page, previous_url=current_url)
        current = await _page_snapshot(page, surface=surface)
        if _snapshot_progressed(previous, current):
            result.progress_events += 1
            await _append_html_fragment(page, result, surface=surface)
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
) -> None:
    previous = await _page_snapshot(page, surface=surface)
    result.card_count = previous["card_count"]
    await _append_html_fragment(page, result, surface=surface)
    page_limit = max(1, int(max_pages))
    for _ in range(max(0, page_limit - 1)):
        locator = await _find_actionable_locator(page, "next_page")
        if locator is None:
            _set_stop_reason(result, "next_page_not_found", surface=surface)
            break
        result.iterations += 1
        current_url = page.url
        href = await locator.get_attribute("href")
        normalized_href = str(href or "").strip().lower()
        if normalized_href.startswith("#"):
            _set_stop_reason(result, "paginate_fragment_only", surface=surface)
            break
        if href and not normalized_href.startswith("javascript:"):
            next_url = urljoin(current_url, href)
            if not _is_same_origin(current_url, next_url):
                _set_stop_reason(result, "paginate_off_domain", surface=surface)
                break
            await page.goto(
                next_url,
                wait_until="domcontentloaded",
                timeout=int(crawler_runtime_settings.pagination_navigation_timeout_ms),
            )
            await _wait_for_transition(
                page,
                previous_url=current_url,
                navigation_expected=True,
            )
        else:
            await locator.click(timeout=1000)
            await _wait_for_transition(page, previous_url=current_url)
        current = await _page_snapshot(page, surface=surface)
        if page.url != current_url or _snapshot_progressed(previous, current):
            await _append_html_fragment(page, result, surface=surface)
            result.progress_events += 1
            result.pages_advanced += 1
            previous = current
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
    return None


async def _append_html_fragment(
    page,
    result: TraversalResult,
    *,
    surface: str,
) -> None:
    html = await page.content()
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
                return fragments
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
    fragments: list[str] = []
    used_bytes = 0
    for node in parser.css("article, li, div"):
        if node.css_first("a[href]") is None:
            continue
        fragment = str(node.html or "").strip()
        if not fragment or fragment in seen:
            continue
        fragment_bytes = len(fragment.encode("utf-8"))
        if used_bytes + fragment_bytes > byte_budget:
            break
        seen.add(fragment)
        fragments.append(fragment)
        used_bytes += fragment_bytes
    return fragments


def _fragments_bytes(fragments: list[str]) -> int:
    return sum(len(fragment.encode("utf-8")) for fragment in fragments if fragment)


async def _page_snapshot(page, *, surface: str) -> dict[str, int]:
    html = await page.content()
    return {
        "card_count": await _card_count(page, surface=surface),
        "content_signature": _content_signature(html),
        **(
            await page.evaluate(
                """
                () => {
                  const root = document.scrollingElement || document.documentElement || document.body;
                  const overflowContainers = Array.from(document.querySelectorAll("*")).filter((node) => {
                    const style = window.getComputedStyle(node);
                    return ["auto", "scroll"].includes(style.overflowY) && node.scrollHeight - node.clientHeight > 150;
                  }).length;
                  return {
                    scroll_height: Number(root?.scrollHeight || 0),
                    client_height: Number(root?.clientHeight || window.innerHeight || 0),
                    overflow_containers: overflowContainers,
                  };
                }
                """
            )
        ),
    }


async def _card_count(page, *, surface: str) -> int:
    selector_group = "jobs" if str(surface or "").strip().lower().startswith("job_") else "ecommerce"
    selectors = CARD_SELECTORS.get(selector_group) if isinstance(CARD_SELECTORS, dict) else []
    normalized_selectors = [
        str(selector).strip() for selector in list(selectors or []) if str(selector).strip()
    ]
    if not normalized_selectors:
        return 0
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
        return max(0, int(count or 0))
    except (TypeError, ValueError):
        return 0


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


def _content_signature(html: str) -> str:
    text = str(html or "").strip()
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


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


async def _settle_after_action(page) -> None:
    try:
        await page.wait_for_load_state(
            "networkidle",
            timeout=int(crawler_runtime_settings.pagination_post_click_settle_timeout_ms),
        )
    except Exception:
        await page.wait_for_timeout(
            max(
                int(crawler_runtime_settings.traversal_min_settle_wait_ms),
                int(crawler_runtime_settings.pagination_post_click_poll_ms),
            )
        )


async def _wait_for_transition(
    page,
    *,
    previous_url: str,
    navigation_expected: bool = False,
) -> None:
    await _wait_for_navigation_if_changed(
        page,
        previous_url=previous_url,
        navigation_expected=navigation_expected,
    )
    await _settle_after_action(page)


async def _wait_for_navigation_if_changed(
    page,
    *,
    previous_url: str,
    navigation_expected: bool,
) -> None:
    if navigation_expected or page.url != previous_url:
        await _wait_for_domcontentloaded(page)
        return
    poll_ms = max(1, int(crawler_runtime_settings.pagination_post_click_poll_ms))
    deadline_ms = max(
        poll_ms,
        int(crawler_runtime_settings.pagination_post_click_timeout_ms),
    )
    waited_ms = 0
    while waited_ms < deadline_ms:
        await page.wait_for_timeout(poll_ms)
        waited_ms += poll_ms
        if page.url != previous_url:
            await _wait_for_domcontentloaded(page)
            return


async def _wait_for_domcontentloaded(page) -> None:
    try:
        await page.wait_for_load_state(
            "domcontentloaded",
            timeout=int(
                crawler_runtime_settings.pagination_post_click_domcontentloaded_timeout_ms
            ),
        )
    except Exception:
        logger.debug("Traversal domcontentloaded wait failed", exc_info=True)
        return


def _is_same_origin(current_url: str, next_url: str) -> bool:
    current = urlsplit(str(current_url or ""))
    next_value = urlsplit(str(next_url or ""))
    return (
        str(current.scheme or "").lower(),
        str(current.netloc or "").lower(),
    ) == (
        str(next_value.scheme or "").lower(),
        str(next_value.netloc or "").lower(),
    )
