"""Static field mappings.

Alias consumers prefer exact canonical field keys before alias fallbacks.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.config._export_data import load_export_data

_EXPORTS_PATH = Path(__file__).with_name("field_mappings.exports.json")
_STATIC_EXPORTS = {
    name: value
    for name, value in load_export_data(str(_EXPORTS_PATH)).items()
    if not name.startswith("_")
}

for _name, _value in _STATIC_EXPORTS.items():
    globals()[_name] = _value if _value is not None else ()

COLOR_FIELD = "color"
TITLE_FIELD = "title"
SIZE_FIELD = "size"
WIDTH_FIELD = "width"
WEIGHT_FIELD = "weight"
PRICE_FIELD = "price"
CURRENCY_FIELD = "currency"
URL_FIELD = "url"
APPLY_URL_FIELD = "apply_url"
CANONICAL_URL_FIELD = "canonical_url"
IMAGE_URL_FIELD = "image_url"
ADDITIONAL_IMAGES_FIELD = "additional_images"
PRODUCT_ID_FIELD = "product_id"
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
BRAND_LIKE_FIELDS = frozenset({"brand", "company", "dealer_name", "vendor"})
TITLE_STRUCTURED_VALUE_KEYS = (
    "name",
    "title",
    "values",
    "label",
    "text",
    "value",
)
PRICE_DICT_PREFERRED_KEYS = (
    "formattedPrice",
    "displayPrice",
    "price",
    "amount",
    "currentValue",
    "lowPrice",
    "minPrice",
    "minValue",
    "highPrice",
    "maxPrice",
    "maxValue",
    "value",
)
UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
NORMALIZER_LIST_TEXT_FIELDS = frozenset(
    {*_STATIC_EXPORTS.get("NORMALIZER_LIST_TEXT_FIELDS", ()), "features"}
)
ECOMMERCE_DETAIL_JS_STATE_PRIORITY_FIELDS = frozenset(
    field_name
    for field_name in _STATIC_EXPORTS.get("ECOMMERCE_DETAIL_JS_STATE_FIELDS", ())
    if field_name not in {PRODUCT_ID_FIELD, IMAGE_URL_FIELD, ADDITIONAL_IMAGES_FIELD}
)
VARIANT_AXIS_FIELD_NAMES = (
    COLOR_FIELD,
    SIZE_FIELD,
    "type",
    "switches",
    "fit",
    "style",
    "material",
    "finish",
    "pattern",
    "scent",
    "flavor",
    "capacity",
    "length",
    WIDTH_FIELD,
)
_EXTRA_EXPORTS = [
    "AVAILABLE_SIZES_FIELD",
    "APPLY_URL_FIELD",
    "AVAILABILITY_FIELD",
    "BARCODE_FIELD",
    "BRAND_LIKE_FIELDS",
    "CANONICAL_URL_FIELD",
    "COLOR_FIELD",
    "CURRENCY_FIELD",
    "ECOMMERCE_DETAIL_JS_STATE_PRIORITY_FIELDS",
    "IMAGE_URL_FIELD",
    "NORMALIZER_LIST_TEXT_FIELDS",
    "PRICE_FIELD",
    "PRICE_DICT_PREFERRED_KEYS",
    "PRODUCT_ID_FIELD",
    "ROUTE_BARCODE_TO_SKU",
    "SELECTED_VARIANT_FIELD",
    "SIZE_FIELD",
    "SKU_FIELD",
    "STOCK_QUANTITY_FIELD",
    "TITLE_FIELD",
    "TITLE_STRUCTURED_VALUE_KEYS",
    "UNICODE_ESCAPE_RE",
    "URL_FIELD",
    "VARIANTS_FIELD",
    "VARIANT_AXES_FIELD",
    "VARIANT_AXIS_FIELD_NAMES",
    "WEIGHT_FIELD",
    "WIDTH_FIELD",
]


def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(list(_STATIC_EXPORTS.keys()) + _EXTRA_EXPORTS)
