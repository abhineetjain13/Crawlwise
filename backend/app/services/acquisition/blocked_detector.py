# Blocked / challenge page detector.
#
# Runs after acquisition and before extraction to catch anti-bot,
# access-denied, and CAPTCHA challenge pages that look like normal
# HTML but contain no useful data.
from __future__ import annotations

import re


_BLOCK_PHRASES = [
    "access denied",
    "access to this page has been denied",
    "robot or human",
    "are you a robot",
    "are you human",
    "please verify you are a human",
    "verify you are human",
    "complete the security check",
    "please complete the captcha",
    "enable javascript to view",
    "enable javascript and cookies",
    "you have been blocked",
    "this request was blocked",
    "sorry, you have been blocked",
    "checking your browser",
    "checking if the site connection is secure",
    "just a moment",
    "attention required",
    "pardon our interruption",
    "please turn javascript on",
    "why do i have to complete a captcha",
]

_ACTIVE_BLOCK_MARKERS = [
    ("px-captcha", "perimeterx"),
    ("cf-challenge", "cloudflare"),
    ("cf-browser-verification", "cloudflare"),
    ("dd-modal", "datadome"),
    ("incapsula", "incapsula"),
    ("distil", "distil"),
    ("shape security", "shape security"),
    ("arkose", "arkose"),
]

_CDN_PROVIDER_MARKERS = [
    ("perimeterx", "perimeterx"),
    ("cloudflare", "cloudflare"),
    ("akamai", "akamai"),
    ("akamaized", "akamai"),
    ("datadome", "datadome"),
    ("kasada", "kasada"),
]

_BLOCK_TITLE_PATTERNS = [
    re.compile(r"access\s+denied", re.I),
    re.compile(r"robot\s+or\s+human", re.I),
    re.compile(r"just\s+a\s+moment", re.I),
    re.compile(r"attention\s+required", re.I),
    re.compile(r"you\s+have\s+been\s+blocked", re.I),
    re.compile(r"security\s+check", re.I),
    re.compile(r"pardon\s+our\s+interruption", re.I),
]


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

    phrase_reason = next((f"blocked_phrase:{phrase}" for phrase in _BLOCK_PHRASES if phrase in visible), "")

    active_reason = ""
    for marker, marker_provider in _ACTIVE_BLOCK_MARKERS:
        if marker in html_lower:
            active_reason = f"active_block_marker:{marker}"
            provider = marker_provider
            break
    if active_reason:
        return BlockedPageResult(is_blocked=True, reason=active_reason, provider=provider)

    provider_marker = ""
    for marker, marker_provider in _CDN_PROVIDER_MARKERS:
        if marker in html_lower:
            provider_marker = marker
            provider = marker_provider
            break

    text_len = len(visible)
    script_count = html_lower.count("<script")
    link_count = html_lower.count("<a ")
    structural_signal = text_len < 500 and script_count > 3 and link_count < 3

    if "kpsdk" in html_lower and text_len < 200:
        return BlockedPageResult(is_blocked=True, reason="kasada_challenge_script", provider="kasada")

    if title_reason and phrase_reason:
        return BlockedPageResult(is_blocked=True, reason=title_reason, provider=provider)

    if phrase_reason and provider_marker:
        return BlockedPageResult(is_blocked=True, reason=f"combined:provider_marker:{provider_marker}", provider=provider)

    if phrase_reason and structural_signal:
        return BlockedPageResult(is_blocked=True, reason="combined:low_content_high_scripts", provider=provider)

    if title_reason and structural_signal:
        return BlockedPageResult(is_blocked=True, reason="combined:blocked_title+low_content_high_scripts", provider=provider)

    return BlockedPageResult()
