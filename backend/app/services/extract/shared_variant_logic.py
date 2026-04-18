from __future__ import annotations

import re


_AXIS_ALIASES = {
    "colour": "color",
    "colourway": "color",
    "colorway": "color",
    "size_name": "size",
}


def normalized_variant_axis_key(value: object) -> str:
    text = str(value or "").strip().lower().replace("&", " ")
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return _AXIS_ALIASES.get(text, text)


def split_variant_axes(
    axes: dict[str, list[str]],
    *,
    always_selectable_axes: frozenset[str] | None = None,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    selectable: dict[str, list[str]] = {}
    single_value_attributes: dict[str, str] = {}
    forced = set(always_selectable_axes or ())
    for axis_name, values in dict(axes or {}).items():
        cleaned_values = [
            str(value).strip()
            for value in list(values or [])
            if str(value).strip()
        ]
        if not cleaned_values:
            continue
        unique_values: list[str] = []
        seen: set[str] = set()
        for value in cleaned_values:
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique_values.append(value)
        if len(unique_values) > 1 or axis_name in forced:
            selectable[str(axis_name)] = unique_values
        else:
            single_value_attributes[str(axis_name)] = unique_values[0]
    return selectable, single_value_attributes
