from __future__ import annotations

import itertools
import logging
import re
from collections.abc import Sequence
from typing import Any

from app.services.config.extraction_rules import (
    DETAIL_VARIANT_CONTEXT_NOISE_TOKENS,
    DETAIL_VARIANT_SCOPE_SELECTOR,
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH,
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT,
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK,
    VARIANT_SCOPE_MAX_ROOTS,
    VARIANT_AXIS_LABEL_NOISE_PATTERNS,
    VARIANT_AXIS_LABEL_NOISE_TOKENS,
    VARIANT_AXIS_ALIASES,
    VARIANT_AXIS_ALLOWED_SINGLE_TOKENS,
    VARIANT_AXIS_GENERIC_TOKENS,
    VARIANT_CHOICE_GROUP_SELECTOR,
    VARIANT_COLOR_HINT_WORDS,
    VARIANT_GROUP_ATTR_NOISE_PATTERNS,
    VARIANT_GROUP_ATTR_NOISE_TOKENS,
    VARIANT_OPTION_VALUE_NOISE_TOKENS,
    VARIANT_QUANTITY_ATTR_TOKENS,
    VARIANT_SIZE_ALIAS_SUFFIXES,
    VARIANT_SIZE_VALUE_PATTERNS,
    VARIANT_SELECT_GROUP_SELECTOR,
    VARIANT_AXIS_TECHNICAL_PATTERNS,
)
from app.services.field_value_core import clean_text, text_or_none

logger = logging.getLogger(__name__)

_variant_axis_label_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_AXIS_LABEL_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_axis_label_noise_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_AXIS_LABEL_NOISE_PATTERNS or ())
    if str(pattern).strip()
)
_variant_group_attr_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_GROUP_ATTR_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_group_attr_noise_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_GROUP_ATTR_NOISE_PATTERNS or ())
    if str(pattern).strip()
)
_variant_color_hint_words = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_COLOR_HINT_WORDS or ())
    if str(token).strip()
)
_variant_size_value_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_SIZE_VALUE_PATTERNS or ())
    if str(pattern).strip()
)
_variant_option_value_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_OPTION_VALUE_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_context_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(DETAIL_VARIANT_CONTEXT_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_scope_selector = str(DETAIL_VARIANT_SCOPE_SELECTOR or "").strip()
_variant_size_alias_suffixes = tuple(
    str(token).strip().lower()
    for token in tuple(VARIANT_SIZE_ALIAS_SUFFIXES or ())
    if str(token).strip()
)
_variant_axis_allowed_single_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_AXIS_ALLOWED_SINGLE_TOKENS or ())
    if str(token).strip()
)
_variant_axis_generic_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_AXIS_GENERIC_TOKENS or ())
    if str(token).strip()
)
_variant_axis_technical_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_AXIS_TECHNICAL_PATTERNS or ())
    if str(pattern).strip()
)
_variant_quantity_attr_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_QUANTITY_ATTR_TOKENS or ())
    if str(token).strip()
)


def _variant_axis_label_is_noise(value: object) -> bool:
    lowered = clean_text(value).lower()
    if not lowered:
        return False
    tokens = [token for token in re.split(r"[^a-z0-9]+", lowered) if token]
    if any(token in _variant_axis_label_noise_tokens for token in tokens):
        return True
    return any(
        pattern.search(lowered) for pattern in _variant_axis_label_noise_patterns
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
        token for token in tokens if token in _variant_axis_allowed_single_tokens
    ]
    if len(semantic_tokens) == 1 and all(
        token == semantic_tokens[0]
        or token in _variant_axis_generic_tokens
        or token.isdigit()
        or len(token) <= 3
        for token in tokens
    ):
        return semantic_tokens[0]
    return normalized


def normalized_variant_axis_display_name(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    axis_key = normalized_variant_axis_key(cleaned)
    if not axis_key:
        return cleaned
    lowered = cleaned.lower().replace("&", " ")
    tokens = [token for token in re.split(r"[^a-z0-9]+", lowered) if token]
    if not tokens:
        return cleaned
    if len(tokens) == 1 and tokens[0] == axis_key:
        return cleaned
    if axis_key not in _variant_axis_allowed_single_tokens:
        return cleaned
    extra_tokens = [token for token in tokens if token != axis_key]
    if extra_tokens and all(
        token in _variant_axis_generic_tokens or token.isdigit() or len(token) <= 3
        for token in extra_tokens
    ):
        return axis_key
    return cleaned


def variant_dom_cues_present(soup: Any) -> bool:
    return bool(iter_variant_select_groups(soup) or iter_variant_choice_groups(soup))


def _variant_node_in_noise_context(node: Any) -> bool:
    try:
        depth = max(0, int(VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH))
    except (TypeError, ValueError):
        try:
            depth = max(0, int(VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK))
        except (TypeError, ValueError):
            depth = VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT
    current = node
    for _ in range(depth):
        if current is None or not hasattr(current, "get"):
            return False
        parts: list[str] = []
        for attr_name in ("id", "class", "aria-label", "data-testid", "role"):
            value = current.get(attr_name)
            if isinstance(value, list):
                parts.extend(str(item) for item in value if item)
            elif value not in (None, "", [], {}):
                parts.append(str(value))
        probe = clean_text(" ".join(parts)).lower()
        if probe and any(token in probe for token in _variant_context_noise_tokens):
            return True
        current = getattr(current, "parent", None)
    return False


def _variant_scope_roots(soup: Any) -> list[Any]:
    if not hasattr(soup, "select") or not _variant_scope_selector:
        return [soup]
    # Defensive coercion: treat missing/invalid limit as "no limit".
    try:
        max_roots = (
            int(VARIANT_SCOPE_MAX_ROOTS)
            if VARIANT_SCOPE_MAX_ROOTS is not None
            else None
        )
    except (TypeError, ValueError):
        max_roots = None
    roots: list[Any] = []
    seen: set[int] = set()
    for node in soup.select(_variant_scope_selector):
        if id(node) in seen or _variant_node_in_noise_context(node):
            continue
        if not (
            node.select(VARIANT_SELECT_GROUP_SELECTOR)
            or node.select(VARIANT_CHOICE_GROUP_SELECTOR)
            or node.select("input[type='radio'], input[type='checkbox']")
        ):
            continue
        roots.append(node)
        seen.add(id(node))
        if max_roots is not None and len(roots) >= max_roots:
            break
    return roots or [soup]


def _select_variant_nodes(soup: Any, selector: str) -> list[Any]:
    nodes: list[Any] = []
    seen: set[int] = set()
    for root in _variant_scope_roots(soup):
        if not hasattr(root, "select"):
            continue
        for node in root.select(selector):
            if id(node) in seen or _variant_node_in_noise_context(node):
                continue
            nodes.append(node)
            seen.add(id(node))
    return nodes


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
    # Check all allowed variant axis tokens (weight, flavor, scent, etc.)
    tokens = [token for token in re.split(r"[^a-z0-9]+", probe) if token]
    for token in tokens:
        if token in _variant_axis_allowed_single_tokens and token not in {
            "color",
            "size",
            "fit",
            "colour",
        }:
            return token
    return ""


def _normalized_group_label_candidates(value: object) -> list[str]:
    cleaned = clean_text(str(value).replace("_", " ").replace("-", " "))
    if not cleaned:
        return []
    candidates = [cleaned]
    if ":" in cleaned:
        trailing = clean_text(cleaned.rsplit(":", 1)[-1])
        if trailing:
            candidates.insert(0, trailing)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        lowered = candidate.casefold()
        if not candidate or lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(candidate)
    return deduped


def _resolve_visible_variant_group_name(value: object) -> str:
    for candidate in _normalized_group_label_candidates(value):
        if _variant_axis_label_is_noise(candidate):
            continue
        if variant_axis_name_is_semantic(candidate):
            normalized_name = normalized_variant_axis_key(candidate)
            tokens = [
                token for token in re.split(r"[^a-z0-9]+", candidate.lower()) if token
            ]
            if normalized_name in _variant_axis_allowed_single_tokens and any(
                token.isdigit() or token in _variant_axis_generic_tokens
                for token in tokens
            ):
                return normalized_name
            return candidate
        resolved_name = _resolve_machine_variant_group_name(candidate)
        if resolved_name:
            return resolved_name
    return ""


def _choice_option_text(node: Any, *, parent: Any | None = None) -> str:
    if node is None or not hasattr(node, "get"):
        return ""
    label_text = ""
    if str(getattr(node, "name", "") or "").strip().lower() in {"input", "button"}:
        label = _variant_input_label(parent or node, node)
        if label is not None:
            label_text = clean_text(label.get_text(" ", strip=True))
    node_text = (
        clean_text(node.get_text(" ", strip=True)) if hasattr(node, "get_text") else ""
    )
    return clean_text(
        node.get("data-attr-displayvalue")
        or node.get("data-displayvalue")
        or node.get("data-display-value")
        or node.get("data-swatch-sr")
        or label_text
        or node.get("data-value")
        or node.get("data-option-value")
        or node.get("aria-label")
        or node.get("value")
        or node_text
    )


def _variant_input_label(container: Any, input_node: Any) -> Any | None:
    input_id = (
        text_or_none(input_node.get("id")) if hasattr(input_node, "get") else None
    )
    if input_id and hasattr(container, "find"):
        label = container.find("label", attrs={"for": input_id})
        if label is not None:
            return label
    if hasattr(input_node, "find_parent"):
        label = input_node.find_parent("label")
        if label is not None:
            return label
    sibling = getattr(input_node, "next_sibling", None)
    while sibling is not None:
        if getattr(sibling, "name", None) == "label":
            return sibling
        sibling = getattr(sibling, "next_sibling", None)
    return None


def _choice_option_texts(node: Any) -> list[str]:
    if not hasattr(node, "select"):
        return []
    values: list[str] = []
    for option in node.select(
        "option, [role='radio'], [role='option'], button, input[type='radio'], input[type='checkbox']"
    )[:24]:
        value = _choice_option_text(option, parent=node)
        if value:
            values.append(value)
    return values


def _descendant_variant_group_name(node: Any) -> str:
    if not hasattr(node, "select"):
        return ""
    for child in node.select("label")[:24]:
        sr_only = child.select_one(".sr-only, .visually-hidden")
        raw_value = (
            sr_only.get_text(" ", strip=True)
            if sr_only is not None
            else child.get_text(" ", strip=True)
        )
        if resolved_name := _resolve_visible_variant_group_name(raw_value):
            return resolved_name
    for child in node.select(
        "[data-option-name], input[type='radio'], input[type='checkbox'], button"
    )[:24]:
        for attr_name in (
            "data-option-name",
            "name",
            "id",
            "data-testid",
            "data-qa-action",
        ):
            raw_value = child.get(attr_name)
            if raw_value in (None, "", [], {}):
                continue
            if resolved_name := _resolve_machine_variant_group_name(raw_value):
                return resolved_name
    return ""


def _node_supports_value_only_axis_inference(node: Any) -> bool:
    return hasattr(node, "select") and bool(
        node.select(
            "select, input[type='radio'], input[type='checkbox'], [data-option-name]"
        )
    )


def _variant_choice_container_is_overbroad(node: Any) -> bool:
    if not hasattr(node, "select"):
        return False
    if str(getattr(node, "name", "") or "").strip().lower() == "fieldset":
        return False
    if len(node.select("fieldset")) >= 2:
        return True
    raw_names = {
        text_or_none(
            child.get("name")
            or child.get("data-option-name")
            or child.get("data-testid")
        )
        for child in node.select("input[type='radio'], input[type='checkbox'], button")[
            :24
        ]
    }
    distinct_names = {
        normalized_variant_axis_key(raw_name) or clean_text(raw_name).casefold()
        for raw_name in raw_names
        if raw_name
    }
    for select in node.select("select")[:8]:
        raw_name = text_or_none(
            select.get("name")
            or select.get("aria-label")
            or select.get("data-option-name")
        )
        if raw_name:
            distinct_names.add(
                normalized_variant_axis_key(raw_name) or clean_text(raw_name).casefold()
            )
    for group_node in node.select("[role='radiogroup'], [aria-label]")[:12]:
        if str(getattr(group_node, "name", "") or "").strip().lower() in {
            "button",
            "input",
            "option",
        }:
            continue
        raw_name = text_or_none(group_node.get("aria-label"))
        if raw_name:
            distinct_names.add(
                normalized_variant_axis_key(raw_name) or clean_text(raw_name).casefold()
            )
    return len(distinct_names) >= 2


def resolve_variant_group_name(node: Any) -> str:
    if not hasattr(node, "get"):
        return ""
    if _variant_group_node_attrs_are_noise(node):
        return ""
    inferred_name = infer_variant_group_name(node)
    visible_candidates: list[object] = []
    machine_candidates: list[object] = []
    tag_name = str(getattr(node, "name", "") or "").strip().lower()
    node_id = text_or_none(node.get("id"))
    if node_id and tag_name not in {"input", "button", "option"}:
        root = node
        while getattr(root, "parent", None) is not None:
            root = root.parent
        if hasattr(root, "find"):
            external_label = root.find("label", attrs={"for": node_id})
            if external_label is not None:
                visible_candidates.append(external_label.get_text(" ", strip=True))
    label = node.find_parent("label") if hasattr(node, "find_parent") else None
    if label is not None and tag_name not in {"input", "button", "option"}:
        visible_candidates.append(label.get_text(" ", strip=True))
    fieldset = (
        node
        if tag_name == "fieldset"
        else (node.find_parent("fieldset") if hasattr(node, "find_parent") else None)
    )
    if fieldset is not None:
        legend = fieldset.find("legend")
        if legend is not None:
            visible_candidates.append(legend.get_text(" ", strip=True))
    if _node_attr_can_hold_group_label(node):
        aria_label = node.get("aria-label")
        if aria_label not in (None, "", [], {}):
            visible_candidates.append(aria_label)
    machine_candidates.extend(
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
    for raw_name in [*visible_candidates, inferred_name]:
        if resolved_name := _resolve_visible_variant_group_name(raw_name):
            return resolved_name
    if descendant_name := _descendant_variant_group_name(node):
        return descendant_name
    for raw_name in machine_candidates:
        resolved_name = _resolve_machine_variant_group_name(raw_name)
        if resolved_name:
            return resolved_name
    if tag_name == "select":
        inferred_from_values = infer_variant_group_name_from_values(
            _select_option_texts(node)
        )
        if inferred_from_values == "size":
            return inferred_from_values
    if (
        tag_name != "select"
        and _node_supports_value_only_axis_inference(node)
        and (
            inferred_from_values := infer_variant_group_name_from_values(
                _choice_option_texts(node)
            )
        )
    ):
        return inferred_from_values
    nearby = _nearby_variant_group_name(node)
    if nearby:
        return nearby
    if hasattr(node, "select"):
        for child in node.select(
            "[data-option-name], [aria-label], [data-testid], [data-qa-action], [role='radio'], input, button"
        )[:24]:
            inferred_child = infer_variant_group_name(child)
            if inferred_child:
                return inferred_child
    return clean_text(inferred_name)


def infer_variant_group_name_from_values(values: Sequence[object]) -> str:
    cleaned_values = [
        clean_text(value) for value in list(values or []) if clean_text(value)
    ]
    if len(cleaned_values) < 2:
        return ""
    # Sequential integer runs are quantity selectors, not variant axes.
    if _is_sequential_integer_run(cleaned_values):
        return ""
    size_hits = sum(
        1
        for value in cleaned_values
        if any(pattern.fullmatch(value) for pattern in _variant_size_value_patterns)
    )
    if size_hits >= 2 and size_hits / len(cleaned_values) >= 0.5:
        return "size"
    color_hits = sum(1 for value in cleaned_values if _value_looks_like_color(value))
    if color_hits >= 2 and color_hits / len(cleaned_values) >= 0.5:
        return "color"
    return ""


def _resolve_machine_variant_group_name(value: object) -> str:
    cleaned = clean_text(str(value).replace("_", " ").replace("-", " "))
    if not cleaned or not variant_axis_name_is_semantic(cleaned):
        return ""
    normalized = normalized_variant_axis_key(cleaned)
    if not normalized:
        return ""
    normalized_tokens = [token for token in normalized.split("_") if token]
    if not normalized_tokens:
        return ""
    if normalized in _variant_axis_allowed_single_tokens:
        return normalized
    if all(
        token in _variant_axis_allowed_single_tokens
        or token in _variant_axis_generic_tokens
        or token.isdigit()
        for token in normalized_tokens
    ):
        return normalized
    return ""


def _variant_group_node_attrs_are_noise(node: Any) -> bool:
    if not hasattr(node, "get"):
        return False
    parts: list[str] = []
    for attr_name in (
        "aria-label",
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
    probe = clean_text(" ".join(parts)).lower()
    if not probe:
        return False
    if any(token in probe for token in _variant_group_attr_noise_tokens):
        return True
    if any(token in probe for token in _variant_context_noise_tokens):
        return True
    return any(pattern.search(probe) for pattern in _variant_group_attr_noise_patterns)


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


def _nearby_variant_group_name(node: Any) -> str:
    current = node
    for _ in range(4):
        sibling = getattr(current, "previous_sibling", None)
        while sibling is not None:
            if hasattr(sibling, "get_text"):
                extracted = _semantic_group_label_from_text(
                    sibling.get_text(" ", strip=True)
                )
                if extracted:
                    return extracted
            sibling = getattr(sibling, "previous_sibling", None)
        parent = getattr(current, "parent", None)
        if parent is None:
            break
        current = parent
    return ""


def _select_option_texts(node: Any) -> list[str]:
    if not hasattr(node, "select"):
        return []
    values: list[str] = []
    for option in node.select("option")[:24]:
        text = (
            clean_text(option.get_text(" ", strip=True))
            if hasattr(option, "get_text")
            else ""
        )
        if text:
            values.append(text)
    return values


def _is_sequential_integer_run(values: list[str]) -> bool:
    """Return True when every value is a bare integer and the set forms a
    contiguous run of >= 5 values.  This is the signature of a quantity
    selector (1, 2, 3 … N), not a product variant axis."""
    if len(values) < 5:
        return False
    ints: list[int] = []
    for value in values:
        stripped = value.strip()
        if not stripped.isdigit():
            return False
        ints.append(int(stripped))
    if not ints:
        return False
    ints.sort()
    return ints[-1] - ints[0] == len(ints) - 1


def _select_option_values_are_noise(node: Any) -> bool:
    values = _select_option_texts(node)
    if not values:
        return False
    if _is_sequential_integer_run(values):
        return True
    normalized = {
        re.sub(r"[^a-z0-9]+", "", value.lower()) for value in values if value.strip()
    }
    return bool(normalized) and normalized <= _variant_option_value_noise_tokens


def _variant_group_has_multiple_options(node: Any) -> bool:
    if not hasattr(node, "select"):
        return False
    tag_name = str(getattr(node, "name", "") or "").strip().lower()
    if tag_name in {"button", "a", "img", "input", "option"}:
        return False
    option_nodes = node.select(
        "button, [role='radio'], [role='option'], input[type='radio'], "
        "input[type='checkbox'], [data-value], [data-option-value], "
        "[data-selected], [aria-selected], [data-state], option"
    )
    return len(option_nodes) >= 2


def _value_looks_like_color(value: object) -> bool:
    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", clean_text(value).lower())
        if token and not token.isdigit()
    ]
    if not tokens:
        return False
    return any(token in _variant_color_hint_words for token in tokens)


def _semantic_group_label_from_text(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if "color" in lowered or "colour" in lowered:
        return "color"
    if "size" in lowered or "fit" in lowered:
        return "size"
    candidates = [
        cleaned,
        clean_text(cleaned.split(":", 1)[0]),
        clean_text(cleaned.split("(", 1)[0]),
    ]
    for candidate in candidates:
        normalized = normalized_variant_axis_key(candidate)
        if normalized in _variant_axis_allowed_single_tokens:
            return normalized
    return ""


def variant_axis_name_is_semantic(value: object) -> bool:
    cleaned = clean_text(value)
    lowered = cleaned.lower()
    if not lowered:
        return False
    if _variant_axis_label_is_noise(cleaned):
        return False
    if any(pattern.fullmatch(lowered) for pattern in _variant_axis_technical_patterns):
        return False
    if (
        re.fullmatch(r"[a-z0-9]+", lowered)
        and lowered in _variant_axis_allowed_single_tokens
    ):
        return True
    tokens = [token for token in re.split(r"[^a-z0-9]+", lowered) if token]
    if not tokens or len(tokens) > 4:
        return False
    if any(token in _variant_axis_label_noise_tokens for token in tokens):
        return False
    axis_key = normalized_variant_axis_key(cleaned)
    if not axis_key or len(axis_key) > 32:
        return False
    axis_tokens = [token for token in axis_key.split("_") if token]
    if not axis_tokens:
        return False
    if any(pattern.fullmatch(axis_key) for pattern in _variant_axis_technical_patterns):
        return False
    if any(token in _variant_axis_allowed_single_tokens for token in axis_tokens):
        return True
    non_generic_tokens = [
        token
        for token in axis_tokens
        if token not in _variant_axis_generic_tokens and not token.isdigit()
    ]
    if not non_generic_tokens:
        return False
    return True


def _select_is_quantity_node(node: Any) -> bool:
    """Return True when the <select> element signals it is a quantity picker,
    not a product variant axis."""
    if not hasattr(node, "get"):
        return False
    for attr_name in ("name", "id", "aria-label", "data-testid"):
        value = str(node.get(attr_name) or "").strip().lower()
        if not value:
            continue
        tokens = re.split(r"[^a-z0-9]+", value)
        if any(t in _variant_quantity_attr_tokens for t in tokens):
            return True
    return False


def iter_variant_select_groups(soup: Any) -> list[Any]:
    groups: list[Any] = []
    seen_ids: set[int] = set()
    for select in _select_variant_nodes(soup, VARIANT_SELECT_GROUP_SELECTOR):
        if _select_is_quantity_node(select):
            continue
        if _select_option_values_are_noise(select):
            continue
        if resolve_variant_group_name(select):
            groups.append(select)
            seen_ids.add(id(select))
        if len(groups) >= 4:
            break
    if len(groups) >= 4:
        return groups
    for select in _select_variant_nodes(soup, "select"):
        if id(select) in seen_ids:
            continue
        if _select_is_quantity_node(select):
            continue
        if _select_option_values_are_noise(select):
            continue
        if resolve_variant_group_name(select):
            groups.append(select)
            seen_ids.add(id(select))
        if len(groups) >= 4:
            break
    return groups


def iter_variant_choice_groups(soup: Any) -> list[Any]:
    groups: list[Any] = []
    seen_ids: set[int] = set()
    for container in _select_variant_nodes(soup, VARIANT_CHOICE_GROUP_SELECTOR):
        if _variant_choice_container_is_overbroad(container):
            continue
        resolved_name = resolve_variant_group_name(container)
        if _variant_group_has_multiple_options(container) and (
            resolved_name
            or (
                _node_supports_value_only_axis_inference(container)
                and infer_variant_group_name_from_values(
                    _choice_option_texts(container)
                )
            )
        ):
            groups.append(container)
            seen_ids.add(id(container))
        if len(groups) >= 8:
            break
    if len(groups) >= 8:
        return groups
    # discovery of variant choice containers for input elements and specific buttons
    for node in soup.select("select, input[type='radio'], input[type='checkbox']"):
        candidate = _variant_choice_container_for_input(node)
        if candidate is not None and id(candidate) not in seen_ids:
            groups.append(candidate)
            seen_ids.add(id(candidate))
            if len(groups) >= 8:
                break
    if len(groups) < 8:
        for node in soup.select(
            "button[data-variant], button.variant-option, button.size-option, button.color-option"
        ):
            if id(node) not in seen_ids:
                groups.append(node)
                seen_ids.add(id(node))
                if len(groups) >= 8:
                    break
    # Fallback: discover containers of button / link / div swatches (e.g. YETI, Shopify visual swatches)
    if len(groups) < 8:
        _swatch_button_selectors = (
            "button[class*='swatch' i], button[class*='color-option' i],"
            " button[class*='color-selector' i], button[class*='size-option' i],"
            " button[class*='size-selector' i], button[class*='variant' i],"
            " button[data-option], button[data-value], a[class*='swatch' i],"
            " div[class*='swatch' i], div[role='radio'],"
            " [data-testid*='variants-selector' i]"
        )
        all_btns = soup.select(_swatch_button_selectors)
        # Cap buttons to avoid O(n) blow-up on large rendered pages; variant groups are near top
        btn_slice = all_btns[:20] if len(all_btns) > 20 else all_btns
        if btn_slice:
            # Cache parent sibling counts so we never re-select the same parent
            _parent_swatch_cache: dict[int, list[Any]] = {}
            for btn in btn_slice:
                parent = getattr(btn, "parent", None)
                depth = 0
                while parent is not None and depth < 6:
                    if not hasattr(parent, "select"):
                        parent = getattr(parent, "parent", None)
                        depth += 1
                        continue
                    pid = id(parent)
                    if pid in seen_ids:
                        break
                    tag_name = str(getattr(parent, "name", "") or "").lower()
                    role = (
                        str(parent.get("role") or "").lower()
                        if hasattr(parent, "get")
                        else ""
                    )
                    class_attr = parent.get("class") if hasattr(parent, "get") else None
                    class_probe = (
                        " ".join(str(v) for v in class_attr)
                        if isinstance(class_attr, list)
                        else str(class_attr or "")
                    ).lower()
                    # Fast path: skip non-container tags unless they have explicit swatch hints
                    if tag_name not in {
                        "div",
                        "section",
                        "fieldset",
                        "ul",
                        "ol",
                        "nav",
                        "form",
                        "li",
                    } and not (
                        role == "radiogroup"
                        or any(
                            hint in class_probe
                            for hint in ("swatch", "variant", "color", "size", "option")
                        )
                    ):
                        parent = getattr(parent, "parent", None)
                        depth += 1
                        continue
                    siblings = _parent_swatch_cache.get(pid)
                    if siblings is None:
                        siblings = parent.select(_swatch_button_selectors)
                        _parent_swatch_cache[pid] = siblings
                    if len(siblings) >= 2:
                        if (
                            role == "radiogroup"
                            or tag_name in {"fieldset", "ul", "ol"}
                            or any(
                                hint in class_probe
                                for hint in (
                                    "color",
                                    "size",
                                    "swatch",
                                    "variant",
                                    "option",
                                    *_variant_axis_allowed_single_tokens,
                                )
                            )
                            or resolve_variant_group_name(parent)
                        ) and _variant_group_has_multiple_options(parent):
                            groups.append(parent)
                            seen_ids.add(pid)
                            if len(groups) >= 8:
                                break
                        # Stop walking up for this button once we found a sibling-rich parent
                        break
                    parent = getattr(parent, "parent", None)
                    depth += 1
                if len(groups) >= 8:
                    break
    return groups


def _variant_choice_container_for_input(
    node: Any, *, axis_name: str | None = None
) -> Any | None:
    if axis_name is None:
        axis_name = resolve_variant_group_name(node)
    parent = getattr(node, "parent", None)
    while parent is not None:
        if not hasattr(parent, "select"):
            parent = getattr(parent, "parent", None)
            continue
        if _variant_choice_container_is_overbroad(parent):
            parent = getattr(parent, "parent", None)
            continue
        candidate_inputs = parent.select(
            "input[type='radio'], input[type='checkbox'], button"
        )
        if axis_name:
            matching_inputs = [
                item
                for item in candidate_inputs
                if resolve_variant_group_name(item) == axis_name
            ]
        else:
            matching_inputs = candidate_inputs
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
        inferred_from_values = (
            infer_variant_group_name_from_values(_choice_option_texts(parent))
            if _node_supports_value_only_axis_inference(parent)
            else ""
        )
        if (
            role == "radiogroup"
            or tag_name in {"fieldset", "ul", "ol"}
            or any(
                hint in class_probe
                for hint in (
                    "color",
                    "size",
                    "swatch",
                    "variant",
                    *_variant_axis_allowed_single_tokens,
                )
            )
            or resolve_variant_group_name(parent)
            or inferred_from_values
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
            str(value).strip() for value in raw_values if str(value).strip()
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
        if existing is None or variant_row_richness(variant) > variant_row_richness(
            existing
        ):
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


def variant_identity(variant: dict[str, Any]) -> str | None:
    """Canonical identity for a variant row.

    Priority: ``variant_id`` > ``sku`` > sorted ``option_values`` pairs > ``url``.
    Used by both the JS-state product-merge path and the post-extraction
    record-level dedupe path so two rows are considered the same iff this
    function returns the same string for them.
    """
    if not isinstance(variant, dict):
        return None
    variant_id = text_or_none(variant.get("variant_id"))
    if variant_id:
        return f"id:{variant_id}"
    sku = text_or_none(variant.get("sku"))
    if sku:
        return f"sku:{sku}"
    option_values = variant.get("option_values")
    if isinstance(option_values, dict) and option_values:
        normalized_pairs = sorted(
            (str(axis_name).strip(), text_or_none(axis_value) or "")
            for axis_name, axis_value in option_values.items()
            if str(axis_name).strip() and text_or_none(axis_value)
        )
        if normalized_pairs:
            return "options:" + "|".join(
                f"{axis}={value}" for axis, value in normalized_pairs
            )
    # URL-based identity causes duplicate rows; unidentifiable variants
    # are handled by merge_variant_rows instead.
    return None


def _canonical_variant_axis_value(axis_name: object, value: object) -> str:
    axis_key = normalized_variant_axis_key(axis_name)
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    if axis_key != "size":
        return cleaned
    lowered = cleaned.lower()
    for suffix in _variant_size_alias_suffixes:
        if lowered.endswith(suffix):
            base = clean_text(cleaned[: -len(suffix)])
            if base:
                return base
    return cleaned


def variant_semantic_identity(variant: dict[str, Any]) -> str | None:
    if not isinstance(variant, dict):
        return None
    option_values = variant.get("option_values")
    normalized_pairs: list[tuple[str, str]] = []
    if isinstance(option_values, dict) and option_values:
        normalized_pairs = sorted(
            (
                axis_key,
                canonical_value,
            )
            for axis_name, axis_value in option_values.items()
            if (axis_key := normalized_variant_axis_key(axis_name))
            and (
                canonical_value := _canonical_variant_axis_value(axis_name, axis_value)
            )
        )
    else:
        for axis_name in ("size", "color", *_variant_axis_allowed_single_tokens):
            canonical_value = _canonical_variant_axis_value(
                axis_name, variant.get(axis_name)
            )
            if canonical_value:
                normalized_pairs.append((axis_name, canonical_value))
        normalized_pairs.sort()
    if not normalized_pairs:
        return None
    return "semantic:" + "|".join(
        f"{axis_name}={axis_value}" for axis_name, axis_value in normalized_pairs
    )


def collapse_duplicate_size_aliases(record: dict[str, Any]) -> None:
    canonical_targets = _duplicate_size_alias_targets(record)
    if not canonical_targets:
        return
    variant_axes = record.get("variant_axes")
    if isinstance(variant_axes, dict) and isinstance(variant_axes.get("size"), list):
        rewritten_values = [
            _canonicalize_size_alias(value, canonical_targets=canonical_targets)
            for value in variant_axes["size"]
        ]
        variant_axes["size"] = list(
            dict.fromkeys(value for value in rewritten_values if clean_text(value))
        )
    for row in [record.get("selected_variant"), *list(record.get("variants") or [])]:
        _rewrite_variant_row_size_alias(row, canonical_targets=canonical_targets)


def _duplicate_size_alias_targets(record: dict[str, Any]) -> dict[str, str]:
    seen_values: dict[str, str] = {}
    variant_axes = record.get("variant_axes")
    if isinstance(variant_axes, dict):
        for value in list(variant_axes.get("size") or []):
            cleaned = clean_text(value)
            if cleaned:
                seen_values.setdefault(cleaned.casefold(), cleaned)
    for row in [record.get("selected_variant"), *list(record.get("variants") or [])]:
        if not isinstance(row, dict):
            continue
        for value in (
            row.get("size"),
            row.get("option_values", {}).get("size")
            if isinstance(row.get("option_values"), dict)
            else None,
        ):
            cleaned = clean_text(value)
            if cleaned:
                seen_values.setdefault(cleaned.casefold(), cleaned)
    targets: dict[str, str] = {}
    for lowered, cleaned in seen_values.items():
        base_value = _canonical_variant_axis_value("size", cleaned)
        if not base_value:
            continue
        base_lowered = base_value.casefold()
        if base_lowered in seen_values and base_lowered != lowered:
            targets[lowered] = seen_values[base_lowered]
    return targets


def _canonicalize_size_alias(
    value: object,
    *,
    canonical_targets: dict[str, str],
) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    return canonical_targets.get(cleaned.casefold(), cleaned)


def _rewrite_variant_row_size_alias(
    row: object,
    *,
    canonical_targets: dict[str, str],
) -> None:
    if not isinstance(row, dict):
        return
    canonical_size = _canonicalize_size_alias(
        row.get("size"), canonical_targets=canonical_targets
    )
    if canonical_size:
        row["size"] = canonical_size
    option_values = row.get("option_values")
    if isinstance(option_values, dict):
        option_size = _canonicalize_size_alias(
            option_values.get("size"),
            canonical_targets=canonical_targets,
        )
        if option_size:
            option_values["size"] = option_size


def variant_row_richness(variant: dict[str, Any]) -> tuple[int, int, int]:
    """Compare key for two rows that share an identity.

    Higher is richer. Larger row, more option axes, presence of stock signals.
    """
    populated_fields = sum(
        1 for value in variant.values() if value not in (None, "", [], {})
    )
    option_values = variant.get("option_values")
    option_value_count = len(option_values) if isinstance(option_values, dict) else 0
    has_stock_signal = int(
        variant.get("stock_quantity") not in (None, "", [], {})
        or variant.get("original_price") not in (None, "", [], {})
    )
    return (populated_fields, option_value_count, has_stock_signal)


def merge_variant_pair(
    primary: dict[str, Any],
    secondary: dict[str, Any],
) -> dict[str, Any]:
    """Merge two rows of the same identity. Primary wins; missing fields filled from secondary."""
    merged = dict(primary)
    for field_name, field_value in secondary.items():
        if merged.get(field_name) in (None, "", [], {}) and field_value not in (
            None,
            "",
            [],
            {},
        ):
            merged[field_name] = field_value
    return merged


def merge_variant_rows(*row_lists: Any) -> list[dict[str, Any]]:
    """Merge variant row lists by canonical identity. Richer row wins per identity.

    Two-stage algorithm:
    1) Exact-identity dedupe: rows sharing the same ``variant_identity`` are
       merged via ``merge_variant_pair`` (richer row as primary). Order is
       preserved by first appearance using ``ordered_keys``.
    2) Semantic merge: rows sharing the same ``variant_semantic_identity``
       (e.g. same size+color but different SKU) are merged similarly via
       ``merge_variant_pair`` using ``variant_row_richness`` to pick primary.
       ``emitted_semantic`` prevents duplicates from being emitted twice.

    Rows with no semantic identity are preserved and re-emitted unchanged
    (no stable way to dedupe them).
    """
    merged_by_identity: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    identityless_rows: list[dict[str, Any]] = []
    for rows in row_lists:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            identity = variant_identity(row)
            if not identity:
                identityless_rows.append(dict(row))
                continue
            current = merged_by_identity.get(identity)
            if current is None:
                merged_by_identity[identity] = dict(row)
                ordered_keys.append(identity)
                continue
            primary, secondary = (
                (row, current)
                if variant_row_richness(row) > variant_row_richness(current)
                else (current, row)
            )
            merged_by_identity[identity] = merge_variant_pair(primary, secondary)
    deduped_rows = [merged_by_identity[key] for key in ordered_keys]
    deduped_rows.extend(identityless_rows)
    merged_by_semantic: dict[str, dict[str, Any]] = {}
    for row in deduped_rows:
        semantic_identity = variant_semantic_identity(row)
        if not semantic_identity:
            continue
        current = merged_by_semantic.get(semantic_identity)
        if current is None:
            merged_by_semantic[semantic_identity] = dict(row)
            continue
        primary, secondary = (
            (row, current)
            if variant_row_richness(row) > variant_row_richness(current)
            else (current, row)
        )
        merged_by_semantic[semantic_identity] = merge_variant_pair(primary, secondary)
    merged_rows: list[dict[str, Any]] = []
    emitted_semantic: set[str] = set()
    for row in deduped_rows:
        semantic_identity = variant_semantic_identity(row)
        if not semantic_identity:
            merged_rows.append(row)
            continue
        if semantic_identity in emitted_semantic:
            continue
        merged = merged_by_semantic.get(semantic_identity)
        if merged is None:
            # Defensive: we populated merged_by_semantic on the first pass, so a
            # miss here signals a semantic-identity inconsistency. Preserve the
            # original row rather than silently losing variant data.
            logger.warning(
                "variant merge missed semantic identity %r; preserving original row",
                semantic_identity,
            )
            emitted_semantic.add(semantic_identity)
            merged_rows.append(row)
            continue
        emitted_semantic.add(semantic_identity)
        merged_rows.append(merged)
    return merged_rows
