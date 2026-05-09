from __future__ import annotations

from typing import Any

from app.services.config.js_state_field_specs import (
    JS_STATE_LIST_ITERATION_LIMIT,
    JS_STATE_PRODUCT_PAYLOAD_LIMIT,
)
from app.services.extract.shared_variant_logic import merge_variant_rows
from app.services.field_value_core import text_or_none
from app.services.js_state_helpers import compact_dict


def extract_marketplace_choice_products(value: Any) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    _collect_marketplace_choice_products(value, buckets=buckets, depth=0)
    return [compact_dict(product) for product in buckets.values() if compact_dict(product)]


def _collect_marketplace_choice_products(
    value: Any,
    *,
    buckets: dict[str, dict[str, Any]],
    depth: int,
) -> None:
    if depth > int(JS_STATE_PRODUCT_PAYLOAD_LIMIT):
        return
    if isinstance(value, dict):
        product = _marketplace_choice_product(value)
        if product:
            key = _marketplace_choice_product_key(product)
            existing = buckets.get(key)
            if existing is None:
                buckets[key] = product
            else:
                merged_variants = merge_variant_rows(
                    existing.get("variants"),
                    product.get("variants"),
                )
                for field_name, field_value in product.items():
                    if field_name == "variants":
                        continue
                    if existing.get(field_name) in (None, "", [], {}) and field_value not in (
                        None,
                        "",
                        [],
                        {},
                    ):
                        existing[field_name] = field_value
                if merged_variants:
                    existing["variants"] = merged_variants
                    existing["variant_count"] = len(merged_variants)
        for item in value.values():
            _collect_marketplace_choice_products(
                item,
                buckets=buckets,
                depth=depth + 1,
            )
        return
    if isinstance(value, list):
        for item in value[: int(JS_STATE_LIST_ITERATION_LIMIT)]:
            _collect_marketplace_choice_products(
                item,
                buckets=buckets,
                depth=depth + 1,
            )


def _marketplace_choice_product(value: dict[str, Any]) -> dict[str, Any]:
    categories = value.get("choiceCategories")
    if not isinstance(categories, list) or not categories:
        return {}
    variants: list[dict[str, Any]] = []
    for category in categories:
        if not isinstance(category, dict):
            continue
        axis_name = text_or_none(category.get("name"))
        if not axis_name:
            continue
        connection = category.get("variantChoices")
        edges = connection.get("edges") if isinstance(connection, dict) else None
        if isinstance(edges, list) and edges:
            for edge in edges:
                edge_node = edge.get("node") if isinstance(edge, dict) else None
                if not isinstance(edge_node, dict):
                    continue
                choice = (
                    edge_node.get("choice")
                    if isinstance(edge_node.get("choice"), dict)
                    else {}
                )
                selectable = (
                    edge_node.get("selectableVariant")
                    if isinstance(edge_node.get("selectableVariant"), dict)
                    else {}
                )
                row = _marketplace_choice_variant_row(
                    axis_name=axis_name,
                    choice_name=choice.get("name"),
                    choice_id=choice.get("displayId") or choice.get("choiceId"),
                    listing_url=selectable.get("listingUrl"),
                    stock_status=_marketplace_stock_status(selectable),
                    price_amount=_marketplace_price_amount(selectable),
                    currency_code=_marketplace_currency_code(selectable),
                )
                if row:
                    variants.append(row)
            continue
        selected = (
            category.get("selectedVariantChoice")
            if isinstance(category.get("selectedVariantChoice"), dict)
            else None
        )
        choice = (
            selected.get("choice")
            if isinstance(selected, dict) and isinstance(selected.get("choice"), dict)
            else {}
        )
        row = _marketplace_choice_variant_row(
            axis_name=axis_name,
            choice_name=choice.get("name"),
            choice_id=choice.get("displayId") or choice.get("choiceId"),
            listing_url=value.get("listingUrl"),
            stock_status=_marketplace_stock_status(value),
            price_amount=_marketplace_price_amount(value),
            currency_code=_marketplace_currency_code(value),
        )
        if row:
            variants.append(row)
    if not variants:
        return {}
    url = next(
        (
            text_or_none(variant.get("url"))
            for variant in variants
            if text_or_none(variant.get("url"))
        ),
        text_or_none(value.get("listingUrl")),
    )
    return compact_dict(
        {
            "title": text_or_none(value.get("displayName")),
            "url": url,
            "product_id": text_or_none(
                value.get("variantId")
                or value.get("id")
                or (value.get("listing") or {}).get("displayListingId")
            ),
            "price": _marketplace_price_amount(value),
            "currency": _marketplace_currency_code(value),
            "availability": _marketplace_stock_status(value),
            "variants": variants,
            "variant_count": len(variants),
        }
    )


def _marketplace_choice_variant_row(
    *,
    axis_name: str,
    choice_name: object,
    choice_id: object,
    listing_url: object,
    stock_status: str | None,
    price_amount: str | None,
    currency_code: str | None,
) -> dict[str, Any]:
    option_value = text_or_none(choice_name)
    if not option_value:
        return {}
    row = compact_dict(
        {
            "id": text_or_none(choice_id),
            "url": text_or_none(listing_url),
            "availability": stock_status,
            "price": price_amount,
            "currency": currency_code,
            "selectedOptions": [{"name": axis_name, "value": option_value}],
        }
    )
    return row if row else {}


def _marketplace_choice_product_key(product: dict[str, Any]) -> str:
    for field_name in ("product_id", "url", "title"):
        value = text_or_none(product.get(field_name))
        if value:
            return value
    return f"marketplace_choice_{id(product)}"


def _marketplace_stock_status(value: dict[str, Any]) -> str | None:
    fulfillment = value.get("fulfillmentv2")
    if not isinstance(fulfillment, dict):
        return None
    return text_or_none(fulfillment.get("stockStatus"))


def _marketplace_price_amount(value: dict[str, Any]) -> str | None:
    pricing = value.get("pricing")
    if not isinstance(pricing, dict):
        return None
    primary = pricing.get("primaryPrice")
    if not isinstance(primary, dict):
        return None
    price = primary.get("price")
    if not isinstance(price, dict):
        return None
    price_value = price.get("value")
    if isinstance(price_value, dict):
        return text_or_none(price_value.get("amount"))
    return text_or_none(price_value)


def _marketplace_currency_code(value: dict[str, Any]) -> str | None:
    pricing = value.get("pricing")
    if not isinstance(pricing, dict):
        return None
    primary = pricing.get("primaryPrice")
    if not isinstance(primary, dict):
        return None
    price = primary.get("price")
    if not isinstance(price, dict):
        return None
    price_value = price.get("value")
    if not isinstance(price_value, dict):
        return None
    currency = price_value.get("currency")
    if not isinstance(currency, dict):
        return None
    return text_or_none(currency.get("code"))
