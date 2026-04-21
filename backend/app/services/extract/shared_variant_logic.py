from __future__ import annotations

import itertools
import re
from typing import Any

from app.services.field_value_core import clean_text


_AXIS_ALIASES = {
    "colour": "color",
    "colourway": "color",
    "colorway": "color",
    "size_name": "size",
}
_VARIANT_DOM_CUE_SELECTORS = (
    "select[name*='variant' i], select[name*='option' i], select[name*='size' i], "
    "select[name*='color' i], select[id*='variant' i], select[id*='option' i], "
    "select[id*='size' i], select[id*='color' i], select[aria-label*='size' i], "
    "select[aria-label*='color' i], select[class*='variant' i], select[data-option], "
    "select[data-option-name]",
    "[data-option-name], [aria-label*='size' i], [aria-label*='color' i], "
    "[class*='swatch' i], [class*='variant' i], [class*='option' i], "
    "[class*='color-selector' i], [class*='size-selector' i], "
    "[data-testid*='swatch' i], [role='radiogroup'], "
    "[data-qa-action='select-color'], [data-qa-action*='size-selector']",
)


def normalized_variant_axis_key(value: object) -> str:
    text = str(value or "").strip().lower().replace("&", " ")
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return _AXIS_ALIASES.get(text, text)


def variant_dom_cues_present(soup: Any) -> bool:
    return any(soup.select(selector) for selector in _VARIANT_DOM_CUE_SELECTORS)


def infer_variant_group_name(node: Any) -> str:
    if not hasattr(node, "get"):
        return ""
    parts: list[str] = []
    for attr_name in ("data-option-name", "aria-label", "data-testid", "data-qa-action", "id", "name", "class"):
        value = node.get(attr_name)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
        elif value not in (None, "", [], {}):
            parts.append(str(value))
    probe = " ".join(parts).replace("_", " ").replace("-", " ").lower()
    if "color" in probe or "colour" in probe:
        return "color"
    if "size" in probe or "fit" in probe:
        return "size"
    return ""


def variant_value_is_noise(value: object) -> bool:
    cleaned = clean_text(value)
    lowered = cleaned.lower()
    return not cleaned or lowered in {"select", "choose", "option", "size guide"} or len(cleaned) > 60 or bool(re.fullmatch(r"\d{3,5}/\d{2,5}/\d{2,5}", cleaned))


def variant_node_is_noise(node: Any) -> bool:
    probe_parts: list[str] = []
    for attr_name in ("data-qa-action", "data-testid", "aria-label", "class", "title"):
        value = node.get(attr_name)
        if isinstance(value, list):
            probe_parts.extend(str(item) for item in value if item)
        elif value not in (None, "", [], {}):
            probe_parts.append(str(value))
    return "copy" in " ".join(probe_parts).lower()


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


def resolve_variants(
    options_matrix: dict[str, list[str]],
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve variants as a Cartesian product matrix.

    Treats variants as a Cartesian product of option axes rather than
    independent dicts, correctly pairing sizes with colors when nested
    deeply.  Eliminates mismatch errors between option1/option2 arrays
    and their corresponding variants in complex nested schemas common
    in Salesforce Commerce Cloud and Magento.

    Computes the full combination matrix from *options_matrix*, matches
    each cell to its corresponding variant row via ``option_values``, and
    returns variants in deterministic Cartesian order.  Duplicate variants
    mapping to the same combination are collapsed (richer row wins).
    Variants that lack full ``option_values`` are appended at the end to
    avoid data loss.
    """
    if not options_matrix or not variants:
        return list(variants)

    keys = list(options_matrix.keys())
    if not keys:
        return list(variants)

    # Index variants by their option_values tuple for O(1) lookup.
    # When duplicates map to the same combo, keep the richer row.
    variant_by_combo: dict[tuple[str, ...], dict[str, Any]] = {}
    no_option_values: list[dict[str, Any]] = []
    for variant in variants:
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict) or not option_values:
            no_option_values.append(variant)
            continue
        combo = tuple(str(option_values.get(k, "")) for k in keys)
        if any(not option_values.get(k) for k in keys):
            no_option_values.append(variant)
            continue
        existing = variant_by_combo.get(combo)
        if existing is None or len(variant) > len(existing):
            variant_by_combo[combo] = variant

    # Walk the Cartesian product; only emit combos that have a real variant.
    resolved: list[dict[str, Any]] = []
    for combo in itertools.product(*(options_matrix[k] for k in keys)):
        matched = variant_by_combo.get(combo)
        if matched is not None:
            resolved.append(matched)

    # Append variants that lacked full option_values (avoid data loss).
    if no_option_values:
        seen_ids = {
            v.get("variant_id") or v.get("sku")
            for v in resolved
            if v.get("variant_id") or v.get("sku")
        }
        for v in no_option_values:
            vid = v.get("variant_id") or v.get("sku")
            if vid and vid in seen_ids:
                continue
            resolved.append(v)
            if vid:
                seen_ids.add(vid)

    return resolved or list(variants)
