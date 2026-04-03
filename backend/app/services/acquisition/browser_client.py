# Playwright browser acquisition client with optional proxy and network interception.
from __future__ import annotations

import logging

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from app.core.config import settings
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.pipeline_config import (
    BLOCK_MIN_HTML_LENGTH,
    CHALLENGE_POLL_INTERVAL_MS,
    CHALLENGE_WAIT_MAX_SECONDS,
    COOKIE_CONSENT_SELECTORS,
    ORIGIN_WARM_PAUSE_MS,
)

logger = logging.getLogger(__name__)


@dataclass
class BrowserResult:
    """Result from a Playwright render including intercepted payloads."""

    html: str = ""
    network_payloads: list[dict] = field(default_factory=list)
    challenge_state: str = "none"
    origin_warmed: bool = False
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass
class ChallengeAssessment:
    state: str
    should_wait: bool
    reasons: list[str] = field(default_factory=list)


_STEALTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


async def fetch_rendered_html(
    url: str,
    proxy: str | None = None,
    advanced_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = 10,
    prefer_stealth: bool = False,
    request_delay_ms: int = 0,
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
        context = await browser.new_context(**_context_kwargs(prefer_stealth))
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
                    logger.debug("Failed to parse intercepted JSON response from %s", response.url, exc_info=True)

        page.on("response", _on_response)

        origin_url = _origin_url(url)
        if origin_url and origin_url != url:
            await _warm_origin(page, origin_url)
            result.origin_warmed = True

        await _goto_with_fallback(page, url)
        await _dismiss_cookie_consent(page)
        challenge_ok, challenge_state, reasons = await _wait_for_challenge_resolution(page)
        result.challenge_state = challenge_state
        result.diagnostics["challenge_reasons"] = reasons
        result.diagnostics["challenge_ok"] = challenge_ok
        if request_delay_ms > 0:
            await asyncio.sleep(request_delay_ms / 1000)
        else:
            await asyncio.sleep(0.25)

        # Advanced crawl modes
        if advanced_mode == "scroll":
            await _scroll_to_bottom(page, max_scrolls, request_delay_ms=request_delay_ms)
        elif advanced_mode == "load_more":
            await _click_load_more(page, max_scrolls, request_delay_ms=request_delay_ms)
        elif advanced_mode == "paginate":
            result.html = await page.content()
            result.network_payloads = intercepted
            # For pagination we'd collect multi-page HTML; for POC return first page
            await browser.close()
            return result
        elif advanced_mode == "auto":
            # Try scroll first, it's the most common SPA pattern
            await _scroll_to_bottom(page, max_scrolls, request_delay_ms=request_delay_ms)

        result.html = await page.content()
        result.network_payloads = intercepted
        if result.html:
            result.diagnostics["html_length"] = len(result.html)
            result.diagnostics["blocked"] = detect_blocked_page(result.html).is_blocked
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

    Also handles non-timeout errors (e.g. ERR_HTTP2_PROTOCOL_ERROR) by
    retrying with less strict wait conditions before giving up.
    """
    strategies = [
        ("networkidle", 30_000),
        ("load", 15_000),
        ("domcontentloaded", 15_000),
    ]
    last_error = None
    for wait_until, timeout in strategies:
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout)
            return
        except PlaywrightTimeoutError:
            last_error = None
            continue
        except Exception as exc:
            last_error = exc
            logger.debug("goto(%s, wait_until=%s) failed: %s", url, wait_until, exc)
            continue
    if last_error is not None:
        raise last_error


async def _warm_origin(page, origin_url: str) -> None:
    try:
        await page.goto(origin_url, wait_until="domcontentloaded", timeout=15_000)
        await page.wait_for_timeout(ORIGIN_WARM_PAUSE_MS)
        try:
            await page.mouse.move(240, 180)
            await page.evaluate("window.scrollBy(0, 120)")
        except Exception:
            logger.debug("Origin warm mouse/scroll interaction failed", exc_info=True)
    except Exception:
        logger.debug("Origin warm navigation failed for %s", origin_url, exc_info=True)
        return


async def _scroll_to_bottom(page, max_scrolls: int, *, request_delay_ms: int) -> None:
    """Scroll to bottom repeatedly until no new content appears."""
    prev_height = 0
    for _ in range(max_scrolls):
        current_height = await page.evaluate("document.body.scrollHeight")
        if current_height == prev_height:
            break
        prev_height = current_height
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(max(request_delay_ms, 1500) / 1000)


async def _click_load_more(page, max_clicks: int, *, request_delay_ms: int) -> None:
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
                    await asyncio.sleep(max(request_delay_ms, 2000) / 1000)
                    clicked = True
                    break
            except Exception:
                logger.debug("Load-more click failed for selector %s", sel, exc_info=True)
                continue
        if not clicked:
            break


async def _dismiss_cookie_consent(page) -> None:
    try:
        await page.wait_for_timeout(400)
    except Exception:
        logger.debug("Cookie consent pre-wait failed", exc_info=True)
        return
    for selector in COOKIE_CONSENT_SELECTORS:
        try:
            button = page.locator(selector).first
            if await button.is_visible():
                await button.click()
                await page.wait_for_timeout(600)
                return
        except Exception:
            logger.debug("Cookie consent click failed for selector %s", selector, exc_info=True)
            continue
    try:
        await page.keyboard.press("Escape")
    except Exception:
        logger.debug("Escape key press failed during cookie consent dismissal", exc_info=True)


async def _wait_for_challenge_resolution(
    page,
    max_wait_ms: int = CHALLENGE_WAIT_MAX_SECONDS * 1000,
    poll_interval_ms: int = CHALLENGE_POLL_INTERVAL_MS,
) -> tuple[bool, str, list[str]]:
    try:
        html = await page.content()
    except Exception:
        logger.debug("Failed to read page content for challenge detection", exc_info=True)
        return True, "none", []

    assessment = _assess_challenge_signals(html)
    if assessment.state == "blocked_signal":
        return False, "blocked", assessment.reasons
    if not assessment.should_wait:
        return True, assessment.state, assessment.reasons

    elapsed = 0
    while elapsed < max_wait_ms:
        await page.wait_for_timeout(poll_interval_ms)
        elapsed += poll_interval_ms
        try:
            html = await page.content()
        except Exception:
            logger.debug("Failed to read page content during challenge polling", exc_info=True)
            break
        assessment = _assess_challenge_signals(html)
        if assessment.state == "blocked_signal":
            return False, "blocked", assessment.reasons
        if not assessment.should_wait:
            state = "waiting_resolved" if elapsed > 0 else "none"
            return True, state, assessment.reasons

    return False, "blocked", assessment.reasons


def _assess_challenge_signals(html: str) -> ChallengeAssessment:
    text = (html or "")[:40_000].lower()
    strong_markers = {
        "captcha": "captcha",
        "verify you are human": "verification_text",
        "checking your browser": "browser_check",
        "cf-browser-verification": "cloudflare_verification",
        "challenge-platform": "challenge_platform",
        "just a moment": "interstitial_text",
        "access denied": "access_denied",
        "powered and protected by akamai": "akamai_banner",
    }
    weak_markers = {
        "one more step": "generic_interstitial",
        "oops!! something went wrong": "generic_error_text",
        "error page": "error_page_text",
    }
    strong_hits = [label for marker, label in strong_markers.items() if marker in text]
    weak_hits = [label for marker, label in weak_markers.items() if marker in text]
    if detect_blocked_page(html).is_blocked:
        return ChallengeAssessment(state="blocked_signal", should_wait=False, reasons=strong_hits or weak_hits or ["blocked_detector"])
    short_html = len(html or "") < max(BLOCK_MIN_HTML_LENGTH, 2500)
    if short_html and strong_hits:
        return ChallengeAssessment(state="blocked_signal", should_wait=False, reasons=strong_hits + ["short_html"])
    if len(strong_hits) >= 2:
        reasons = strong_hits[:]
        if short_html:
            reasons.append("short_html")
        return ChallengeAssessment(state="waiting_unresolved", should_wait=True, reasons=reasons)
    if strong_hits or weak_hits:
        reasons = (strong_hits + weak_hits)[:]
        if short_html:
            reasons.append("short_html")
        return ChallengeAssessment(state="weak_signal_ignored", should_wait=False, reasons=reasons)
    if len(re.sub(r"<[^>]+>", " ", text).split()) < 50:
        return ChallengeAssessment(state="waiting_unresolved", should_wait=True, reasons=["low_visible_text"])
    return ChallengeAssessment(state="none", should_wait=False, reasons=[])


def _context_kwargs(prefer_stealth: bool) -> dict:
    kwargs = {
        "java_script_enabled": True,
        "ignore_https_errors": True,
        "bypass_csp": True,
        "locale": "en-US",
        "timezone_id": "UTC",
        "viewport": {"width": 1365, "height": 900},
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
        "color_scheme": "light",
        "extra_http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
        },
    }
    if prefer_stealth:
        kwargs["user_agent"] = _STEALTH_USER_AGENT
    return kwargs


def _origin_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))


async def _load_cookies(context, domain: str) -> bool:
    cookie_path = _cookie_store_path(domain)
    if cookie_path is None or not cookie_path.exists():
        return False
    try:
        payload = json.loads(cookie_path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Failed to parse cookie file for domain %s", domain, exc_info=True)
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
        logger.debug("Failed to add cookies to context for domain %s", domain, exc_info=True)
        return False
    return True


async def _save_cookies(context, domain: str) -> None:
    cookie_path = _cookie_store_path(domain)
    if cookie_path is None:
        return
    try:
        cookies = await context.cookies()
    except Exception:
        logger.debug("Failed to read cookies from context for domain %s", domain, exc_info=True)
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
        or requested_host.endswith(f".{cookie_host}")
    )


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()
