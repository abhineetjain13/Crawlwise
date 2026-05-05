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
    globals()[_name] = _value if _value is not None else ()

NORMALIZER_LIST_TEXT_FIELDS = frozenset(
    {*_STATIC_EXPORTS.get("NORMALIZER_LIST_TEXT_FIELDS", ()), "features"}
)

JS_STATE_GLOM_SKIP: tuple[object, ...] = ("", [], {})
JS_STATE_PRODUCT_FIELD_SPEC = {
    "title": Coalesce("title", "name", "pn", default=None, skip=JS_STATE_GLOM_SKIP),
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
        "pd",
        default=None,
        skip=JS_STATE_GLOM_SKIP,
    ),
    "product_id": Coalesce(
        "id",
        "product_id",
        "productId",
        "pid",
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
    "sku": Coalesce("sku", default=None, skip=JS_STATE_GLOM_SKIP),
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
        "mrp",
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
    "sku": Coalesce("sku", default=None, skip=JS_STATE_GLOM_SKIP),
    "barcode": Coalesce("barcode", default=None, skip=JS_STATE_GLOM_SKIP),
}
COLOR_FIELD = "color"
SIZE_FIELD = "size"
WIDTH_FIELD = "width"
PRICE_FIELD = "price"
CURRENCY_FIELD = "currency"
URL_FIELD = "url"
APPLY_URL_FIELD = "apply_url"
CANONICAL_URL_FIELD = "canonical_url"
IMAGE_URL_FIELD = "image_url"
ADDITIONAL_IMAGES_FIELD = "additional_images"
AVAILABILITY_FIELD = "availability"
STOCK_QUANTITY_FIELD = "stock_quantity"
VARIANTS_FIELD = "variants"
AVAILABLE_SIZES_FIELD = "available_sizes"
VARIANT_AXES_FIELD = "variant_axes"
SELECTED_VARIANT_FIELD = "selected_variant"
BARCODE_FIELD = "barcode"
SKU_FIELD = "sku"
ROUTE_BARCODE_TO_SKU = True
NAVIGATION_URL_FIELDS = frozenset({URL_FIELD, APPLY_URL_FIELD, CANONICAL_URL_FIELD})
# Kept distinct because navigation cleanup and public canonicalization can diverge.
PUBLIC_RECORD_CANONICAL_URL_FIELDS = frozenset(
    {APPLY_URL_FIELD, CANONICAL_URL_FIELD, URL_FIELD}
)
BRAND_LIKE_FIELDS = frozenset({"brand", "company", "dealer_name", "vendor"})
OPTION_SCALAR_FIELDS = frozenset(
    {COLOR_FIELD, "condition", "material", SIZE_FIELD, "storage", "style"}
)
PUBLIC_RECORD_CANONICAL_SURFACE = "ecommerce_detail"
FLAT_VARIANT_KEYS: tuple[str, ...] = (
    COLOR_FIELD,
    SIZE_FIELD,
    SKU_FIELD,
    PRICE_FIELD,
    CURRENCY_FIELD,
    URL_FIELD,
    IMAGE_URL_FIELD,
    AVAILABILITY_FIELD,
    STOCK_QUANTITY_FIELD,
)
PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS = frozenset(
    {"page_markdown", "table_markdown", "record_type"}
)
PUBLIC_RECORD_MARKDOWN_HIDDEN_FIELDS = frozenset({"product_attributes", "variants"})
PUBLIC_RECORD_ECOMMERCE_DROPPED_FIELDS = frozenset({"tags"})
PUBLIC_RECORD_LEGACY_VARIANT_FIELDS = frozenset(
    {
        "selected_variant",
        "variant_axes",
        "available_sizes",
        "option1_name",
        "option1_values",
        "option2_name",
        "option2_values",
        "option_1_name",
        "option_1_value",
        "option_1_values",
        "option_2_name",
        "option_2_value",
        "option_2_values",
    }
)
PUBLIC_RECORD_BARCODE_LENGTHS = frozenset({8, 12, 13, 14})
PUBLIC_RECORD_BRAND_REGION_SUFFIX_TOKENS = frozenset(
    {
        "USA",
        "US",
        "UK",
        "EU",
        "EN",
        "CA",
        "AU",
        "IN",
        "UAE",
        "GCC",
        "GLOBAL",
        "INTL",
        "INTERNATIONAL",
        "OFFICIAL",
        "ONLINE",
        "STORE",
        "SHOP",
        "HOME",
        "WEBSITE",
    }
)
PUBLIC_RECORD_GENDER_TAXONOMY = {
    "men": "Men",
    "man": "Men",
    "male": "Men",
    "mens": "Men",
    "men's": "Men",
    "women": "Women",
    "woman": "Women",
    "female": "Women",
    "womens": "Women",
    "women's": "Women",
    "unisex": "Unisex",
    "uni": "Unisex",
    "kids": "Kids",
    "kid": "Kids",
    "children": "Kids",
    "child": "Kids",
    "boys": "Boys",
    "boy": "Boys",
    "girls": "Girls",
    "girl": "Girls",
}
PUBLIC_RECORD_GENDER_REJECT_TOKENS = frozenset(
    {"default", "null", "na", "n/a", "none", "all", "other", ""}
)
PUBLIC_RECORD_IDENTITY_INTERNAL_TOKENS = frozenset(
    {
        "plp",
        "pdp",
        "specifications",
        "specification",
        "description",
        "details",
        "detail",
        "overview",
        "reviews",
        "review",
        "summary",
        "untitled",
    }
)
PUBLIC_RECORD_PRODUCT_TYPE_NOISE_TOKENS = frozenset(
    {"brightcove", "video", "player", "iframe", "embed", "widget"}
)
PUBLIC_RECORD_SKU_DRAFT_PREFIX_PATTERN = r"^(?:copy|draft|tmp|temp|test)[-_]+"

_EXTRA_EXPORTS = [
    "JS_STATE_GLOM_SKIP",
    "JS_STATE_PRODUCT_FIELD_SPEC",
    "JS_STATE_VARIANT_FIELD_SPEC",
    "AVAILABLE_SIZES_FIELD",
    "APPLY_URL_FIELD",
    "AVAILABILITY_FIELD",
    "BARCODE_FIELD",
    "BRAND_LIKE_FIELDS",
    "CANONICAL_URL_FIELD",
    "COLOR_FIELD",
    "CURRENCY_FIELD",
    "FLAT_VARIANT_KEYS",
    "IMAGE_URL_FIELD",
    "NORMALIZER_LIST_TEXT_FIELDS",
    "OPTION_SCALAR_FIELDS",
    "PRICE_FIELD",
    "PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS",
    "PUBLIC_RECORD_MARKDOWN_HIDDEN_FIELDS",
    "PUBLIC_RECORD_ECOMMERCE_DROPPED_FIELDS",
    "PUBLIC_RECORD_LEGACY_VARIANT_FIELDS",
    "PUBLIC_RECORD_BARCODE_LENGTHS",
    "PUBLIC_RECORD_BRAND_REGION_SUFFIX_TOKENS",
    "PUBLIC_RECORD_GENDER_TAXONOMY",
    "PUBLIC_RECORD_GENDER_REJECT_TOKENS",
    "PUBLIC_RECORD_IDENTITY_INTERNAL_TOKENS",
    "PUBLIC_RECORD_PRODUCT_TYPE_NOISE_TOKENS",
    "PUBLIC_RECORD_SKU_DRAFT_PREFIX_PATTERN",
    "ROUTE_BARCODE_TO_SKU",
    "SELECTED_VARIANT_FIELD",
    "SIZE_FIELD",
    "SKU_FIELD",
    "STOCK_QUANTITY_FIELD",
    "URL_FIELD",
    "VARIANTS_FIELD",
    "VARIANT_AXES_FIELD",
    "WIDTH_FIELD",
]


def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(list(_STATIC_EXPORTS.keys()) + _EXTRA_EXPORTS)
