from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.services.config.field_mappings import (
    CANONICAL_SCHEMAS,
    PUBLIC_RECORD_URL_BLOCKED_PATH_MARKERS,
    PUBLIC_RECORD_URL_MAX_LENGTH,
)
from app.services.field_policy import normalize_field_key
from app.services.field_value_core import (
    IMAGE_FIELDS,
    LONG_TEXT_FIELDS,
    STRUCTURED_MULTI_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    URL_FIELDS,
    coerce_field_value,
    finalize_record,
    text_or_none,
)


def public_record_data_for_surface(
    record: dict[str, Any],
    *,
    surface: str,
    page_url: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    normalized_surface = str(surface or "").strip().lower()
    allowed_fields = {
        str(field_name).strip()
        for field_name in list(CANONICAL_SCHEMAS.get(normalized_surface, []))
        if str(field_name).strip()
    }
    allowed_fields.add("url")
    data: dict[str, Any] = {}
    rejected: dict[str, str] = {}
    for raw_field_name, raw_value in dict(record or {}).items():
        field_name = normalize_field_key(raw_field_name)
        if not field_name or str(raw_field_name).startswith("_"):
            continue
        if raw_value in (None, "", [], {}):
            continue
        if field_name not in allowed_fields:
            rejected[str(raw_field_name)] = "field_not_allowed_for_surface"
            continue
        coerced = coerce_field_value(field_name, raw_value, page_url)
        if coerced in (None, "", [], {}):
            rejected[str(raw_field_name)] = "empty_after_coercion"
            continue
        if not _public_record_field_shape_valid(field_name, coerced):
            rejected[str(raw_field_name)] = "invalid_field_shape"
            continue
        if field_name in {"url", "apply_url"} and not public_navigation_url_safe(coerced):
            rejected[str(raw_field_name)] = "unsafe_navigation_url"
            continue
        data[field_name] = coerced
    return finalize_record(data, surface=surface), rejected


def _public_record_field_shape_valid(field_name: str, value: object) -> bool:
    if field_name in STRUCTURED_OBJECT_FIELDS:
        return isinstance(value, dict)
    if field_name in STRUCTURED_OBJECT_LIST_FIELDS:
        return isinstance(value, list) and all(isinstance(item, dict) for item in value)
    if field_name in STRUCTURED_MULTI_FIELDS or field_name == "additional_images":
        return isinstance(value, list) and all(
            not isinstance(item, (dict, list, tuple, set))
            for item in value
        )
    if field_name in URL_FIELDS | IMAGE_FIELDS | LONG_TEXT_FIELDS:
        return isinstance(value, str)
    return not isinstance(value, (dict, list, tuple, set))


def public_navigation_url_safe(value: object) -> bool:
    text = text_or_none(value)
    if not text:
        return False
    if len(text) > int(PUBLIC_RECORD_URL_MAX_LENGTH):
        return False
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return False
    lowered_path = str(parsed.path or "").lower()
    if any(
        marker in lowered_path
        for marker in tuple(PUBLIC_RECORD_URL_BLOCKED_PATH_MARKERS or ())
    ):
        return False
    return True
