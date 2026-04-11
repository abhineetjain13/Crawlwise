from __future__ import annotations

import json

from app.services.extract.noise_policy import sanitize_product_attribute_map
from app.services.normalizers import normalize_and_validate_value
from app.services.requested_field_policy import normalize_requested_field

# ---------------------------------------------------------------------------
# Module-level constants (only used by functions in this module)
# ---------------------------------------------------------------------------

_STRUCTURED_CANONICAL_ATTRIBUTE_KEYS = {
    "additional_images",
    "availability",
    "brand",
    "category",
    "color",
    "description",
    "features",
    "image_url",
    "materials",
    "original_price",
    "price",
    "product_attributes",
    "selected_variant",
    "size",
    "sku",
    "specifications",
    "variant_axes",
    "variants",
}
_TRUE_VARIANT_AXES = {"color", "size", "waist", "width", "length", "inseam"}
# ---------------------------------------------------------------------------
# Inline helper (avoids circular import with service.py)
# ---------------------------------------------------------------------------

def _normalized_candidate_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


# ---------------------------------------------------------------------------
# Moved functions
# ---------------------------------------------------------------------------

def _canonical_structured_key(value: object) -> str:
    text = _normalized_candidate_text(value).lower()
    if text in {"color", "colour", "colors", "colours"}:
        return "color"
    if text in {"size", "sizes", "dimension", "dimensions"}:
        return "size"
    normalized = normalize_requested_field(text)
    if normalized in {"dimension", "dimensions"}:
        return "size"
    return normalized or text


def _split_variant_axes(
    axis_values: dict[str, list[str]],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    selectable: dict[str, list[str]] = {}
    product_attributes: dict[str, str] = {}
    for axis_name, values in axis_values.items():
        cleaned_values = list(
            dict.fromkeys(
                _normalized_candidate_text(value)
                for value in values
                if _normalized_candidate_text(value)
            )
        )
        if len(cleaned_values) > 1 or axis_name in _TRUE_VARIANT_AXES:
            selectable[axis_name] = cleaned_values
        elif len(cleaned_values) == 1:
            product_attributes[axis_name] = cleaned_values[0]
    return selectable, product_attributes


def _sync_selected_variant_root_fields(final_candidates: dict[str, list[dict]]) -> None:
    selected_rows = final_candidates.get("selected_variant")
    if not isinstance(selected_rows, list) or not selected_rows:
        return
    selected_row = selected_rows[0]
    selected_variant = (
        selected_row.get("value") if isinstance(selected_row, dict) else None
    )
    if not isinstance(selected_variant, dict):
        return
    source = (
        str(selected_row.get("source") or "selected_variant").strip()
        or "selected_variant"
    )
    for field_name in (
        "price",
        "original_price",
        "sku",
        "color",
        "size",
        "availability",
        "image_url",
    ):
        value = selected_variant.get(field_name)
        if value in (None, "", [], {}):
            continue
        final_candidates[field_name] = [{"value": value, "source": source}]


def _merge_product_attributes_into_candidates(
    final_candidates: dict[str, list[dict]],
    attributes: dict[str, object],
    *,
    source: str,
) -> None:
    if not attributes:
        return
    merged: dict[str, object] = {}
    existing_rows = final_candidates.get("product_attributes")
    if isinstance(existing_rows, list) and existing_rows:
        current = (
            existing_rows[0].get("value")
            if isinstance(existing_rows[0], dict)
            else None
        )
        if isinstance(current, dict):
            merged.update(current)
    merged.update(attributes)
    sanitized = sanitize_product_attribute_map(
        merged,
        blocked_keys=_STRUCTURED_CANONICAL_ATTRIBUTE_KEYS,
    )
    if sanitized:
        final_candidates["product_attributes"] = [{"value": sanitized, "source": source}]
    else:
        final_candidates.pop("product_attributes", None)


def _sanitize_product_attributes(final_candidates: dict[str, list[dict]]) -> None:
    product_rows = final_candidates.get("product_attributes")
    if not isinstance(product_rows, list) or not product_rows:
        return
    product_row = product_rows[0]
    payload = product_row.get("value") if isinstance(product_row, dict) else None
    if not isinstance(payload, dict):
        final_candidates.pop("product_attributes", None)
        return
    blocked_keys = {
        key
        for key in final_candidates.keys()
        if key in _STRUCTURED_CANONICAL_ATTRIBUTE_KEYS and key != "product_attributes"
    } | _STRUCTURED_CANONICAL_ATTRIBUTE_KEYS
    sanitized = sanitize_product_attribute_map(payload, blocked_keys=blocked_keys)
    if sanitized:
        final_candidates["product_attributes"] = [{**product_row, "value": sanitized}]
    else:
        final_candidates.pop("product_attributes", None)


def _reconcile_variant_bundle(
    final_candidates: dict[str, list[dict]],
    *,
    base_url: str,
) -> None:
    variants_row = _first_candidate_row(final_candidates.get("variants"))
    selected_row = _first_candidate_row(final_candidates.get("selected_variant"))
    axes_row = _first_candidate_row(final_candidates.get("variant_axes"))

    variants = _normalized_variant_rows_payload(
        variants_row.get("value") if variants_row else None,
        base_url=base_url,
    )
    selected_variant = _normalized_selected_variant_payload(
        selected_row.get("value") if selected_row else None,
        base_url=base_url,
    )
    variant_axes = _normalized_variant_axes_payload(
        axes_row.get("value") if axes_row else None,
        base_url=base_url,
    )

    if variants:
        matched_index = (
            _find_matching_variant_index(variants, selected_variant)
            if selected_variant
            else -1
        )
        if selected_variant and matched_index >= 0:
            merged_selected = _merge_variant_records(
                variants[matched_index],
                selected_variant,
            )
            variants[matched_index] = merged_selected
            selected_variant = merged_selected
        elif selected_variant and _is_meaningful_variant_record(selected_variant):
            variants.append(selected_variant)
        if selected_variant is None:
            selected_variant = _choose_default_variant(variants)

        raw_axis_values = _collect_variant_axis_values(variants)
        merged_axis_values = _merge_variant_axis_values(
            discovered_axes=raw_axis_values,
            declared_axes=variant_axes,
        )
        if merged_axis_values:
            variant_axes, variant_attributes = _split_variant_axes(merged_axis_values)
            if variant_axes:
                source = _row_source_label(variants_row, fallback="variants")
                final_candidates["variant_axes"] = [
                    {"value": variant_axes, "source": source}
                ]
            else:
                final_candidates.pop("variant_axes", None)
            if variant_attributes:
                _merge_product_attributes_into_candidates(
                    final_candidates,
                    variant_attributes,
                    source=_row_source_label(variants_row, fallback="variants"),
                )
        else:
            final_candidates.pop("variant_axes", None)

        final_candidates["variants"] = [
            {
                "value": variants,
                "source": _row_source_label(variants_row, fallback="variants"),
            }
        ]
        selected_source = _row_source_label(
            selected_row or variants_row,
            fallback="selected_variant",
        )
        if selected_variant:
            final_candidates["selected_variant"] = [
                {
                    "value": selected_variant,
                    "source": selected_source,
                }
            ]
        else:
            final_candidates.pop("selected_variant", None)
        return

    if variant_axes:
        cleaned_axes, moved_attributes = _split_variant_axes(variant_axes)
        if cleaned_axes:
            final_candidates["variant_axes"] = [
                {
                    "value": cleaned_axes,
                    "source": _row_source_label(axes_row, fallback="variant_axes"),
                }
            ]
        else:
            final_candidates.pop("variant_axes", None)
        if moved_attributes:
            _merge_product_attributes_into_candidates(
                final_candidates,
                moved_attributes,
                source=_row_source_label(axes_row, fallback="variant_axes"),
            )
    else:
        final_candidates.pop("variant_axes", None)

    if selected_variant:
        final_candidates["selected_variant"] = [
            {
                "value": selected_variant,
                "source": _row_source_label(selected_row, fallback="selected_variant"),
            }
        ]
    else:
        final_candidates.pop("selected_variant", None)


def _merge_variant_axis_values(
    *,
    discovered_axes: dict[str, list[str]],
    declared_axes: dict[str, list[str]],
) -> dict[str, list[str]]:
    if not discovered_axes:
        return dict(declared_axes)
    merged: dict[str, list[str]] = {
        axis_name: list(values) for axis_name, values in discovered_axes.items()
    }
    for axis_name, values in declared_axes.items():
        normalized_axis = _canonical_structured_key(axis_name)
        if not normalized_axis or normalized_axis not in discovered_axes:
            continue
        bucket = merged.setdefault(normalized_axis, [])
        for value in values:
            cleaned = _normalized_candidate_text(value)
            if cleaned and cleaned not in bucket:
                bucket.append(cleaned)
    return merged


def _first_candidate_row(rows: object) -> dict[str, object] | None:
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _row_source_label(row: dict[str, object] | None, *, fallback: str) -> str:
    if not isinstance(row, dict):
        return fallback
    return str(row.get("source") or fallback).strip() or fallback


def _normalized_variant_rows_payload(
    value: object,
    *,
    base_url: str,
) -> list[dict[str, object]]:
    normalized = normalize_and_validate_value("variants", value, base_url=base_url)
    if not isinstance(normalized, list):
        return []
    reconciled: list[dict[str, object]] = []
    seen: set[str] = set()
    for variant in normalized:
        if not _is_meaningful_variant_record(variant):
            continue
        fingerprint = _variant_record_fingerprint(variant)
        if fingerprint and fingerprint in seen:
            continue
        if fingerprint:
            seen.add(fingerprint)
        reconciled.append(dict(variant))
    return reconciled


def _normalized_selected_variant_payload(
    value: object,
    *,
    base_url: str,
) -> dict[str, object] | None:
    normalized = normalize_and_validate_value("selected_variant", value, base_url=base_url)
    if not isinstance(normalized, dict) or not _is_meaningful_variant_record(normalized):
        return None
    return dict(normalized)


def _normalized_variant_axes_payload(
    value: object,
    *,
    base_url: str,
) -> dict[str, list[str]]:
    normalized = normalize_and_validate_value("variant_axes", value, base_url=base_url)
    return normalized if isinstance(normalized, dict) else {}


def _is_meaningful_variant_record(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("variant_id") not in (None, "", [], {}):
        return True
    if value.get("sku") not in (None, "", [], {}):
        return True
    option_values = value.get("option_values")
    if isinstance(option_values, dict) and option_values:
        return True
    for key in ("color", "size", "price", "original_price", "availability", "image_url"):
        if value.get(key) not in (None, "", [], {}):
            return True
    return False


def _variant_record_fingerprint(value: dict[str, object]) -> str:
    variant_id = str(value.get("variant_id") or "").strip()
    if variant_id:
        return f"id:{variant_id}"
    sku = str(value.get("sku") or "").strip()
    option_values = value.get("option_values")
    if sku and isinstance(option_values, dict) and option_values:
        return json.dumps({"sku": sku, "option_values": option_values}, sort_keys=True, default=str)
    if sku:
        return f"sku:{sku}"
    if isinstance(option_values, dict) and option_values:
        return json.dumps({"option_values": option_values}, sort_keys=True, default=str)
    fallback = {
        key: value.get(key)
        for key in ("color", "size", "price", "original_price", "availability", "image_url")
        if value.get(key) not in (None, "", [], {})
    }
    if not fallback:
        return ""
    extra_disambiguator = (
        value.get("source")
        or value.get("scraper_name")
        or value.get("row_index")
        or value.get("row_number")
        or value.get("sequence")
    )
    if extra_disambiguator not in (None, "", [], {}):
        fallback["source_disambiguator"] = extra_disambiguator
    return json.dumps(fallback, sort_keys=True, default=str)


def _find_matching_variant_index(
    variants: list[dict[str, object]],
    selected_variant: dict[str, object] | None,
) -> int:
    if not selected_variant:
        return -1
    selected_fingerprint = _variant_record_fingerprint(selected_variant)
    if selected_fingerprint:
        for index, variant in enumerate(variants):
            if _variant_record_fingerprint(variant) == selected_fingerprint:
                return index
    selected_options = selected_variant.get("option_values")
    if isinstance(selected_options, dict) and selected_options:
        for index, variant in enumerate(variants):
            if variant.get("option_values") == selected_options:
                return index
    return -1


def _merge_variant_records(
    primary: dict[str, object],
    secondary: dict[str, object],
) -> dict[str, object]:
    merged = dict(primary)
    for key, value in secondary.items():
        if merged.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
            merged[key] = value
    if isinstance(primary.get("option_values"), dict) and isinstance(secondary.get("option_values"), dict):
        merged["option_values"] = {
            **secondary["option_values"],
            **primary["option_values"],
        }
    return merged


def _choose_default_variant(
    variants: list[dict[str, object]],
) -> dict[str, object] | None:
    if not variants:
        return None
    return next(
        (variant for variant in variants if variant.get("availability") == "in_stock"),
        variants[0],
    )


def _collect_variant_axis_values(
    variants: list[dict[str, object]],
) -> dict[str, list[str]]:
    axis_values: dict[str, list[str]] = {}
    for variant in variants:
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict):
            continue
        for axis_name, value in option_values.items():
            normalized_axis = _canonical_structured_key(axis_name)
            cleaned_value = _normalized_candidate_text(value)
            if not normalized_axis or not cleaned_value:
                continue
            bucket = axis_values.setdefault(normalized_axis, [])
            if cleaned_value not in bucket:
                bucket.append(cleaned_value)
    return axis_values
