from __future__ import annotations

import json

from app.services.extract.noise_policy import sanitize_product_attribute_map
from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_key as _canonical_structured_key,
    split_variant_axes as _split_variant_axes,
)
from app.services.extract.variant_types import (
    VariantAxisValues,
    VariantCandidateRow,
    VariantCandidateRowMap,
    VariantProductAttributes,
    VariantRecord,
    VariantRecords,
)
from app.services.normalizers import normalize_and_validate_value

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
_VARIANT_AXIS_REJECT_TOKENS = frozenset(
    {
        "guide",
        "size guide",
        "size chart",
        "share",
        "see more",
        "select",
        "choose",
        "notify",
        "waitlist",
    }
)
# ---------------------------------------------------------------------------
# Inline helper (avoids circular import with service.py)
# ---------------------------------------------------------------------------

def _normalized_candidate_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


# ---------------------------------------------------------------------------
# Moved functions
# ---------------------------------------------------------------------------

def _sync_selected_variant_root_fields(final_candidates: VariantCandidateRowMap) -> None:
    variant_rows = final_candidates.get("variants")
    if not isinstance(variant_rows, list) or not variant_rows:
        return
    variant_payload = (
        variant_rows[0].get("value") if isinstance(variant_rows[0], dict) else None
    )
    if not isinstance(variant_payload, list) or not variant_payload:
        return
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
    inferred_default = "inferred_default" in source
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
        if inferred_default and final_candidates.get(field_name):
            continue
        final_candidates[field_name] = [{"value": value, "source": source}]


def _merge_product_attributes_into_candidates(
    final_candidates: VariantCandidateRowMap,
    attributes: VariantProductAttributes,
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


def _sanitize_product_attributes(final_candidates: VariantCandidateRowMap) -> None:
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


def assess_variant_completeness(
    *,
    variant_rows: VariantCandidateRowMap,
    final_candidates: VariantCandidateRowMap,
    surface: str,
) -> dict[str, object]:
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface != "ecommerce_detail":
        return {
            "applicable": False,
            "complete": True,
            "reason": "non_commerce_detail_surface",
        }

    raw_variant_signal_count = sum(
        len(rows)
        for field_name, rows in (variant_rows or {}).items()
        if field_name in {"variants", "variant_axes", "selected_variant"}
        and isinstance(rows, list)
    )
    if raw_variant_signal_count <= 0:
        return {
            "applicable": False,
            "complete": True,
            "reason": "no_variant_signals_detected",
        }

    variants_row = _first_candidate_row(final_candidates.get("variants"))
    selected_row = _first_candidate_row(final_candidates.get("selected_variant"))
    axes_row = _first_candidate_row(final_candidates.get("variant_axes"))
    variants = (
        variants_row.get("value")
        if isinstance(variants_row, dict) and isinstance(variants_row.get("value"), list)
        else []
    )
    selected_variant = (
        selected_row.get("value")
        if isinstance(selected_row, dict) and isinstance(selected_row.get("value"), dict)
        else None
    )
    variant_axes = (
        axes_row.get("value")
        if isinstance(axes_row, dict) and isinstance(axes_row.get("value"), dict)
        else {}
    )
    polluted_axis_values = _polluted_variant_axis_values(variant_axes)
    if variants and not selected_variant:
        return {
            "applicable": True,
            "complete": False,
            "reason": "variant_rows_missing_selected_variant",
            "raw_variant_signal_count": raw_variant_signal_count,
            "variant_count": len(variants),
            "axis_count": len(variant_axes),
        }
    if polluted_axis_values:
        return {
            "applicable": True,
            "complete": False,
            "reason": "polluted_variant_axes",
            "raw_variant_signal_count": raw_variant_signal_count,
            "variant_count": len(variants),
            "axis_count": len(variant_axes),
            "polluted_axis_values": polluted_axis_values,
        }
    if not variants:
        return {
            "applicable": True,
            "complete": False,
            "reason": "variant_signals_without_reconciled_bundle",
            "raw_variant_signal_count": raw_variant_signal_count,
            "variant_count": len(variants),
            "axis_count": len(variant_axes),
        }
    return {
        "applicable": True,
        "complete": True,
        "reason": "variant_bundle_reconciled",
        "raw_variant_signal_count": raw_variant_signal_count,
        "variant_count": len(variants),
        "axis_count": len(variant_axes),
    }


def _reconcile_variant_bundle(
    final_candidates: VariantCandidateRowMap,
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
        inferred_default_selected = False
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
            strong_selected_identity = any(
                selected_variant.get(key) not in (None, "", [], {})
                for key in ("variant_id", "sku", "availability", "price", "original_price", "image_url")
            )
            if strong_selected_identity:
                variants.append(selected_variant)
            else:
                selected_variant = None
        if selected_variant is None:
            selected_variant = _choose_default_variant(variants)
            inferred_default_selected = selected_variant is not None

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
        if inferred_default_selected:
            selected_source = "variants_inferred_default"
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
    discovered_axes: VariantAxisValues,
    declared_axes: VariantAxisValues,
) -> VariantAxisValues:
    if not discovered_axes:
        return {
            axis_name: list(values) for axis_name, values in declared_axes.items()
        }
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


def _first_candidate_row(rows: object) -> VariantCandidateRow | None:
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _row_source_label(row: VariantCandidateRow | None, *, fallback: str) -> str:
    if not isinstance(row, dict):
        return fallback
    return str(row.get("source") or fallback).strip() or fallback


def _normalized_variant_rows_payload(
    value: object,
    *,
    base_url: str,
) -> VariantRecords:
    normalized = normalize_and_validate_value("variants", value, base_url=base_url)
    if not isinstance(normalized, list):
        return []
    reconciled: VariantRecords = []
    seen: set[str] = set()
    for variant in normalized:
        if not _is_meaningful_variant_record(variant):
            continue
        fingerprint = _variant_record_fingerprint(variant)
        if fingerprint and fingerprint in seen:
            continue
        if fingerprint:
            seen.add(fingerprint)
        reconciled.append(_sanitize_variant_record(dict(variant)))
    return reconciled


def _normalized_selected_variant_payload(
    value: object,
    *,
    base_url: str,
) -> VariantRecord | None:
    normalized = normalize_and_validate_value("selected_variant", value, base_url=base_url)
    if not isinstance(normalized, dict) or not _is_meaningful_variant_record(normalized):
        return None
    return _sanitize_variant_record(dict(normalized))


def _normalized_variant_axes_payload(
    value: object,
    *,
    base_url: str,
) -> VariantAxisValues:
    normalized = normalize_and_validate_value("variant_axes", value, base_url=base_url)
    return normalized if isinstance(normalized, dict) else {}


def _polluted_variant_axis_values(variant_axes: VariantAxisValues) -> dict[str, list[str]]:
    polluted: dict[str, list[str]] = {}
    for axis_name, values in (variant_axes or {}).items():
        if not isinstance(values, list):
            continue
        rejected = [
            text
            for value in values
            if (text := _normalized_candidate_text(value))
            and any(token in text.casefold() for token in _VARIANT_AXIS_REJECT_TOKENS)
        ]
        if rejected:
            polluted[str(axis_name)] = rejected
    return polluted


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


def _variant_record_fingerprint(value: VariantRecord) -> str:
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
    variants: VariantRecords,
    selected_variant: VariantRecord | None,
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
    primary: VariantRecord,
    secondary: VariantRecord,
) -> VariantRecord:
    merged = dict(primary)
    for key, value in secondary.items():
        if merged.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
            merged[key] = value
    if isinstance(primary.get("option_values"), dict) and isinstance(secondary.get("option_values"), dict):
        merged["option_values"] = {
            **secondary["option_values"],
            **primary["option_values"],
        }
    return _sanitize_variant_record(merged)


def _choose_default_variant(
    variants: VariantRecords,
) -> VariantRecord | None:
    if not variants:
        return None
    return next(
        (variant for variant in variants if variant.get("availability") == "in_stock"),
        variants[0],
    )

def _sanitize_option_values(option_values: object) -> dict[str, str] | None:
    if not isinstance(option_values, dict):
        return None
    sanitized: dict[str, str] = {}
    for raw_key, raw_value in option_values.items():
        key_text = _normalized_candidate_text(raw_key)
        if not key_text:
            continue
        if key_text.lower() == "pid":
            continue
        normalized_axis = _canonical_structured_key(key_text)
        cleaned_value = _normalized_candidate_text(raw_value)
        if (
            not normalized_axis
            or normalized_axis in {"id", "pid", "variant_id", "sku", "product_id"}
            or not cleaned_value
        ):
            continue
        sanitized.setdefault(normalized_axis, cleaned_value)
    return sanitized or None


def _sanitize_variant_record(variant: VariantRecord) -> VariantRecord:
    sanitized = {
        key: value
        for key, value in dict(variant).items()
        if not str(key or "").strip().lower().startswith("dwvar_")
    }
    option_values = _sanitize_option_values(sanitized.get("option_values"))
    if option_values:
        sanitized["option_values"] = option_values
    else:
        sanitized.pop("option_values", None)
    for axis_name in ("color", "size", "fittype", "fit_type"):
        if sanitized.get(axis_name) in (None, "", [], {}) and option_values and option_values.get(axis_name):
            sanitized[axis_name] = option_values[axis_name]
    return sanitized


def _collect_variant_axis_values(
    variants: VariantRecords,
) -> VariantAxisValues:
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
