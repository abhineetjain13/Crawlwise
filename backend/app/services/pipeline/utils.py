"""Utility functions for pipeline processing."""
from __future__ import annotations

import json
import re
import time
from html import unescape


def _elapsed_ms(started_at: float) -> int:
    """Calculate elapsed milliseconds from a start time."""
    return max(0, int(round((time.perf_counter() - started_at) * 1000)))


def _compact_dict(payload: dict) -> dict:
    """Remove None, empty string, empty list, and empty dict values."""
    return {
        key: value for key, value in payload.items() if value not in (None, "", [], {})
    }


def _clean_page_text(value: object) -> str:
    """Clean and normalize text from HTML."""
    text = unescape(str(value or "")).replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _first_non_empty_text(*nodes: object) -> str:
    """Extract first non-empty text from a list of nodes."""
    for node in nodes:
        text = ""
        if node is not None and hasattr(node, "get_text"):
            text = _clean_page_text(node.get_text(" ", strip=True))
        if text:
            return text
    return ""


def _normalize_committed_field_name(value: object) -> str:
    """Normalize field name to snake_case."""
    text = str(value or "").strip()
    if not text:
        return ""
    # Convert camelCase to snake_case
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    # Replace spaces with underscores
    normalized = re.sub(r"\s+", "_", text.lower())
    # Remove non-alphanumeric except underscores
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    # Collapse multiple underscores
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _review_bucket_fingerprint(value: object) -> str:
    """Generate a fingerprint for review bucket deduplication."""
    from .field_normalization import _normalize_review_value
    
    normalized_value = _normalize_review_value(value)
    try:
        return json.dumps(normalized_value, sort_keys=True, default=str)
    except TypeError:
        return str(normalized_value)


def _clean_candidate_text(value: object, *, limit: int | None = None) -> str:
    """Clean candidate text with optional length limit."""
    text = _clean_page_text(value)
    if limit is not None and len(text) > limit:
        return text[:limit].strip()
    return text
