# Playwright browser acquisition client with optional proxy and network interception.
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from app.core.config import settings


@dataclass
class BrowserResult:
    """Result from a Playwright render including intercepted payloads."""

    html: str = ""
    network_payloads: list[dict] = field(default_factory=list)


COOKIE_CONSENT_SELECTORS = [
    "button#onetrust-accept-btn-handler",
    "button#CybotCookiebotDialogBodyUnderlayAccept",
    "[aria-label='Accept Cookies']",
    "[aria-label='Accept all']",
    "button:has-text('Accept All')",
    "button:has-text('Accept Cookies')",
    "button:has-text('Accept')",
    "button:has-text('I Accept')",
    "button:has-text('Agree')",
    ".cookie-consent-accept",
    "#cookieConsentAccept",
    ".fc-button.fc-cta-accept",
    ".fc-primary-button",
]


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
        context = await browser.new_context()
        original_domain = _domain(url)
        await _load_cookies(context, original_domain)
        page = await context.new_page()

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

        await _goto_with_fallback(page, url)
        await _dismiss_cookie_consent(page)
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
        final_domain = _domain(page.url or url)
        await _save_cookies(context, final_domain)
        if final_domain != original_domain:
            await _save_cookies(context, original_domain)
        await context.close()
        await browser.close()
    return result


async def _goto_with_fallback(page, url: str) -> None:
    """Navigate with progressively less strict wait conditions.

    Some modern storefronts keep background requests open long enough that
    `networkidle` times out even though the page is already usable. We still
    want the rendered DOM in those cases, so fall back to `load` and then
    `domcontentloaded` before failing the crawl.
    """
    try:
        await page.goto(url, wait_until="networkidle", timeout=30_000)
        return
    except PlaywrightTimeoutError:
        pass

    try:
        await page.goto(url, wait_until="load", timeout=15_000)
        return
    except PlaywrightTimeoutError:
        pass

    await page.goto(url, wait_until="domcontentloaded", timeout=15_000)


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


async def _dismiss_cookie_consent(page) -> None:
    try:
        await page.wait_for_timeout(400)
    except Exception:
        return
    for selector in COOKIE_CONSENT_SELECTORS:
        try:
            button = page.locator(selector).first
            if await button.is_visible():
                await button.click()
                await page.wait_for_timeout(600)
                return
        except Exception:
            continue
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def _load_cookies(context, domain: str) -> bool:
    cookie_path = _cookie_store_path(domain)
    if cookie_path is None or not cookie_path.exists():
        return False
    try:
        payload = json.loads(cookie_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, list):
        return False
    cookies = [
        cookie
        for cookie in payload
        if isinstance(cookie, dict)
        and cookie.get("name")
        and (cookie.get("domain") or cookie.get("url"))
    ]
    if not cookies:
        return False
    try:
        await context.add_cookies(cookies)
    except Exception:
        return False
    return True


async def _save_cookies(context, domain: str) -> None:
    cookie_path = _cookie_store_path(domain)
    if cookie_path is None:
        return
    try:
        cookies = await context.cookies()
    except Exception:
        return
    filtered = [
        cookie
        for cookie in cookies
        if isinstance(cookie, dict)
        and cookie.get("name")
        and _cookie_domain_matches(str(cookie.get("domain") or ""), domain)
    ]
    if not filtered:
        return
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cookie_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(filtered, indent=2), encoding="utf-8")
    Path(tmp_path).replace(cookie_path)


def _cookie_store_path(domain: str) -> Path | None:
    normalized = str(domain or "").strip().lower()
    if not normalized:
        return None
    safe = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in normalized)
    if not safe:
        return None
    return Path(settings.cookie_store_dir) / f"{safe}.json"


def _cookie_domain_matches(cookie_domain: str, requested_domain: str) -> bool:
    cookie_host = str(cookie_domain or "").strip().lower().lstrip(".")
    requested_host = str(requested_domain or "").strip().lower().lstrip(".")
    if not cookie_host or not requested_host:
        return False
    return (
        cookie_host == requested_host
        or cookie_host.endswith(f".{requested_host}")
        or requested_host.endswith(f".{cookie_host}")
    )


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()
