"""Publish-owned helpers for review-bucket shaping and LLM review payloads."""

from __future__ import annotations

from app.services.config.extraction_rules import (
    DISCOVERED_FIELD_NOISE_TOKENS,
    DISCOVERED_SOURCE_NOISE_TOKENS,
    DISCOVERED_VALUE_NOISE_PHRASES,
)
from app.services.extract.candidate_processing import (
    clean_candidate_text,
    normalize_committed_field_name,
)
from app.services.extract.review_bucket import review_bucket_fingerprint
from app.services.normalizers import (
    normalize_review_value as _normalize_review_value,
    passes_detail_quality_gate as _passes_detail_quality_gate,
    review_values_equal as _review_values_equal,
)
from app.services.pipeline.utils import _compact_dict


def _should_surface_discovered_field(
    field_name: object, value: object, *, source: str = ""
) -> bool:
    normalized_field = normalize_committed_field_name(field_name)
    if not normalized_field or normalized_field.startswith("_"):
        return False
    tokens = {token for token in normalized_field.split("_") if token}
    if tokens & DISCOVERED_FIELD_NOISE_TOKENS:
        return False

    normalized_value = _normalize_review_value(value)
    if normalized_value is None:
        return False
    cleaned_text = clean_candidate_text(normalized_value, limit=None)
    if isinstance(normalized_value, str):
        lowered_text = cleaned_text.lower()
        if len(cleaned_text) < 3:
            return False
        if any(phrase in lowered_text for phrase in DISCOVERED_VALUE_NOISE_PHRASES):
            return False

    lowered_source = str(source or "").strip().lower()
    if any(token in lowered_source for token in DISCOVERED_SOURCE_NOISE_TOKENS):
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
            fingerprint = (key, review_bucket_fingerprint(normalized_value))
            candidate = _compact_dict(
                {
                    "key": key,
                    "value": normalized_value,
                    "source": source,
                }
            )
            if fingerprint not in merged:
                merged[fingerprint] = candidate
    return sorted(
        merged.values(),
        key=lambda item: (
            str(item.get("key") or ""),
            str(item.get("source") or ""),
        ),
    )


def _normalize_llm_cleanup_review(
    field_name: object, raw_review: object, *, current_value: object
) -> dict | None:
    """Normalize an LLM cleanup review item."""
    normalized_field = str(field_name or "").strip()
    if not normalized_field or normalized_field.startswith("_"):
        return None
    if isinstance(raw_review, dict):
        suggested_value = _normalize_review_value(
            raw_review.get("suggested_value")
            if raw_review.get("suggested_value") not in (None, "", [], {})
            else raw_review.get("value"),
        )
        source = str(raw_review.get("source") or "llm_cleanup").strip() or "llm_cleanup"
        note = clean_candidate_text(
            raw_review.get("note") or raw_review.get("reason"), limit=280
        )
        supporting_sources = [
            str(item).strip()
            for item in (raw_review.get("supporting_sources") or [])
            if str(item).strip()
        ]
    else:
        suggested_value = _normalize_review_value(raw_review)
        source = "llm_cleanup"
        note = ""
        supporting_sources = []
    if not suggested_value:
        return None
    if _review_values_equal(current_value, suggested_value):
        return None
    return _compact_dict(
        {
            "field_name": normalized_field,
            "suggested_value": suggested_value,
            "source": source,
            "supporting_sources": supporting_sources or None,
            "note": note or None,
            "status": "pending_review",
        }
    )


def _split_llm_cleanup_payload(
    payload: object,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Split LLM cleanup payload into canonical and review bucket."""
    if not isinstance(payload, dict):
        return {}, []
    if "canonical" not in payload and "review_bucket" not in payload:
        canonical = {
            str(key).strip(): value
            for key, value in payload.items()
            if str(key).strip()
        }
        return canonical, []
    raw_canonical = payload.get("canonical")
    canonical = raw_canonical if isinstance(raw_canonical, dict) else {}
    raw_review_bucket = payload.get("review_bucket")
    review_bucket: list[dict[str, object]] = []
    if isinstance(raw_review_bucket, list):
        for row in raw_review_bucket:
            normalized = _normalize_llm_review_bucket_item(row)
            if normalized is not None:
                review_bucket.append(normalized)
    return canonical, _merge_review_bucket_entries(review_bucket)


def _normalize_llm_review_bucket_item(value: object) -> dict[str, object] | None:
    """Normalize a single LLM review bucket item."""
    if not isinstance(value, dict):
        return None
    key = str(value.get("key") or "").strip()
    if not key or key.startswith("_"):
        return None
    normalized_value = _normalize_review_value(value.get("value"))
    if normalized_value is None:
        return None
    return _compact_dict(
        {
            "key": key,
            "value": normalized_value,
            "source": str(value.get("source") or "llm_cleanup").strip()
            or "llm_cleanup",
        }
    )
