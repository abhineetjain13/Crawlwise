from __future__ import annotations

import re
from typing import Any

from app.services.field_value_core import clean_text, text_or_none
from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_display_name,
    normalized_variant_axis_key,
    split_variant_axes,
)


def normalize_variant_record(record: dict[str, Any]) -> None:
    _backfill_selected_variant_from_record(record)
    _apply_variant_axis_label_aliases(record)
    _prune_variant_axis_header_values(record)
    _dedupe_variant_rows(record)
    _prune_non_selectable_variant_axes(record)
    _align_top_level_variant_axis_fields(record)
    _normalize_variant_option_summaries(record)
    _prune_duplicate_variant_axis_fields(record)
    _prune_redundant_size_option_summary(record)
    _backfill_variant_prices_from_record(record)

def _apply_variant_axis_label_aliases(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    aliases: dict[str, dict[str, str]] = {}
    rows_by_identity: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        identity = text_or_none(variant.get("variant_id")) or text_or_none(variant.get("sku"))
        if identity:
            rows_by_identity.setdefault(identity, []).append(variant)
    for rows in rows_by_identity.values():
        for left in rows:
            left_options = left.get("option_values")
            if not isinstance(left_options, dict):
                continue
            for right in rows:
                if left is right:
                    continue
                right_options = right.get("option_values")
                if not isinstance(right_options, dict):
                    continue
                for axis_name, left_value in left_options.items():
                    right_value = right_options.get(axis_name)
                    if not _axis_values_describe_same_choice(
                        left_options,
                        right_options,
                        axis_name=str(axis_name),
                    ):
                        continue
                    code, label = _code_label_pair(left_value, right_value)
                    if code and label:
                        aliases.setdefault(str(axis_name), {})[code] = label
    if not aliases:
        return
    _rewrite_variant_axis_values(record, aliases)


def _axis_values_describe_same_choice(
    left_options: dict[str, Any],
    right_options: dict[str, Any],
    *,
    axis_name: str,
) -> bool:
    for other_axis, left_value in left_options.items():
        if str(other_axis) == axis_name:
            continue
        right_value = right_options.get(other_axis)
        if clean_text(left_value).lower() != clean_text(right_value).lower():
            return False
    return True


def _code_label_pair(left: object, right: object) -> tuple[str, str] | tuple[None, None]:
    left_text = clean_text(left)
    right_text = clean_text(right)
    if not left_text or not right_text or left_text.lower() == right_text.lower():
        return (None, None)
    if _variant_axis_value_looks_like_code(left_text) and not _variant_axis_value_looks_like_code(right_text):
        return left_text, right_text
    if _variant_axis_value_looks_like_code(right_text) and not _variant_axis_value_looks_like_code(left_text):
        return right_text, left_text
    return (None, None)


def _variant_axis_value_looks_like_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{2,6}", str(value or "").strip()))


def _rewrite_variant_axis_values(
    record: dict[str, Any],
    aliases: dict[str, dict[str, str]],
) -> None:
    for axis_name, axis_aliases in aliases.items():
        if clean_text(record.get(axis_name)) in axis_aliases:
            record[axis_name] = axis_aliases[clean_text(record.get(axis_name))]
    variant_axes = record.get("variant_axes")
    if isinstance(variant_axes, dict):
        for axis_name, axis_values in list(variant_axes.items()):
            axis_aliases = aliases.get(str(axis_name)) or {}
            if not axis_aliases or not isinstance(axis_values, list):
                continue
            rewritten = [axis_aliases.get(clean_text(value), value) for value in axis_values]
            variant_axes[axis_name] = list(dict.fromkeys(clean_text(value) for value in rewritten if clean_text(value)))
    for row in [record.get("selected_variant"), *list(record.get("variants") or [])]:
        if not isinstance(row, dict):
            continue
        for axis_name, axis_aliases in aliases.items():
            if clean_text(row.get(axis_name)) in axis_aliases:
                row[axis_name] = axis_aliases[clean_text(row.get(axis_name))]
        option_values = row.get("option_values")
        if not isinstance(option_values, dict):
            continue
        for axis_name, axis_aliases in aliases.items():
            current = clean_text(option_values.get(axis_name))
            if current in axis_aliases:
                option_values[axis_name] = axis_aliases[current]


def _normalize_variant_option_summaries(record: dict[str, Any]) -> None:
    variant_axes = record.get("variant_axes")
    if not isinstance(variant_axes, dict) or not variant_axes:
        return
    axis_keys = {str(axis_name).strip() for axis_name in variant_axes if str(axis_name).strip()}
    if not axis_keys:
        return
    for index in range(1, 5):
        name_key = f"option{index}_name"
        option_name = text_or_none(record.get(name_key))
        if not option_name:
            continue
        axis_key = normalized_variant_axis_key(option_name)
        if axis_key not in axis_keys:
            continue
        display_name = normalized_variant_axis_display_name(option_name)
        if display_name and display_name != option_name:
            record[name_key] = display_name

def _backfill_selected_variant_from_record(record: dict[str, Any]) -> None:
    selected_variant = record.get("selected_variant")
    if not isinstance(selected_variant, dict):
        return
    for field_name in (
        "price",
        "original_price",
        "currency",
        "availability",
        "sku",
        "barcode",
        "image_url",
    ):
        if selected_variant.get(field_name) not in (None, "", [], {}):
            continue
        fallback_value = record.get(field_name)
        if fallback_value in (None, "", [], {}):
            continue
        selected_variant[field_name] = fallback_value

def _dedupe_variant_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    best_by_identity: dict[tuple[tuple[str, str], ...] | str, dict[str, Any]] = {}
    ordered_keys: list[tuple[tuple[str, str], ...] | str] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        option_values = variant.get("option_values")
        identity_key: tuple[tuple[str, str], ...] | str | None = None
        if isinstance(option_values, dict) and option_values:
            normalized_pairs = tuple(
                sorted(
                    (
                        str(axis_name).strip(),
                        clean_text(axis_value),
                    )
                    for axis_name, axis_value in option_values.items()
                    if str(axis_name).strip() and clean_text(axis_value)
                )
            )
            if normalized_pairs:
                identity_key = normalized_pairs
        if identity_key is None:
            identity_key = (
                text_or_none(variant.get("variant_id"))
                or text_or_none(variant.get("sku"))
                or text_or_none(variant.get("url"))
            )
        if not identity_key:
            continue
        existing = best_by_identity.get(identity_key)
        candidate = dict(variant)
        if existing is None:
            best_by_identity[identity_key] = candidate
            ordered_keys.append(identity_key)
            continue
        if len(candidate) > len(existing):
            best_by_identity[identity_key] = candidate
            existing = candidate
        for field_name, field_value in candidate.items():
            if existing.get(field_name) in (None, "", [], {}) and field_value not in (
                None,
                "",
                [],
                {},
            ):
                existing[field_name] = field_value
    deduped_variants = [best_by_identity[key] for key in ordered_keys]
    if not deduped_variants:
        return
    record["variants"] = deduped_variants
    record["variant_count"] = len(deduped_variants)
    selected_variant = record.get("selected_variant")
    if not isinstance(selected_variant, dict):
        return
    selected_option_values = selected_variant.get("option_values")
    if isinstance(selected_option_values, dict) and selected_option_values:
        selected_key = tuple(
            sorted(
                (
                    str(axis_name).strip(),
                    clean_text(axis_value),
                )
                for axis_name, axis_value in selected_option_values.items()
                if str(axis_name).strip() and clean_text(axis_value)
            )
        )
        if selected_key in best_by_identity:
            record["selected_variant"] = _merge_selected_variant_candidate(
                selected_variant,
                best_by_identity[selected_key],
            )
    elif deduped_variants:
        record["selected_variant"] = dict(deduped_variants[0])

def _merge_selected_variant_candidate(
    selected_variant: dict[str, Any],
    matched_variant: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(matched_variant)
    selected_option_values = selected_variant.get("option_values")
    selected_option_axes = (
        {
            str(axis_name).strip()
            for axis_name, axis_value in selected_option_values.items()
            if str(axis_name).strip() and axis_value not in (None, "", [], {})
        }
        if isinstance(selected_option_values, dict)
        else set()
    )
    for field_name, field_value in selected_variant.items():
        if merged.get(field_name) in (None, "", [], {}) and field_value not in (
            None,
            "",
            [],
            {},
        ):
            merged[field_name] = field_value
    if selected_option_axes:
        for axis_name in selected_option_axes:
            if axis_name not in selected_variant and axis_name in merged:
                merged.pop(axis_name, None)
    return merged

def _prune_non_selectable_variant_axes(record: dict[str, Any]) -> None:
    variant_axes = record.get("variant_axes")
    if not isinstance(variant_axes, dict) or not variant_axes:
        return
    always_selectable_axes = {"size"}
    for axis_name in _referenced_variant_axes(record):
        if axis_name in variant_axes:
            always_selectable_axes.add(axis_name)
    selectable_axes, _single_value_attributes = split_variant_axes(
        variant_axes,
        always_selectable_axes=frozenset(always_selectable_axes),
    )
    if selectable_axes:
        record["variant_axes"] = selectable_axes
    else:
        record.pop("variant_axes", None)
    for field_name, field_value in _single_value_attributes.items():
        if record.get(field_name) in (None, "", [], {}):
            normalized_value = clean_text(field_value)
            if normalized_value:
                record[field_name] = normalized_value
    for field_name, axis_values in selectable_axes.items():
        if record.get(field_name) not in (None, "", [], {}):
            continue
        if not isinstance(axis_values, list) or len(axis_values) != 1:
            continue
        normalized_value = clean_text(axis_values[0])
        if normalized_value:
            record[field_name] = normalized_value
    allowed_axes = set(selectable_axes)
    if not allowed_axes:
        return
    _prune_variant_option_values(record.get("selected_variant"), allowed_axes=allowed_axes)
    variants = record.get("variants")
    if not isinstance(variants, list):
        return
    for variant in variants:
        _prune_variant_option_values(variant, allowed_axes=allowed_axes)


def _prune_variant_axis_header_values(record: dict[str, Any]) -> None:
    variant_axes = record.get("variant_axes")
    if not isinstance(variant_axes, dict) or not variant_axes:
        return
    invalid_by_axis: dict[str, set[str]] = {}
    for axis_name, axis_values in list(variant_axes.items()):
        normalized_axis = str(axis_name).strip()
        if not normalized_axis or not isinstance(axis_values, list):
            continue
        cleaned_values: list[str] = []
        invalid_values: set[str] = set()
        for raw_value in axis_values:
            value = clean_text(raw_value)
            if not value:
                continue
            if _variant_axis_value_is_header(normalized_axis, value):
                invalid_values.add(value.casefold())
                continue
            cleaned_values.append(value)
        if cleaned_values:
            variant_axes[normalized_axis] = list(dict.fromkeys(cleaned_values))
        else:
            variant_axes.pop(normalized_axis, None)
        if invalid_values:
            invalid_by_axis[normalized_axis] = invalid_values
    if not invalid_by_axis:
        return
    for row in [record.get("selected_variant"), *list(record.get("variants") or [])]:
        _prune_variant_row_axis_headers(row, invalid_by_axis=invalid_by_axis)
    if "size" in invalid_by_axis:
        _prune_available_sizes_axis_headers(
            record,
            invalid_values=invalid_by_axis["size"],
        )
    variants = [
        variant
        for variant in list(record.get("variants") or [])
        if isinstance(variant, dict)
        and (
            not isinstance(variant.get("option_values"), dict)
            or bool(variant.get("option_values"))
        )
    ]
    if variants:
        record["variants"] = variants
        record["variant_count"] = len(variants)


def _variant_axis_value_is_header(axis_name: str, value: str) -> bool:
    axis_key = normalized_variant_axis_key(axis_name)
    display = normalized_variant_axis_display_name(axis_name) or axis_key
    lowered_value = clean_text(value).casefold()
    axis_forms = {
        clean_text(axis_name).casefold(),
        clean_text(axis_key).casefold(),
        clean_text(display).casefold(),
        f"{clean_text(axis_key).casefold()}s",
        f"{clean_text(display).casefold()}s",
    }
    return lowered_value in axis_forms or any(
        form and lowered_value.startswith(f"{form}:")
        for form in axis_forms
    )


def _prune_variant_row_axis_headers(
    value: object,
    *,
    invalid_by_axis: dict[str, set[str]],
) -> None:
    if not isinstance(value, dict):
        return
    option_values = value.get("option_values")
    if isinstance(option_values, dict):
        for axis_name, invalid_values in invalid_by_axis.items():
            current = clean_text(option_values.get(axis_name))
            if current and current.casefold() in invalid_values:
                option_values.pop(axis_name, None)
                if clean_text(value.get(axis_name)).casefold() == current.casefold():
                    value.pop(axis_name, None)
        if not option_values:
            value.pop("option_values", None)


def _prune_available_sizes_axis_headers(
    record: dict[str, Any],
    *,
    invalid_values: set[str],
) -> None:
    available_sizes = record.get("available_sizes")
    values: list[str] = []
    if isinstance(available_sizes, list):
        values = [clean_text(value) for value in available_sizes if clean_text(value)]
    elif available_sizes not in (None, "", [], {}):
        values = [
            clean_text(value)
            for value in str(available_sizes).split(",")
            if clean_text(value)
        ]
    if not values:
        return
    cleaned = [
        value
        for value in values
        if value.casefold() not in invalid_values
        and not _variant_axis_value_is_header("size", value)
    ]
    if cleaned:
        record["available_sizes"] = cleaned
    else:
        record.pop("available_sizes", None)


def _align_top_level_variant_axis_fields(record: dict[str, Any]) -> None:
    selected_variant = record.get("selected_variant")
    if not isinstance(selected_variant, dict):
        return
    option_values = selected_variant.get("option_values")
    if not isinstance(option_values, dict) or not option_values:
        return
    for axis_name, axis_value in option_values.items():
        normalized_axis = normalized_variant_axis_key(axis_name)
        if normalized_axis not in {"size", "color"}:
            continue
        normalized_value = clean_text(axis_value)
        if normalized_value:
            record[normalized_axis] = normalized_value

def _referenced_variant_axes(record: dict[str, Any]) -> set[str]:
    referenced_axes: set[str] = set()
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict):
        option_values = selected_variant.get("option_values")
        if isinstance(option_values, dict):
            referenced_axes.update(
                str(axis_name).strip()
                for axis_name, axis_value in option_values.items()
                if str(axis_name).strip() and axis_value not in (None, "", [], {})
            )
    variants = record.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            option_values = variant.get("option_values")
            if not isinstance(option_values, dict):
                continue
            referenced_axes.update(
                str(axis_name).strip()
                for axis_name, axis_value in option_values.items()
                if str(axis_name).strip() and axis_value not in (None, "", [], {})
            )
    return referenced_axes

def _prune_variant_option_values(
    value: object,
    *,
    allowed_axes: set[str],
) -> None:
    if not isinstance(value, dict):
        return
    option_values = value.get("option_values")
    if not isinstance(option_values, dict) or not option_values:
        return
    pruned = {
        str(axis_name): axis_value
        for axis_name, axis_value in option_values.items()
        if str(axis_name) in allowed_axes and axis_value not in (None, "", [], {})
    }
    if pruned:
        value["option_values"] = pruned
        return
    value.pop("option_values", None)


def _prune_duplicate_variant_axis_fields(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list):
        return
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict) or len(option_values) < 2:
            continue
        for axis_name, axis_value in option_values.items():
            normalized_axis = str(axis_name).strip()
            if not normalized_axis:
                continue
            normalized_value = clean_text(axis_value)
            if not normalized_value:
                continue
            if clean_text(variant.get(normalized_axis)) == normalized_value:
                variant.pop(normalized_axis, None)


def _prune_redundant_size_option_summary(record: dict[str, Any]) -> None:
    has_size_summary = bool(
        record.get("available_sizes")
        or (
            isinstance(record.get("variant_axes"), dict)
            and bool(record["variant_axes"].get("size"))
        )
    )
    if not has_size_summary:
        return
    option_pairs: list[tuple[str, object]] = []
    removed_size_summary = False
    for index in range(1, 5):
        name_key = f"option{index}_name"
        values_key = f"option{index}_values"
        option_name = text_or_none(record.get(name_key))
        option_values = record.get(values_key)
        record.pop(name_key, None)
        record.pop(values_key, None)
        if option_name is None and option_values in (None, "", [], {}):
            continue
        if normalized_variant_axis_key(option_name) == "size":
            removed_size_summary = True
            continue
        if option_name is not None and option_values not in (None, "", [], {}):
            option_pairs.append((option_name, option_values))
    if not removed_size_summary:
        for index, (option_name, option_values) in enumerate(option_pairs, start=1):
            record[f"option{index}_name"] = option_name
            record[f"option{index}_values"] = option_values
        return
    for index, (option_name, option_values) in enumerate(option_pairs, start=1):
        record[f"option{index}_name"] = option_name
        record[f"option{index}_values"] = option_values

def _backfill_variant_prices_from_record(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    fallback_fields = {
        field_name: record.get(field_name)
        for field_name in ("price", "original_price", "currency")
        if record.get(field_name) not in (None, "", [], {})
    }
    if not fallback_fields:
        return

    def _has_distinct_variant_value(field_name: str) -> bool:
        fallback_value = text_or_none(fallback_fields.get(field_name))
        if fallback_value is None:
            return False
        return any(
            isinstance(variant, dict)
            and text_or_none(variant.get(field_name)) not in (None, fallback_value)
            for variant in variants
        )

    distinct_price = _has_distinct_variant_value("price")
    distinct_original_price = _has_distinct_variant_value("original_price")
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if not distinct_price and variant.get("price") in (None, "", [], {}):
            variant["price"] = fallback_fields.get("price")
        if not distinct_original_price and variant.get("original_price") in (None, "", [], {}):
            variant["original_price"] = fallback_fields.get("original_price")
        if variant.get("currency") in (None, "", [], {}) and fallback_fields.get("currency") not in (
            None,
            "",
            [],
            {},
        ):
            variant["currency"] = fallback_fields.get("currency")
    selected_variant = record.get("selected_variant")
    if not isinstance(selected_variant, dict):
        return
    if not distinct_price and selected_variant.get("price") in (None, "", [], {}):
        selected_variant["price"] = fallback_fields.get("price")
    if not distinct_original_price and selected_variant.get("original_price") in (None, "", [], {}):
        selected_variant["original_price"] = fallback_fields.get("original_price")
    if selected_variant.get("currency") in (None, "", [], {}) and fallback_fields.get("currency") not in (
        None,
        "",
        [],
        {},
    ):
        selected_variant["currency"] = fallback_fields.get("currency")
