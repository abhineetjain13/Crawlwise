# Playwright browser acquisition client with optional proxy and network interception.
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from playwright.async_api import async_playwright

from app.core.config import settings


@dataclass
class BrowserResult:
    """Result from a Playwright render including intercepted payloads."""

    html: str = ""
    network_payloads: list[dict] = field(default_factory=list)


async def fetch_rendered_html(
    url: str,
    proxy: str | None = None,
    advanced_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = 10,
) -> BrowserResult:
    """Render a page with Playwright and intercept XHR/fetch responses.

    Args:
        url: Target URL.
        proxy: Optional proxy URL.
        advanced_mode: None, "paginate", "scroll", "load_more", or "auto".
        max_pages: Max pagination clicks (for paginate mode).
        max_scrolls: Max scroll attempts (for scroll mode).
    """
    result = BrowserResult()
    intercepted: list[dict] = []

    async with async_playwright() as pw:
        launch_kwargs: dict = {"headless": settings.playwright_headless}
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
        browser = await pw.chromium.launch(**launch_kwargs)
        page = await browser.new_page()

        # Intercept XHR/fetch responses for structured data
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
                    pass

        page.on("response", _on_response)

        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(1)

        # Advanced crawl modes
        if advanced_mode == "scroll":
            await _scroll_to_bottom(page, max_scrolls)
        elif advanced_mode == "load_more":
            await _click_load_more(page, max_scrolls)
        elif advanced_mode == "paginate":
            result.html = await page.content()
            result.network_payloads = intercepted
            # For pagination we'd collect multi-page HTML; for POC return first page
            await browser.close()
            return result
        elif advanced_mode == "auto":
            # Try scroll first, it's the most common SPA pattern
            await _scroll_to_bottom(page, max_scrolls)

        result.html = await page.content()
        result.network_payloads = intercepted
        await browser.close()
    return result


async def _scroll_to_bottom(page, max_scrolls: int) -> None:
    """Scroll to bottom repeatedly until no new content appears."""
    prev_height = 0
    for _ in range(max_scrolls):
        current_height = await page.evaluate("document.body.scrollHeight")
        if current_height == prev_height:
            break
        prev_height = current_height
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1.5)


async def _click_load_more(page, max_clicks: int) -> None:
    """Click load-more/show-all buttons until exhausted."""
    selectors = [
        "button:has-text('Load More')",
        "button:has-text('Show More')",
        "button:has-text('View All')",
        "a:has-text('Load More')",
        "[data-testid='load-more']",
        ".load-more",
    ]
    for _ in range(max_clicks):
        clicked = False
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(2)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            break
