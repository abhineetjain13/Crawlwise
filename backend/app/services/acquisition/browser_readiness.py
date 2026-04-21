from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Comment

from app.services.acquisition.dom_runtime import get_page_html
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_value_core import clean_text


@dataclass(frozen=True, slots=True)
class HtmlAnalysis:
    html: str
    lowered_html: str
    soup: BeautifulSoup
    visible_text: str
    normalized_text: str
    title_text: str
    h1_present: bool


def analyze_html(html: str) -> HtmlAnalysis:
    text = str(html or "")
    soup = BeautifulSoup(text, "html.parser")
    visible_text = visible_text_from_soup(soup)
    return HtmlAnalysis(
        html=text,
        lowered_html=text.lower(),
        soup=soup,
        visible_text=visible_text,
        normalized_text=" ".join(visible_text.split()),
        title_text=clean_text(
            soup.title.get_text(" ", strip=True) if soup.title else ""
        ),
        h1_present=bool(soup.find("h1")),
    )


async def wait_for_listing_readiness_impl(
    page: Any,
    *,
    override: dict[str, object] | None,
) -> dict[str, object]:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    if not override:
        return {}
    selectors = [
        str(selector or "").strip()
        for selector in list(override.get("selectors") or [])
        if str(selector or "").strip()
    ]
    if not selectors:
        return {}
    max_wait_ms = int(
        override.get("max_wait_ms")
        or crawler_runtime_settings.listing_readiness_max_wait_ms
        or 0
    )
    if max_wait_ms <= 0:
        return {}
    combined_selector = ", ".join(selectors)
    try:
        await page.wait_for_selector(
            combined_selector,
            state="attached",
            timeout=max_wait_ms,
        )
    except asyncio.CancelledError:
        raise
    except PlaywrightTimeoutError as exc:
        return {
            "platform": str(override.get("platform") or ""),
            "max_wait_ms": max_wait_ms,
            "status": "timed_out",
            "attempted_selectors": selectors,
            "failures": [f"{combined_selector}:{type(exc).__name__}"],
        }
    matched_selector = None
    for selector in selectors:
        if await page.locator(selector).count():
            matched_selector = selector
            break
    return {
        "platform": str(override.get("platform") or ""),
        "combined_selector": combined_selector,
        "max_wait_ms": max_wait_ms,
        "matched_selector": matched_selector or combined_selector,
        "status": "matched",
    }


async def probe_browser_readiness_impl(
    page: Any,
    *,
    url: str,
    surface: str,
    listing_override: dict[str, object] | None = None,
    html: str | None = None,
    detail_readiness_hint_count,
) -> dict[str, object]:
    html_text = html if html is not None else await get_page_html(page)
    analysis = analyze_html(html_text or "")
    visible_text_length = len(analysis.normalized_text)
    structured_data_present = any(
        token in analysis.lowered_html
        for token in (
            '"@type":"product"',
            '"@type":"jobposting"',
            "application/ld+json",
            "__next_data__",
            "__nuxt__",
            "shopifyanalytics.meta",
        )
    )
    detail_hints = detail_readiness_hint_count(surface, analysis.visible_text.lower())
    detail_like = analysis.h1_present or structured_data_present or detail_hints > 0
    is_detail = "detail" in surface
    is_listing = "listing" in surface
    listing_card_count = 0
    matched_listing_selectors = 0
    if is_listing:
        listing_card_count = await listing_card_signal_count_impl(page, surface=surface)
        matched_listing_selectors = await count_matching_selectors(
            page,
            selectors=list(listing_override.get("selectors") or [])
            if isinstance(listing_override, dict)
            else [],
        )
    if is_detail:
        is_ready = bool(
            structured_data_present
            or (
                detail_like
                and detail_hints >= int(crawler_runtime_settings.detail_field_signal_min_count)
                and visible_text_length >= int(crawler_runtime_settings.browser_readiness_visible_text_min)
            )
        )
    elif is_listing:
        selector_match = bool(
            listing_card_count >= int(crawler_runtime_settings.listing_min_items)
            or matched_listing_selectors > 0
        )
        heuristic_ready = bool(
            not selector_match
            and visible_text_length
            >= int(crawler_runtime_settings.browser_readiness_visible_text_min) * 2
        )
        is_ready = selector_match or heuristic_ready
    else:
        is_ready = visible_text_length >= int(
            crawler_runtime_settings.browser_readiness_visible_text_min
        )
    return {
        "url": url,
        "surface": surface,
        "is_ready": is_ready,
        "detail_like": detail_like,
        "structured_data_present": structured_data_present,
        "visible_text_length": visible_text_length,
        "detail_hint_count": detail_hints,
        "listing_card_count": listing_card_count,
        "matched_listing_selectors": matched_listing_selectors,
        "h1_present": analysis.h1_present,
    }


async def listing_card_signal_count_impl(page: Any, *, surface: str) -> int:
    from app.services.acquisition.traversal import count_listing_cards

    return await count_listing_cards(
        page,
        surface=surface,
        allow_heuristic=False,
    )


async def count_matching_selectors(page: Any, *, selectors: list[str]) -> int:
    from playwright.async_api import Error as PlaywrightError

    matches = 0
    for selector in selectors:
        normalized = str(selector or "").strip()
        if not normalized:
            continue
        try:
            matches += int(await page.locator(normalized).count())
        except PlaywrightError:
            raise
        except Exception:
            continue
    return matches


def classify_browser_outcome_impl(
    *,
    html: str,
    html_bytes: int,
    blocked: bool,
    block_classification,
    traversal_result: Any = None,
    looks_like_low_content_shell,
) -> str:
    if block_classification.blocked or blocked:
        return "challenge_page"
    if traversal_result is not None and bool(getattr(traversal_result, "activated", False)):
        progress_events = int(getattr(traversal_result, "progress_events", 0) or 0)
        stop_reason = str(getattr(traversal_result, "stop_reason", "") or "").strip()
        if progress_events == 0 and stop_reason.endswith(("_not_found", "_no_progress")):
            return "traversal_failed"
    if looks_like_low_content_shell(html, html_bytes=html_bytes):
        return "low_content_shell"
    return "usable_content"


def classify_low_content_reason_impl(html: str, *, html_bytes: int) -> str | None:
    analysis = analyze_html(html)
    if not analysis.html.strip():
        return "empty_html"
    lowered_text = analysis.normalized_text.lower()
    if any(
        phrase in lowered_text
        for phrase in (
            "empty category",
            "no products found",
            "no jobs found",
            "0 results",
            "there are no items",
        )
    ):
        return "empty_terminal_page"
    if len(analysis.visible_text.strip()) >= 120:
        return None
    if any(
        token in analysis.lowered_html
        for token in ("product", "jobposting", "__next_data__", "__nuxt__", "application/ld+json")
    ):
        return None
    if html_bytes <= 8_000:
        return "low_visible_text"
    return None


def visible_text_from_soup(soup: BeautifulSoup) -> str:
    pieces: list[str] = []
    for node in soup.find_all(string=True):
        if isinstance(node, Comment):
            continue
        parent_name = str(getattr(getattr(node, "parent", None), "name", "") or "").lower()
        if parent_name in {"script", "style", "noscript"}:
            continue
        text = clean_text(str(node))
        if text:
            pieces.append(text)
    return clean_text(" ".join(pieces))
