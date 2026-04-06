# Blocked / challenge page detector.
#
# Runs after acquisition and before extraction to catch anti-bot,
# access-denied, and CAPTCHA challenge pages that look like normal
# HTML but contain no useful data.
from __future__ import annotations

import re
from app.services.pipeline_config import (
    BLOCK_ACTIVE_PROVIDER_MARKERS,
    BLOCK_CDN_PROVIDER_MARKERS,
    BLOCK_PHRASES,
    BLOCK_TITLE_REGEXES,
)


_BLOCK_TITLE_PATTERNS = [re.compile(pattern, re.I) for pattern in BLOCK_TITLE_REGEXES]


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
    """Detect whether *html* is a blocked or challenge page."""
    if not html or len(html.strip()) < 100:
        return BlockedPageResult(is_blocked=True, reason="empty_or_too_short")

    html_lower = html.lower()
    html_no_script_style = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1\s*>",
        " ",
        html_lower,
        flags=re.IGNORECASE | re.DOTALL,
    )

    visible = re.sub(r"<[^>]+>", " ", html_no_script_style)
    visible = " ".join(visible.split())
    provider = ""

    title_reason = ""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_lower, re.DOTALL)
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
        if marker in html_lower:
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

    if (
        "no treats beyond this point" in visible
        or (
            "page error: 403" in visible
            and "restricted access" in visible
        )
    ):
        chewy_provider = "akamai" if "akamai" in html_lower or "reference error number" in visible else provider
        reason = (
            "blocked_phrase:no_treats_beyond_this_point"
            if "no treats beyond this point" in visible
            else "blocked_phrase:restricted_access_403"
        )
        return BlockedPageResult(
            is_blocked=True,
            reason=reason,
            provider=chewy_provider,
        )

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
