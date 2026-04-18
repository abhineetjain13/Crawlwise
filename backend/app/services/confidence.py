from __future__ import annotations

from typing import Any


_SURFACE_WEIGHTS: dict[str, dict[str, float]] = {
    "ecommerce_detail": {
        "title": 0.2,
        "price": 0.15,
        "brand": 0.1,
        "image_url": 0.1,
        "description": 0.1,
        "availability": 0.1,
        "variants": 0.15,
        "selected_variant": 0.1,
    },
    "job_detail": {
        "title": 0.2,
        "company": 0.1,
        "location": 0.1,
        "description": 0.1,
        "responsibilities": 0.15,
        "qualifications": 0.15,
        "apply_url": 0.1,
        "posted_date": 0.1,
    },
}


def score_record_confidence(
    record: dict[str, Any],
    *,
    surface: str,
    requested_fields: list[str] | None = None,
) -> dict[str, Any]:
    normalized_surface = str(surface or "").strip().lower()
    weights = dict(_SURFACE_WEIGHTS.get(normalized_surface) or {})
    if not weights:
        weights = {
            key: 1.0
            for key in ("title", "description", "image_url", "price", "company", "location")
        }
    score = 0.0
    present_fields: list[str] = []
    missing_fields: list[str] = []
    total_weight = sum(weights.values()) or 1.0

    for field_name, weight in weights.items():
        if record.get(field_name) not in (None, "", [], {}):
            score += weight
            present_fields.append(field_name)
        else:
            missing_fields.append(field_name)

    requested = [str(item or "").strip().lower() for item in list(requested_fields or []) if str(item or "").strip()]
    requested_found = [
        field_name for field_name in requested if record.get(field_name) not in (None, "", [], {})
    ]
    if requested:
        score += 0.15 * (len(requested_found) / max(len(requested), 1))
        total_weight += 0.15

    normalized_score = round(min(score / total_weight, 1.0), 4)
    return {
        "score": normalized_score,
        "level": _confidence_level(normalized_score),
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "requested_fields_total": len(requested),
        "requested_fields_found_best": len(requested_found),
    }


def _confidence_level(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"
