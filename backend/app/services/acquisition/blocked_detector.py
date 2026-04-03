# Blocked / challenge page detector.
#
# Runs after acquisition and before extraction to catch anti-bot,
# access-denied, and CAPTCHA challenge pages that look like normal
# HTML but contain no useful data.
from __future__ import annotations

import re


# Deterministic phrases that indicate a blocked or challenge page.
# Checked against lower-cased visible text (tags stripped).
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

# Known WAF / anti-bot provider markers in raw HTML.
_PROVIDER_MARKERS = [
    "perimeterx",
    "px-captcha",
    "cloudflare",
    "cf-challenge",
    "cf-browser-verification",
    "akamai",
    "akamaized",
    "datadome",
    "dd-modal",
    "kasada",
    "incapsula",
    "distil",
    "shape security",
    "arkose",
]

# Title patterns commonly used by challenge pages.
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

    __slots__ = ("is_blocked", "confidence", "reason", "provider")

    def __init__(
        self,
        is_blocked: bool = False,
        confidence: float = 0.0,
        reason: str = "",
        provider: str = "",
    ):
        self.is_blocked = is_blocked
        self.confidence = confidence
        self.reason = reason
        self.provider = provider

    def as_dict(self) -> dict:
        return {
            "is_blocked": self.is_blocked,
            "confidence": self.confidence,
            "reason": self.reason,
            "provider": self.provider,
        }


def detect_blocked_page(html: str) -> BlockedPageResult:
    """Detect whether *html* is a blocked or challenge page.

    Returns a ``BlockedPageResult`` with ``is_blocked=True`` when the page
    matches known anti-bot signatures.  The detection is intentionally
    conservative — it flags pages only when multiple signals agree or a
    single high-confidence marker is found.
    """
    if not html or len(html.strip()) < 100:
        return BlockedPageResult(
            is_blocked=True,
            confidence=0.95,
            reason="empty_or_too_short",
        )

    html_lower = html.lower()
    html_no_script_style = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1\s*>",
        " ",
        html_lower,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Strip tags for visible-text matching.
    visible = re.sub(r"<[^>]+>", " ", html_no_script_style)
    visible = " ".join(visible.split())

    signals: list[tuple[float, str, str]] = []  # (confidence, reason, provider)

    # 1. Check title tag for known block patterns.
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_lower, re.DOTALL)
    if title_match:
        title_text = title_match.group(1).strip()
        for pattern in _BLOCK_TITLE_PATTERNS:
            if pattern.search(title_text):
                signals.append((0.90, f"blocked_title:{title_text[:60]}", ""))

    # 2. Check visible text for block phrases.
    for phrase in _BLOCK_PHRASES:
        if phrase in visible:
            signals.append((0.80, f"blocked_phrase:{phrase}", ""))

    # 3. Check raw HTML for WAF/provider markers.
    for marker in _PROVIDER_MARKERS:
        if marker in html_lower:
            signals.append((0.75, f"provider_marker:{marker}", marker))

    # 4. Structural signals: very few visible links/text but lots of scripts.
    text_len = len(visible)
    script_count = html_lower.count("<script")
    link_count = html_lower.count("<a ")
    if text_len < 500 and script_count > 3 and link_count < 3:
        signals.append((0.50, "low_content_high_scripts", ""))

    if not signals:
        return BlockedPageResult()

    # Aggregate: take the highest-confidence signal.
    best = max(signals, key=lambda s: s[0])
    provider = next((s[2] for s in signals if s[2]), "")

    # Require confidence >= 0.70 to flag as blocked.
    if best[0] >= 0.70:
        return BlockedPageResult(
            is_blocked=True,
            confidence=best[0],
            reason=best[1],
            provider=provider,
        )

    # Multiple low-confidence signals can combine, but still must meet the threshold.
    if len(signals) >= 2:
        combined = min(0.95, best[0] + 0.10 * (len(signals) - 1))
        if combined >= 0.70:
            return BlockedPageResult(
                is_blocked=True,
                confidence=combined,
                reason=f"combined:{len(signals)}_signals",
                provider=provider,
            )

    return BlockedPageResult()
