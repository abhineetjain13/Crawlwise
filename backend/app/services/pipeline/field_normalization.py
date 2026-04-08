"""Field normalization and validation functions."""
from __future__ import annotations

from app.services.normalizers import extract_currency_hint, normalize_value, validate_value
from .utils import _clean_page_text, _compact_dict, _normalize_committed_field_name


def _normalize_review_value(value: object) -> object | None:
    """Normalize a value for review bucket."""
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (list, dict)):
        return value
    text = _clean_page_text(value)
    if not text or text.lower() in {"-", "—", "--", "n/a", "na", "none", "null", "undefined"}:
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
    
    # Remove currency for job listings
    if "job" in normalized_surface:
        normalized.pop("currency", None)
    
    # Extract currency hint for non-job listings
    if (
        "job" not in normalized_surface
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
            and text.lower()
            not in {"-", "—", "--", "n/a", "na", "none", "null", "undefined"}
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
    """Merge two records, preferring primary but taking better secondary values."""
    from .utils import _clean_candidate_text
    
    merged = dict(primary)
    for key, value in secondary.items():
        if key.startswith("_"):
            continue
        if _should_prefer_secondary_field(key, merged.get(key), value):
            merged[key] = value
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
    if field_name in {"description", "specifications"}:
        return len(_clean_candidate_text(candidate, limit=None)) > len(
            _clean_candidate_text(existing, limit=None)
        )
    if field_name in {"brand", "category"}:
        existing_text = _clean_candidate_text(existing, limit=None).casefold()
        candidate_text = _clean_candidate_text(candidate, limit=None).casefold()
        if not candidate_text:
            return False
        low_quality_tokens = {
            "cookie",
            "privacy",
            "sign in",
            "log in",
            "account",
            "home",
            "menu",
        }
        existing_is_noisy = any(token in existing_text for token in low_quality_tokens)
        candidate_is_noisy = any(token in candidate_text for token in low_quality_tokens)
        if existing_is_noisy and not candidate_is_noisy:
            return True
        if not existing_is_noisy and candidate_is_noisy:
            return False
        # Prefer a richer candidate label when both pass baseline quality.
        return len(candidate_text) > len(existing_text)
    if field_name == "additional_images":
        # Handle both list/tuple and string inputs
        if isinstance(existing, (list, tuple)):
            existing_count = len([p for p in existing if p])
        else:
            existing_count = len(
                [part for part in str(existing or "").split(",") if part.strip()]
            )
        
        if isinstance(candidate, (list, tuple)):
            candidate_count = len([p for p in candidate if p])
        else:
            candidate_count = len(
                [part for part in str(candidate or "").split(",") if part.strip()]
            )
        
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
