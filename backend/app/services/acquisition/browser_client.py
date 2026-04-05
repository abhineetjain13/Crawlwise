# Playwright browser acquisition client with optional proxy and network interception.
from __future__ import annotations

import logging

import asyncio
import ipaddress
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
import time
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from app.core.config import settings
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.pipeline_config import (
    ACCORDION_EXPAND_MAX,
    ACCORDION_EXPAND_WAIT_MS,
    BLOCK_MIN_HTML_LENGTH,
    BROWSER_ERROR_RETRY_ATTEMPTS,
    BROWSER_ERROR_RETRY_DELAY_MS,
    CHALLENGE_POLL_INTERVAL_MS,
    CHALLENGE_WAIT_MAX_SECONDS,
    COOKIE_POLICY,
    COOKIE_CONSENT_SELECTORS,
    ORIGIN_WARM_PAUSE_MS,
)
from app.services.url_safety import validate_public_target

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
    max_pages: int = 1,
    max_scrolls: int = 10,
    prefer_stealth: bool = False,
    request_delay_ms: int = 0,
) -> BrowserResult:
    """Render a page with Playwright and intercept XHR/fetch responses.

    Args:
        url: Target URL.
        proxy: Optional proxy URL.
        advanced_mode: None, "paginate", "scroll", "load_more", or "auto".
        max_scrolls: Max scroll attempts (for scroll mode).
    """
    result = BrowserResult()
    intercepted: list[dict] = []
    target = await validate_public_target(url)

    async with async_playwright() as pw:
        launch_kwargs = _build_launch_kwargs(proxy, target)
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

        result.origin_warmed = await _maybe_warm_origin(page, url)

        await _goto_with_fallback(page, url)
        await _dismiss_cookie_consent(page)
        challenge_ok, challenge_state, reasons = await _wait_for_challenge_resolution(page)
        result.challenge_state = challenge_state
        result.diagnostics["challenge_reasons"] = reasons
        result.diagnostics["challenge_ok"] = challenge_ok
        await _pause_after_navigation(request_delay_ms)

        # Expand accordion/tab sections so content is in the DOM for extraction
        await _expand_accordions(page)

        combined_html = await _apply_advanced_mode(
            page,
            advanced_mode,
            max_scrolls,
            max_pages=max_pages,
            request_delay_ms=request_delay_ms,
        )
        if combined_html is not None:
            result.html = combined_html
            result.network_payloads = intercepted
            result.diagnostics["pagination_mode"] = advanced_mode
            result.diagnostics["max_pages"] = max_pages
            result.diagnostics["page_count"] = combined_html.count("<!-- PAGE BREAK:") if combined_html else 0
            await _persist_context_cookies(context, page.url or url, original_domain)
            await context.close()
            await browser.close()
            return result
        await _populate_result(result, page, intercepted)
        await _persist_context_cookies(context, page.url or url, original_domain)
        await context.close()
        await browser.close()
    return result


def _build_launch_kwargs(proxy: str | None, target) -> dict:
    launch_kwargs: dict = {"headless": settings.playwright_headless}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    if target.dns_resolved and target.resolved_ips:
        pinned_ip = target.resolved_ips[0]
        launch_kwargs["args"] = [
            f"--host-resolver-rules=MAP {target.hostname} {_chromium_host_rule_ip(pinned_ip)}",
        ]
    return launch_kwargs


async def _maybe_warm_origin(page, url: str) -> bool:
    origin_url = _origin_url(url)
    if not origin_url or origin_url == url:
        return False
    await _warm_origin(page, origin_url)
    return True


async def _pause_after_navigation(request_delay_ms: int) -> None:
    delay_seconds = request_delay_ms / 1000 if request_delay_ms > 0 else 0.25
    await asyncio.sleep(delay_seconds)


async def _apply_advanced_mode(
    page,
    advanced_mode: str | None,
    max_scrolls: int,
    *,
    max_pages: int,
    request_delay_ms: int,
) -> str | None:
    if advanced_mode == "scroll":
        await _scroll_to_bottom(page, max_scrolls, request_delay_ms=request_delay_ms)
        return None
    if advanced_mode == "load_more":
        await _click_load_more(page, max_scrolls, request_delay_ms=request_delay_ms)
        return None
    if advanced_mode == "paginate":
        return await _collect_paginated_html(page, max_pages=max_pages, request_delay_ms=request_delay_ms)
    if advanced_mode == "auto":
        # Scroll first, then collect pagination when present.
        await _scroll_to_bottom(page, max_scrolls, request_delay_ms=request_delay_ms)
        next_page_url = await _find_next_page_url(page)
        if next_page_url:
            return await _collect_paginated_html(page, max_pages=max_pages, request_delay_ms=request_delay_ms)
    return None


async def _collect_paginated_html(page, *, max_pages: int, request_delay_ms: int) -> str:
    fragments: list[str] = []
    visited_urls: set[str] = set()
    current_url = str(page.url or "").strip()
    if current_url:
        visited_urls.add(current_url)

    page_limit = max(1, int(max_pages or 1))
    for page_index in range(page_limit):
        fragments.append(f"<!-- PAGE BREAK:{page_index + 1}:{page.url} -->\n{await page.content()}")
        if page_index + 1 >= page_limit:
            break
        next_page_url = await _find_next_page_url(page)
        if not next_page_url or next_page_url in visited_urls:
            break
        try:
            await validate_public_target(next_page_url)
        except ValueError as exc:
            logger.warning("Rejected pagination URL %s from %s: %s", next_page_url, page.url, exc)
            break
        visited_urls.add(next_page_url)
        await page.goto(next_page_url, wait_until="domcontentloaded", timeout=20_000)
        await _dismiss_cookie_consent(page)
        await _pause_after_navigation(request_delay_ms)
    return "\n".join(fragments)


async def _find_next_page_url(page) -> str:
    selectors = [
        "link[rel='next']",
        "a[rel='next']",
        "a[aria-label*='next' i]",
        "a[title*='next' i]",
        "a:has-text('Next')",
        "button[aria-label*='next' i]",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if not await locator.count():
                continue
            href = await locator.get_attribute("href")
            if href:
                return urljoin(page.url, href)
        except Exception:
            logger.debug("Failed to inspect pagination selector %s", selector, exc_info=True)
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
    except Exception:
        logger.debug("Failed to evaluate DOM for next-page link", exc_info=True)
        return ""
    return str(href or "").strip()


async def _expand_accordions(page) -> None:
    """Click collapsed accordion/tab triggers to reveal hidden content for extraction."""
    try:
        expand_max = ACCORDION_EXPAND_MAX
        expanded_count = await page.evaluate("""
            (maxExpand) => {
                let count = 0;
                const collapsed = document.querySelectorAll(
                    '[aria-expanded="false"], ' +
                    'details:not([open]), ' +
                    '[data-accordion-heading]:not([aria-expanded="true"]), ' +
                    '[role="tab"][aria-selected="false"]'
                );
                for (const el of collapsed) {
                    if (el.tagName === 'DETAILS') {
                        el.setAttribute('open', '');
                        count++;
                    } else {
                        try { el.click(); count++; } catch(e) {}
                    }
                    if (count >= maxExpand) break;
                }
                return count;
            }
        """, expand_max)
        if expanded_count:
            logger.debug("Expanded %d accordion/tab sections", expanded_count)
            await asyncio.sleep(ACCORDION_EXPAND_WAIT_MS / 1000.0)
    except Exception:
        logger.debug("Accordion expansion failed (non-critical)", exc_info=True)


async def _populate_result(result: BrowserResult, page, intercepted: list[dict]) -> None:
    result.html = await page.content()
    result.network_payloads = intercepted
    if result.html:
        result.diagnostics["html_length"] = len(result.html)
        result.diagnostics["blocked"] = detect_blocked_page(result.html).is_blocked


async def _persist_context_cookies(context, final_url: str, original_domain: str) -> None:
    final_domain = _domain(final_url)
    await _save_cookies(context, final_domain)
    if final_domain != original_domain:
        await _save_cookies(context, original_domain)


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
    last_timeout: PlaywrightTimeoutError | None = None
    browser_error_retries = max(0, BROWSER_ERROR_RETRY_ATTEMPTS)
    for wait_until, timeout in strategies:
        try:
            for attempt in range(browser_error_retries + 1):
                await page.goto(url, wait_until=wait_until, timeout=timeout)
                browser_error_reason = await _retryable_browser_error_reason(page)
                if browser_error_reason is None:
                    return
                if attempt >= browser_error_retries:
                    last_error = RuntimeError(f"browser_navigation_error:{browser_error_reason}")
                    break
                logger.debug(
                    "goto(%s, wait_until=%s) landed on transient browser error page (%s); retrying",
                    url,
                    wait_until,
                    browser_error_reason,
                )
                await page.wait_for_timeout(BROWSER_ERROR_RETRY_DELAY_MS)
        except PlaywrightTimeoutError as exc:
            last_timeout = exc
            continue
        except Exception as exc:
            last_error = exc
            logger.debug("goto(%s, wait_until=%s) failed: %s", url, wait_until, exc)
            continue
    if last_error is not None:
        raise last_error
    if last_timeout is not None:
        raise last_timeout


async def _retryable_browser_error_reason(page) -> str | None:
    page_url = str(getattr(page, "url", "") or "").strip().lower()
    if page_url.startswith("chrome-error://"):
        return "chrome_error_url"
    try:
        html = await page.content()
    except Exception:
        logger.debug("Failed to inspect page content for browser error markers", exc_info=True)
        return None
    text = (html or "")[:20_000].lower().replace("’", "'")
    markers = {
        "err_name_not_resolved": "dns_name_not_resolved",
        "dns_probe_finished_nxdomain": "dns_probe_finished_nxdomain",
        "dns_probe_finished_no_internet": "dns_probe_finished_no_internet",
        "this site can't be reached": "site_cannot_be_reached",
        "server ip address could not be found": "server_ip_not_found",
        "err_network_changed": "network_changed",
        "err_connection_reset": "connection_reset",
    }
    for marker, reason in markers.items():
        if marker in text:
            return reason
    return None


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
    cookies = _filter_persistable_cookies(payload, domain=domain)
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
    filtered = _filter_persistable_cookies(cookies, domain=domain)
    if not filtered:
        if cookie_path.exists():
            cookie_path.unlink(missing_ok=True)
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


def _filter_persistable_cookies(payload: object, *, domain: str) -> list[dict]:
    if not isinstance(payload, list):
        return []
    filtered: list[dict] = []
    for cookie in payload:
        if not isinstance(cookie, dict):
            continue
        if _is_persistable_cookie(cookie, domain=domain):
            filtered.append(cookie)
    return filtered


def _is_persistable_cookie(cookie: dict, *, domain: str) -> bool:
    policy = _cookie_policy_for_domain(domain)
    name = str(cookie.get("name") or "").strip()
    if not name:
        return False
    cookie_domain = str(cookie.get("domain") or "").strip()
    cookie_url = str(cookie.get("url") or "").strip()
    if not cookie_domain and not cookie_url:
        return False
    if cookie_domain and not _cookie_domain_matches(cookie_domain, domain):
        return False
    if not cookie_domain:
        try:
            extracted_domain = str(urlparse(cookie_url).hostname or "").strip().lower()
        except ValueError:
            extracted_domain = ""
        if extracted_domain and not _cookie_domain_matches(extracted_domain, domain):
            return False
    name_allowed = _cookie_name_allowed(name, policy)
    if not name_allowed and _cookie_name_blocked(name, policy):
        return False
    expires = _cookie_expiry(cookie)
    now = time.time()
    if expires is None:
        return bool(policy.get("persist_session_cookies", False))
    if expires <= now:
        return False
    max_ttl = int(policy.get("max_persisted_ttl_seconds", 0) or 0)
    if max_ttl > 0 and expires - now > max_ttl:
        return False
    return True


def _cookie_name_allowed(name: str, policy: dict[str, object]) -> bool:
    normalized = str(name or "").strip().lower()
    allowed_names = {
        str(value).strip().lower()
        for value in policy.get("allowed_cookie_names", [])
        if str(value).strip()
    }
    return normalized in allowed_names


def _cookie_name_blocked(name: str, policy: dict[str, object]) -> bool:
    normalized = str(name or "").strip().lower()
    if not normalized:
        return True
    blocked_prefixes = [str(value).strip().lower() for value in policy.get("blocked_name_prefixes", []) if str(value).strip()]
    for prefix in blocked_prefixes:
        if normalized.startswith(prefix):
            return True
    blocked_substrings = [str(value).strip().lower() for value in policy.get("blocked_name_contains", []) if str(value).strip()]
    for fragment in blocked_substrings:
        if fragment in normalized:
            return True
    return False


def _cookie_policy_for_domain(domain: str) -> dict[str, object]:
    normalized = str(domain or "").strip().lower().lstrip(".")
    policy = dict(COOKIE_POLICY)
    overrides = COOKIE_POLICY.get("domain_overrides", {})
    if not isinstance(overrides, dict):
        return policy
    for override_domain, override_values in overrides.items():
        candidate = str(override_domain or "").strip().lower().lstrip(".")
        if not candidate or not isinstance(override_values, dict):
            continue
        if normalized == candidate or normalized.endswith(f".{candidate}"):
            policy.update(override_values)
    return policy


def _cookie_expiry(cookie: dict) -> float | None:
    raw_expires = cookie.get("expires")
    if raw_expires in (None, "", -1):
        return None
    try:
        return float(raw_expires)
    except (TypeError, ValueError):
        return None


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


def _chromium_host_rule_ip(ip_text: str) -> str:
    try:
        value = ipaddress.ip_address(ip_text)
    except ValueError:
        return ip_text
    return f"[{value.compressed}]" if value.version == 6 else value.compressed
