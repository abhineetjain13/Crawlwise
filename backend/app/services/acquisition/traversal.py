from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS, PAGINATION_SELECTORS


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
    html_fragments: list[str] = field(default_factory=list)

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
        }


def should_run_traversal(surface: str | None, traversal_mode: str | None) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    normalized_mode = str(traversal_mode or "").strip().lower()
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
        result.stop_reason = "not_listing_or_disabled"
        result.html_fragments = [await page.content()]
        return result

    selected_mode = normalized_mode
    if normalized_mode == "auto":
        selected_mode = await _detect_auto_mode(page, surface=surface)
        result.selected_mode = selected_mode
        if not selected_mode:
            result.stop_reason = "no_mode_detected"
            result.card_count = (await _page_snapshot(page, surface=surface))["card_count"]
            result.html_fragments = [await page.content()]
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
        result.stop_reason = "unsupported_mode"

    if not result.html_fragments:
        result.html_fragments = [await page.content()]
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
            weak_progress_streak = 0
        else:
            weak_progress_streak += 1
        previous = current
        if weak_progress_streak > int(crawler_runtime_settings.traversal_weak_progress_streak_max):
            result.stop_reason = "no_scroll_progress"
            break
    else:
        result.stop_reason = "scroll_limit_reached"
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
    previous = await _page_snapshot(page, surface=surface)
    for _ in range(max_iterations):
        locator = await _find_actionable_locator(page, "load_more")
        if locator is None:
            result.stop_reason = "load_more_not_found"
            break
        result.iterations += 1
        result.load_more_clicks += 1
        await locator.click(timeout=1000)
        await page.wait_for_timeout(int(crawler_runtime_settings.load_more_wait_min_ms))
        await _settle_after_action(page)
        current = await _page_snapshot(page, surface=surface)
        if _snapshot_progressed(previous, current):
            result.progress_events += 1
            previous = current
            continue
        result.stop_reason = "load_more_no_progress"
        previous = current
        break
    else:
        result.stop_reason = "load_more_limit_reached"
    result.card_count = previous["card_count"]


async def _run_paginate_traversal(
    page,
    *,
    surface: str,
    max_pages: int,
    result: TraversalResult,
) -> None:
    html_fragments = [await page.content()]
    previous = await _page_snapshot(page, surface=surface)
    result.card_count = previous["card_count"]
    page_limit = max(1, int(max_pages))
    for _ in range(max(0, page_limit - 1)):
        locator = await _find_actionable_locator(page, "next_page")
        if locator is None:
            result.stop_reason = "next_page_not_found"
            break
        result.iterations += 1
        current_url = page.url
        href = await locator.get_attribute("href")
        if href and not str(href).strip().lower().startswith("javascript:"):
            await page.goto(
                urljoin(current_url, href),
                wait_until="domcontentloaded",
                timeout=int(crawler_runtime_settings.pagination_navigation_timeout_ms),
            )
        else:
            await locator.click(timeout=1000)
        await _settle_after_action(page)
        current = await _page_snapshot(page, surface=surface)
        html_fragments.append(await page.content())
        if page.url != current_url or _snapshot_progressed(previous, current):
            result.progress_events += 1
            result.pages_advanced += 1
            previous = current
            continue
        result.stop_reason = "paginate_no_progress"
        previous = current
        break
    else:
        result.stop_reason = "paginate_limit_reached"
    result.card_count = previous["card_count"]
    result.html_fragments = html_fragments


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
            continue
    return None


async def _page_snapshot(page, *, surface: str) -> dict[str, int]:
    return {
        "card_count": await _card_count(page, surface=surface),
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
    highest = 0
    for selector in list(selectors or []):
        try:
            highest = max(highest, await page.locator(str(selector)).count())
        except Exception:
            continue
    return highest


def _snapshot_progressed(previous: dict[str, int], current: dict[str, int]) -> bool:
    if int(current.get("card_count", 0)) > int(previous.get("card_count", 0)):
        return True
    if int(current.get("scroll_height", 0)) >= int(previous.get("scroll_height", 0)) + int(
        crawler_runtime_settings.traversal_force_probe_min_advance_px
    ):
        return True
    return False


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
