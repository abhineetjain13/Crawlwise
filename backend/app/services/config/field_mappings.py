"""Static field mappings.

Alias consumers prefer exact canonical field keys before alias fallbacks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from glom import Coalesce  # type: ignore[import-untyped]

from app.services.config._export_data import load_export_data

_EXPORTS_PATH = Path(__file__).with_name("field_mappings.exports.json")
_STATIC_EXPORTS = {
    name: value
    for name, value in load_export_data(str(_EXPORTS_PATH)).items()
    if not name.startswith("_")
}

for _name, _value in _STATIC_EXPORTS.items():
    globals()[_name] = _value

JS_STATE_GLOM_SKIP: tuple[object, ...] = ("", [], {})
JS_STATE_PRODUCT_FIELD_SPEC = {
    "title": Coalesce("title", "name", default=None, skip=JS_STATE_GLOM_SKIP),
    "brand": Coalesce(
        "brand.name",
        "brand",
        "vendor.name",
        "vendor",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "vendor": Coalesce("vendor.name", "vendor", default=None, skip=JS_STATE_GLOM_SKIP),
    "handle": Coalesce("handle", "slug", default=None, skip=JS_STATE_GLOM_SKIP),
    "description": Coalesce(
        "description",
        "body_html",
        "descriptionHtml",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "product_id": Coalesce(
        "id",
        "product_id",
        "productId",
        "legacyResourceId",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "category": Coalesce("category", default=None, skip=JS_STATE_GLOM_SKIP),
    "product_type": Coalesce(
        "product_type", "productType", "type", default=None, skip=JS_STATE_GLOM_SKIP
    ),
    "gender": Coalesce(
        "gender", "target_gender", "targetGender", default=None, skip=JS_STATE_GLOM_SKIP
    ),
    "sku": Coalesce(
        "sku", "productId", "product_id", default=None, skip=JS_STATE_GLOM_SKIP
    ),
    "barcode": Coalesce("barcode", default=None, skip=JS_STATE_GLOM_SKIP),
    "currency": Coalesce(
        "currency",
        "currencyCode",
        "priceCurrency",
        "prices.currency",
        "prices.currentPrice.currencyCode",
        "pricing_information.currency",
        "pricing_information.currentPrice.currencyCode",
        "prices.promo.currency.code",
        "prices.base.currency.code",
        "prices.promo.currencyCode",
        "prices.base.currencyCode",
        "priceRange.minVariantPrice.currencyCode",
        "priceRange.maxVariantPrice.currencyCode",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "price": Coalesce(
        "price",
        "amount",
        "minPrice",
        "maxPrice",
        "formattedPrice",
        "salePrice",
        "salePrice.amount",
        "salePrice.value",
        "currentPrice",
        "currentPrice.amount",
        "currentPrice.value",
        "prices.currentPrice",
        "prices.currentPrice.amount",
        "pricing_information.currentPrice",
        "pricing_information.currentPrice.amount",
        "pricing_information.standard_price",
        "prices.promo.value",
        "prices.base.value",
        "prices.promo.amount",
        "prices.base.amount",
        "priceRange.minVariantPrice.amount",
        "priceRange.maxVariantPrice.amount",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "original_price": Coalesce(
        "compare_at_price",
        "compareAtPrice",
        "original_price",
        "originalPrice",
        "listPrice",
        "fullPrice",
        "fullPrice.amount",
        "prices.initialPrice",
        "prices.initialPrice.amount",
        "pricing_information.standard_price",
        "pricing_information.listPrice",
        "prices.base.value",
        "prices.base.amount",
        "compareAtPriceRange.minVariantPrice.amount",
        "compareAtPriceRange.maxVariantPrice.amount",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "availability": Coalesce(
        "availability",
        "inventory.status",
        "availableForSale",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "tags": Coalesce("tags", default=None, skip=JS_STATE_GLOM_SKIP),
    "created_at": Coalesce("created_at", default=None, skip=JS_STATE_GLOM_SKIP),
    "updated_at": Coalesce("updated_at", default=None, skip=JS_STATE_GLOM_SKIP),
    "published_at": Coalesce("published_at", default=None, skip=JS_STATE_GLOM_SKIP),
}
JS_STATE_VARIANT_FIELD_SPEC = {
    "price": Coalesce(
        "price.amount",
        "price.value",
        "priceV2.amount",
        "priceV2.value",
        "salePrice.amount",
        "salePrice.value",
        "salePrice",
        "currentPrice.amount",
        "currentPrice.value",
        "currentPrice",
        "prices.currentPrice",
        "prices.currentPrice.amount",
        "amount",
        "formattedPrice",
        "price",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "original_price": Coalesce(
        "compare_at_price.amount",
        "compare_at_price",
        "compareAtPrice.amount",
        "compareAtPriceV2.amount",
        "compareAtPrice",
        "original_price",
        "originalPrice",
        "listPrice.amount",
        "listPrice",
        "fullPrice.amount",
        "fullPrice",
        "prices.initialPrice",
        "prices.initialPrice.amount",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "currency": Coalesce(
        "currency",
        "currencyCode",
        "priceCurrency",
        "currentPrice.currencyCode",
        "salePrice.currencyCode",
        "prices.currency",
        "price.currencyCode",
        "price.currency_code",
        "priceV2.currencyCode",
        "compareAtPrice.currencyCode",
        "compareAtPriceV2.currencyCode",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "sku": Coalesce(
        "sku", "productId", "product_id", default=None, skip=JS_STATE_GLOM_SKIP
    ),
    "barcode": Coalesce("barcode", default=None, skip=JS_STATE_GLOM_SKIP),
}
PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS = frozenset(
    {"page_markdown", "table_markdown", "record_type"}
)
PUBLIC_RECORD_MARKDOWN_HIDDEN_FIELDS = frozenset(
    {"product_attributes", "selected_variant", "variant_axes", "variants"}
)

_EXTRA_EXPORTS = [
    "JS_STATE_GLOM_SKIP",
    "JS_STATE_PRODUCT_FIELD_SPEC",
    "JS_STATE_VARIANT_FIELD_SPEC",
    "PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS",
    "PUBLIC_RECORD_MARKDOWN_HIDDEN_FIELDS",
]


def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(list(_STATIC_EXPORTS.keys()) + _EXTRA_EXPORTS)
