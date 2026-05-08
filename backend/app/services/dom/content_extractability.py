from __future__ import annotations

from collections.abc import Callable

from bs4 import BeautifulSoup, Tag

from app.services.config.extraction_rules import EXTRACTION_RULES
from app.services.field_policy import (
    exact_requested_field_key,
    normalize_field_key,
    normalize_requested_field,
)
from app.services.field_value_core import (
    clean_text,
    surface_alias_lookup,
    surface_fields,
)


def requested_content_extractability_impl(
    root: BeautifulSoup | Tag,
    *,
    surface: str,
    requested_fields: list[str] | None,
    selector_rules: list[dict[str, object]] | None = None,
    probe_fields: list[str] | tuple[str, ...] | set[str] | None = None,
    extract_heading_sections: Callable[..., dict[str, object]],
    safe_select: Callable[[BeautifulSoup | Tag, str], list[Tag]],
    max_selector_matches: int,
) -> dict[str, object]:
    requested = {
        normalized
        for value in list(requested_fields or [])
        for normalized in (
            exact_requested_field_key(value),
            normalize_requested_field(value),
        )
        if normalized
    }
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    fields = (
        [
            field_name
            for field_name in (
                normalize_field_key(str(value or "")) for value in list(probe_fields or [])
            )
            if field_name
        ]
        if probe_fields is not None
        else surface_fields(surface, requested_fields)
    )
    field_scope = set(fields)
    section_fields = {
        normalized
        for label in extract_heading_sections(
            root,
            alias_lookup=alias_lookup,
            allowed_fields=field_scope,
        ).keys()
        for normalized in (alias_lookup.get(normalize_field_key(label)),)
        if normalized
    }
    dom_patterns_raw = EXTRACTION_RULES.get("dom_patterns")
    dom_patterns = dict(dom_patterns_raw) if isinstance(dom_patterns_raw, dict) else {}
    dom_pattern_fields = {
        field_name
        for field_name in fields
        if (selector := str(dom_patterns.get(field_name) or "").strip())
        and dom_pattern_has_extractable_content(
            safe_select(root, selector),
            max_selector_matches=max_selector_matches,
        )
    }
    selector_backed_fields = {
        normalize_field_key(str(row.get("field_name") or ""))
        for row in list(selector_rules or [])
        if isinstance(row, dict)
        and bool(row.get("is_active", True))
        and normalize_field_key(str(row.get("field_name") or "")) in field_scope
        and (
            str(row.get("css_selector") or "").strip()
            or str(row.get("xpath") or "").strip()
            or str(row.get("regex") or "").strip()
        )
    }
    extractable_fields = section_fields | dom_pattern_fields | selector_backed_fields
    matched_requested_fields = sorted(requested & extractable_fields)
    return {
        "verified": bool(
            matched_requested_fields or (not requested and section_fields)
        ),
        "matched_requested_fields": matched_requested_fields,
        "extractable_fields": sorted(extractable_fields),
        "section_fields": sorted(section_fields),
        "dom_pattern_fields": sorted(dom_pattern_fields),
        "selector_backed_fields": sorted(
            field for field in selector_backed_fields if field
        ),
    }


def dom_pattern_has_extractable_content(
    nodes: list[Tag],
    *,
    max_selector_matches: int,
) -> bool:
    for node in list(nodes or [])[:max_selector_matches]:
        if clean_text(node.get_text(" ", strip=True)):
            return True
        attrs = getattr(node, "attrs", None)
        if not isinstance(attrs, dict):
            continue
        for key in ("content", "value", "src", "href", "alt", "title", "aria-label"):
            if clean_text(attrs.get(key)):
                return True
    return False
