# Blocked / challenge page detector.
#
# Runs after acquisition and before extraction to catch anti-bot,
# access-denied, and CAPTCHA challenge pages that look like normal
# HTML but contain no useful data.
from __future__ import annotations

import logging
import re

from app.services.config.block_signatures import BLOCK_SIGNATURES
from app.services.runtime_metrics import incr

BLOCK_PHRASES = tuple(BLOCK_SIGNATURES.get("phrases", []))
BLOCK_ACTIVE_PROVIDER_MARKERS = tuple(
    BLOCK_SIGNATURES.get("active_provider_markers", [])
)
BLOCK_CDN_PROVIDER_MARKERS = tuple(BLOCK_SIGNATURES.get("cdn_provider_markers", []))
BLOCK_TITLE_REGEXES = tuple(BLOCK_SIGNATURES.get("title_regexes", []))
_BLOCK_TITLE_PATTERNS = [re.compile(pattern, re.I) for pattern in BLOCK_TITLE_REGEXES]
logger = logging.getLogger(__name__)


class BlockedPageResult:
    """Result of blocked-page detection."""

    __slots__ = ("is_blocked", "reason", "provider")

    def __init__(
        self,
        is_blocked: bool = False,
        reason: str = "",
        provider: str = "",
    ):
        self.is_blocked = is_blocked
        self.reason = reason
        self.provider = provider

    def as_dict(self) -> dict:
        return {
            "is_blocked": self.is_blocked,
            "reason": self.reason,
            "provider": self.provider,
        }


def detect_blocked_page(html: str) -> BlockedPageResult:
    """Detect whether *html* is a blocked or challenge page safely without ReDoS."""
    if not html or len(html.strip()) < 100:
        return BlockedPageResult(is_blocked=True, reason="empty_or_too_short")

    html_lower = html.lower()
    
    # FIX: Optimized visible text extraction for large HTML
    if len(html) > 100000:
        # For very large HTML, use a faster regex-based approach to get some visible text
        # rather than parsing the entire DOM with BeautifulSoup.
        stripped = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        stripped = re.sub(r"<style.*?</style>", " ", stripped, flags=re.DOTALL | re.IGNORECASE)
        stripped = re.sub(r"<noscript.*?</noscript>", " ", stripped, flags=re.DOTALL | re.IGNORECASE)
        stripped = re.sub(r"<svg.*?</svg>", " ", stripped, flags=re.DOTALL | re.IGNORECASE)
        stripped = re.sub(r"<[^>]*?>", " ", stripped, flags=re.DOTALL)
        visible = " ".join(stripped.lower().split())[:50000]
    else:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for tag in list(soup.find_all(["script", "style", "noscript", "svg"])):
                tag.decompose()
            visible = " ".join(soup.get_text(" ", strip=True).lower().split())
        except Exception:
            incr("blocked_detector_parse_fallback_total")
            logger.debug(
                "Blocked-page parsing failed; falling back to bounded raw HTML scan",
                exc_info=True,
            )
            # Failsafe if BS4 hits a recursion limit on deeply nested malicious HTML
            visible = html_lower[:20000]

    provider = ""
    title_reason = ""
    
    # Safe bounded title extraction
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_lower[:50000], re.DOTALL)
    if title_match:
        title_text = title_match.group(1).strip()
        for pattern in _BLOCK_TITLE_PATTERNS:
            if pattern.search(title_text):
                title_reason = f"blocked_title:{title_text[:60]}"
                break

    phrase_reason = next((f"blocked_phrase:{phrase}" for phrase in BLOCK_PHRASES if phrase in visible), "")

    active_reason = ""
    for item in BLOCK_ACTIVE_PROVIDER_MARKERS:
        marker = str(item.get("marker") or "")
        marker_provider = str(item.get("provider") or "")
        if marker and marker in html_lower:
            active_reason = f"active_block_marker:{marker}"
            provider = marker_provider
            break

    provider_marker = ""
    for item in BLOCK_CDN_PROVIDER_MARKERS:
        marker = str(item.get("marker") or "")
        marker_provider = str(item.get("provider") or "")
        if marker and marker in html_lower:
            provider_marker = marker
            provider = marker_provider
            break

    text_len = len(visible)
    script_count = html_lower.count("<script")
    link_count = html_lower.count("<a ")
    structural_signal = text_len < 500 and script_count > 3 and link_count < 3
    rich_content_signal = text_len >= 2000 and link_count >= 5

    if "kpsdk" in html_lower and text_len < 200:
        return BlockedPageResult(is_blocked=True, reason="kasada_challenge_script", provider="kasada")

    if "no treats beyond this point" in visible or ("page error: 403" in visible and "restricted access" in visible):
        chewy_provider = "akamai" if "akamai" in html_lower or "reference error number" in visible else provider
        reason = "blocked_phrase:no_treats_beyond_this_point" if "no treats beyond this point" in visible else "blocked_phrase:restricted_access_403"
        return BlockedPageResult(is_blocked=True, reason=reason, provider=chewy_provider)

    if "generated by cloudfront" in visible and "request blocked" in visible and "request could not be satisfied" in visible:
        return BlockedPageResult(is_blocked=True, reason="blocked_phrase:cloudfront_request_blocked", provider="cloudfront")

    if ("403 forbidden" in visible or "403 forbidden" in html_lower or "access denied" in visible) and text_len < 500 and link_count < 3:
        return BlockedPageResult(is_blocked=True, reason="blocked_phrase:403_forbidden", provider=provider or "origin")

    if active_reason and (title_reason or phrase_reason or structural_signal or not rich_content_signal):
        return BlockedPageResult(is_blocked=True, reason=active_reason, provider=provider)

    if title_reason and phrase_reason:
        return BlockedPageResult(is_blocked=True, reason=title_reason, provider=provider)

    if phrase_reason and provider_marker:
        return BlockedPageResult(is_blocked=True, reason=f"combined:provider_marker:{provider_marker}", provider=provider)

    if phrase_reason and structural_signal:
        return BlockedPageResult(is_blocked=True, reason="combined:low_content_high_scripts", provider=provider)

    if title_reason and structural_signal:
        return BlockedPageResult(is_blocked=True, reason="combined:blocked_title+low_content_high_scripts", provider=provider)

    return BlockedPageResult()
