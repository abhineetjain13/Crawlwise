"""Field normalization and validation functions."""
from __future__ import annotations

from app.services.config.field_mappings import field_allowed_for_surface
from app.services.normalizers import (
    normalize_record_fields as _normalize_record_fields,
    normalize_review_value as _normalize_review_value,
    passes_detail_quality_gate as _passes_detail_quality_gate,
    review_values_equal as _review_values_equal,
)

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
