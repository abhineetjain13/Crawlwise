"""Verdict computation for extraction quality assessment."""
from __future__ import annotations

import json

from app.services.config.extraction_rules import REQUIRED_FIELDS_BY_SURFACE
from app.services.extract import assess_listing_record_quality
from app.services.normalizers import normalize_review_value as _normalize_review_value

VERDICT_SUCCESS = "success"
VERDICT_PARTIAL = "partial"
VERDICT_BLOCKED = "blocked"
VERDICT_SCHEMA_MISS = "schema_miss"
VERDICT_LISTING_FAILED = "listing_detection_failed"
VERDICT_EMPTY = "empty"
VERDICT_ERROR = "error"

__all__ = [
    "VERDICT_SUCCESS",
    "VERDICT_PARTIAL",
    "VERDICT_BLOCKED",
    "VERDICT_SCHEMA_MISS",
    "VERDICT_LISTING_FAILED",
    "VERDICT_EMPTY",
    "VERDICT_ERROR",
    "compute_verdict",
    "_passes_core_verdict",
    "_aggregate_verdict",
]


def compute_verdict(records: list[dict], surface: str, *, is_listing: bool) -> str:
    """Compute extraction quality verdict for a single URL."""
    if not records:
        return VERDICT_LISTING_FAILED if is_listing else VERDICT_EMPTY

    for record in records:
        if _passes_core_verdict(record, surface, is_listing=is_listing):
            return VERDICT_SUCCESS

    return VERDICT_PARTIAL


_compute_verdict = compute_verdict


def _passes_core_verdict(record: dict, surface: str, *, is_listing: bool) -> bool:
    """Check if a record passes core quality requirements."""
    if is_listing:
        return assess_listing_record_quality(
            record, surface=str(surface or "").strip().lower()
        ).meaningful

    normalized_record = {
        key: value
        for key, value in dict(record or {}).items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    title = normalized_record.get("title")
    price = (
        normalized_record.get("price")
        or normalized_record.get("sale_price")
        or normalized_record.get("original_price")
    )
    image_url = normalized_record.get("image_url")
    company = normalized_record.get("company")
    description = normalized_record.get("description")

    surface_key = str(surface or "").strip().lower()
    required_fields = REQUIRED_FIELDS_BY_SURFACE.get(surface_key, frozenset())
    if required_fields:
        if required_fields == frozenset({"title"}):
            return bool(title and (price or image_url))
        return all(
            normalized_record.get(field) not in (None, "", [], {})
            for field in required_fields
        )
    return bool(title and (price or image_url or company or description))


def _aggregate_verdict(verdicts: list[str]) -> str:
    """Aggregate per-URL verdicts into a single run verdict."""
    if not verdicts:
        return VERDICT_EMPTY
    if all(v == VERDICT_ERROR for v in verdicts):
        return VERDICT_ERROR
    if all(v == VERDICT_BLOCKED for v in verdicts):
        return VERDICT_BLOCKED
    if all(v == VERDICT_SUCCESS for v in verdicts):
        return VERDICT_SUCCESS
    if VERDICT_ERROR in verdicts:
        return VERDICT_ERROR
    if any(v in {VERDICT_SUCCESS, VERDICT_PARTIAL} for v in verdicts):
        return VERDICT_PARTIAL

    for verdict in [
        VERDICT_ERROR,
        VERDICT_LISTING_FAILED,
        VERDICT_SCHEMA_MISS,
        VERDICT_BLOCKED,
        VERDICT_EMPTY,
    ]:
        if verdict in verdicts:
            return verdict
    return VERDICT_PARTIAL


def _review_bucket_fingerprint(value: object) -> str:
    """Generate a fingerprint for a review bucket value."""
    normalized_value = _normalize_review_value(value)
    try:
        return json.dumps(normalized_value, sort_keys=True, default=str)
    except TypeError:
        return str(normalized_value)
