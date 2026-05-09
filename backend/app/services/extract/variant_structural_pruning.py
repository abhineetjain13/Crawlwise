from __future__ import annotations

import re
from collections.abc import Callable
from itertools import combinations
from typing import Any

from app.services.config.extraction_rules import (
    DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS,
    DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS,
    VARIANT_OPTION_LABEL_MAX_WORDS,
    VARIANT_TITLE_STOPWORDS,
)
from app.services.config.variant_policy import PUBLIC_VARIANT_AXIS_FIELDS
from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_key,
    variant_row_richness,
    variant_semantic_identity,
)
from app.services.field_value_core import clean_text, text_or_none

_PUBLIC_VARIANT_AXIS_FIELDS = tuple(str(field).strip().lower() for field in PUBLIC_VARIANT_AXIS_FIELDS if str(field).strip())
_VARIANT_TITLE_STOPWORDS = frozenset(clean_text(token).lower() for token in tuple(VARIANT_TITLE_STOPWORDS or ()) if clean_text(token))
detail_cross_product_text_type_tokens = frozenset(clean_text(token).lower() for token in tuple(DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS or ()) if clean_text(token))
detail_cross_product_text_generic_tokens = frozenset(clean_text(token).lower() for token in tuple(DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS or ()) if clean_text(token))
try:
    _VARIANT_OPTION_LABEL_MAX_WORDS = max(1, int(VARIANT_OPTION_LABEL_MAX_WORDS))
except (TypeError, ValueError):
    _VARIANT_OPTION_LABEL_MAX_WORDS = 6


def drop_cross_product_variant_rows(
    record: dict[str, Any],
    *,
    color_extractor: Callable[[object], str],
) -> None:
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
        if _variant_row_looks_like_foreign_product(record, variant, color_extractor=color_extractor):
            continue
        variant_tokens = _variant_title_tokens(variant.get("title") or variant.get("name"))
        unmatched_tokens = variant_tokens - _variant_axis_tokens(variant)
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


def drop_parent_shared_variant_axes(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    variant_rows = [variant for variant in variants if isinstance(variant, dict)]
    if len(variant_rows) < 2:
        return
    varying_axes = {
        axis
        for axis in _PUBLIC_VARIANT_AXIS_FIELDS
        if len({clean_text(variant.get(axis)).casefold() for variant in variant_rows if clean_text(variant.get(axis))}) >= 2
    }
    if not varying_axes:
        return
    for axis in _PUBLIC_VARIANT_AXIS_FIELDS:
        parent_value = clean_text(record.get(axis))
        if not parent_value:
            continue
        variant_values = [clean_text(variant.get(axis)) for variant in variant_rows if clean_text(variant.get(axis))]
        if len(variant_values) != len(variant_rows):
            continue
        if any(value.casefold() != parent_value.casefold() for value in variant_values):
            continue
        if varying_axes == {axis}:
            continue
        for variant in variant_rows:
            variant.pop(axis, None)


def prune_axisless_rows_when_axisful_rows_exist(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    axisful_rows = [variant for variant in variants if isinstance(variant, dict) and _variant_has_axis_value(variant)]
    if not axisful_rows:
        return
    semantic_keys = {variant_semantic_identity(variant) for variant in axisful_rows if variant_semantic_identity(variant)}
    pruned = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and not _drop_axisless_variant_row(variant, semantic_variant_count=len(semantic_keys))
    ]
    _replace_or_drop_variants(record, pruned)


def drop_color_only_rows_when_size_rows_exist(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    rows = [variant for variant in variants if isinstance(variant, dict)]
    if len(rows) < 2:
        return
    if [variant for variant in rows if clean_text(variant.get("size")) and clean_text(variant.get("color"))]:
        return
    size_rows = [variant for variant in rows if clean_text(variant.get("size"))]
    color_only_rows = [variant for variant in rows if clean_text(variant.get("color")) and not clean_text(variant.get("size"))]
    if len(size_rows) < 2 or not color_only_rows:
        return
    parent_color = clean_text(record.get("color")).casefold()
    if not parent_color or any(clean_text(row.get("color")).casefold() != parent_color for row in color_only_rows):
        return
    _replace_or_drop_variants(record, [variant for variant in rows if variant not in color_only_rows])


def drop_subset_variants_when_richer_alternative_exists(record: dict[str, Any]) -> None:
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
    kept = [variant for variant in rows if not _variant_row_axis_key(variant) or _variant_row_axis_key(variant) not in superset_axis_keys]
    _replace_or_drop_variants(record, kept)


def drop_parent_sku_alias_variant_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    variant_rows = [variant for variant in variants if isinstance(variant, dict)]
    children_by_terminal_size: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, variant in enumerate(variant_rows):
        if terminal := _variant_sku_terminal_token(clean_text(variant.get("sku"))):
            children_by_terminal_size.setdefault(terminal, []).append((index, variant))
    dropped_indexes: set[int] = set()
    for index, variant in enumerate(variant_rows):
        sku = clean_text(variant.get("sku"))
        size = clean_text(variant.get("size"))
        size_token = re.sub(r"[^a-z0-9]+", "", size.casefold())
        if not sku or not size_token:
            continue
        for other_index, other in children_by_terminal_size.get(size_token, []):
            if index != other_index and _variant_sku_is_size_specific_child(parent_sku=sku, child_sku=clean_text(other.get("sku")), size=size) and variant_row_richness(other) >= variant_row_richness(variant):
                dropped_indexes.add(index)
                break
    if dropped_indexes:
        _replace_or_drop_variants(record, [variant for index, variant in enumerate(variant_rows) if index not in dropped_indexes])


def prune_low_signal_numeric_only_variants(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    if all(_variant_row_is_low_signal_numeric_only(variant) for variant in variants) and _numeric_only_variants_add_no_signal(record, variants):
        record.pop("variants", None)
        record.pop("variant_count", None)


def _variant_has_axis_value(variant: dict[str, Any]) -> bool:
    return any(clean_text(variant.get(axis)) for axis in _PUBLIC_VARIANT_AXIS_FIELDS)


def _variant_title_tokens(value: object) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", clean_text(value).casefold()) if len(token) >= 3 and token not in _VARIANT_TITLE_STOPWORDS}


def _variant_axis_tokens(variant: dict[str, Any]) -> set[str]:
    values: list[object] = [variant.get("color"), variant.get("size")]
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        values.extend(option_values.values())
    tokens: set[str] = set()
    for value in values:
        tokens.update(_variant_title_tokens(value))
    return tokens


def _variant_row_looks_like_foreign_product(record: dict[str, Any], variant: dict[str, Any], *, color_extractor: Callable[[object], str]) -> bool:
    parent_tokens = _variant_title_tokens(record.get("title"))
    color_value = clean_text(variant.get("color"))
    if not parent_tokens or not color_value:
        return False
    color_tokens = _variant_title_tokens(color_value)
    if len(color_tokens) < max(3, _VARIANT_OPTION_LABEL_MAX_WORDS - 1) or not color_extractor(color_value):
        return False
    unmatched_tokens = color_tokens - parent_tokens
    if len(unmatched_tokens) < 2:
        return False
    product_like_tokens = unmatched_tokens & (detail_cross_product_text_type_tokens | detail_cross_product_text_generic_tokens)
    return bool(product_like_tokens) or "(" in color_value or ")" in color_value


def _single_nonpublic_option_variant_should_drop(variant: dict[str, Any]) -> bool:
    if clean_text(variant.get("size")) or clean_text(variant.get("color")):
        return False
    if any(text_or_none(variant.get(field_name)) for field_name in ("sku", "url", "image_url", "availability")):
        return False
    option_values = variant.get("option_values")
    if not isinstance(option_values, dict) or not option_values:
        return False
    axis_keys = {normalized_variant_axis_key(axis_name) for axis_name in option_values if normalized_variant_axis_key(axis_name)}
    return bool(axis_keys) and axis_keys.isdisjoint({"size", "color"})


def _variant_row_axis_map(variant: dict[str, Any]) -> dict[str, str]:
    return {axis: clean_text(variant.get(axis)) for axis in _PUBLIC_VARIANT_AXIS_FIELDS if clean_text(variant.get(axis))}


def _variant_row_axis_key(variant: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(_variant_row_axis_map(variant).items()))


def _drop_axisless_variant_row(variant: dict[str, Any], *, semantic_variant_count: int) -> bool:
    if _variant_has_axis_value(variant):
        return False
    if semantic_variant_count >= 2:
        return True
    return not (clean_text(variant.get("sku")) or clean_text(variant.get("url")))


def _variant_sku_terminal_token(sku: str) -> str:
    tokens = [token for token in re.split(r"[^a-z0-9]+", sku.casefold()) if token]
    return tokens[-1] if tokens else ""


def _variant_sku_is_size_specific_child(*, parent_sku: str, child_sku: str, size: str) -> bool:
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
    if any(clean_text(variant.get(field_name)) for field_name in ("sku", "url", "image_url", "availability", "color")):
        return False
    if variant.get("stock_quantity") not in (None, "", [], {}):
        return False
    size_value = clean_text(variant.get("size"))
    return bool(size_value) and size_value.isdigit()


def _numeric_only_variants_add_no_signal(record: dict[str, Any], variants: list[dict[str, Any]]) -> bool:
    parent_price = text_or_none(record.get("price"))
    parent_currency = text_or_none(record.get("currency"))
    return all(isinstance(variant, dict) and text_or_none(variant.get("price")) in (None, parent_price) and text_or_none(variant.get("currency")) in (None, parent_currency) for variant in variants)


def _replace_or_drop_variants(record: dict[str, Any], variants: list[dict[str, Any]]) -> None:
    if variants:
        record["variants"] = variants
        record["variant_count"] = len(variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)
