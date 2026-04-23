from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlsplit

from app.services.extract.shared_variant_logic import normalized_variant_axis_key
from app.services.field_value_core import text_or_none
from app.services.normalizers import normalize_decimal_price


def select_variant(
    variants: list[dict[str, Any]],
    *,
    page_url: str,
) -> dict[str, Any] | None:
    if not variants:
        return None
    parsed = urlsplit(str(page_url or "").strip())
    requested_variant_id = next(
        (
            str(value).strip()
            for key, value in parse_qsl(parsed.query, keep_blank_values=False)
            if key == "variant" and str(value).strip()
        ),
        "",
    )
    if requested_variant_id:
        matched = next(
            (
                variant
                for variant in variants
                if text_or_none(variant.get("variant_id")) == requested_variant_id
            ),
            None,
        )
        if matched is not None:
            return matched
    return next(
        (variant for variant in variants if variant.get("availability") == "in_stock"),
        variants[0],
    )


def variant_axes(variants: list[dict[str, Any]]) -> dict[str, list[str]]:
    axes: dict[str, list[str]] = {}
    for variant in variants:
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict):
            continue
        for axis_name, value in option_values.items():
            cleaned = text_or_none(value)
            if not cleaned:
                continue
            axes.setdefault(str(axis_name), [])
            if cleaned not in axes[str(axis_name)]:
                axes[str(axis_name)].append(cleaned)
    return axes


def ordered_axes(
    option_names: list[str],
    selectable_axes: dict[str, list[str]],
) -> list[tuple[str, list[str]]]:
    ordered: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for option_name in option_names:
        axis_key = normalized_variant_axis_key(option_name)
        axis_values = selectable_axes.get(axis_key or "")
        if axis_key and axis_values:
            ordered.append((axis_key, axis_values))
            seen.add(axis_key)
    for axis_name, axis_values in selectable_axes.items():
        if axis_name in seen or not axis_values:
            continue
        ordered.append((axis_name, axis_values))
    return ordered


def availability_value(value: dict[str, Any] | None) -> str | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("availability") or value.get("inventory_status") or value.get("stock_status")
    cleaned = text_or_none(raw)
    if cleaned:
        lowered = cleaned.lower()
        if lowered in {"instock", "in stock", "available", "true"}:
            return "in_stock"
        if lowered in {"outofstock", "out of stock", "sold out", "false"}:
            return "out_of_stock"
        if lowered in {"limited stock", "low stock"}:
            return "limited_stock"
        return cleaned
    available = value.get("available")
    if isinstance(available, bool):
        return "in_stock" if available else "out_of_stock"
    if available not in (None, "", [], {}):
        normalized_available = str(available).strip().lower()
        if normalized_available in {"1", "true", "yes", "available", "in-stock"}:
            return "in_stock"
        return None
    qty = stock_quantity(value)
    if qty is None:
        return None
    return "in_stock" if qty > 0 else "out_of_stock"


def stock_quantity(value: dict[str, Any] | None) -> int | None:
    if not isinstance(value, dict):
        return None
    for key in ("inventory_quantity", "stock_quantity", "quantity"):
        raw = value.get(key)
        if raw in (None, "", [], {}):
            continue
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            continue
    return None


def variant_attribute(
    variant: dict[str, Any] | None,
    field_name: str,
) -> Any:
    if not isinstance(variant, dict):
        return None
    return variant.get(field_name)


def normalize_price(
    value: Any,
    *,
    interpret_integral_as_cents: bool,
) -> str | None:
    return normalize_decimal_price(
        value,
        interpret_integral_as_cents=interpret_integral_as_cents,
    )


def compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in dict(value or {}).items()
        if item not in (None, "", [], {})
    }
