from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.config._export_data import load_export_data

_EXPORTS_PATH = Path(__file__).with_name("field_mappings.exports.json")
_STATIC_EXPORTS = load_export_data(str(_EXPORTS_PATH))

for _name, _value in _STATIC_EXPORTS.items():
    globals()[_name] = _value

DOM_HIGH_VALUE_FIELDS: dict[str, frozenset[str]] = {
    "ecommerce_detail": frozenset({"additional_images", "description", "specifications"}),
    "job_detail": frozenset({"description", "responsibilities", "qualifications"}),
}
DOM_OPTIONAL_CUE_FIELDS: dict[str, frozenset[str]] = {
    "ecommerce_detail": frozenset({"features", "materials", "care", "dimensions"}),
    "job_detail": frozenset({"benefits", "skills", "requirements"}),
}
ECOMMERCE_DETAIL_JS_STATE_FIELDS: frozenset[str] = frozenset(
    {
        "additional_images",
        "availability",
        "available_sizes",
        "brand",
        "color",
        "currency",
        "image_count",
        "image_url",
        "option1_name",
        "option1_values",
        "option2_name",
        "option2_values",
        "original_price",
        "price",
        "product_id",
        "selected_variant",
        "size",
        "sku",
        "stock_quantity",
        "title",
        "variant_axes",
        "variant_count",
        "variants",
    }
)
VARIANT_DOM_FIELD_NAMES: tuple[str, ...] = (
    "available_sizes",
    "option1_name",
    "option1_values",
    "option2_name",
    "option2_values",
    "variant_axes",
    "variant_count",
    "variants",
)

def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(
    [
        *_STATIC_EXPORTS.keys(),
        "DOM_HIGH_VALUE_FIELDS",
        "DOM_OPTIONAL_CUE_FIELDS",
        "ECOMMERCE_DETAIL_JS_STATE_FIELDS",
        "VARIANT_DOM_FIELD_NAMES",
    ]
)
