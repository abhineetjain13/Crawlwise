from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_readiness import (
    cooperative_page_wait,
    wait_for_surface_readiness,
)
from app.services.config.block_signatures import BLOCK_SIGNATURES
from app.services.config.crawl_runtime import (
    BLOCK_MIN_HTML_LENGTH,
    CHALLENGE_POLL_INTERVAL_MS,
    CHALLENGE_WAIT_MAX_SECONDS,
)
from playwright.async_api import Error as PlaywrightError

logger = logging.getLogger(__name__)

BLOCK_BROWSER_CHALLENGE_STRONG_MARKERS = dict(
    BLOCK_SIGNATURES.get("browser_challenge_strong_markers", {})
)
BLOCK_BROWSER_CHALLENGE_WEAK_MARKERS = dict(
    BLOCK_SIGNATURES.get("browser_challenge_weak_markers", {})
)


@dataclass
class ChallengeAssessment:
    state: str
    should_wait: bool
    reasons: list[str] = field(default_factory=list)


def _html_looks_low_value(html: str) -> bool:
    if not html:
        return True
    if detect_blocked_page(html).is_blocked:
        return True
    html_lower = html.lower()
    visible = re.sub(r"<[^>]+>", " ", html_lower)
    visible = " ".join(visible.split())
    low_value_phrases = (
        "sorry, this page is not available",
        "this page is not available",
        "page not found",
        "not available",
        "just a moment",
    )
    return len(html_lower) < 1200 and any(
        phrase in visible for phrase in low_value_phrases
    )


async def _page_looks_low_value(page, page_content_with_retry) -> bool:
    try:
        html = await page_content_with_retry(page)
    except PlaywrightError:
        logger.debug(
            "Failed to inspect page content for low-value result detection",
            exc_info=True,
        )
        return False
    return _html_looks_low_value(html)


async def _retryable_browser_error_reason(page) -> str | None:
    page_url = str(getattr(page, "url", "") or "").strip().lower()
    if page_url.startswith("chrome-error://"):
        return "chrome_error_url"
    try:
        html = await page.content()
    except PlaywrightError:
        logger.debug(
            "Failed to inspect page content for browser error markers", exc_info=True
        )
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


async def _wait_for_challenge_resolution(
    page,
    max_wait_ms: int = CHALLENGE_WAIT_MAX_SECONDS * 1000,
    poll_interval_ms: int = CHALLENGE_POLL_INTERVAL_MS,
    surface: str | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> tuple[bool, str, list[str]]:
    try:
        html = await page.content()
    except PlaywrightError:
        logger.debug(
            "Failed to read page content for challenge detection", exc_info=True
        )
        return False, "page_content_unavailable", ["page_content_read_failed"]

    assessment = _assess_challenge_signals(html)
    if assessment.state == "blocked_signal":
        return False, "blocked", assessment.reasons
    if not assessment.should_wait:
        return True, assessment.state, assessment.reasons

    elapsed = 0
    while elapsed < max_wait_ms:
        await cooperative_page_wait(page, poll_interval_ms, checkpoint=checkpoint)
        elapsed += poll_interval_ms
        try:
            html = await page.content()
        except PlaywrightError:
            logger.debug(
                "Failed to read page content during challenge polling", exc_info=True
            )
            break
        assessment = _assess_challenge_signals(html)
        if assessment.state == "blocked_signal":
            return False, "blocked", assessment.reasons
        if not assessment.should_wait:
            readiness = await wait_for_surface_readiness(
                page,
                surface=surface,
                max_wait_ms=0,
                checkpoint=checkpoint,
            )
            if readiness and not bool(readiness.get("ready")):
                continue
            state = "waiting_resolved" if elapsed > 0 else "none"
            return True, state, assessment.reasons

    return False, "blocked", assessment.reasons


def _assess_challenge_signals(html: str) -> ChallengeAssessment:
    text = (html or "")[:40_000].lower()
    strong_markers = BLOCK_BROWSER_CHALLENGE_STRONG_MARKERS or {
        "captcha": "captcha",
        "verify you are human": "verification_text",
        "checking your browser": "browser_check",
        "cf-browser-verification": "cloudflare_verification",
        "challenge-platform": "challenge_platform",
        "just a moment": "interstitial_text",
        "access denied": "access_denied",
        "powered and protected by akamai": "akamai_banner",
    }
    weak_markers = BLOCK_BROWSER_CHALLENGE_WEAK_MARKERS or {
        "one more step": "generic_interstitial",
        "oops!! something went wrong": "generic_error_text",
        "error page": "error_page_text",
    }
    strong_hits = [label for marker, label in strong_markers.items() if marker in text]
    weak_hits = [label for marker, label in weak_markers.items() if marker in text]
    blocked_verdict = detect_blocked_page(html)
    challenge_like_hits = {
        "captcha",
        "verification_text",
        "browser_check",
        "cloudflare_verification",
        "challenge_platform",
        "interstitial_text",
        "datadome_marker",
    }
    short_html = len(html or "") < max(BLOCK_MIN_HTML_LENGTH, 2500)
    if blocked_verdict.is_blocked and challenge_like_hits & set(strong_hits):
        reasons = strong_hits or weak_hits or ["blocked_detector"]
        if short_html:
            reasons.append("short_html")
        return ChallengeAssessment(
            state="waiting_unresolved", should_wait=True, reasons=reasons
        )
    has_provider_signature = bool(blocked_verdict.provider)
    if blocked_verdict.is_blocked and short_html and has_provider_signature:
        reasons = (
            strong_hits
            or weak_hits
            or [str(blocked_verdict.provider), "blocked_detector"]
        )
        return ChallengeAssessment(
            state="waiting_unresolved", should_wait=True, reasons=reasons
        )
    if blocked_verdict.is_blocked:
        return ChallengeAssessment(
            state="blocked_signal",
            should_wait=False,
            reasons=strong_hits or weak_hits or ["blocked_detector"],
        )
    if short_html and strong_hits:
        return ChallengeAssessment(
            state="blocked_signal",
            should_wait=False,
            reasons=strong_hits + ["short_html"],
        )
    if len(strong_hits) >= 2:
        reasons = strong_hits[:]
        if short_html:
            reasons.append("short_html")
        return ChallengeAssessment(
            state="waiting_unresolved", should_wait=True, reasons=reasons
        )
    if weak_hits:
        reasons = weak_hits[:]
        if short_html:
            reasons.append("short_html")
        return ChallengeAssessment(
            state="waiting_unresolved", should_wait=True, reasons=reasons
        )
    if strong_hits:
        reasons = strong_hits[:]
        if short_html:
            reasons.append("short_html")
        return ChallengeAssessment(
            state="weak_signal_ignored", should_wait=False, reasons=reasons
        )
    return ChallengeAssessment(state="none", should_wait=False, reasons=[])
