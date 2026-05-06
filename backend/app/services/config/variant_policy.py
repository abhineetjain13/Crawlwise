"""Public variant axis and transport-field policy."""

from __future__ import annotations

import re

from app.services.config.field_mappings import (
    AVAILABILITY_FIELD,
    COLOR_FIELD,
    CURRENCY_FIELD,
    IMAGE_URL_FIELD,
    PRICE_FIELD,
    SIZE_FIELD,
    SKU_FIELD,
    STOCK_QUANTITY_FIELD,
    URL_FIELD,
)


def _normalized_variant_axis_alias_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower().replace("&", " ")).strip(
        "_"
    )


VARIANT_AXIS_CANONICAL_MAPPING: dict[frozenset[str], str] = {
    frozenset(
        {
            COLOR_FIELD,
            "colors",
            "colour",
            "colours",
            "hue",
            "shade",
            "color way",
            "color_way",
            "colorway",
            "frame color",
            "frame_color",
            "frame colour",
            "frame_colour",
        }
    ): COLOR_FIELD,
    frozenset({SIZE_FIELD, "sizes", "frame size", "frame_size"}): SIZE_FIELD,
    frozenset(
        {
            "dimensions",
            "dimension",
            "measurements",
            "measurement",
            "proportions",
            "proportion",
        }
    ): "dimensions",
    frozenset({"flavor", "flavors", "flavour", "flavours", "taste"}): "flavor",
    frozenset({"material", "materials"}): "material",
    frozenset({"pattern", "patterns"}): "pattern",
    frozenset({"finish", "finishes"}): "finish",
    frozenset(
        {
            "count",
            "counts",
            "pack count",
            "pack_count",
            "package count",
            "package_count",
        }
    ): "count",
    frozenset(
        {
            "bundle type",
            "bundle_type",
            "bundle",
            "bundles",
            "part or kit",
            "part_or_kit",
        }
    ): "bundle_type",
    frozenset({"weight", "weights"}): "weight",
    frozenset({"storage capacity", "storage_capacity"}): "storage_capacity",
    frozenset({"material composition", "material_composition", "composition"}): (
        "material_composition"
    ),
}
PUBLIC_VARIANT_AXIS_FIELDS: tuple[str, ...] = (
    COLOR_FIELD,
    SIZE_FIELD,
    "flavor",
    "material",
    "pattern",
    "finish",
    "count",
    "bundle_type",
    "weight",
    "dimensions",
    "style",
    "condition",
    "state",
    "storage",
    "storage_capacity",
    "connectivity",
    "voltage",
    "plug_type",
    "volume",
    "scent",
    "spf_rating",
    "skin_type",
    "configuration",
    "fabric_grade",
    "leg_finish",
    "tolerance_level",
    "thread_size",
    "material_composition",
    "load_rating",
    "frequency",
    "commitment_period",
    "seat_count",
    "usage_limit",
    "tier",
)
AXIS_NAME_ALIASES = {
    normalized_alias: normalized_canonical
    for group, canonical in VARIANT_AXIS_CANONICAL_MAPPING.items()
    for normalized_canonical in [_normalized_variant_axis_alias_key(canonical)]
    for normalized_alias in (
        _normalized_variant_axis_alias_key(str(raw_alias)) for raw_alias in group
    )
    if normalized_alias and normalized_canonical
}
OPTION_SCALAR_FIELDS = frozenset(PUBLIC_VARIANT_AXIS_FIELDS)
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
VARIANT_PARENT_SHARED_FIELDS: tuple[str, ...] = (
    PRICE_FIELD,
    CURRENCY_FIELD,
    URL_FIELD,
    IMAGE_URL_FIELD,
)
