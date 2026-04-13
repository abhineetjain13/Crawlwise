"""Field normalization and validation functions."""
from __future__ import annotations

from app.services.config.field_mappings import field_allowed_for_surface
from app.services.config.extraction_rules import EMPTY_SENTINEL_VALUES
from app.services.normalizers import extract_currency_hint, normalize_value, validate_value

from .utils import _clean_page_text, _compact_dict, _normalize_committed_field_name

_PERSISTENCE_DISALLOWED_DISCOVERED_KEYS = frozenset(
    {
        "_raw_item",
        "raw_item",
        "container",
        "schema",
        "schema_data",
        "__typename",
        "@context",
        "@type",
    }
)


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


def _surface_public_record_fields(record: dict, *, surface: str) -> dict:
    """Filter record fields to the public schema allowed for the target surface."""
    return {
        key: value
        for key, value in _public_record_fields(record).items()
        if field_allowed_for_surface(surface, str(key))
    }


def _surface_raw_record_payload(record: dict, *, surface: str) -> dict:
    """Return a surface-scoped raw payload without internal or disallowed fields."""
    raw_item = record.get("_raw_item")
    if isinstance(raw_item, dict):
        return {
            key: value
            for key, value in raw_item.items()
            if field_allowed_for_surface(surface, str(key))
        }
    return _surface_public_record_fields(record, surface=surface)


def _sanitize_persisted_record_payload(
    record: dict[str, object] | None,
    *,
    discovered_data: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    sanitized_record = dict(record or {})
    sanitized_record.pop("_raw_item", None)
    sanitized_record = {
        key: value
        for key, value in sanitized_record.items()
        if not str(key).startswith("_")
    }
    sanitized_discovered = {
        key: value
        for key, value in dict(discovered_data or {}).items()
        if key not in _PERSISTENCE_DISALLOWED_DISCOVERED_KEYS
    }
    return sanitized_record, sanitized_discovered


def _merge_record_fields(
    primary: dict,
    secondary: dict,
    *,
    return_reconciliation: bool = False,
) -> dict | tuple[dict, dict[str, dict[str, object]]]:
    """Merge two records through the field arbitration engine."""
    from app.services.extract import FieldDecisionEngine

    engine = FieldDecisionEngine()
    merged = engine.merge_record_fields(
        primary,
        secondary,
        return_reconciliation=return_reconciliation,
    )
    if return_reconciliation:
        merged_record, reconciliation = merged
        return merged_record, {
            key: _compact_dict(value) for key, value in reconciliation.items()
        }
    return merged


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
