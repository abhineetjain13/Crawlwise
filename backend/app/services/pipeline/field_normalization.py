"""Field normalization and validation functions."""
from __future__ import annotations

from app.services.normalizers import extract_currency_hint, normalize_value, validate_value
from app.services.pipeline_config import EMPTY_SENTINEL_VALUES

from .utils import _clean_page_text, _compact_dict, _normalize_committed_field_name


def _normalize_review_value(value: object) -> object | None:
    """Normalize a value for review bucket."""
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (list, dict)):
        return value
    text = _clean_page_text(value)
    if not text or text.lower() in EMPTY_SENTINEL_VALUES:
        return None
    return text


def _review_values_equal(left: object, right: object) -> bool:
    """Check if two review values are equal."""
    normalized_left = _normalize_review_value(left)
    normalized_right = _normalize_review_value(right)
    if normalized_left is None and normalized_right is None:
        return True
    if normalized_left is None or normalized_right is None:
        return False
    return normalized_left == normalized_right


def _normalize_record_fields(
    record: dict[str, object], *, surface: str = ""
) -> dict[str, object]:
    """Normalize all fields in a record."""
    normalized: dict[str, object] = {}
    normalized_surface = str(surface or "").strip().lower()
    
    for key, value in record.items():
        normalized_key = _normalize_committed_field_name(key)
        if not normalized_key:
            continue
        normalized_value = normalize_value(normalized_key, value)
        validated_value = validate_value(normalized_key, normalized_value)
        if validated_value in (None, "", [], {}):
            continue
        normalized[normalized_key] = validated_value
    
    normalized = _compact_dict(normalized)

    # Extract currency hint for non-job listings
    if (
        normalized_surface != "job"
        and not normalized_surface.startswith("job_")
        and not str(normalized.get("currency") or "").strip()
    ):
        for field_name in ("price", "sale_price", "original_price", "salary"):
            currency_hint = extract_currency_hint(normalized.get(field_name))
            if currency_hint:
                normalized["currency"] = currency_hint
                break
    
    return normalized


def _passes_detail_quality_gate(field_name: str, value: object) -> bool:
    """Check if a field value passes quality gate."""
    if value in (None, "", [], {}):
        return False
    validated = validate_value(field_name, value)
    if validated in (None, "", [], {}):
        return False
    if isinstance(validated, str):
        text = " ".join(validated.split()).strip()
        return bool(
            text
            and text.lower() not in EMPTY_SENTINEL_VALUES
        )
    return True


def _raw_record_payload(record: dict) -> dict:
    """Extract raw record payload."""
    raw_item = record.get("_raw_item")
    if isinstance(raw_item, dict):
        return raw_item
    return _public_record_fields(record)


def _public_record_fields(record: dict) -> dict:
    """Filter to public record fields (non-underscore prefixed)."""
    return {
        key: value
        for key, value in record.items()
        if not str(key).startswith("_")
    }


def _merge_record_fields(primary: dict, secondary: dict) -> dict:
    """Merge two records, preferring primary but taking better secondary values.

    Uses FieldDecisionEngine for sanitisation-aware merge preference.
    """
    from app.services.extract.field_decision import FieldDecisionEngine

    engine = FieldDecisionEngine()
    merged = dict(primary)
    for key, value in secondary.items():
        if key.startswith("_"):
            continue
        merged[key] = engine.decide_merge_preference(key, merged.get(key), value)
    return merged


def _should_prefer_secondary_field(
    field_name: str, existing: object, candidate: object
) -> bool:
    """Determine if secondary field value should be preferred."""
    from .utils import _clean_candidate_text
    
    if candidate in (None, "", [], {}):
        return False
    if existing in (None, "", [], {}):
        return True
        
    existing_text = _clean_candidate_text(existing, limit=None).casefold()
    candidate_text = _clean_candidate_text(candidate, limit=None).casefold()
    
    if not candidate_text:
        return False

    # 1. Long-form text fields: longer is generally better
    if field_name in {"description", "specifications", "responsibilities", "requirements"}:
        return len(candidate_text) > len(existing_text)

    # 2. Short-form categorical fields: prevent long noise from overwriting short facts
    if field_name in {"brand", "category", "color", "size", "availability"}:
        # FIX: If the candidate is suspiciously long (e.g., a sentence), reject it
        if len(candidate_text) > 40 or len(candidate_text.split()) > 5:
            return False
            
        low_quality_tokens = {
            "cookie", "privacy", "sign in", "log in", 
            "account", "home", "menu", "agree", "policy"
        }
        existing_is_noisy = any(token in existing_text for token in low_quality_tokens)
        candidate_is_noisy = any(token in candidate_text for token in low_quality_tokens)
        
        if existing_is_noisy and not candidate_is_noisy:
            return True
        if not existing_is_noisy and candidate_is_noisy:
            return False
            
        # If both are clean, prefer the slightly longer/richer label,
        # but only up to our 40-character safety cap.
        return len(candidate_text) > len(existing_text)

    # 3. List-based fields (images)
    if field_name == "additional_images":
        existing_count = len([p.strip() for p in (existing if isinstance(existing, (list, tuple)) else str(existing or "").split(",")) if p.strip()])
        candidate_count = len([p.strip() for p in (candidate if isinstance(candidate, (list, tuple)) else str(candidate or "").split(",")) if p.strip()])
        return candidate_count > existing_count
        
    return False


def _requested_field_coverage(record: dict, requested_fields: list[str]) -> dict:
    """Calculate coverage of requested fields in a record."""
    if not requested_fields:
        return {}
    normalized_requested = [field for field in requested_fields if field]
    found = [
        field
        for field in normalized_requested
        if record.get(field) not in (None, "", [], {})
    ]
    return {
        "requested": len(normalized_requested),
        "found": len(found),
        "missing": [field for field in normalized_requested if field not in found],
    }
