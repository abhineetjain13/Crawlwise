from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlparse

from w3lib.url import url_query_cleaner


TRACKING_PARAM_EXACT_KEYS = {"fbclid", "gclid", "ref", "sid"}
TRACKING_DETAIL_CONTEXT_EXACT_KEYS = {
    "content_source",
    "external",
    "pf_from",
    "qs",
    "sr_prefetch",
}


TRACKING_PARAM_PREFIXES = ("utm_", "click_")
TRACKING_STRIP_URL_FIELDS = {"apply_url", "source_url", "url"}
_PRESERVED_SHORT_QUERY_KEYS = {"id", "ids", "p", "page", "pid", "q", "sku", "v"}
_SHORT_TRACKING_VALUE_RE = re.compile(r"^[a-z0-9_-]{0,8}$", re.I)


def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None

def _surface_needs_tracking_strip(surface: str | None) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    return normalized_surface.startswith(("ecommerce_", "job_"))


def strip_tracking_query_params(url: object) -> str | None:
    text = _text_or_none(url)
    if not text:
        return None
    parsed = urlparse(text)
    if not parsed.query:
        return text
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    has_detail_context_tracking = any(
        _is_tracking_detail_context_key(key)
        for key, _ in query_pairs
    )
    removable_keys: list[str] = []
    for key, value in query_pairs:
        if _is_tracking_query_key(key) or _is_short_tracking_flag(
            key,
            value,
            has_detail_context_tracking=has_detail_context_tracking,
        ):
            removable_keys.append(key)
    if not removable_keys:
        return text
    return url_query_cleaner(
        text,
        parameterlist=tuple(dict.fromkeys(removable_keys)),
        remove=True,
        keep_fragments=True,
    )


def _is_tracking_query_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAM_EXACT_KEYS | TRACKING_DETAIL_CONTEXT_EXACT_KEYS or any(
        lowered.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES
    )


def _is_tracking_detail_context_key(key: str) -> bool:
    return key.lower() in TRACKING_DETAIL_CONTEXT_EXACT_KEYS


def _is_short_tracking_flag(
    key: str,
    value: str,
    *,
    has_detail_context_tracking: bool,
) -> bool:
    lowered = key.lower()
    if not has_detail_context_tracking or lowered in _PRESERVED_SHORT_QUERY_KEYS:
        return False
    if len(lowered) > 3:
        return False
    normalized_value = str(value or "").strip().lower()
    if len(normalized_value) > 8:
        return False
    if normalized_value and _SHORT_TRACKING_VALUE_RE.fullmatch(normalized_value) is None:
        return False
    return True


def strip_record_tracking_params(
    record: dict[str, Any],
    *,
    surface: str | None,
) -> dict[str, Any]:
    if not _surface_needs_tracking_strip(surface):
        return record
    cleaned = dict(record)
    for field_name in TRACKING_STRIP_URL_FIELDS:
        value = strip_tracking_query_params(cleaned.get(field_name))
        if value:
            cleaned[field_name] = value
    return cleaned
