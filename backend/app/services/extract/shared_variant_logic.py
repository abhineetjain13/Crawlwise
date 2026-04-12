from __future__ import annotations

from app.services.requested_field_policy import normalize_requested_field

VARIANT_ALWAYS_SELECTABLE_AXES = frozenset(
    {"color", "size", "waist", "width", "length", "inseam"}
)


def normalized_variant_axis_key(value: object) -> str:
    text = " ".join(str(value or "").split()).strip().lower()
    if text in {"color", "colour", "colors", "colours"}:
        return "color"
    if text in {"size", "sizes", "dimension", "dimensions"}:
        return "size"
    normalized = normalize_requested_field(text)
    if normalized in {"dimension", "dimensions"}:
        return "size"
    return normalized or text


def split_variant_axes(
    axis_values: dict[str, list[str]],
    *,
    always_selectable_axes: frozenset[str] = VARIANT_ALWAYS_SELECTABLE_AXES,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    selectable: dict[str, list[str]] = {}
    product_attributes: dict[str, str] = {}
    for axis_name, values in axis_values.items():
        cleaned_values = list(
            dict.fromkeys(
                " ".join(str(value or "").split()).strip()
                for value in values
                if " ".join(str(value or "").split()).strip()
            )
        )
        if len(cleaned_values) > 1 or axis_name in always_selectable_axes:
            selectable[axis_name] = cleaned_values
        elif len(cleaned_values) == 1:
            product_attributes[axis_name] = cleaned_values[0]
    return selectable, product_attributes
