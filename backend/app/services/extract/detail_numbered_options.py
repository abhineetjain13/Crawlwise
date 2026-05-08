from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.services.extract.detail_price_extractor import format_detail_price_decimal
from app.services.extract.shared_variant_logic import (
    iter_variant_choice_groups,
    normalized_variant_axis_key,
    resolve_variant_group_name,
    variant_axis_allowed_single_tokens,
)
from app.services.field_value_core import clean_text, text_or_none


def hydrate_numbered_variant_options_from_dom(
    record: dict[str, Any], *, soup: Any | None
) -> None:
    variants = [row for row in list(record.get("variants") or []) if isinstance(row, dict)]
    if soup is None or not variants:
        return
    axis_order = _dom_axis_order(soup)
    if not axis_order:
        return
    for variant in variants:
        _hydrate_variant_numbered_options(variant, axis_order)
    _promote_shared_parent_axes(record, variants, axis_order)


def _dom_axis_order(soup: Any) -> list[str]:
    groups: list[Any] = []
    if hasattr(soup, "find_all"):
        groups.extend(soup.find_all("fieldset", limit=12))
        groups.extend(soup.find_all(attrs={"role": "radiogroup"}, limit=12))
    groups.extend(iter_variant_choice_groups(soup))
    axis_order: list[str] = []
    seen_axes: set[str] = set()
    for group in groups:
        axis_key = normalized_variant_axis_key(resolve_variant_group_name(group))
        if (
            not axis_key
            or axis_key in seen_axes
            or axis_key not in variant_axis_allowed_single_tokens
        ):
            continue
        axis_order.append(axis_key)
        seen_axes.add(axis_key)
        if len(axis_order) >= 3:
            break
    return axis_order


def _hydrate_variant_numbered_options(
    variant: dict[str, Any], axis_order: list[str]
) -> None:
    option_values = variant.get("option_values")
    cleaned_options = dict(option_values) if isinstance(option_values, dict) else {}
    hydrated_numbered_option = False
    for key, value in list(variant.items()):
        match = re.fullmatch(r"option([1-9]\d*)", str(key))
        if match is None:
            continue
        option_index = int(match.group(1)) - 1
        if option_index >= len(axis_order):
            continue
        axis_key = axis_order[option_index]
        option_text = text_or_none(value)
        if not option_text or variant.get(axis_key) not in (None, "", [], {}):
            continue
        variant[axis_key] = option_text
        cleaned_options.setdefault(axis_key, option_text)
        hydrated_numbered_option = True
    if cleaned_options:
        variant["option_values"] = cleaned_options
    price_text = text_or_none(variant.get("price"))
    if hydrated_numbered_option and price_text and re.fullmatch(r"\d{3,}", price_text):
        variant["price"] = format_detail_price_decimal(Decimal(price_text) / 100)


def _promote_shared_parent_axes(
    record: dict[str, Any], variants: list[dict[str, Any]], axis_order: list[str]
) -> None:
    for axis_key in axis_order:
        axis_values = {
            clean_text(variant.get(axis_key))
            for variant in variants
            if clean_text(variant.get(axis_key))
        }
        if len(axis_values) != 1 or record.get(axis_key) not in (None, "", [], {}):
            continue
        record[axis_key] = next(iter(axis_values))
        field_sources = record.setdefault("_field_sources", {})
        if isinstance(field_sources, dict):
            field_sources.setdefault(axis_key, []).append("dom_variant_axis")
