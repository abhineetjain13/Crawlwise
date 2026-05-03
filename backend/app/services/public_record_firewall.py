from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.services.config.field_mappings import (
    ADDITIONAL_IMAGES_FIELD,
    BARCODE_FIELD,
    CANONICAL_SCHEMAS,
    NAVIGATION_URL_FIELDS,
    PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS,
    PUBLIC_RECORD_URL_BLOCKED_PATH_MARKERS,
    PUBLIC_RECORD_URL_MAX_LENGTH,
    ROUTE_BARCODE_TO_SKU,
    SKU_FIELD,
    URL_FIELD,
    VARIANTS_FIELD,
)
from app.services.field_policy import canonical_requested_fields, normalize_field_key
from app.services.field_value_core import (
    IMAGE_FIELDS,
    LONG_TEXT_FIELDS,
    STRUCTURED_MULTI_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    URL_FIELDS,
    coerce_field_value,
    finalize_record,
    flatten_variants_for_public_output,
    text_or_none,
)
from app.services.field_url_normalization import (
    canonical_public_record_url,
    is_concatenated_url,
)

def public_record_data_for_surface(
    record: dict[str, Any],
    *,
    surface: str,
    page_url: str,
    requested_fields: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    normalized_surface = str(surface or "").strip().lower()
    allowed_fields = {
        str(field_name).strip()
        for field_name in list(CANONICAL_SCHEMAS.get(normalized_surface, []))
        if str(field_name).strip()
    }
    allowed_fields.add(URL_FIELD)
    explicit_fields = {
        normalize_field_key(field_name)
        for field_name in canonical_requested_fields(requested_fields or [])
        if normalize_field_key(field_name)
    }
    default_excluded = {
        normalize_field_key(field_name)
        for field_name in list(
            PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS.get(normalized_surface, [])
            if isinstance(PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS, dict)
            else []
        )
        if normalize_field_key(field_name)
    }
    data: dict[str, Any] = {}
    rejected: dict[str, str] = {}
    for raw_field_name, raw_value in dict(record or {}).items():
        field_name = normalize_field_key(raw_field_name)
        if not field_name or str(raw_field_name).startswith("_"):
            continue
        if raw_value in (None, "", [], {}):
            continue
        if field_name in default_excluded and field_name not in explicit_fields:
            rejected[str(raw_field_name)] = "default_public_field_excluded"
            continue
        if field_name not in allowed_fields:
            rejected[str(raw_field_name)] = "field_not_allowed_for_surface"
            continue
        coerced = coerce_field_value(field_name, raw_value, page_url)
        if field_name == VARIANTS_FIELD:
            coerced = flatten_variants_for_public_output(coerced, page_url=page_url)
        if coerced in (None, "", [], {}):
            if field_name == BARCODE_FIELD and ROUTE_BARCODE_TO_SKU:
                routed_sku = coerce_field_value(SKU_FIELD, raw_value, page_url)
                if (
                    routed_sku not in (None, "", [], {})
                    and SKU_FIELD in allowed_fields
                    and record.get(SKU_FIELD) in (None, "", [], {})
                    and _public_record_field_shape_valid(SKU_FIELD, routed_sku)
                ):
                    data[SKU_FIELD] = routed_sku
                    rejected[str(raw_field_name)] = "routed_to_sku"
                    continue
            rejected[str(raw_field_name)] = "empty_after_coercion"
            continue
        if not _public_record_field_shape_valid(field_name, coerced):
            rejected[str(raw_field_name)] = "invalid_field_shape"
            continue
        if field_name in URL_FIELDS and isinstance(coerced, str) and is_concatenated_url(coerced):
            rejected[str(raw_field_name)] = "concatenated_url"
            continue
        if field_name in NAVIGATION_URL_FIELDS and not public_navigation_url_safe(coerced):
            rejected[str(raw_field_name)] = "unsafe_navigation_url"
            continue
        if field_name in NAVIGATION_URL_FIELDS:
            coerced = canonical_public_record_url(
                coerced,
                surface=normalized_surface,
                field_name=field_name,
            )
            if coerced in (None, "", [], {}):
                rejected[str(raw_field_name)] = "empty_after_canonical_url"
                continue
        data[field_name] = coerced
    return finalize_record(data, surface=surface), rejected


def _public_record_field_shape_valid(field_name: str, value: object) -> bool:
    if field_name in STRUCTURED_OBJECT_FIELDS:
        return isinstance(value, dict)
    if field_name in STRUCTURED_OBJECT_LIST_FIELDS:
        return isinstance(value, list) and all(isinstance(item, dict) for item in value)
    if field_name in STRUCTURED_MULTI_FIELDS or field_name == ADDITIONAL_IMAGES_FIELD:
        return isinstance(value, list) and all(
            not isinstance(item, (dict, list, tuple, set)) for item in value
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
