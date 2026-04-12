from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.services.config.crawl_runtime import (
    INTERRUPTIBLE_WAIT_POLL_MS,
    LISTING_MIN_ITEMS,
    LISTING_READINESS_MAX_WAIT_MS,
    LISTING_READINESS_POLL_MS,
    SURFACE_READINESS_MAX_WAIT_MS,
    SURFACE_READINESS_POLL_MS,
)
from app.services.config.selectors import CARD_SELECTORS, DOM_PATTERNS
from playwright.async_api import Error as PlaywrightError

logger = logging.getLogger(__name__)

CARD_SELECTORS_COMMERCE = list(CARD_SELECTORS.get("ecommerce", []))
CARD_SELECTORS_JOBS = list(CARD_SELECTORS.get("jobs", []))


def _is_listing_surface(surface: str | None) -> bool:
    return str(surface or "").strip().lower().endswith("listing")


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


async def _wait_for_listing_readiness(
    page,
    surface: str | None,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, object] | None:
    from app.services.config.platform_readiness import (
        resolve_listing_readiness_override,
    )

    normalized_surface = str(surface or "").strip().lower()
    if not normalized_surface.endswith("listing"):
        return None
    selectors = (
        CARD_SELECTORS_JOBS
        if normalized_surface == "job_listing"
        else CARD_SELECTORS_COMMERCE
    )
    page_url = str(getattr(page, "url", "") or "").lower()
    override = resolve_listing_readiness_override(page_url)
    if override is not None:
        selectors = [*selectors, *list(override.get("selectors") or [])]
    if not selectors:
        return None

    elapsed = 0
    poll_ms = max(100, LISTING_READINESS_POLL_MS)
    max_wait_ms = max(0, LISTING_READINESS_MAX_WAIT_MS)
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
                logger.debug(
                    "Listing readiness count failed for selector %s",
                    selector,
                    exc_info=True,
                )
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
                const MAX_IDENTITIES = 20;
                const hashToken = (value) => {
                    const normalized = String(value || "").trim().toLowerCase();
                    if (!normalized) return "";
                    let hash = 2166136261;
                    for (const ch of normalized) {
                        hash ^= ch.charCodeAt(0);
                        hash = Math.imul(hash, 16777619);
                    }
                    return `h:${(hash >>> 0).toString(16).padStart(8, "0")}`;
                };
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
                    .filter((token, index, arr) => token && arr.indexOf(token) === index);
                const identityCount = identities.length;
                const anonymizedIdentities = identities
                    .slice(0, MAX_IDENTITIES)
                    .map((token) => hashToken(token))
                    .filter((token, index, arr) => token && arr.indexOf(token) === index);
                const domSignature = JSON.stringify({
                    linkCount,
                    cardishCount,
                    htmlLength,
                    identities: anonymizedIdentities,
                    textHash: hashToken(text.slice(0, 240)),
                });
                return {
                    link_count: linkCount,
                    cardish_count: cardishCount,
                    text_length: text.length,
                    html_length: htmlLength,
                    identity_count: identityCount,
                    identities: anonymizedIdentities,
                    dom_signature: domSignature,
                    loading: loading,
                };
            }
            """
        )
    except PlaywrightError:
        logger.debug("Failed to snapshot listing page metrics", exc_info=True)
        return {}


def _listing_metrics_stable(
    previous: dict[str, object] | None, current: dict[str, object] | None
) -> bool:
    if not previous or not current:
        return False
    keys = ("link_count", "cardish_count", "text_length")
    return all(
        int(previous.get(key, -1) or 0) == int(current.get(key, -2) or 0)
        for key in keys
    )


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
        selectors = [
            DOM_PATTERNS.get("title", ""),
            DOM_PATTERNS.get("company", ""),
            DOM_PATTERNS.get("salary", ""),
        ]
    elif normalized_surface == "ecommerce_detail":
        selectors = [
            DOM_PATTERNS.get("title", ""),
            DOM_PATTERNS.get("price", ""),
            DOM_PATTERNS.get("sku", ""),
        ]
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
            selectors = (
                CARD_SELECTORS_JOBS
                if normalized_surface == "job_listing"
                else CARD_SELECTORS_COMMERCE
            )
            for selector in selectors:
                try:
                    count = await page.locator(selector).count()
                except PlaywrightError:
                    continue
                if count >= LISTING_MIN_ITEMS:
                    return {
                        "ready": True,
                        "selector": selector,
                        "count": count,
                        "waited_ms": 0,
                    }
            return {"ready": False, "selector": None, "count": 0, "waited_ms": 0}
        return await _wait_for_listing_readiness(
            page, surface, checkpoint=checkpoint
        )
    selectors = _detail_readiness_selectors(surface)
    if not selectors:
        return None
    elapsed = 0
    poll_ms = max(100, SURFACE_READINESS_POLL_MS)
    max_wait_ms = max(
        0, SURFACE_READINESS_MAX_WAIT_MS if max_wait_ms is None else max_wait_ms
    )
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
                logger.debug(
                    "Surface readiness check failed for selector %s",
                    selector,
                    exc_info=True,
                )
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
