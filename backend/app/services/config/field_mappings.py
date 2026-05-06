"""Static field mappings.

Alias consumers prefer exact canonical field keys before alias fallbacks.
"""

from __future__ import annotations

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

NORMALIZER_LIST_TEXT_FIELDS = frozenset(
    {*_STATIC_EXPORTS.get("NORMALIZER_LIST_TEXT_FIELDS", ()), "features"}
)

COLOR_FIELD = "color"
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
_EXTRA_EXPORTS = [
    "AVAILABLE_SIZES_FIELD",
    "APPLY_URL_FIELD",
    "AVAILABILITY_FIELD",
    "BARCODE_FIELD",
    "BRAND_LIKE_FIELDS",
    "CANONICAL_URL_FIELD",
    "COLOR_FIELD",
    "CURRENCY_FIELD",
    "IMAGE_URL_FIELD",
    "NORMALIZER_LIST_TEXT_FIELDS",
    "PRICE_FIELD",
    "ROUTE_BARCODE_TO_SKU",
    "SELECTED_VARIANT_FIELD",
    "SIZE_FIELD",
    "SKU_FIELD",
    "STOCK_QUANTITY_FIELD",
    "URL_FIELD",
    "VARIANTS_FIELD",
    "VARIANT_AXES_FIELD",
    "WEIGHT_FIELD",
    "WIDTH_FIELD",
]


def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(list(_STATIC_EXPORTS.keys()) + _EXTRA_EXPORTS)
