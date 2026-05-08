from __future__ import annotations

import ast
import re
from html import unescape

from app.services.config.extraction_rules import (
    CSS_NOISE_PATTERN,
    DETAIL_LOW_SIGNAL_TITLE_VALUES,
    DETAIL_TRACKING_TOKEN_PATTERN,
    LISTING_ACTION_NOISE_PATTERNS,
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_TITLE_CTA_TITLES,
    LISTING_UTILITY_TITLE_PATTERNS,
    LISTING_WEAK_TITLES,
    RATING_RE,
    REVIEW_TITLE_RE,
)
from app.services.config.field_mappings import UNICODE_ESCAPE_RE
from app.services.extraction_html_helpers import html_to_text

__all__ = [
    "clean_text",
    "coerce_literal_text_list",
    "coerce_long_text",
    "coerce_text",
    "is_title_noise",
    "slug_tokens",
    "strip_html_tags",
    "text_or_none",
]

whitespace_re = re.compile(r"\s+")
html_entity_re = re.compile(r"&(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);")
_CSS_NOISE_RE = re.compile(str(CSS_NOISE_PATTERN), re.I)
_LEADING_CSS_BLOCK_RE = re.compile(r"^(?:\s*\.[a-z0-9_-]+\{[^{}]*\})+", re.I)
_REVIEW_TITLE_RE = REVIEW_TITLE_RE
tracking_token_re = re.compile(str(DETAIL_TRACKING_TOKEN_PATTERN), re.I)
_LISTING_UTILITY_TITLE_REGEXES = tuple(
    re.compile(pattern, re.I) for pattern in LISTING_UTILITY_TITLE_PATTERNS
)


def clean_text(value: object) -> str:
    text = _decode_common_escaped_text(unescape(str(value or "")).strip())
    if text.startswith(".") and _CSS_NOISE_RE.search(text[:256]):
        text = _LEADING_CSS_BLOCK_RE.sub("", text).strip()
    return whitespace_re.sub(" ", text)


def _decode_common_escaped_text(value: str) -> str:
    text = str(value or "")
    if "\\" not in text:
        return text
    backslash_marker = "\0BACKSLASH\0"
    text = text.replace("\\\\", backslash_marker)
    text = UNICODE_ESCAPE_RE.sub(
        lambda match: chr(int(match.group(1), 16)),
        text,
    )
    text = (
        text.replace("\\/", "/")
        .replace('\\"', '"')
        .replace("\\'", "'")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
    )
    return text.replace(backslash_marker, "\\")


def is_title_noise(title: object) -> bool:
    cleaned = clean_text(title)
    lowered = cleaned.lower()
    if not lowered:
        return True
    if "undefined" in lowered or lowered in {"nan", "none", "null"}:
        return True
    if cleaned.isdigit():
        return True
    if tracking_token_re.fullmatch(cleaned):
        return True
    if _REVIEW_TITLE_RE.fullmatch(cleaned):
        return True
    if "star" in lowered and RATING_RE.search(lowered) and len(cleaned.split()) <= 4:
        return True
    if lowered in LISTING_TITLE_CTA_TITLES:
        return True
    if lowered in DETAIL_LOW_SIGNAL_TITLE_VALUES:
        return True
    if lowered in LISTING_NAVIGATION_TITLE_HINTS or lowered in LISTING_WEAK_TITLES:
        return True
    if any(
        lowered.startswith(prefix) for prefix in LISTING_MERCHANDISING_TITLE_PREFIXES
    ):
        return True
    if any(pattern.search(lowered) for pattern in LISTING_ACTION_NOISE_PATTERNS):
        return True
    if any(pattern.search(lowered) for pattern in _LISTING_UTILITY_TITLE_REGEXES):
        return True
    if LISTING_ALT_TEXT_TITLE_PATTERN.search(lowered):
        return True
    return any(pattern.search(lowered) for pattern in LISTING_EDITORIAL_TITLE_PATTERNS)


def strip_html_tags(value: object) -> str:
    text = str(value or "")
    if "<" not in text or ">" not in text:
        return text
    return html_to_text(text)


def text_or_none(value: object) -> str | None:
    text = clean_text(value)
    return text or None


def slug_tokens(value: object) -> list[str]:
    return [
        token for token in re.split(r"[^a-z0-9]+", str(value or "").casefold()) if token
    ]


def coerce_text(value: object) -> str | None:
    if isinstance(value, str):
        literal_rows = _coerce_literal_text_list(value)
        if literal_rows:
            return text_or_none("; ".join(literal_rows))
        if "<" in value or html_entity_re.search(value):
            return text_or_none(html_to_text(value))
        return text_or_none(value)
    return text_or_none(value)


def coerce_long_text(value: object) -> str | None:
    if isinstance(value, str):
        literal_rows = _coerce_literal_text_list(value)
        if literal_rows:
            return text_or_none("; ".join(literal_rows))
        if "<" in value or html_entity_re.search(value):
            return text_or_none(html_to_text(value, preserve_block_breaks=True))
    return coerce_text(value)


def _coerce_literal_text_list(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text.startswith("[") or not text.endswith("]"):
        return []
    try:
        parsed = ast.literal_eval(text)
    except (MemoryError, RecursionError, SyntaxError, TypeError, ValueError):
        return []
    if not isinstance(parsed, (list, tuple)):
        return []
    return [
        clean_text(item)
        for item in parsed
        if not isinstance(item, (bool, dict, list, tuple, set)) and clean_text(item)
    ]


coerce_literal_text_list = _coerce_literal_text_list
