from __future__ import annotations

import json
import re
from typing import Any

from app.services.config.extraction_rules import (
    DETAIL_ARTIFACT_IDENTIFIER_VALUES,
    DETAIL_ARTIFACT_PRICE_VALUES,
    DETAIL_ARTIFACT_PRODUCT_TYPE_VALUES,
    DETAIL_ARTIFACT_SKU_PREFIXES,
    DETAIL_CATEGORY_UI_TOKENS,
    DETAIL_COOKIE_DISCLOSURE_TEXT_PATTERNS,
    DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS,
    DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS,
    DETAIL_DOCUMENT_LINK_LABEL_PATTERNS,
    DETAIL_FULFILLMENT_ONLY_LONG_TEXT_PHRASES,
    DETAIL_FULFILLMENT_LONG_TEXT_PATTERNS,
    DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS,
    DETAIL_GUIDE_GLOSSARY_HEADING_TOKENS,
    DETAIL_GUIDE_GLOSSARY_TEXT_PATTERNS,
    DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES,
    DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX,
    DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES,
    DETAIL_LOW_SIGNAL_TITLE_VALUES,
    DETAIL_LONG_TEXT_DISCLAIMER_PATTERNS,
    DETAIL_LONG_TEXT_UI_TAIL_PHRASES,
    DETAIL_LONG_TEXT_UI_TAIL_MIN_PRODUCT_WORDS,
    DETAIL_MATERIALS_POLLUTION_TOKENS,
    DETAIL_NOISE_PREFIXES,
    DETAIL_TITLE_DIMENSION_SIZE_PATTERN,
    DETAIL_TRACKING_TOKEN_PATTERN,
    DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS,
)
from app.services.field_value_core import LONG_TEXT_FIELDS, clean_text, text_or_none

document_link_label_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(DETAIL_DOCUMENT_LINK_LABEL_PATTERNS or ())
    if str(pattern).strip()
)
fulfillment_only_long_text_phrases = frozenset(
    clean_text(phrase).lower()
    for phrase in tuple(DETAIL_FULFILLMENT_ONLY_LONG_TEXT_PHRASES or ())
    if clean_text(phrase)
)
fulfillment_long_text_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(DETAIL_FULFILLMENT_LONG_TEXT_PATTERNS or ())
    if str(pattern).strip()
)
guide_glossary_text_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(DETAIL_GUIDE_GLOSSARY_TEXT_PATTERNS or ())
    if str(pattern).strip()
)
guide_glossary_heading_tokens = frozenset(
    clean_text(value).lower()
    for value in tuple(DETAIL_GUIDE_GLOSSARY_HEADING_TOKENS or ())
    if clean_text(value)
)
long_text_disclaimer_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(DETAIL_LONG_TEXT_DISCLAIMER_PATTERNS or ())
    if str(pattern).strip()
)
low_signal_title_values = frozenset(
    clean_text(value).lower()
    for value in tuple(DETAIL_LOW_SIGNAL_TITLE_VALUES or ())
    if clean_text(value)
)
low_signal_long_text_values = frozenset(
    clean_text(value).lower()
    for value in tuple(DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES or ())
    if clean_text(value)
)
materials_pollution_tokens = frozenset(
    clean_text(token).casefold()
    for token in tuple(DETAIL_MATERIALS_POLLUTION_TOKENS or ())
    if clean_text(token)
)
low_signal_product_type_values = frozenset(
    clean_text(value).lower()
    for value in tuple(DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES or ())
    if clean_text(value)
)
cross_product_text_type_tokens = frozenset(
    clean_text(value).lower()
    for value in tuple(DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS or ())
    if clean_text(value)
)
cross_product_text_generic_tokens = frozenset(
    clean_text(value).lower()
    for value in tuple(DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS or ())
    if clean_text(value)
)
title_dimension_size_re = re.compile(str(DETAIL_TITLE_DIMENSION_SIZE_PATTERN), re.I)
tracking_token_re = re.compile(str(DETAIL_TRACKING_TOKEN_PATTERN), re.I)
cookie_disclosure_text_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(DETAIL_COOKIE_DISCLOSURE_TEXT_PATTERNS or ())
    if str(pattern).strip()
)
low_signal_numeric_size_max = int(DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX)
_detail_noise_prefixes = tuple(
    clean_text(prefix).lower()
    for prefix in tuple(DETAIL_NOISE_PREFIXES or ())
    if clean_text(prefix)
)
_long_text_ui_tail_min_product_words = int(DETAIL_LONG_TEXT_UI_TAIL_MIN_PRODUCT_WORDS)
_guide_glossary_heading_min_hits = int(DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS)
artifact_price_values = frozenset(
    clean_text(v).lower()
    for v in tuple(DETAIL_ARTIFACT_PRICE_VALUES or ())
    if clean_text(v)
)


def detail_title_value_is_low_signal(value: object) -> bool:
    text = clean_text(value)
    return bool(text and text.lower() in low_signal_title_values)


def detail_product_type_is_low_signal(value: object) -> bool:
    text = clean_text(value)
    return bool(text and text.lower() in low_signal_product_type_values)


def detail_scalar_size_is_low_signal(value: str, *, title: object) -> bool:
    if not value or not value.isdigit():
        return False
    try:
        numeric_value = int(value)
    except ValueError:
        return False
    return numeric_value <= low_signal_numeric_size_max and bool(
        title_dimension_size_re.search(clean_text(title))
    )


def detail_candidate_is_valid(
    field_name: str,
    value: object,
    *,
    source: str | None = None,
) -> bool:
    return not (
        _long_text_candidate_is_noise(field_name, value, source=source)
        or _title_candidate_is_artifact(field_name, value)
        or _category_candidate_is_noise(field_name, value)
        or _sku_candidate_is_artifact(field_name, value)
        or _identifier_candidate_is_artifact(field_name, value)
        or _product_type_candidate_is_artifact(field_name, value)
        or _price_candidate_is_artifact(field_name, value)
        or _variant_candidate_is_artifact(field_name, value)
    )


def _title_candidate_is_artifact(field_name: str, value: object) -> bool:
    return field_name == "title" and bool(
        tracking_token_re.fullmatch(clean_text(value))
    )


def _category_candidate_is_noise(field_name: str, value: object) -> bool:
    if field_name != "category":
        return False
    cleaned = clean_text(value)
    if not cleaned:
        return True
    parts = [
        clean_text(part).lower()
        for part in re.split(r">\s*|/+", cleaned)
        if clean_text(part)
    ]
    if not parts or any(part in DETAIL_CATEGORY_UI_TOKENS for part in parts):
        return True
    lowered = f" {cleaned.lower()} "
    return any(
        f" {token} " in lowered for token in DETAIL_CATEGORY_UI_TOKENS if token != "..."
    )


def _sku_candidate_is_artifact(field_name: str, value: object) -> bool:
    if field_name not in {"sku", "part_number", "product_id"}:
        return False
    cleaned = clean_text(value).lower()
    return bool(
        cleaned
        and any(cleaned.startswith(prefix) for prefix in DETAIL_ARTIFACT_SKU_PREFIXES)
    )


def _identifier_candidate_is_artifact(field_name: str, value: object) -> bool:
    if field_name not in {"product_id", "part_number"}:
        return False
    cleaned = clean_text(value).lower()
    return bool(cleaned and cleaned in DETAIL_ARTIFACT_IDENTIFIER_VALUES)


def _product_type_candidate_is_artifact(field_name: str, value: object) -> bool:
    return (
        field_name == "product_type"
        and clean_text(value).lower() in DETAIL_ARTIFACT_PRODUCT_TYPE_VALUES
    )


def _price_candidate_is_artifact(field_name: str, value: object) -> bool:
    if field_name not in {"price", "sale_price", "original_price"}:
        return False
    cleaned = clean_text(value).lower()
    if cleaned in artifact_price_values:
        return True
    if re.search(r"(^|[^\d])-\s*\d", cleaned):
        return True
    normalized = re.sub(r"[^0-9.]+", "", cleaned)
    if not normalized:
        return True
    try:
        return float(normalized) < 0
    except ValueError:
        return True


def _variant_candidate_is_artifact(field_name: str, value: object) -> bool:
    if field_name not in {"variants", "selected_variant", "variant_axes"}:
        return False
    return any(
        _variant_artifact_token_seen(item) for item in _walk_variant_values(value)
    )


def _walk_variant_values(value: object) -> list[object]:
    if isinstance(value, dict):
        values: list[object] = list(value.keys())
        for item in value.values():
            values.extend(_walk_variant_values(item))
        return values
    if isinstance(value, list):
        return [nested for item in value for nested in _walk_variant_values(item)]
    return [value]


def _variant_artifact_token_seen(value: object) -> bool:
    text = clean_text(value).lower()
    return bool(
        text
        and (
            text in DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS
            or re.fullmatch(r"\d+\s*%", text)
        )
    )


def _long_text_candidate_is_noise(
    field_name: str,
    value: object,
    *,
    source: str | None = None,
) -> bool:
    if field_name not in LONG_TEXT_FIELDS:
        return False
    cleaned = clean_text(value)
    lowered = cleaned.lower()
    if not lowered or lowered in low_signal_long_text_values:
        return True
    if field_name in {"description", "specifications"} and lowered.startswith(
        _detail_noise_prefixes
    ):
        return True
    tail_stripped = _strip_long_text_ui_tail(cleaned)
    if tail_stripped != cleaned:
        return len(tail_stripped.split()) < _long_text_ui_tail_min_product_words
    if (
        source == "dom_sections"
        and field_name in {"description", "specifications", "product_details"}
        and len(cleaned.split()) <= 4
        and not any(token in cleaned for token in ".:;!?\n")
    ):
        return True
    if any(pattern.search(cleaned) for pattern in guide_glossary_text_patterns):
        return True
    if detail_long_text_is_cookie_disclosure_dump(cleaned):
        return True
    return len(cleaned.split()) < 2


def sanitize_detail_long_text_fields(
    record: dict[str, Any],
    *,
    title_hint: str | None = None,
) -> None:
    record_title = clean_text(record.get("title")) or clean_text(title_hint)
    for field_name in LONG_TEXT_FIELDS:
        text = text_or_none(record.get(field_name))
        if not text:
            continue
        cleaned = sanitize_detail_long_text(text, title=record_title)
        if cleaned:
            record[field_name] = cleaned
        else:
            record.pop(field_name, None)
    description = clean_text(record.get("description")).casefold()
    specifications = clean_text(record.get("specifications")).casefold()
    if description and specifications and description == specifications:
        record.pop("specifications", None)
    materials = _clean_materials_pollution(record.get("materials"))
    if materials:
        record["materials"] = materials
    else:
        record.pop("materials", None)
    features = sanitize_detail_features(record.get("features"), title=record_title)
    if features:
        record["features"] = features
    else:
        record.pop("features", None)


def sanitize_detail_long_text(text: str, *, title: str) -> str:
    cleaned_text = _strip_long_text_ui_tail(clean_text(text))
    if cleaned_text.lower() in low_signal_long_text_values:
        return ""
    if detail_long_text_is_numeric_sequence(cleaned_text):
        return ""
    if detail_long_text_is_fulfillment_only(cleaned_text):
        return ""
    if detail_long_text_is_guide_or_glossary_dump(cleaned_text):
        return ""
    if detail_long_text_is_cookie_disclosure_dump(cleaned_text):
        return ""
    if detail_long_text_is_document_label_cluster(text):
        return ""
    chunks = [
        clean_text(chunk)
        for chunk in re.split(r"(?<=[.!?])\s+|\s+:\s+|\n+", cleaned_text)
        if clean_text(chunk)
    ]
    seen: set[str] = set()
    kept: list[str] = []
    for chunk in chunks:
        lowered = chunk.lower()
        if lowered in seen:
            continue
        if detail_long_text_chunk_is_legal_tail(chunk):
            continue
        if any(pattern.search(chunk) for pattern in long_text_disclaimer_patterns):
            continue
        if detail_long_text_chunk_is_variant_title(chunk, title=title):
            continue
        if detail_long_text_chunk_is_other_product(chunk, title=title):
            continue
        seen.add(lowered)
        kept.append(chunk)
    if kept and all(detail_long_text_chunk_is_document_label(chunk) for chunk in kept):
        return ""
    return " ".join(kept).strip()


def sanitize_detail_features(value: object, *, title: str) -> list[str]:
    rows = value if isinstance(value, list) else [value]
    seen: set[str] = set()
    cleaned_rows: list[str] = []
    for row in rows:
        text = text_or_none(row)
        if not text:
            continue
        cleaned = sanitize_detail_long_text(text, title=title)
        lowered = cleaned.lower()
        if (
            not cleaned
            or any(pattern.search(cleaned) for pattern in long_text_disclaimer_patterns)
        ):
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned_rows.append(cleaned)
    return cleaned_rows


def _strip_long_text_ui_tail(text: str) -> str:
    cleaned = clean_text(text)
    lowered = cleaned.lower()
    for phrase in tuple(DETAIL_LONG_TEXT_UI_TAIL_PHRASES or ()):
        normalized_phrase = clean_text(phrase).lower()
        if not normalized_phrase:
            continue
        if lowered == normalized_phrase:
            return ""
        suffix = f" {normalized_phrase}"
        if lowered.endswith(suffix):
            return clean_text(cleaned[: -len(suffix)])
    return cleaned


def _clean_materials_pollution(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    stripped = text.lstrip()
    if stripped.startswith("{") or _text_is_structured_json_array(stripped):
        return ""
    if detail_long_text_is_fulfillment_only(text) or any(
        pattern.search(text) for pattern in long_text_disclaimer_patterns
    ):
        return ""
    chunks = [
        clean_text(chunk)
        for chunk in re.split(r"(?<=[.!?])\s+|\s+:\s+|\n+", text)
        if clean_text(chunk)
    ]
    kept = [
        chunk
        for chunk in chunks
        if clean_text(chunk).casefold() not in materials_pollution_tokens
    ]
    cleaned = " ".join(kept).strip()
    while True:
        parts = cleaned.split(maxsplit=1)
        if (
            not parts
            or parts[0].casefold().strip(":") not in materials_pollution_tokens
        ):
            return cleaned
        cleaned = parts[1] if len(parts) > 1 else ""


def detail_long_text_is_numeric_sequence(text: str) -> bool:
    tokens = text.split()
    if len(tokens) < 5 or any(not token.isdigit() for token in tokens):
        return False
    numbers = [int(token) for token in tokens]
    return numbers == list(range(numbers[0], numbers[0] + len(numbers)))


def detail_long_text_is_fulfillment_only(text: str) -> bool:
    lowered = clean_text(text).lower().strip(" .;:")
    if lowered in fulfillment_only_long_text_phrases:
        return True
    return any(pattern.search(lowered) for pattern in fulfillment_long_text_patterns)


def detail_long_text_is_guide_or_glossary_dump(text: str) -> bool:
    cleaned = clean_text(text)
    if not cleaned:
        return False
    if any(pattern.search(cleaned) for pattern in guide_glossary_text_patterns):
        return True
    lowered = cleaned.lower()
    words = set(re.findall(r"\w+", lowered))
    heading_hits = sum(1 for token in guide_glossary_heading_tokens if token in words)
    return heading_hits >= _guide_glossary_heading_min_hits


def _text_is_structured_json_array(text: str) -> bool:
    if not text.startswith("["):
        return False
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, list)


def detail_long_text_is_cookie_disclosure_dump(text: str) -> bool:
    cleaned = clean_text(text)
    return bool(
        cleaned
        and any(pattern.search(cleaned) for pattern in cookie_disclosure_text_patterns)
    )


def detail_long_text_chunk_is_legal_tail(chunk: str) -> bool:
    lowered = chunk.lower()
    return (
        "product safety" in lowered
        or "powered by product details have been supplied by the manufacturer"
        in lowered
        or ("customer service" in lowered and any(char.isdigit() for char in chunk))
        or ("contact " in lowered and any(char.isdigit() for char in chunk))
        or ("privacy" in lowered and "policy" in lowered)
        or lowered == "view more"
    )


def detail_long_text_chunk_is_document_label(chunk: str) -> bool:
    normalized = clean_text(chunk)
    if not normalized:
        return False
    return any(
        pattern.fullmatch(normalized) for pattern in document_link_label_patterns
    )


def detail_long_text_is_document_label_cluster(text: str) -> bool:
    normalized = clean_text(text)
    if not normalized:
        return False
    normalized = re.sub(r"\b(guide|label|manual)\b\s+", r"\1\n", normalized, flags=re.I)
    parts = [clean_text(part) for part in normalized.splitlines() if clean_text(part)]
    return len(parts) >= 2 and all(
        detail_long_text_chunk_is_document_label(part) for part in parts
    )


def detail_long_text_chunk_is_variant_title(chunk: str, *, title: str) -> bool:
    if not title:
        return False
    normalized_chunk = clean_text(chunk)
    if len(normalized_chunk.split()) > 16:
        return False
    if " - " not in normalized_chunk:
        return False
    title_tokens = detail_product_text_tokens(title)
    chunk_tokens = detail_product_text_tokens(normalized_chunk)
    return bool(title_tokens) and len(title_tokens & chunk_tokens) >= max(
        1,
        min(2, len(title_tokens)),
    )


def detail_long_text_chunk_is_other_product(chunk: str, *, title: str) -> bool:
    if not title:
        return False
    normalized_chunk = clean_text(chunk)
    words = normalized_chunk.split()
    if len(words) < 3 or len(words) > 14:
        return False
    if not detail_long_text_chunk_has_product_name_shape(chunk):
        return False
    chunk_tokens = detail_product_text_tokens(normalized_chunk)
    if not (chunk_tokens & cross_product_text_type_tokens):
        return False
    title_tokens = detail_product_text_tokens(title)
    distinctive_title_tokens = {
        token
        for token in title_tokens
        if len(token) >= 5 and token not in cross_product_text_generic_tokens
    }
    lowered_chunk = normalized_chunk.lower()
    if chunk_tokens & distinctive_title_tokens and lowered_chunk.startswith(
        ("official ", "shop for ")
    ):
        return False
    if not distinctive_title_tokens or chunk_tokens & distinctive_title_tokens:
        distinctive_chunk_tokens = {
            token
            for token in chunk_tokens
            if len(token) >= 4 and token not in cross_product_text_generic_tokens
        }
        return bool(
            distinctive_chunk_tokens - title_tokens
            and not distinctive_title_tokens <= chunk_tokens
        )
    distinctive_chunk_tokens = {
        token
        for token in chunk_tokens
        if len(token) >= 4 and token not in cross_product_text_generic_tokens
    }
    return bool(distinctive_chunk_tokens - title_tokens)


def detail_product_text_tokens(value: str) -> set[str]:
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", clean_text(value).lower())
        if token and not token.isdigit()
    }
    tokens.update(
        token[:-1] for token in list(tokens) if len(token) > 4 and token.endswith("s")
    )
    return tokens


def detail_long_text_chunk_has_product_name_shape(chunk: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", str(chunk or ""))
    if not words:
        return False
    capitalized = [word for word in words if word[:1].isupper()]
    non_initial_capitalized = [word for word in words[1:] if word[:1].isupper()]
    if len(capitalized) >= 2 or non_initial_capitalized:
        return True
    return bool(
        words
        and words[0].lower() == "the"
        and len(words) > 1
        and words[1][:1].isupper()
    )
