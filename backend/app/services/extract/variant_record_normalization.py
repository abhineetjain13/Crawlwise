from __future__ import annotations

import logging
import re
from itertools import combinations
from typing import Any
from urllib.parse import unquote, urlparse

from app.services.config.extraction_rules import (
    DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS,
    DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS,
    ADULT_SIZE_CONTEXT_TOKENS,
    COMMON_WORD_SIZE_VALUES,
    CURRENCY_CODES,
    GENDER_ARTIFACT_PATTERN,
    GENDER_KEYWORD_TOKENS,
    GENDER_POSSESSIVE_PATTERN,
    VARIANT_CHILD_SIZE_PATTERNS,
    VARIANT_COLOR_HINT_WORDS,
    VARIANT_CONDITION_HEADER_PREFIXES,
    VARIANT_OPTION_LABEL_MAX_WORDS,
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS,
    VARIANT_PLACEHOLDER_PREFIXES,
    VARIANT_PLACEHOLDER_VALUES,
    SCALAR_FIELD_MAX_OPTION_TOKENS,
    SHADE_CODE_COLOR_MIN_TOKENS,
    SCALAR_FIELD_POLLUTION_VALUES,
    VARIANT_SEPARATE_DIMENSION_SIZE_RULES,
    VARIANT_SKU_SIZE_SUFFIX_PATTERNS,
    VARIANT_SIZE_QUANTITY_CONTROL_VALUES,
    VARIANT_SIZE_VALUE_PATTERNS,
    VARIANT_SIZE_VALUE_EXTRACT_PATTERNS,
    STANDARD_SIZE_VALUES,
    VARIANT_TITLE_STOPWORDS,
)
from app.services.config.variant_policy import (
    FLAT_VARIANT_KEYS,
    PUBLIC_VARIANT_AXIS_FIELDS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_value_core import (
    clean_text,
    enforce_flat_variant_public_contract,
    extract_currency_code,
    flatten_variants_for_public_output,
    text_or_none,
)
from app.services.extract.shared_variant_logic import (
    collapse_duplicate_size_aliases,
    merge_variant_pair,
    normalized_variant_axis_key,
    variant_option_value_is_noise,
    variant_identity,
    variant_row_richness,
    variant_semantic_identity,
)

logger = logging.getLogger(__name__)

try:
    _SCALAR_FIELD_MAX_OPTION_TOKENS = max(1, int(SCALAR_FIELD_MAX_OPTION_TOKENS))
except (TypeError, ValueError):
    _SCALAR_FIELD_MAX_OPTION_TOKENS = 6

try:
    _SHADE_CODE_COLOR_MIN_TOKENS = max(2, int(SHADE_CODE_COLOR_MIN_TOKENS))
except (TypeError, ValueError):
    _SHADE_CODE_COLOR_MIN_TOKENS = 2

_VARIANT_SIZE_VALUE_EXTRACT_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_SIZE_VALUE_EXTRACT_PATTERNS or ())
    if str(pattern).strip()
)
_VARIANT_SIZE_VALUE_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_SIZE_VALUE_PATTERNS or ())
    if str(pattern).strip()
)
_VARIANT_COLOR_HINT_WORDS = frozenset(
    clean_text(value).lower()
    for value in tuple(VARIANT_COLOR_HINT_WORDS or ())
    if clean_text(value)
)
_CURRENCY_CODES_UPPER = frozenset(
    str(code).upper() for code in tuple(CURRENCY_CODES or ()) if str(code).strip()
)
_VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS or ())
    if str(pattern).strip()
)
_VARIANT_PLACEHOLDER_VALUES_SET = frozenset(
    clean_text(value).lower()
    for value in tuple(VARIANT_PLACEHOLDER_VALUES or ())
    if clean_text(value)
)
_VARIANT_PLACEHOLDER_PREFIXES_LOWER = tuple(
    clean_text(prefix).lower()
    for prefix in tuple(VARIANT_PLACEHOLDER_PREFIXES or ())
    if clean_text(prefix)
)
_VARIANT_SIZE_QUANTITY_CONTROL_VALUES = frozenset(
    clean_text(value).lower()
    for value in tuple(VARIANT_SIZE_QUANTITY_CONTROL_VALUES or ())
    if clean_text(value)
)
try:
    _VARIANT_OPTION_LABEL_MAX_WORDS = max(1, int(VARIANT_OPTION_LABEL_MAX_WORDS))
except (TypeError, ValueError):
    _VARIANT_OPTION_LABEL_MAX_WORDS = 6
_OPTION_FIELD_PATTERN = re.compile(r"option\d+_(?:name|values?)")
_GENDER_ARTIFACT_PATTERN = str(GENDER_ARTIFACT_PATTERN or "")
_GENDER_ARTIFACT_RE = (
    re.compile(
        _GENDER_ARTIFACT_PATTERN.format(candidate=r"[a-z0-9.]+"),
        re.I,
    )
    if _GENDER_ARTIFACT_PATTERN
    else None
)
_GENDER_POSSESSIVE_RE = (
    re.compile(str(GENDER_POSSESSIVE_PATTERN), re.I)
    if GENDER_POSSESSIVE_PATTERN
    else None
)
_STANDARD_SIZE_VALUES = frozenset(
    str(value).lower() for value in tuple(STANDARD_SIZE_VALUES or ())
)
_COMMON_WORD_SIZE_VALUES = frozenset(
    clean_text(value).lower()
    for value in tuple(COMMON_WORD_SIZE_VALUES or ())
    if clean_text(value)
)
_VARIANT_TITLE_STOPWORDS = frozenset(
    clean_text(token).lower()
    for token in tuple(VARIANT_TITLE_STOPWORDS or ())
    if clean_text(token)
)
_GENDER_KEYWORD_TOKENS_SET = frozenset(
    clean_text(token).lower()
    for token in tuple(GENDER_KEYWORD_TOKENS or ())
    if clean_text(token)
)
_ADULT_SIZE_CONTEXT_TOKENS = frozenset(
    clean_text(token).lower()
    for token in tuple(ADULT_SIZE_CONTEXT_TOKENS or ())
    if clean_text(token)
)
_DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS = frozenset(
    clean_text(token).lower()
    for token in tuple(DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS or ())
    if clean_text(token)
)
_DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS = frozenset(
    clean_text(token).lower()
    for token in tuple(DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS or ())
    if clean_text(token)
)
_VARIANT_CHILD_SIZE_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_CHILD_SIZE_PATTERNS or ())
    if str(pattern).strip()
)
_VARIANT_SKU_SIZE_SUFFIX_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_SKU_SIZE_SUFFIX_PATTERNS or ())
    if str(pattern).strip()
)
_VARIANT_CONDITION_HEADER_PREFIXES = frozenset(
    clean_text(token).lower()
    for token in tuple(VARIANT_CONDITION_HEADER_PREFIXES or ())
    if clean_text(token)
)
_VARIANT_SEPARATE_DIMENSION_SIZE_RULES = tuple(
    (re.compile(str(rule.get("pattern")), re.I), clean_text(rule.get("style")))
    for rule in tuple(VARIANT_SEPARATE_DIMENSION_SIZE_RULES or ())
    if isinstance(rule, dict)
    and str(rule.get("pattern") or "").strip()
    and clean_text(rule.get("style"))
)
_LEGACY_VARIANT_KEYS = ("selected_variant", "variant_axes", "available_sizes")
_PUBLIC_VARIANT_AXIS_FIELDS = tuple(
    str(field_name).strip().lower()
    for field_name in tuple(PUBLIC_VARIANT_AXIS_FIELDS or ())
    if str(field_name).strip()
)
_SCALAR_FIELD_POLLUTION_VALUES = frozenset(
    clean_text(value).casefold()
    for value in tuple(SCALAR_FIELD_POLLUTION_VALUES or ())
    if clean_text(value)
)


def _variant_has_axis_value(variant: dict[str, Any]) -> bool:
    return any(clean_text(variant.get(axis)) for axis in _PUBLIC_VARIANT_AXIS_FIELDS)


def normalize_variant_record(record: dict[str, Any], *, finalize_contract: bool = True) -> None:
    _hydrate_variant_axes(record)
    _sanitize_variant_axes(record)
    _dedupe_and_prune_variant_rows(record)
    _backfill_variant_context(record)
    _backfill_parent_scalar_axes_from_variants(record)
    _drop_polluted_parent_scalar_axes(record)
    if finalize_contract:
        _finalize_variant_contract(record)


def _hydrate_variant_axes(record: dict[str, Any]) -> None:
    _infer_variant_sizes_from_titles(record)
    _infer_variant_sizes_from_skus(record)
    _infer_single_variant_axes(record)


def _sanitize_variant_axes(record: dict[str, Any]) -> None:
    _drop_cross_product_variant_rows(record)
    _flatten_variant_rows(record)
    _clean_variant_rows(record)
    _normalize_separate_dimension_size_rows(record)
    _prune_unrecognized_size_rows_when_real_sizes_exist(record)
    _prune_child_size_rows_from_adult_products(record)
    _drop_parent_shared_variant_axes(record)
    _enforce_variant_axis_contract(record)
    _enforce_variant_currency_context(record)


def _dedupe_and_prune_variant_rows(record: dict[str, Any]) -> None:
    collapse_duplicate_size_aliases(record)
    _dedupe_variant_rows(record)
    _drop_color_only_rows_when_size_rows_exist(record)
    _drop_subset_variants_when_richer_alternative_exists(record)
    _prune_axisless_rows_when_axisful_rows_exist(record)


def _backfill_variant_context(record: dict[str, Any]) -> None:
    _backfill_variant_prices_from_record(record)
    _enforce_variant_currency_context(record)
    _backfill_variant_shared_fields_from_record(record)
    _prune_low_signal_numeric_only_variants(record)
    _drop_parent_sku_alias_variant_rows(record)


def _backfill_parent_scalar_axes_from_variants(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    variant_rows = [variant for variant in variants if isinstance(variant, dict)]
    if len(variant_rows) < 2:
        return
    for field_name in ("color", "size"):
        if clean_text(record.get(field_name)):
            continue
        values = [
            clean_text(variant.get(field_name))
            for variant in variant_rows
            if clean_text(variant.get(field_name))
        ]
        if len(values) != len(variant_rows):
            continue
        first_value = values[0]
        if all(value.casefold() == first_value.casefold() for value in values[1:]):
            record[field_name] = first_value


def _finalize_variant_contract(record: dict[str, Any]) -> None:
    _enforce_variant_payload_limits(record)
    _enforce_flat_variant_contract(record)


def _flatten_variant_rows(record: dict[str, Any]) -> None:
    variants = flatten_variants_for_public_output(record.get("variants"))
    if variants:
        record["variants"] = variants
        record["variant_count"] = len(variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _drop_cross_product_variant_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    parent_tokens = _variant_title_tokens(record.get("title"))
    if not parent_tokens:
        return
    kept: list[dict[str, Any]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if _variant_row_looks_like_foreign_product(record, variant):
            continue
        variant_tokens = _variant_title_tokens(
            variant.get("title") or variant.get("name")
        )
        axis_tokens = _variant_axis_tokens(variant)
        unmatched_tokens = variant_tokens - axis_tokens
        if len(unmatched_tokens) >= 2 and parent_tokens.isdisjoint(unmatched_tokens):
            continue
        kept.append(variant)
    if kept:
        if len(kept) == 1 and _single_nonpublic_option_variant_should_drop(kept[0]):
            record.pop("variants", None)
            record.pop("variant_count", None)
            return
        record["variants"] = kept
        record["variant_count"] = len(kept)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _variant_title_tokens(value: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", clean_text(value).casefold())
        if len(token) >= 3 and token not in _VARIANT_TITLE_STOPWORDS
    }


def _variant_axis_tokens(variant: dict[str, Any]) -> set[str]:
    values: list[object] = [variant.get("color"), variant.get("size")]
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        values.extend(option_values.values())
    tokens: set[str] = set()
    for value in values:
        tokens.update(_variant_title_tokens(value))
    return tokens


def _variant_row_looks_like_foreign_product(
    record: dict[str, Any],
    variant: dict[str, Any],
) -> bool:
    parent_tokens = _variant_title_tokens(record.get("title"))
    if not parent_tokens:
        return False
    color_value = clean_text(variant.get("color"))
    if not color_value:
        return False
    color_tokens = _variant_title_tokens(color_value)
    if len(color_tokens) < max(3, _VARIANT_OPTION_LABEL_MAX_WORDS - 1):
        return False
    extracted_color = _extract_color_value(color_value)
    if not extracted_color:
        return False
    unmatched_tokens = color_tokens - parent_tokens
    if len(unmatched_tokens) < 2:
        return False
    product_like_tokens = unmatched_tokens & (
        _DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS
        | _DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS
    )
    return bool(product_like_tokens) or "(" in color_value or ")" in color_value


def _single_nonpublic_option_variant_should_drop(variant: dict[str, Any]) -> bool:
    if not isinstance(variant, dict):
        return False
    if clean_text(variant.get("size")) or clean_text(variant.get("color")):
        return False
    if any(
        text_or_none(variant.get(field_name))
        for field_name in ("sku", "url", "image_url", "availability")
    ):
        return False
    option_values = variant.get("option_values")
    if not isinstance(option_values, dict) or not option_values:
        return False
    axis_keys = {
        normalized_variant_axis_key(axis_name)
        for axis_name in option_values
        if normalized_variant_axis_key(axis_name)
    }
    return bool(axis_keys) and axis_keys.isdisjoint({"size", "color"})


def _clean_variant_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    cleaned_variants: list[dict[str, Any]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        cleaned_variant = dict(variant)
        drop_row = False
        for field_name in _PUBLIC_VARIANT_AXIS_FIELDS:
            raw_axis_value = cleaned_variant.get(field_name)
            if _variant_size_axis_value_is_quantity_control(
                field_name,
                raw_axis_value,
            ):
                drop_row = True
                break
            cleaned_value = _normalize_variant_axis_value(
                field_name,
                raw_axis_value,
            )
            if cleaned_value:
                cleaned_variant[field_name] = cleaned_value
            else:
                cleaned_variant.pop(field_name, None)
        if drop_row:
            continue
        _promote_misfiled_color_size(cleaned_variant)
        _drop_shade_code_size_duplicate(cleaned_variant)
        _drop_invalid_variant_urls(cleaned_variant)
        if any(
            cleaned_variant.get(field_name) not in (None, "", [], {})
            for field_name in (*FLAT_VARIANT_KEYS, *_PUBLIC_VARIANT_AXIS_FIELDS)
        ):
            cleaned_variants.append(cleaned_variant)
    if cleaned_variants:
        record["variants"] = cleaned_variants
        record["variant_count"] = len(cleaned_variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _enforce_variant_axis_contract(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    axisful_variants = [
        variant
        for variant in variants
        if isinstance(variant, dict) and _variant_has_axis_value(variant)
    ]
    if axisful_variants:
        record["variants"] = axisful_variants
        record["variant_count"] = len(axisful_variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _drop_parent_shared_variant_axes(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    variant_rows = [variant for variant in variants if isinstance(variant, dict)]
    if len(variant_rows) < 2:
        return
    varying_axes = {
        axis
        for axis in _PUBLIC_VARIANT_AXIS_FIELDS
        if len(
            {
                clean_text(variant.get(axis)).casefold()
                for variant in variant_rows
                if clean_text(variant.get(axis))
            }
        )
        >= 2
    }
    if not varying_axes:
        return
    for axis in _PUBLIC_VARIANT_AXIS_FIELDS:
        parent_value = clean_text(record.get(axis))
        if not parent_value:
            continue
        variant_values = [
            clean_text(variant.get(axis))
            for variant in variant_rows
            if clean_text(variant.get(axis))
        ]
        if len(variant_values) != len(variant_rows):
            continue
        if any(value.casefold() != parent_value.casefold() for value in variant_values):
            continue
        if varying_axes == {axis}:
            continue
        for variant in variant_rows:
            variant.pop(axis, None)


def _enforce_variant_currency_context(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    parent_currency = _currency_code(record.get("currency"))
    if not parent_currency:
        return
    kept: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_currency = _currency_code(variant.get("currency"))
        if variant_currency and variant_currency != parent_currency:
            logger.warning(
                "Dropping variant with mismatched currency",
                extra={
                    "variant_id": variant.get("id") or variant.get("sku"),
                    "variant_currency": variant_currency,
                    "parent_currency": parent_currency,
                },
            )
            mismatch = dict(variant)
            mismatch["currency_mismatch"] = True
            mismatch["parent_currency"] = parent_currency
            mismatch["variant_currency"] = variant_currency
            mismatched.append(mismatch)
            continue
        variant["currency"] = parent_currency
        kept.append(variant)
    if mismatched:
        record["variants_currency_mismatch"] = mismatched
    if kept:
        record["variants"] = kept
        record["variant_count"] = len(kept)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _currency_code(value: object) -> str:
    extracted = extract_currency_code(value)
    if extracted:
        return extracted
    text = text_or_none(value)
    if text:
        upper = text.upper()
        if upper in _CURRENCY_CODES_UPPER:
            return upper
    return ""


def _normalize_variant_axis_value(field_name: str, value: object) -> str:
    cleaned = _strip_variant_option_suffix_noise(value)
    if (
        not cleaned
        or _value_is_placeholder(cleaned)
        or _value_is_ui_noise(cleaned)
        or _value_is_axis_header_noise(field_name, cleaned)
        or _variant_axis_value_is_header(field_name, cleaned)
    ):
        return ""
    return cleaned


def _variant_size_axis_value_is_quantity_control(
    field_name: str,
    value: object,
) -> bool:
    return (
        normalized_variant_axis_key(field_name) == "size"
        and clean_text(value).lower() in _VARIANT_SIZE_QUANTITY_CONTROL_VALUES
    )


def _strip_variant_option_suffix_noise(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    stripped = cleaned
    for pattern in _VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS:
        stripped = clean_text(pattern.sub("", stripped))
    return stripped or cleaned


def _value_is_placeholder(value: str) -> bool:
    lowered = clean_text(value).lower()
    if not lowered:
        return True
    return lowered in _VARIANT_PLACEHOLDER_VALUES_SET or any(
        lowered.startswith(prefix) for prefix in _VARIANT_PLACEHOLDER_PREFIXES_LOWER
    )


def _value_is_ui_noise(value: str) -> bool:
    return variant_option_value_is_noise(value)


def _drop_polluted_parent_scalar_axes(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not any(
        isinstance(variant, dict) for variant in variants
    ):
        return
    max_tokens = _SCALAR_FIELD_MAX_OPTION_TOKENS
    for field_name in ("color", "size"):
        value = clean_text(record.get(field_name))
        if not value:
            continue
        lowered = value.casefold()
        tokens = [token for token in re.split(r"[\s,|/]+", lowered) if token]
        numeric_tokens = sum(1 for token in tokens if re.search(r"\d", token))
        if lowered in _SCALAR_FIELD_POLLUTION_VALUES or (
            field_name == "size"
            and len(tokens) > max_tokens + 2
            and numeric_tokens >= 2
        ):
            record.pop(field_name, None)


def _value_is_axis_header_noise(field_name: str, value: str) -> bool:
    axis_name = normalized_variant_axis_key(field_name)
    lowered = clean_text(value).casefold()
    if axis_name not in {"condition", "state"}:
        return False
    return any(
        prefix
        and re.fullmatch(rf"{re.escape(prefix)}\s*\(\d+\)", lowered) is not None
        for prefix in _VARIANT_CONDITION_HEADER_PREFIXES
    )


def _drop_invalid_variant_urls(variant: dict[str, Any]) -> None:
    for field_name in ("url", "image_url"):
        value = text_or_none(variant.get(field_name))
        if value and _variant_url_is_public_http(value):
            continue
        variant.pop(field_name, None)


def _variant_url_is_public_http(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _promote_misfiled_color_size(variant: dict[str, Any]) -> None:
    if clean_text(variant.get("color")):
        return
    size_value = clean_text(variant.get("size"))
    if not size_value:
        return
    if _extract_size_value(size_value):
        return
    color_value = _extract_color_value(size_value)
    if not color_value:
        return
    variant["color"] = color_value
    variant.pop("size", None)


def _drop_shade_code_size_duplicate(variant: dict[str, Any]) -> None:
    size_value = clean_text(variant.get("size"))
    color_value = clean_text(variant.get("color"))
    if not size_value or not color_value:
        return
    option_values = variant.get("option_values")
    if isinstance(option_values, dict) and clean_text(option_values.get("size")):
        return
    if not size_value.isdigit():
        return
    color_tokens = color_value.split()
    if len(color_tokens) < _SHADE_CODE_COLOR_MIN_TOKENS:
        return
    if color_tokens[0].casefold() != size_value:
        return
    variant.pop("size", None)


def _infer_variant_sizes_from_titles(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    inferred_by_index: dict[int, str] = {}
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict) or clean_text(variant.get("size")):
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
        if isinstance(variant, dict) and variant.get("size") in (None, "", [], {}):
            variant["size"] = size_value


def _infer_variant_sizes_from_skus(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    inferred_by_index: dict[int, str] = {}
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict) or clean_text(variant.get("size")):
            continue
        size_value = _variant_size_from_sku(variant.get("sku"))
        if size_value:
            inferred_by_index[index] = size_value
    unique_values = {
        value.casefold() for value in inferred_by_index.values() if clean_text(value)
    }
    if len(unique_values) < 2:
        return
    for index, size_value in inferred_by_index.items():
        variant = variants[index]
        if isinstance(variant, dict) and variant.get("size") in (None, "", [], {}):
            variant["size"] = size_value


def _infer_single_variant_axes(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) != 1:
        return
    variant = variants[0]
    if not isinstance(variant, dict):
        return
    if not clean_text(variant.get("size")):
        size_value = _variant_size_from_title_or_url(variant, record=record)
        if size_value:
            variant["size"] = size_value
    if not clean_text(variant.get("color")):
        color_value = _variant_color_from_title_or_url(variant, record=record)
        if color_value:
            variant["color"] = color_value


def _variant_size_from_title_or_url(
    variant: dict[str, Any],
    *,
    record: dict[str, Any],
) -> str:
    candidates = [
        (variant.get("title"), False),
        (variant.get("name"), False),
        (record.get("title"), True),
        (_url_terminal_text(variant.get("url")), False),
        (_url_terminal_text(record.get("url")), False),
    ]
    record_title = clean_text(record.get("title")).casefold()
    for candidate, allow_record_title in candidates:
        text = clean_text(candidate)
        if not text:
            continue
        if not allow_record_title and record_title and text.casefold() == record_title:
            continue
        extracted = _extract_size_value(text)
        if (
            extracted
            and extracted.lower() in _STANDARD_SIZE_VALUES
            and _GENDER_POSSESSIVE_RE is not None
            and _GENDER_POSSESSIVE_RE.search(text)
        ):
            continue
        if extracted:
            return extracted
    return ""


def _variant_size_from_sku(value: object) -> str:
    sku = clean_text(value)
    if not sku:
        return ""
    for pattern in _VARIANT_SKU_SIZE_SUFFIX_PATTERNS:
        match = pattern.search(sku)
        if match is None:
            continue
        size_value = clean_text(match.groupdict().get("size") or match.group(0))
        if size_value:
            return size_value.upper()
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
    lowered_text = text.lower()

    def _size_candidate_is_gender_artifact(candidate: str) -> bool:
        if len(candidate) != 1 or not _GENDER_ARTIFACT_PATTERN:
            return False
        pattern = _GENDER_ARTIFACT_PATTERN.format(
            candidate=re.escape(candidate.lower())
        )
        return re.search(pattern, lowered_text) is not None

    for pattern in _VARIANT_SIZE_VALUE_EXTRACT_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            candidate = clean_text(match.group(0))
            if len(candidate) == 1 and (
                (match.start() > 0 and text[match.start() - 1] in {"'", "’"})
                or _size_candidate_is_gender_artifact(candidate)
            ):
                continue
            # Numeric values <4 are usually counts like 2-pack, not child sizes.
            if candidate.isdigit() and int(candidate) < 4:
                continue
            return candidate
    tokens = [token for token in re.split(r"[^a-z0-9.]+", text, flags=re.I) if token]
    for width in range(min(3, len(tokens)), 0, -1):
        for index in range(0, len(tokens) - width + 1):
            candidate = clean_text(" ".join(tokens[index : index + width]))
            if not candidate:
                continue
            if _size_candidate_is_gender_artifact(candidate):
                continue
            # Numeric values <4 are usually counts like 2-pack, not child sizes.
            if candidate.isdigit() and int(candidate) < 4:
                continue
            if any(
                pattern.fullmatch(candidate) for pattern in _VARIANT_SIZE_VALUE_PATTERNS
            ):
                return candidate
    return ""


def _size_value_is_recognized(value: object) -> bool:
    cleaned = clean_text(value)
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if lowered in _COMMON_WORD_SIZE_VALUES:
        return True
    if any(pattern.fullmatch(cleaned) for pattern in _VARIANT_SIZE_VALUE_PATTERNS):
        return True
    extracted = _extract_size_value(cleaned)
    return bool(extracted) and extracted.casefold() == lowered


def _size_value_is_child_specific(value: object) -> bool:
    cleaned = clean_text(value)
    return bool(
        cleaned and any(pattern.fullmatch(cleaned) for pattern in _VARIANT_CHILD_SIZE_PATTERNS)
    )


def _record_targets_adult_sizes(record: dict[str, Any]) -> bool:
    probes = (
        record.get("title"),
        record.get("gender"),
        record.get("category"),
    )
    tokens: set[str] = set()
    for value in probes:
        tokens.update(_variant_title_tokens(value))
    return bool(tokens & _ADULT_SIZE_CONTEXT_TOKENS)


def _prune_unrecognized_size_rows_when_real_sizes_exist(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    recognized_rows = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and (
            _size_value_is_recognized(variant.get("size"))
            or _variant_row_has_labeled_size_dimension(variant)
        )
    ]
    if len(recognized_rows) < 2:
        return
    kept = [
        variant
        for variant in variants
        if not isinstance(variant, dict)
        or not clean_text(variant.get("size"))
        or _size_value_is_recognized(variant.get("size"))
        or _variant_row_has_labeled_size_dimension(variant)
        or clean_text(variant.get("color"))
    ]
    if kept:
        record["variants"] = kept
        record["variant_count"] = len(kept)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _variant_row_has_labeled_size_dimension(variant: dict[str, Any]) -> bool:
    if not clean_text(variant.get("size")):
        return False
    option_values = variant.get("option_values")
    if not isinstance(option_values, dict):
        return False
    return bool(clean_text(option_values.get("style")))


def _prune_child_size_rows_from_adult_products(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    if not _record_targets_adult_sizes(record):
        return
    adult_rows = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and _size_value_is_recognized(variant.get("size"))
        and not _size_value_is_child_specific(variant.get("size"))
    ]
    child_rows = [
        variant
        for variant in variants
        if isinstance(variant, dict) and _size_value_is_child_specific(variant.get("size"))
    ]
    if len(adult_rows) < 2 or not child_rows:
        return
    kept = [
        variant
        for variant in variants
        if not isinstance(variant, dict)
        or not _size_value_is_child_specific(variant.get("size"))
    ]
    if kept:
        record["variants"] = kept
        record["variant_count"] = len(kept)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _variant_color_from_title_or_url(
    variant: dict[str, Any],
    *,
    record: dict[str, Any],
) -> str:
    for candidate in (
        variant.get("title"),
        variant.get("name"),
        record.get("title"),
        _url_terminal_text(variant.get("url")),
        _url_terminal_text(record.get("url")),
    ):
        if color_value := _extract_color_value(candidate):
            return color_value
    return ""


def _extract_color_value(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    for chunk in reversed(
        [
            part
            for part in re.split(r"\s+[|/]\s+|\s+[–—-]\s+|\(", text)
            if clean_text(part)
        ]
    ):
        if color_value := _extract_trailing_color_phrase(chunk):
            return color_value
    return _extract_trailing_color_phrase(text)


def _extract_trailing_color_phrase(value: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", clean_text(value))
        if token and not token.isdigit()
    ]
    if not tokens:
        return ""
    color_indexes = [
        index
        for index, token in enumerate(tokens)
        if token.lower() in _VARIANT_COLOR_HINT_WORDS
    ]
    if not color_indexes:
        return ""
    start = color_indexes[-1]
    while start > 0 and tokens[start - 1].lower() in _VARIANT_COLOR_HINT_WORDS:
        start -= 1
    if start > 0:
        previous = tokens[start - 1].lower()
        if (
            previous not in _STANDARD_SIZE_VALUES
            and previous not in _GENDER_KEYWORD_TOKENS_SET
        ):
            start -= 1
    end = color_indexes[-1] + 1
    while end < len(tokens) and tokens[end].lower() in _VARIANT_COLOR_HINT_WORDS:
        end += 1
    phrase = clean_text(" ".join(tokens[start:end]))
    if not phrase or len(phrase.split()) > 4:
        return ""
    return _title_preserving_acronyms(phrase)


def _title_preserving_acronyms(phrase: str) -> str:
    return " ".join(
        token if token.isupper() else token.capitalize() for token in phrase.split()
    )


def _dedupe_variant_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    merged_by_key: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        key = _variant_primary_key(variant)
        if key is None:
            continue
        current = merged_by_key.get(key)
        if current is None:
            merged_by_key[key] = dict(variant)
            ordered_keys.append(key)
            continue
        primary, secondary = _richer_variant_pair(current, variant)
        merged_by_key[key] = merge_variant_pair(primary, secondary)
    deduped_variants = [merged_by_key[key] for key in ordered_keys]
    semantic_merged: dict[str, dict[str, Any]] = {}
    semantic_order: list[str] = []
    passthrough: list[dict[str, Any]] = []
    for variant in deduped_variants:
        semantic_key = variant_semantic_identity(variant)
        if not semantic_key:
            passthrough.append(variant)
            continue
        current = semantic_merged.get(semantic_key)
        if current is None:
            semantic_merged[semantic_key] = dict(variant)
            semantic_order.append(semantic_key)
            continue
        primary, secondary = _richer_variant_pair(current, variant)
        semantic_merged[semantic_key] = merge_variant_pair(primary, secondary)
    merged_variants = [semantic_merged[key] for key in semantic_order]
    merged_variants.extend(passthrough)
    if merged_variants:
        record["variants"] = merged_variants
        record["variant_count"] = len(merged_variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _prune_axisless_rows_when_axisful_rows_exist(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    axisful_rows = [
        variant
        for variant in variants
        if isinstance(variant, dict) and _variant_has_axis_value(variant)
    ]
    if not axisful_rows:
        return
    semantic_keys = {
        variant_semantic_identity(variant)
        for variant in axisful_rows
        if variant_semantic_identity(variant)
    }
    pruned = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and not _drop_axisless_variant_row(
            variant,
            semantic_variant_count=len(semantic_keys),
        )
    ]
    if pruned:
        record["variants"] = pruned
        record["variant_count"] = len(pruned)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _drop_color_only_rows_when_size_rows_exist(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    rows = [variant for variant in variants if isinstance(variant, dict)]
    if len(rows) < 2:
        return
    combo_rows = [
        variant
        for variant in rows
        if clean_text(variant.get("size")) and clean_text(variant.get("color"))
    ]
    if combo_rows:
        return
    size_rows = [
        variant for variant in rows if clean_text(variant.get("size"))
    ]
    color_only_rows = [
        variant
        for variant in rows
        if clean_text(variant.get("color")) and not clean_text(variant.get("size"))
    ]
    if len(size_rows) < 2 or not color_only_rows:
        return
    if not _color_only_rows_match_selected_parent_color(record, color_only_rows):
        return
    kept = [variant for variant in rows if variant not in color_only_rows]
    if kept:
        record["variants"] = kept
        record["variant_count"] = len(kept)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _color_only_rows_match_selected_parent_color(
    record: dict[str, Any],
    color_only_rows: list[dict[str, Any]],
) -> bool:
    parent_color = clean_text(record.get("color")).casefold()
    if not parent_color:
        return False
    return all(
        clean_text(row.get("color")).casefold() == parent_color
        for row in color_only_rows
    )


def _drop_subset_variants_when_richer_alternative_exists(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    rows = [variant for variant in variants if isinstance(variant, dict)]
    if len(rows) < 2:
        return
    superset_axis_keys: set[tuple[tuple[str, str], ...]] = set()
    for variant in rows:
        axis_items = tuple(_variant_row_axis_map(variant).items())
        if len(axis_items) < 2:
            continue
        for subset_size in range(1, len(axis_items)):
            for subset in combinations(axis_items, subset_size):
                superset_axis_keys.add(tuple(sorted(subset)))
    kept: list[dict[str, Any]] = []
    for variant in rows:
        candidate_key = _variant_row_axis_key(variant)
        if not candidate_key:
            kept.append(variant)
            continue
        if candidate_key not in superset_axis_keys:
            kept.append(variant)
    if kept:
        record["variants"] = kept
        record["variant_count"] = len(kept)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _variant_row_axis_map(variant: dict[str, Any]) -> dict[str, str]:
    return {
        axis_name: clean_text(variant.get(axis_name))
        for axis_name in _PUBLIC_VARIANT_AXIS_FIELDS
        if clean_text(variant.get(axis_name))
    }


def _variant_row_axis_key(variant: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(_variant_row_axis_map(variant).items()))


def _drop_axisless_variant_row(
    variant: dict[str, Any],
    *,
    semantic_variant_count: int,
) -> bool:
    if _variant_has_axis_value(variant):
        return False
    if semantic_variant_count >= 2:
        return True
    return not (clean_text(variant.get("sku")) or clean_text(variant.get("url")))


def _variant_primary_key(variant: dict[str, Any]) -> str | None:
    identity = variant_identity(variant)
    if identity:
        return identity
    semantic = variant_semantic_identity(variant)
    if semantic:
        return semantic
    fingerprint = tuple(
        (field_name, _variant_field_fingerprint(variant.get(field_name)))
        for field_name in FLAT_VARIANT_KEYS
        if _variant_field_fingerprint(variant.get(field_name)) is not None
    )
    if fingerprint:
        return f"flat:{repr(fingerprint)}"
    return None


def _variant_field_fingerprint(value: object) -> str | int | float | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (int, float)):
        return value
    cleaned = clean_text(value)
    return cleaned or None


def _richer_variant_pair(
    left: dict[str, Any],
    right: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if variant_row_richness(right) > variant_row_richness(left):
        return right, left
    return left, right


def _prune_low_signal_numeric_only_variants(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    if not all(
        _variant_row_is_low_signal_numeric_only(variant) for variant in variants
    ):
        return
    if not _numeric_only_variants_add_no_signal(record, variants):
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _drop_parent_sku_alias_variant_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    variant_rows = [variant for variant in variants if isinstance(variant, dict)]
    children_by_terminal_size: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, variant in enumerate(variant_rows):
        sku = clean_text(variant.get("sku"))
        terminal = _variant_sku_terminal_token(sku)
        if terminal:
            children_by_terminal_size.setdefault(terminal, []).append((index, variant))
    dropped_indexes: set[int] = set()
    for index, variant in enumerate(variant_rows):
        sku = clean_text(variant.get("sku"))
        size = clean_text(variant.get("size"))
        if not sku or not size:
            continue
        size_token = re.sub(r"[^a-z0-9]+", "", size.casefold())
        if not size_token:
            continue
        for other_index, other in children_by_terminal_size.get(size_token, []):
            if index == other_index:
                continue
            if _variant_sku_is_size_specific_child(
                parent_sku=sku,
                child_sku=clean_text(other.get("sku")),
                size=size,
            ) and variant_row_richness(other) >= variant_row_richness(variant):
                dropped_indexes.add(index)
                break
    if not dropped_indexes:
        return
    kept = [
        variant
        for index, variant in enumerate(variant_rows)
        if index not in dropped_indexes
    ]
    if kept:
        record["variants"] = kept
        record["variant_count"] = len(kept)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _variant_sku_terminal_token(sku: str) -> str:
    tokens = [token for token in re.split(r"[^a-z0-9]+", sku.casefold()) if token]
    return tokens[-1] if tokens else ""


def _normalize_separate_dimension_size_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    rows = [variant for variant in variants if isinstance(variant, dict)]
    if not rows or any(clean_text(row.get("color")) for row in rows):
        return
    size_values = [clean_text(row.get("size")) for row in rows if clean_text(row.get("size"))]
    if len(size_values) < 2:
        return
    separate_family_hits = [
        sum(1 for value in size_values if pattern.fullmatch(value))
        for pattern, _label in _VARIANT_SEPARATE_DIMENSION_SIZE_RULES
    ]
    if sum(1 for count in separate_family_hits if count >= 2) < 2:
        return
    relabeled_rows: list[dict[str, Any]] = []
    for row in rows:
        relabeled = dict(row)
        size_value = clean_text(relabeled.get("size"))
        style_label = _separate_dimension_style_label(size_value)
        if style_label and size_value:
            option_values = relabeled.get("option_values")
            relabeled["option_values"] = (
                dict(option_values) if isinstance(option_values, dict) else {}
            )
            relabeled["option_values"]["style"] = style_label
            relabeled["option_values"]["size"] = size_value
        relabeled_rows.append(relabeled)
    record["variants"] = relabeled_rows
    record["variant_count"] = len(relabeled_rows)


def _separate_dimension_style_label(size_value: str) -> str:
    for pattern, label in _VARIANT_SEPARATE_DIMENSION_SIZE_RULES:
        if pattern.fullmatch(size_value):
            return label
    return ""


def _variant_sku_is_size_specific_child(
    *,
    parent_sku: str,
    child_sku: str,
    size: str,
) -> bool:
    parent = parent_sku.casefold()
    child = child_sku.casefold()
    size_token = re.sub(r"[^a-z0-9]+", "", size.casefold())
    if not parent or not child or not size_token:
        return False
    if not child.startswith(parent) or len(child) <= len(parent):
        return False
    separator = child[len(parent) : len(parent) + 1]
    if separator and separator.isalnum():
        return False
    child_tokens = [token for token in re.split(r"[^a-z0-9]+", child) if token]
    return bool(child_tokens and child_tokens[-1] == size_token)


def _variant_row_is_low_signal_numeric_only(variant: object) -> bool:
    if not isinstance(variant, dict):
        return False
    if any(
        clean_text(variant.get(field_name))
        for field_name in ("sku", "url", "image_url", "availability", "color")
    ):
        return False
    if variant.get("stock_quantity") not in (None, "", [], {}):
        return False
    size_value = clean_text(variant.get("size"))
    return bool(size_value) and size_value.isdigit()


def _numeric_only_variants_add_no_signal(
    record: dict[str, Any],
    variants: list[dict[str, Any]],
) -> bool:
    parent_price = text_or_none(record.get("price"))
    parent_currency = text_or_none(record.get("currency"))
    return all(
        isinstance(variant, dict)
        and text_or_none(variant.get("price")) in (None, parent_price)
        and text_or_none(variant.get("currency")) in (None, parent_currency)
        for variant in variants
    )


def _variant_axis_value_is_header(field_name: str, value: str) -> bool:
    axis_name = clean_text(field_name).casefold()
    lowered_value = clean_text(value).casefold()
    axis_forms = {
        axis_name,
        f"{axis_name}s",
    }
    return lowered_value in axis_forms or any(
        form and lowered_value.startswith(f"{form}:") for form in axis_forms
    )


def _enforce_variant_payload_limits(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    try:
        raw_limit = crawler_runtime_settings.detail_max_variant_rows
        max_rows = int(raw_limit) if raw_limit is not None else 0
    except (TypeError, ValueError):
        max_rows = 0
    if max_rows <= 0:
        return
    if len(variants) <= max_rows:
        return
    kept = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and (_variant_primary_key(variant) or _variant_has_axis_value(variant))
    ]
    truncated = kept[:max_rows] if kept else list(variants[:max_rows])
    if truncated:
        record["variants"] = truncated
        record["variant_count"] = len(truncated)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _backfill_variant_prices_from_record(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    fallback_fields = {
        field_name: record.get(field_name)
        for field_name in ("price", "currency")
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
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if not distinct_price and variant.get("price") in (None, "", [], {}):
            variant["price"] = fallback_fields.get("price")
        if variant.get("currency") in (None, "", [], {}) and fallback_fields.get(
            "currency"
        ) not in (
            None,
            "",
            [],
            {},
        ):
            variant["currency"] = fallback_fields.get("currency")


def _backfill_variant_shared_fields_from_record(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    fallback_image = record.get("image_url")
    if fallback_image in (None, "", [], {}):
        return
    for variant in variants:
        if isinstance(variant, dict) and variant.get("image_url") in (None, "", [], {}):
            variant["image_url"] = fallback_image


def _enforce_flat_variant_contract(record: dict[str, Any]) -> None:
    enforce_flat_variant_public_contract(record)
    for field_name in _LEGACY_VARIANT_KEYS:
        record.pop(field_name, None)
    for field_name in list(record):
        if _OPTION_FIELD_PATTERN.fullmatch(str(field_name)):
            record.pop(field_name, None)
