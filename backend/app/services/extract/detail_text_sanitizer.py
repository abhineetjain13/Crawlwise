from __future__ import annotations

import re
from typing import Any

from app.services.config.extraction_rules import (
    DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS,
    DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS,
    DETAIL_DOCUMENT_LINK_LABEL_PATTERNS,
    DETAIL_FULFILLMENT_ONLY_LONG_TEXT_PHRASES,
    DETAIL_FULFILLMENT_LONG_TEXT_PATTERNS,
    DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES,
    DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX,
    DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES,
    DETAIL_LOW_SIGNAL_TITLE_VALUES,
    DETAIL_TITLE_DIMENSION_SIZE_PATTERN,
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
low_signal_numeric_size_max = int(DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX)


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


def sanitize_detail_long_text(text: str, *, title: str) -> str:
    cleaned_text = clean_text(text)
    if cleaned_text.lower() in low_signal_long_text_values:
        return ""
    if detail_long_text_is_numeric_sequence(cleaned_text):
        return ""
    if detail_long_text_is_fulfillment_only(cleaned_text):
        return ""
    if detail_long_text_is_document_label_cluster(text):
        return ""
    chunks = [
        clean_text(chunk)
        for chunk in re.split(r"(?<=[.!?])\s+|\s+:\s+|\n+", text)
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
        if detail_long_text_chunk_is_variant_title(chunk, title=title):
            continue
        if detail_long_text_chunk_is_other_product(chunk, title=title):
            continue
        seen.add(lowered)
        kept.append(chunk)
    if kept and all(detail_long_text_chunk_is_document_label(chunk) for chunk in kept):
        return ""
    return " ".join(kept).strip()


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


def detail_long_text_chunk_is_legal_tail(chunk: str) -> bool:
    lowered = chunk.lower()
    return (
        "product safety" in lowered
        or "powered by product details have been supplied by the manufacturer" in lowered
        or ("customer service" in lowered and any(char.isdigit() for char in chunk))
        or ("contact " in lowered and any(char.isdigit() for char in chunk))
        or ("privacy" in lowered and "policy" in lowered)
        or lowered == "view more"
    )


def detail_long_text_chunk_is_document_label(chunk: str) -> bool:
    normalized = clean_text(chunk)
    if not normalized:
        return False
    return any(pattern.fullmatch(normalized) for pattern in document_link_label_patterns)


def detail_long_text_is_document_label_cluster(text: str) -> bool:
    normalized = clean_text(text)
    if not normalized:
        return False
    normalized = re.sub(r"\b(guide|label|manual)\b\s+", r"\1\n", normalized, flags=re.I)
    parts = [
        clean_text(part)
        for part in normalized.splitlines()
        if clean_text(part)
    ]
    return len(parts) >= 2 and all(detail_long_text_chunk_is_document_label(part) for part in parts)


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
    if chunk_tokens & distinctive_title_tokens and lowered_chunk.startswith(("official ", "shop for ")):
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
        token[:-1]
        for token in list(tokens)
        if len(token) > 4 and token.endswith("s")
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
    return bool(words and words[0].lower() == "the" and len(words) > 1 and words[1][:1].isupper())
