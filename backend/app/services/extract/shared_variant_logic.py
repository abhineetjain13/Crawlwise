from __future__ import annotations

import itertools
import re
from typing import Any

from app.services.config.extraction_rules import (
    VARIANT_AXIS_ALIASES,
    VARIANT_CHOICE_GROUP_SELECTOR,
    VARIANT_SELECT_GROUP_SELECTOR,
)
from app.services.field_value_core import clean_text


def normalized_variant_axis_key(value: object) -> str:
    text = str(value or "").strip().lower().replace("&", " ")
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    aliases = VARIANT_AXIS_ALIASES if isinstance(VARIANT_AXIS_ALIASES, dict) else {}
    return str(aliases.get(text) or text)


def variant_dom_cues_present(soup: Any) -> bool:
    return bool(iter_variant_select_groups(soup) or iter_variant_choice_groups(soup))


def infer_variant_group_name(node: Any) -> str:
    if not hasattr(node, "get"):
        return ""
    parts: list[str] = []
    for attr_name in (
        "data-option-name",
        "data-testid",
        "data-qa-action",
        "id",
        "name",
        "class",
    ):
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


def resolve_variant_group_name(node: Any) -> str:
    if not hasattr(node, "get"):
        return ""
    inferred_name = infer_variant_group_name(node)
    raw_candidates: list[object] = [
        node.get(attr_name)
        for attr_name in (
            "data-option-name",
            "aria-label",
            "name",
            "id",
            "data-testid",
            "data-qa-action",
        )
        if node.get(attr_name) not in (None, "", [], {})
    ]
    label = node.find_parent("label") if hasattr(node, "find_parent") else None
    if label is not None:
        raw_candidates.append(label.get_text(" ", strip=True))
    fieldset = node.find_parent("fieldset") if hasattr(node, "find_parent") else None
    if fieldset is not None:
        legend = fieldset.find("legend")
        if legend is not None:
            raw_candidates.append(legend.get_text(" ", strip=True))
    for raw_name in [*raw_candidates, inferred_name]:
        cleaned_name = clean_text(str(raw_name).replace("_", " ").replace("-", " "))
        axis_key = normalized_variant_axis_key(cleaned_name)
        if axis_key in {"color", "size"}:
            return cleaned_name
    return clean_text(inferred_name)


def iter_variant_select_groups(soup: Any) -> list[Any]:
    groups: list[Any] = []
    for select in soup.select(VARIANT_SELECT_GROUP_SELECTOR):
        if resolve_variant_group_name(select):
            groups.append(select)
        if len(groups) >= 4:
            break
    return groups


def iter_variant_choice_groups(soup: Any) -> list[Any]:
    groups: list[Any] = []
    for container in soup.select(VARIANT_CHOICE_GROUP_SELECTOR):
        if resolve_variant_group_name(container):
            groups.append(container)
        if len(groups) >= 8:
            break
    return groups


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
