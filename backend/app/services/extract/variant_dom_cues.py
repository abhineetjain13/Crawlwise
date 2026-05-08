from __future__ import annotations

from typing import Any

from app.services.config.extraction_rules import (
    DETAIL_VARIANT_CONTEXT_NOISE_TOKENS,
    DETAIL_VARIANT_SCOPE_SELECTOR,
    VARIANT_CHOICE_GROUP_SELECTOR,
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH,
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT,
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK,
    VARIANT_SCOPE_MAX_ROOTS,
    VARIANT_SELECT_GROUP_SELECTOR,
)
from app.services.field_value_core import clean_text

variant_context_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(DETAIL_VARIANT_CONTEXT_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_scope_selector = str(DETAIL_VARIANT_SCOPE_SELECTOR or "").strip()


def variant_node_in_noise_context(node: Any) -> bool:
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
        if probe and any(token in probe for token in variant_context_noise_tokens):
            return True
        current = getattr(current, "parent", None)
    return False


def variant_scope_roots(soup: Any) -> list[Any]:
    if not hasattr(soup, "select") or not _variant_scope_selector:
        return [soup]
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
        if id(node) in seen or variant_node_in_noise_context(node):
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


def select_variant_nodes(soup: Any, selector: str) -> list[Any]:
    nodes: list[Any] = []
    seen: set[int] = set()
    for root in variant_scope_roots(soup):
        if not hasattr(root, "select"):
            continue
        for node in root.select(selector):
            if id(node) in seen or variant_node_in_noise_context(node):
                continue
            nodes.append(node)
            seen.add(id(node))
    return nodes
