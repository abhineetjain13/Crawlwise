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

_VARIANT_AXIS_LABEL_NOISE_TOKENS = frozenset(
    {
        "answer",
        "answers",
        "delivery",
        "emi",
        "faq",
        "helpfulness",
        "payment",
        "question",
        "questions",
        "rating",
        "ratings",
        "review",
        "reviews",
        "shipping",
        "warranty",
    }
)
_VARIANT_AXIS_LABEL_NOISE_PATTERNS = (
    re.compile(r"\bq&a\b", re.I),
    re.compile(r"\b\d+\s+answers?\b", re.I),
    re.compile(r"\bask\s+a\s+question\b", re.I),
    re.compile(r"\bcontent\s+helpfulness\b", re.I),
    re.compile(r"\breport\s+this\s+answer\b", re.I),
)
_VARIANT_AXIS_ALLOWED_SINGLE_TOKENS = frozenset(
    {
        "color",
        "colour",
        "condition",
        "cup",
        "edition",
        "finish",
        "flavor",
        "flavour",
        "format",
        "fit",
        "material",
        "memory",
        "model",
        "pack",
        "scent",
        "shade",
        "size",
        "storage",
        "style",
        "type",
        "weight",
    }
)
_VARIANT_AXIS_GENERIC_TOKENS = frozenset(
    {
        "attribute",
        "choice",
        "dropdown",
        "option",
        "options",
        "select",
        "selected",
        "selector",
        "styledselect",
        "swatch",
        "variant",
        "variation",
    }
)
_VARIANT_AXIS_TECHNICAL_PATTERNS = (
    re.compile(r"^(?:option|options?|select|selector|dropdown|variant|variation|styledselect)[_\s-]*\d+$", re.I),
    re.compile(r"^(?:variation|variant|option|attribute|selector|styledselect)(?:[_\s-]+(?:selector|select))?(?:[_\s-]*\d+)?$", re.I),
    re.compile(r"^[a-z]*select\d+$", re.I),
)


def normalized_variant_axis_key(value: object) -> str:
    text = str(value or "").strip().lower().replace("&", " ")
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    aliases = VARIANT_AXIS_ALIASES if isinstance(VARIANT_AXIS_ALIASES, dict) else {}
    normalized = str(aliases.get(text) or text)
    tokens = [token for token in normalized.split("_") if token]
    semantic_tokens = [
        token
        for token in tokens
        if token in _VARIANT_AXIS_ALLOWED_SINGLE_TOKENS
    ]
    if (
        len(semantic_tokens) == 1
        and all(
            token == semantic_tokens[0]
            or token in _VARIANT_AXIS_GENERIC_TOKENS
            or token.isdigit()
            or len(token) <= 3
            for token in tokens
        )
    ):
        return semantic_tokens[0]
    return normalized


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
    raw_candidates: list[object] = []
    tag_name = str(getattr(node, "name", "") or "").strip().lower()
    label = node.find_parent("label") if hasattr(node, "find_parent") else None
    if label is not None and tag_name not in {"input", "button", "option"}:
        raw_candidates.append(label.get_text(" ", strip=True))
    fieldset = node.find_parent("fieldset") if hasattr(node, "find_parent") else None
    if fieldset is not None:
        legend = fieldset.find("legend")
        if legend is not None:
            raw_candidates.append(legend.get_text(" ", strip=True))
    if _node_attr_can_hold_group_label(node):
        aria_label = node.get("aria-label")
        if aria_label not in (None, "", [], {}):
            raw_candidates.append(aria_label)
    raw_candidates.extend(
        node.get(attr_name)
        for attr_name in (
            "data-option-name",
            "name",
            "id",
            "data-testid",
            "data-qa-action",
        )
        if node.get(attr_name) not in (None, "", [], {})
    )
    for raw_name in [*raw_candidates, inferred_name]:
        cleaned_name = clean_text(str(raw_name).replace("_", " ").replace("-", " "))
        if variant_axis_name_is_semantic(cleaned_name):
            normalized_name = normalized_variant_axis_key(cleaned_name)
            tokens = [token for token in re.split(r"[^a-z0-9]+", cleaned_name.lower()) if token]
            if normalized_name in _VARIANT_AXIS_ALLOWED_SINGLE_TOKENS and any(
                token.isdigit() or token in _VARIANT_AXIS_GENERIC_TOKENS
                for token in tokens
            ):
                return normalized_name
            return cleaned_name
    return clean_text(inferred_name)


def _node_attr_can_hold_group_label(node: Any) -> bool:
    tag_name = str(getattr(node, "name", "") or "").strip().lower()
    role = str(node.get("role") or "").strip().lower()
    if role == "radiogroup":
        return True
    if tag_name in {"select", "fieldset"}:
        return True
    if tag_name in {"input", "button", "option", "img", "a"}:
        return False
    if not hasattr(node, "select"):
        return True
    input_count = len(node.select("input[type='radio'], input[type='checkbox']"))
    return input_count >= 2 or tag_name in {"div", "section", "ul", "ol", "form"}


def _looks_like_variant_axis_name(value: object) -> bool:
    return variant_axis_name_is_semantic(value)


def variant_axis_name_is_semantic(value: object) -> bool:
    cleaned = clean_text(value)
    lowered = cleaned.lower()
    if not lowered:
        return False
    if any(pattern.search(lowered) for pattern in _VARIANT_AXIS_LABEL_NOISE_PATTERNS):
        return False
    if any(pattern.fullmatch(lowered) for pattern in _VARIANT_AXIS_TECHNICAL_PATTERNS):
        return False
    if re.fullmatch(r"[a-z0-9]+", lowered) and lowered in _VARIANT_AXIS_ALLOWED_SINGLE_TOKENS:
        return True
    tokens = [token for token in re.split(r"[^a-z0-9]+", lowered) if token]
    if not tokens or len(tokens) > 4:
        return False
    if any(token in _VARIANT_AXIS_LABEL_NOISE_TOKENS for token in tokens):
        return False
    axis_key = normalized_variant_axis_key(cleaned)
    if not axis_key or len(axis_key) > 32:
        return False
    axis_tokens = [token for token in axis_key.split("_") if token]
    if not axis_tokens:
        return False
    if any(pattern.fullmatch(axis_key) for pattern in _VARIANT_AXIS_TECHNICAL_PATTERNS):
        return False
    if any(token in _VARIANT_AXIS_ALLOWED_SINGLE_TOKENS for token in axis_tokens):
        return True
    non_generic_tokens = [
        token for token in axis_tokens if token not in _VARIANT_AXIS_GENERIC_TOKENS and not token.isdigit()
    ]
    if not non_generic_tokens:
        return False
    return True


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
    seen_ids: set[int] = set()
    for container in soup.select(VARIANT_CHOICE_GROUP_SELECTOR):
        if resolve_variant_group_name(container):
            groups.append(container)
            seen_ids.add(id(container))
        if len(groups) >= 8:
            break
    if len(groups) >= 8:
        return groups
    for node in soup.select("input[type='radio'], input[type='checkbox']"):
        axis_name = resolve_variant_group_name(node)
        if not axis_name:
            continue
        candidate = _variant_choice_container_for_input(node, axis_name=axis_name)
        if candidate is None or id(candidate) in seen_ids:
            continue
        groups.append(candidate)
        seen_ids.add(id(candidate))
        if len(groups) >= 8:
            break
    return groups


def _variant_choice_container_for_input(node: Any, *, axis_name: str) -> Any | None:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if not hasattr(parent, "select"):
            parent = getattr(parent, "parent", None)
            continue
        matching_inputs = [
            item
            for item in parent.select("input[type='radio'], input[type='checkbox']")
            if resolve_variant_group_name(item) == axis_name
        ]
        if len(matching_inputs) < 2:
            parent = getattr(parent, "parent", None)
            continue
        class_attr = parent.get("class") if hasattr(parent, "get") else None
        class_probe = (
            " ".join(str(value) for value in class_attr)
            if isinstance(class_attr, list)
            else str(class_attr or "")
        ).lower()
        tag_name = str(getattr(parent, "name", "") or "").lower()
        role = str(parent.get("role") or "").lower() if hasattr(parent, "get") else ""
        if (
            role == "radiogroup"
            or tag_name in {"fieldset", "ul", "ol"}
            or any(hint in class_probe for hint in ("color", "size", "swatch", "variant"))
            or resolve_variant_group_name(parent)
        ):
            return parent
        if len(matching_inputs) <= 12 and tag_name in {"div", "section"}:
            return parent
        parent = getattr(parent, "parent", None)
    return None


def split_variant_axes(
    axes: dict[str, list[str]],
    *,
    always_selectable_axes: frozenset[str] | None = None,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    selectable: dict[str, list[str]] = {}
    single_value_attributes: dict[str, str] = {}
    forced = set(always_selectable_axes or ())
    for axis_name, values in dict(axes or {}).items():
        raw_values = (
            list(values)
            if isinstance(values, (list, tuple, set))
            else ([values] if values not in (None, "", [], {}) else [])
        )
        cleaned_values = [
            str(value).strip()
            for value in raw_values
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
