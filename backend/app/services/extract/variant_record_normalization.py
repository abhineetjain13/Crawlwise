from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import unquote, urlparse

from app.services.config.extraction_rules import (
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
from app.services.extract.variant_structural_pruning import (
    drop_color_only_rows_when_size_rows_exist,
    drop_cross_product_variant_rows,
    drop_parent_shared_variant_axes,
    drop_parent_sku_alias_variant_rows,
    drop_subset_variants_when_richer_alternative_exists,
    prune_axisless_rows_when_axisful_rows_exist,
    prune_low_signal_numeric_only_variants,
)
from app.services.extract.variant_value_guards import (
    drop_invalid_variant_urls,
    variant_axis_value_exceeds_word_limit,
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
    drop_cross_product_variant_rows(record, color_extractor=_extract_color_value)
    _flatten_variant_rows(record)
    _clean_variant_rows(record)
    _normalize_separate_dimension_size_rows(record)
    _prune_unrecognized_size_rows_when_real_sizes_exist(record)
    _prune_child_size_rows_from_adult_products(record)
    drop_parent_shared_variant_axes(record)
    _enforce_variant_axis_contract(record)
    _enforce_variant_currency_context(record)


def _dedupe_and_prune_variant_rows(record: dict[str, Any]) -> None:
    collapse_duplicate_size_aliases(record)
    _dedupe_variant_rows(record)
    drop_color_only_rows_when_size_rows_exist(record)
    drop_subset_variants_when_richer_alternative_exists(record)
    prune_axisless_rows_when_axisful_rows_exist(record)


def _backfill_variant_context(record: dict[str, Any]) -> None:
    _backfill_variant_prices_from_record(record)
    _enforce_variant_currency_context(record)
    _backfill_variant_shared_fields_from_record(record)
    prune_low_signal_numeric_only_variants(record)
    drop_parent_sku_alias_variant_rows(record)


def _backfill_parent_scalar_axes_from_variants(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    variant_rows = [variant for variant in variants if isinstance(variant, dict)]
    if len(variant_rows) < 2:
        return
    for field_name in ("color",):
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


def _variant_title_tokens(value: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", clean_text(value).casefold())
        if len(token) >= 3 and token not in _VARIANT_TITLE_STOPWORDS
    }


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
        drop_invalid_variant_urls(cleaned_variant)
        if _should_restore_original_variant_url(
            original_variant=variant,
            cleaned_variant=cleaned_variant,
        ):
            cleaned_variant["url"] = variant.get("url")
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


def _should_restore_original_variant_url(
    *,
    original_variant: dict[str, Any],
    cleaned_variant: dict[str, Any],
) -> bool:
    original_url = clean_text(original_variant.get("url"))
    if not original_url or clean_text(cleaned_variant.get("url")):
        return False
    remaining_transport_fields = [
        field_name
        for field_name in FLAT_VARIANT_KEYS
        if (
            field_name != "url"
            and field_name not in _PUBLIC_VARIANT_AXIS_FIELDS
            and cleaned_variant.get(field_name) not in (None, "", [], {})
        )
    ]
    return not remaining_transport_fields


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
    if not cleaned:
        return ""
    if variant_axis_value_exceeds_word_limit(
        normalized_variant_axis_key(field_name),
        cleaned,
        max_words=_VARIANT_OPTION_LABEL_MAX_WORDS,
        color_extractor=_extract_color_value,
    ):
        return ""
    if (
        _value_is_placeholder(cleaned)
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
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if fallback_image not in (None, "", [], {}) and variant.get("image_url") in (
            None,
            "",
            [],
            {},
        ):
            variant["image_url"] = fallback_image


def _enforce_flat_variant_contract(record: dict[str, Any]) -> None:
    enforce_flat_variant_public_contract(record)
    for field_name in _LEGACY_VARIANT_KEYS:
        record.pop(field_name, None)
    for field_name in list(record):
        if _OPTION_FIELD_PATTERN.fullmatch(str(field_name)):
            record.pop(field_name, None)
