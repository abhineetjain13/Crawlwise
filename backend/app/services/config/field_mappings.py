from __future__ import annotations

from pathlib import Path

from glom import Coalesce  # type: ignore[import-untyped]

from app.services.config._export_data import load_export_data

_EXPORTS = load_export_data(str(Path(__file__).with_name("field_mappings.exports.json")))
JS_STATE_GLOM_SKIP: tuple[object, ...] = ("", [], {})

CANONICAL_SCHEMAS = _EXPORTS['CANONICAL_SCHEMAS']
COLLECTION_KEYS = _EXPORTS['COLLECTION_KEYS']
DATALAYER_ECOMMERCE_FIELD_MAP = _EXPORTS['DATALAYER_ECOMMERCE_FIELD_MAP']
DOM_HIGH_VALUE_FIELDS = _EXPORTS['DOM_HIGH_VALUE_FIELDS']
DOM_OPTIONAL_CUE_FIELDS = _EXPORTS['DOM_OPTIONAL_CUE_FIELDS']
SURFACE_FIELD_REPAIR_TARGETS = _EXPORTS['SURFACE_FIELD_REPAIR_TARGETS']
SURFACE_BROWSER_RETRY_TARGETS = _EXPORTS['SURFACE_BROWSER_RETRY_TARGETS']
ECOMMERCE_DETAIL_JS_STATE_FIELDS = _EXPORTS['ECOMMERCE_DETAIL_JS_STATE_FIELDS']
JS_STATE_PRODUCT_FIELD_SPEC = {
    "title": Coalesce("title", "name", default=None, skip=JS_STATE_GLOM_SKIP),
    "brand": Coalesce("brand.name", "brand", "vendor.name", "vendor", default=None, skip=JS_STATE_GLOM_SKIP),
    "vendor": Coalesce("vendor.name", "vendor", default=None, skip=JS_STATE_GLOM_SKIP),
    "handle": Coalesce("handle", "slug", default=None, skip=JS_STATE_GLOM_SKIP),
    "description": Coalesce("description", "body_html", "descriptionHtml", default=None, skip=JS_STATE_GLOM_SKIP),
    "product_id": Coalesce("id", "product_id", "productId", "legacyResourceId", default=None, skip=JS_STATE_GLOM_SKIP),
    "category": Coalesce("category", default=None, skip=JS_STATE_GLOM_SKIP),
    "product_type": Coalesce("product_type", "productType", "type", default=None, skip=JS_STATE_GLOM_SKIP),
    "sku": Coalesce("sku", "productId", "product_id", default=None, skip=JS_STATE_GLOM_SKIP),
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
    "availability": Coalesce("availability", "inventory.status", "availableForSale", default=None, skip=JS_STATE_GLOM_SKIP),
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
    "sku": Coalesce("sku", "productId", "product_id", default=None, skip=JS_STATE_GLOM_SKIP),
    "barcode": Coalesce("barcode", default=None, skip=JS_STATE_GLOM_SKIP),
}
ECOMMERCE_ONLY_FIELDS = _EXPORTS['ECOMMERCE_ONLY_FIELDS']
FIELD_ALIASES = _EXPORTS['FIELD_ALIASES']
INTERNAL_ONLY_FIELDS = _EXPORTS['INTERNAL_ONLY_FIELDS']
JOB_ONLY_FIELDS = _EXPORTS['JOB_ONLY_FIELDS']
PROMPT_REGISTRY = _EXPORTS['PROMPT_REGISTRY']
PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS = _EXPORTS.get('PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS', {})
PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS = _EXPORTS['PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS']
PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES = _EXPORTS['PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES']
PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS = frozenset(
    {"page_markdown", "table_markdown", "record_type"}
)
PUBLIC_RECORD_MARKDOWN_HIDDEN_FIELDS = frozenset(
    {"product_attributes", "selected_variant", "variant_axes", "variants"}
)
VARIANT_DOM_FIELD_NAMES = _EXPORTS['VARIANT_DOM_FIELD_NAMES']

PUBLIC_RECORD_URL_BLOCKED_PATH_MARKERS = (
    "/api/",
    "/event/",
    "/events/",
    "/tracking/",
    "/analytics/",
    "/beacon/",
    "/click",
)
PUBLIC_RECORD_URL_MAX_LENGTH = 2048

__all__ = sorted(
    [
        'CANONICAL_SCHEMAS',
        'COLLECTION_KEYS',
        'DATALAYER_ECOMMERCE_FIELD_MAP',
        'DOM_HIGH_VALUE_FIELDS',
        'DOM_OPTIONAL_CUE_FIELDS',
        'SURFACE_FIELD_REPAIR_TARGETS',
        'SURFACE_BROWSER_RETRY_TARGETS',
        'ECOMMERCE_DETAIL_JS_STATE_FIELDS',
        'JS_STATE_GLOM_SKIP',
        'JS_STATE_PRODUCT_FIELD_SPEC',
        'JS_STATE_VARIANT_FIELD_SPEC',
        'ECOMMERCE_ONLY_FIELDS',
        'FIELD_ALIASES',
        'INTERNAL_ONLY_FIELDS',
        'JOB_ONLY_FIELDS',
        'PROMPT_REGISTRY',
        'PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS',
        'PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS',
        'PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES',
        'PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS',
        'PUBLIC_RECORD_MARKDOWN_HIDDEN_FIELDS',
        'PUBLIC_RECORD_URL_BLOCKED_PATH_MARKERS',
        'PUBLIC_RECORD_URL_MAX_LENGTH',
        'VARIANT_DOM_FIELD_NAMES',
    ]
)
