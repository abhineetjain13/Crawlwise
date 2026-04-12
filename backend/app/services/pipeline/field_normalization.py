"""Field normalization and validation functions."""
from __future__ import annotations

import re

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
_DISCOVERED_EMAIL_RE = re.compile(
    r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b"
)
_DISCOVERED_PHONE_CANDIDATE_RE = re.compile(
    r"(?ix)"
    r"(?<!\w)"
    r"(?:\+?\(?\d[\d().\-\s]{7,}\d)"
    r"(?:\s*(?:ext\.?|x)\s*\d{1,5})?"
    r"(?!\w)"
)
_REDACTED = "[REDACTED]"


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
        validated_value = _scrub_persisted_value(validated_value)
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


def _scrub_persisted_text(text: str) -> str:
    scrubbed = _DISCOVERED_EMAIL_RE.sub(_REDACTED, str(text or ""))

    def _replace_phone(match: re.Match[str]) -> str:
        candidate = match.group(0)
        digits_only = re.sub(r"\D", "", candidate)
        if 10 <= len(digits_only) <= 15:
            return _REDACTED
        return candidate

    return _DISCOVERED_PHONE_CANDIDATE_RE.sub(_replace_phone, scrubbed)


def _scrub_persisted_value(value: object) -> object:
    if isinstance(value, str):
        return _scrub_persisted_text(value)
    if isinstance(value, dict):
        return {
            key: _scrub_persisted_value(inner_value)
            for key, inner_value in value.items()
        }
    if isinstance(value, list):
        return [_scrub_persisted_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_persisted_value(item) for item in value)
    return value


def _sanitize_review_bucket(value: object) -> object:
    if not isinstance(value, list):
        return _sanitize_discovered_data_value(value)
    sanitized_rows: list[object] = []
    for row in value:
        if not isinstance(row, dict):
            sanitized_rows.append(_sanitize_discovered_data_value(row))
            continue
        sanitized_row = {
            key: _sanitize_discovered_data_value(item)
            for key, item in row.items()
        }
        if "value" in sanitized_row:
            sanitized_row["value"] = _sanitize_discovered_data_value(row.get("value"))
        sanitized_rows.append(sanitized_row)
    return sanitized_rows


def _sanitize_discovered_fields(value: object) -> object:
    if not isinstance(value, dict):
        return _sanitize_discovered_data_value(value)
    return {
        key: _sanitize_discovered_data_value(item)
        for key, item in value.items()
    }


def _sanitize_discovered_data_value(value: object) -> object:
    if isinstance(value, str):
        return _scrub_persisted_value(value)
    if isinstance(value, dict):
        sanitized: dict[object, object] = {}
        for key, inner_value in value.items():
            key_text = str(key)
            if key_text == "review_bucket":
                sanitized[key] = _sanitize_review_bucket(inner_value)
                continue
            if key_text == "discovered_fields":
                sanitized[key] = _sanitize_discovered_fields(inner_value)
                continue
            sanitized[key] = _scrub_persisted_value(inner_value)
        return sanitized
    if isinstance(value, list):
        return [_scrub_persisted_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_persisted_value(item) for item in value)
    return value


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
    sanitized_discovered = _sanitize_discovered_data_value(sanitized_discovered)
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
