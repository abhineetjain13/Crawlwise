from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from app.services.config.extraction_rules import (
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS,
    VARIANT_SIZE_VALUE_EXTRACT_PATTERNS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_value_core import clean_text, text_or_none
from app.services.extract.shared_variant_logic import (
    merge_variant_rows,
    normalized_variant_axis_display_name,
    normalized_variant_axis_key,
    split_variant_axes,
    variant_axis_name_is_semantic,
    variant_identity,
)

_VARIANT_SIZE_VALUE_EXTRACT_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_SIZE_VALUE_EXTRACT_PATTERNS or ())
    if str(pattern).strip()
)
_VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS or ())
    if str(pattern).strip()
)


def normalize_variant_record(record: dict[str, Any]) -> None:
    _backfill_selected_variant_from_record(record)
    _infer_variant_options_from_titles(record)
    _backfill_variant_axes_from_option_values(record)
    _apply_variant_axis_label_aliases(record)
    _prune_variant_axis_header_values(record)
    _dedupe_variant_rows(record)
    _prune_non_selectable_variant_axes(record)
    _clean_variant_option_noise(record)
    _prune_placeholder_option_values(record)
    _dedupe_variant_rows(record)
    _enforce_variant_payload_limits(record)
    _align_top_level_variant_axis_fields(record)
    _normalize_variant_option_summaries(record)
    _prune_duplicate_variant_axis_fields(record)
    _prune_redundant_size_option_summary(record)
    _backfill_variant_prices_from_record(record)
    _backfill_variant_shared_fields_from_record(record)
    _normalize_selected_variant_title(record)
    _prune_low_signal_numeric_only_variants(record)


def _prune_placeholder_option_values(record: dict[str, Any]) -> None:
    variant_axes = record.get("variant_axes")
    if isinstance(variant_axes, dict):
        cleaned_axes: dict[str, list[str]] = {}
        for axis_name, axis_values in variant_axes.items():
            axis_key = normalized_variant_axis_key(axis_name)
            if not axis_key or not variant_axis_name_is_semantic(axis_name):
                continue
            if axis_key.startswith("toggle"):
                continue
            cleaned_values = [
                clean_text(value)
                for value in list(axis_values or [])
                if clean_text(value) and not _value_is_placeholder(clean_text(value))
            ]
            if cleaned_values:
                output_axis = (
                    clean_text(axis_name)
                    if clean_text(axis_name).casefold() in {"flavour", "flavours"}
                    else axis_key
                )
                cleaned_axes[output_axis] = list(dict.fromkeys(cleaned_values))
        if cleaned_axes:
            record["variant_axes"] = cleaned_axes
        else:
            record.pop("variant_axes", None)
    for row in [record.get("selected_variant"), *list(record.get("variants") or [])]:
        if not isinstance(row, dict):
            continue
        option_values = row.get("option_values")
        if isinstance(option_values, dict):
            cleaned_options: dict[str, str] = {}
            for axis_name, axis_value in option_values.items():
                axis_key = normalized_variant_axis_key(axis_name)
                cleaned_value = clean_text(axis_value)
                if not axis_key or not cleaned_value:
                    continue
                if not variant_axis_name_is_semantic(axis_name) or axis_key.startswith("toggle"):
                    continue
                if _value_is_placeholder(cleaned_value):
                    continue
                cleaned_options[axis_key] = cleaned_value
                if axis_key in {"size", "color"}:
                    row[axis_key] = cleaned_value
            if cleaned_options:
                row["option_values"] = cleaned_options
            else:
                row.pop("option_values", None)
        for field_name in ("size", "color"):
            cleaned_value = clean_text(row.get(field_name))
            if cleaned_value and not _value_is_placeholder(cleaned_value):
                row[field_name] = cleaned_value
            elif row.get(field_name) not in (None, "", [], {}):
                row.pop(field_name, None)


def _value_is_placeholder(value: str) -> bool:
    lowered = clean_text(value).lower()
    if not lowered:
        return True
    return (
        lowered == "default title"
        or lowered in {"choose", "option", "select", "swatch"}
        or lowered.startswith("please select")
        or lowered.startswith("open ")
    )


def _prune_low_signal_numeric_only_variants(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    if not all(_variant_row_is_low_signal_numeric_only(variant) for variant in variants):
        return
    record.pop("variants", None)
    record.pop("variant_axes", None)
    record.pop("variant_count", None)
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict) and _variant_row_is_low_signal_numeric_only(selected_variant):
        record.pop("selected_variant", None)


def _variant_row_is_low_signal_numeric_only(variant: object) -> bool:
    if not isinstance(variant, dict):
        return False
    if any(
        clean_text(variant.get(field_name))
        for field_name in ("variant_id", "barcode", "image_url", "availability")
    ):
        return False
    if clean_text(variant.get("url")):
        return False
    option_values = variant.get("option_values")
    if not isinstance(option_values, dict) or set(option_values) != {"size"}:
        return False
    size_value = clean_text(option_values.get("size") or variant.get("size"))
    return bool(size_value) and size_value.isdigit()


def _clean_variant_option_noise(record: dict[str, Any]) -> None:
    variant_axes = record.get("variant_axes")
    if isinstance(variant_axes, dict):
        for axis_name, axis_values in list(variant_axes.items()):
            if not isinstance(axis_values, list):
                continue
            cleaned_values = [
                cleaned
                for raw_value in axis_values
                if (cleaned := _strip_variant_option_suffix_noise(raw_value))
            ]
            if cleaned_values:
                variant_axes[axis_name] = list(dict.fromkeys(cleaned_values))
            else:
                variant_axes.pop(axis_name, None)
    for row in [record, record.get("selected_variant"), *list(record.get("variants") or [])]:
        if not isinstance(row, dict):
            continue
        for field_name in ("size", "color"):
            cleaned = _strip_variant_option_suffix_noise(row.get(field_name))
            if cleaned:
                row[field_name] = cleaned
        option_values = row.get("option_values")
        if not isinstance(option_values, dict):
            continue
        for axis_name, axis_value in list(option_values.items()):
            cleaned = _strip_variant_option_suffix_noise(axis_value)
            if cleaned:
                option_values[axis_name] = cleaned


def _strip_variant_option_suffix_noise(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    stripped = cleaned
    for pattern in _VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS:
        stripped = clean_text(pattern.sub("", stripped))
    return stripped or cleaned


def _backfill_variant_axes_from_option_values(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    axes = record.get("variant_axes")
    if not isinstance(axes, dict):
        axes = {}
    changed = False
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict):
            continue
        for axis_name, axis_value in option_values.items():
            axis_key = str(axis_name).strip()
            cleaned = clean_text(axis_value)
            if not axis_key or not cleaned:
                continue
            bucket = axes.setdefault(axis_key, [])
            if cleaned not in [clean_text(value) for value in bucket]:
                bucket.append(cleaned)
                changed = True
    if changed or axes:
        record["variant_axes"] = axes


def _infer_variant_options_from_titles(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    inferred_by_index: dict[int, str] = {}
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict):
            continue
        option_values = variant.get("option_values")
        if isinstance(option_values, dict) and option_values:
            continue
        size_value = _variant_size_from_title_or_url(variant, record=record)
        if size_value:
            inferred_by_index[index] = size_value
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in inferred_by_index.values():
        lowered = value.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_values.append(value)
    if len(unique_values) < 2:
        return
    for index, size_value in inferred_by_index.items():
        variant = variants[index]
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict):
            option_values = {}
        option_values["size"] = size_value
        variant["option_values"] = option_values
        if variant.get("size") in (None, "", [], {}):
            variant["size"] = size_value
    axes = record.get("variant_axes")
    if not isinstance(axes, dict):
        axes = {}
    existing_values = [
        clean_text(value)
        for value in list(axes.get("size") or [])
        if clean_text(value)
    ]
    axes["size"] = list(dict.fromkeys([*existing_values, *unique_values]))
    record["variant_axes"] = axes
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict):
        size_value = _variant_size_from_title_or_url(selected_variant, record=record)
        if size_value:
            option_values = selected_variant.get("option_values")
            if not isinstance(option_values, dict):
                option_values = {}
            option_values.setdefault("size", size_value)
            selected_variant["option_values"] = option_values
            selected_variant.setdefault("size", size_value)


def _variant_size_from_title_or_url(
    variant: dict[str, Any],
    *,
    record: dict[str, Any],
) -> str:
    candidates = [
        variant.get("title"),
        variant.get("name"),
        _url_terminal_text(variant.get("url")),
    ]
    record_title = clean_text(record.get("title")).casefold()
    for candidate in candidates:
        text = clean_text(candidate)
        if not text:
            continue
        if record_title and text.casefold() == record_title:
            continue
        extracted = _extract_size_value(text)
        if extracted:
            return extracted
    return ""


def _url_terminal_text(value: object) -> str:
    text = text_or_none(value)
    if not text:
        return ""
    parsed = urlparse(text)
    parts = [part for part in str(parsed.path or "").split("/") if part]
    if not parts:
        return ""
    return clean_text(unquote(parts[-1]).replace("-", " ").replace("_", " "))


def _extract_size_value(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    for pattern in _VARIANT_SIZE_VALUE_EXTRACT_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return clean_text(match.group(0))
    return ""

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


def _normalize_selected_variant_title(record: dict[str, Any]) -> None:
    selected_variant = record.get("selected_variant")
    if not isinstance(selected_variant, dict):
        return
    record_title = clean_text(record.get("title"))
    selected_title = clean_text(selected_variant.get("title"))
    if not record_title:
        return
    option_values = selected_variant.get("option_values")
    option_value_texts = {
        clean_text(value).casefold()
        for value in (option_values.values() if isinstance(option_values, dict) else [])
        if clean_text(value)
    }
    if (
        selected_title
        and (
            selected_title.casefold() in option_value_texts
            or selected_title.casefold() == clean_text(selected_variant.get("size")).casefold()
        )
    ):
        selected_variant["title"] = record_title


def _dedupe_variant_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    deduped_variants = merge_variant_rows(variants)
    if not deduped_variants:
        return
    record["variants"] = deduped_variants
    record["variant_count"] = len(deduped_variants)
    selected_variant = record.get("selected_variant")
    if not isinstance(selected_variant, dict):
        return
    selected_id = variant_identity(selected_variant)
    if selected_id:
        match = next(
            (row for row in deduped_variants if variant_identity(row) == selected_id),
            None,
        )
        if match is not None:
            record["selected_variant"] = _merge_selected_variant_candidate(
                selected_variant,
                match,
            )
            return
    # No identity match — only overwrite if current selected_variant has no
    # meaningful identity (preserve adapter-provided data like sku).
    if not selected_id:
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
    always_selectable_axes = {"color", "size"} | _referenced_variant_axes(record)
    selectable_axes, _single_value_attributes = split_variant_axes(
        variant_axes,
        always_selectable_axes=frozenset(always_selectable_axes),
    )
    if (
        len(list(selectable_axes.get("color") or [])) <= 1
        and any(
            axis_name != "color" and len(list(axis_values or [])) > 1
            for axis_name, axis_values in selectable_axes.items()
        )
    ):
        selectable_axes.pop("color", None)
    selectable_axes = _limit_variant_axes(selectable_axes)
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


def _referenced_variant_axes(record: dict[str, Any]) -> set[str]:
    referenced_axes: set[str] = set()
    rows = [record.get("selected_variant"), *list(record.get("variants") or [])]
    for row in rows:
        if not isinstance(row, dict):
            continue
        option_values = row.get("option_values")
        if not isinstance(option_values, dict):
            continue
        referenced_axes.update(
            axis_key
            for axis_name, axis_value in option_values.items()
            if (axis_key := normalized_variant_axis_key(axis_name))
            and "_" not in axis_key
            and variant_axis_name_is_semantic(axis_name)
            and axis_value not in (None, "", [], {})
        )
    return referenced_axes


def _limit_variant_axes(axes: dict[str, list[str]]) -> dict[str, list[str]]:
    if not isinstance(axes, dict) or not axes:
        return {}
    max_axes = max(1, int(crawler_runtime_settings.detail_max_variant_axes))
    limited: dict[str, list[str]] = {}
    for axis_name, axis_values in axes.items():
        if len(limited) >= max_axes:
            break
        if not variant_axis_name_is_semantic(axis_name):
            continue
        limited[str(axis_name)] = axis_values
    return limited


def _enforce_variant_payload_limits(record: dict[str, Any]) -> None:
    variant_axes = record.get("variant_axes")
    if isinstance(variant_axes, dict):
        limited_axes = _limit_variant_axes(variant_axes)
        if limited_axes:
            matrix_cells = 1
            for axis_values in limited_axes.values():
                matrix_cells *= max(1, len(axis_values if isinstance(axis_values, list) else []))
            if matrix_cells <= int(crawler_runtime_settings.detail_max_variant_matrix_cells):
                record["variant_axes"] = limited_axes
            else:
                record.pop("variant_axes", None)
        else:
            record.pop("variant_axes", None)

    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    max_rows = max(1, int(crawler_runtime_settings.detail_max_variant_rows))
    if len(variants) <= max_rows:
        return
    kept = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and any(variant.get(field_name) not in (None, "", [], {}) for field_name in ("variant_id", "sku", "barcode"))
    ]
    if not kept:
        record.pop("variants", None)
        record.pop("variant_count", None)
        record.pop("selected_variant", None)
        return
    record["variants"] = kept[:max_rows]
    record["variant_count"] = len(record["variants"])
    selected_variant = record.get("selected_variant")
    selected_identity = variant_identity(selected_variant) if isinstance(selected_variant, dict) else None
    kept_identities = {
        identity
        for variant in record["variants"]
        if (identity := variant_identity(variant))
    }
    if selected_identity is not None and selected_identity not in kept_identities:
        record["selected_variant"] = dict(record["variants"][0])


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
    variant_price_values = {
        text_or_none(variant.get("price"))
        for variant in variants
        if isinstance(variant, dict) and text_or_none(variant.get("price"))
    }
    backfill_original_price = (
        not distinct_original_price
        and not distinct_price
        and len(variant_price_values) <= 1
    )
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if not distinct_price and variant.get("price") in (None, "", [], {}):
            variant["price"] = fallback_fields.get("price")
        if backfill_original_price and variant.get("original_price") in (None, "", [], {}):
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
    if backfill_original_price and selected_variant.get("original_price") in (None, "", [], {}):
        selected_variant["original_price"] = fallback_fields.get("original_price")
    if selected_variant.get("currency") in (None, "", [], {}) and fallback_fields.get("currency") not in (
        None,
        "",
        [],
        {},
    ):
        selected_variant["currency"] = fallback_fields.get("currency")


def _backfill_variant_shared_fields_from_record(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    shared_fields = {
        field_name: record.get(field_name)
        for field_name in ("image_url",)
        if record.get(field_name) not in (None, "", [], {})
    }
    if not shared_fields:
        return
    for field_name, fallback_value in shared_fields.items():
        if any(
            isinstance(variant, dict) and variant.get(field_name) not in (None, "", [], {})
            for variant in variants
        ):
            continue
        for variant in variants:
            if isinstance(variant, dict) and variant.get(field_name) in (None, "", [], {}):
                variant[field_name] = fallback_value
