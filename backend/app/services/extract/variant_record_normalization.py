from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from app.services.config.extraction_rules import (
    CURRENCY_CODES,
    DEFAULT_DETAIL_MAX_VARIANT_ROWS,
    FALLBACK_MAX_VARIANT_ROWS,
    GENDER_ARTIFACT_PATTERN,
    GENDER_KEYWORD_TOKENS,
    GENDER_POSSESSIVE_PATTERN,
    VARIANT_COLOR_HINT_WORDS,
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS,
    VARIANT_PLACEHOLDER_PREFIXES,
    VARIANT_PLACEHOLDER_VALUES,
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
    variant_identity,
    variant_row_richness,
    variant_semantic_identity,
)

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
_OPTION_FIELD_PATTERN = re.compile(r"option\d+_(?:name|values?)")
_GENDER_ARTIFACT_PATTERN = str(GENDER_ARTIFACT_PATTERN or "")
_GENDER_ARTIFACT_RE = re.compile(
    _GENDER_ARTIFACT_PATTERN.format(candidate=r"[a-z0-9.]+"),
    re.I,
) if _GENDER_ARTIFACT_PATTERN else None
_GENDER_POSSESSIVE_RE = (
    re.compile(str(GENDER_POSSESSIVE_PATTERN), re.I)
    if GENDER_POSSESSIVE_PATTERN
    else None
)
_STANDARD_SIZE_VALUES = frozenset(str(value).lower() for value in tuple(STANDARD_SIZE_VALUES or ()))
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
_LEGACY_VARIANT_KEYS = ("selected_variant", "variant_axes", "available_sizes")
_PUBLIC_VARIANT_AXIS_FIELDS = tuple(
    str(field_name).strip().lower()
    for field_name in tuple(PUBLIC_VARIANT_AXIS_FIELDS or ())
    if str(field_name).strip()
)


def _variant_has_axis_value(variant: dict[str, Any]) -> bool:
    return any(clean_text(variant.get(axis)) for axis in _PUBLIC_VARIANT_AXIS_FIELDS)


def normalize_variant_record(record: dict[str, Any]) -> None:
    _infer_variant_sizes_from_titles(record)
    _infer_single_variant_axes(record)
    _drop_cross_product_variant_rows(record)
    _flatten_variant_rows(record)
    _clean_variant_rows(record)
    _enforce_variant_axis_contract(record)
    _enforce_variant_currency_context(record)
    collapse_duplicate_size_aliases(record)
    _dedupe_variant_rows(record)
    _prune_axisless_rows_when_axisful_rows_exist(record)
    _backfill_variant_prices_from_record(record)
    _enforce_variant_currency_context(record)
    _backfill_variant_shared_fields_from_record(record)
    _prune_low_signal_numeric_only_variants(record)
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
        variant_tokens = _variant_title_tokens(
            variant.get("title") or variant.get("name")
        )
        axis_tokens = _variant_axis_tokens(variant)
        unmatched_tokens = variant_tokens - axis_tokens
        if (
            len(unmatched_tokens) >= 2
            and parent_tokens.isdisjoint(unmatched_tokens)
        ):
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
        for field_name in _PUBLIC_VARIANT_AXIS_FIELDS:
            cleaned_value = _normalize_variant_axis_value(
                field_name,
                cleaned_variant.get(field_name),
            )
            if cleaned_value:
                cleaned_variant[field_name] = cleaned_value
            else:
                cleaned_variant.pop(field_name, None)
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
        if isinstance(variant, dict)
        and _variant_has_axis_value(variant)
    ]
    if axisful_variants:
        record["variants"] = axisful_variants
        record["variant_count"] = len(axisful_variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _enforce_variant_currency_context(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    parent_currency = _currency_code(record.get("currency"))
    if not parent_currency:
        return
    kept: list[dict[str, Any]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_currency = _currency_code(variant.get("currency"))
        if variant_currency and variant_currency != parent_currency:
            continue
        variant["currency"] = parent_currency
        kept.append(variant)
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
        or _variant_axis_value_is_header(field_name, cleaned)
    ):
        return ""
    return cleaned


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
            if (
                len(candidate) == 1
                and (
                    (
                        match.start() > 0
                        and text[match.start() - 1] in {"'", "’"}
                    )
                    or _size_candidate_is_gender_artifact(candidate)
                )
            ):
                continue
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
            if candidate.isdigit() and int(candidate) < 4:
                continue
            if any(pattern.fullmatch(candidate) for pattern in _VARIANT_SIZE_VALUE_PATTERNS):
                return candidate
    return ""


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
        [part for part in re.split(r"\s+[|/]\s+|\s+[–—-]\s+|\(", text) if clean_text(part)]
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
    return phrase.title()


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
        if isinstance(variant, dict)
        and _variant_has_axis_value(variant)
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
        max_rows = max(1, int(crawler_runtime_settings.detail_max_variant_rows))
    except (TypeError, ValueError):
        try:
            max_rows = max(1, int(DEFAULT_DETAIL_MAX_VARIANT_ROWS))
        except (TypeError, ValueError):
            max_rows = max(1, int(FALLBACK_MAX_VARIANT_ROWS))
    if len(variants) <= max_rows:
        return
    kept = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and (
            _variant_primary_key(variant)
            or _variant_has_axis_value(variant)
        )
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
