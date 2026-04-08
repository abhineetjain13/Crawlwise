"""Shared review helpers used across pipeline modules.

This module intentionally avoids importing ``pipeline.core`` so helper
functions can be reused without circular dependencies.
"""

from __future__ import annotations

from app.services.pipeline_config import (
    DISCOVERED_FIELD_NOISE_TOKENS,
    DISCOVERED_VALUE_NOISE_PHRASES,
)

from .field_normalization import (
    _normalize_review_value,
    _passes_detail_quality_gate,
)
from .utils import _clean_candidate_text, _normalize_committed_field_name, _compact_dict
from .verdict import _review_bucket_fingerprint


def _should_surface_discovered_field(
    field_name: object, value: object, *, source: str = ""
) -> bool:
    normalized_field = _normalize_committed_field_name(field_name)
    if not normalized_field or normalized_field.startswith("_"):
        return False
    tokens = {token for token in normalized_field.split("_") if token}
    if tokens & DISCOVERED_FIELD_NOISE_TOKENS:
        return False

    normalized_value = _normalize_review_value(value)
    if normalized_value is None:
        return False
    cleaned_text = _clean_candidate_text(normalized_value, limit=None)
    if isinstance(normalized_value, str):
        lowered_text = cleaned_text.lower()
        if len(cleaned_text) < 3:
            return False
        if any(phrase in lowered_text for phrase in DISCOVERED_VALUE_NOISE_PHRASES):
            return False

    lowered_source = str(source or "").strip().lower()
    if any(
        token in lowered_source
        for token in ("review", "reviews", "bazaarvoice", "rating_distribution")
    ):
        return False

    return _passes_detail_quality_gate(normalized_field, normalized_value)


def _merge_review_bucket_entries(
    *groups: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for group in groups:
        for row in group:
            key = str(row.get("key") or "").strip()
            if not key:
                continue
            normalized_value = _normalize_review_value(row.get("value"))
            if normalized_value is None:
                continue
            source = (
                str(row.get("source") or "review_bucket").strip() or "review_bucket"
            )
            if not _should_surface_discovered_field(
                key, normalized_value, source=source
            ):
                continue
            fingerprint = (key, _review_bucket_fingerprint(normalized_value))
            existing = merged.get(fingerprint)
            candidate = _compact_dict(
                {
                    "key": key,
                    "value": normalized_value,
                    "source": source,
                }
            )
            if existing is None:
                merged[fingerprint] = candidate
    return sorted(
        merged.values(),
        key=lambda item: (
            str(item.get("key") or ""),
            str(item.get("source") or ""),
        ),
    )
