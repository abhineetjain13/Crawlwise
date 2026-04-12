from __future__ import annotations

import re
from copy import deepcopy
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from app.services.config.extraction_rules import (
    DIMENSION_KEYWORDS,
    FEATURE_SECTION_ALIASES,
    JSONLD_TYPE_NOISE,
    SECTION_ANCESTOR_STOP_TAGS,
    SECTION_ANCESTOR_STOP_TOKENS,
    SECTION_SKIP_PATTERNS,
    SEMANTIC_AGGREGATE_SEPARATOR,
    SPEC_DROP_LABELS,
    SPEC_LABEL_BLOCK_PATTERNS,
)
from app.services.config.field_mappings import REQUESTED_FIELD_ALIASES, get_surface_field_aliases
from app.services.extract.candidate_processing import (
    _DYNAMIC_NUMERIC_FIELD_RE,
    _coerce_scalar_for_dynamic_row,
)
from app.services.extract.noise_policy import (
    SECTION_BODY_SKIP_PHRASES as _SECTION_BODY_SKIP_PHRASES,
    SECTION_KEY_SKIP_PREFIXES as _SECTION_KEY_SKIP_PREFIXES,
    SECTION_LABEL_SKIP_TOKENS as _SECTION_LABEL_SKIP_TOKENS,
    is_noisy_product_attribute_entry,
)
from app.services.extract.field_classifier import _dynamic_field_name_is_valid
from app.services.requested_field_policy import normalize_requested_field
from bs4 import BeautifulSoup, Tag

@lru_cache(maxsize=16)
def _canonical_to_aliases(surface: str) -> dict[str, tuple[str, ...]]:
    alias_map: dict[str, set[str]] = {}
    for source_aliases in (
        get_surface_field_aliases(surface),
        REQUESTED_FIELD_ALIASES,
    ):
        for canonical, aliases in source_aliases.items():
            canonical_key = normalize_requested_field(canonical)
            if not canonical_key:
                continue
            alias_set = alias_map.setdefault(canonical_key, set())
            alias_set.add(canonical_key)
            for alias in aliases:
                alias_key = normalize_requested_field(alias)
                if alias_key:
                    alias_set.add(alias_key)
    return {
        canonical: tuple(sorted(aliases, key=len, reverse=True))
        for canonical, aliases in alias_map.items()
    }

_FEATURE_SKIP_PATTERN = re.compile(
    r"\b(?:shop|review(?:s)?|verified reviewer)\b|read the story",
    re.IGNORECASE,
)
_NON_CONTENT_TAGS = ("script", "style", "svg", "noscript", "iframe", "object", "embed", "meta", "link", "template")
_IMAGE_COUNTER_RE = re.compile(r"^\d+\s+of\s+\d+$", re.IGNORECASE)
_PRICE_ONLY_TEXT_RE = re.compile(r"[$€£]\s?\d[\d,.\s]*", re.IGNORECASE)
_HEADING_TAG_RE = re.compile(r"h[1-6]", re.IGNORECASE)
_HEADING_LEVEL_RE = re.compile(r"h([1-6])", re.IGNORECASE)
_PACK_KEY_RE = re.compile(r"pack[_-]?\d+", re.IGNORECASE)
_NUMERIC_KEY_RE = re.compile(r"\d+(?:[_-]\d+)*")
_HAS_ALPHA_RE = re.compile(r"[a-z]", re.IGNORECASE)


def extract_semantic_detail_data(
    html: str,
    *,
    surface: str = "",
    requested_fields: list[str] | None = None,
    soup: BeautifulSoup | None = None,
    page_url: str = "",
    adapter_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not html and soup is None:
        return {
            "sections": {},
            "specifications": {},
            "promoted_fields": {},
            "coverage": {},
            "aggregates": {},
            "table_groups": [],
            "semantic_rows": {},
        }

    working_soup = deepcopy(soup) if soup is not None else BeautifulSoup(html, "html.parser")
    _strip_non_content_nodes(working_soup)
    working_root = _semantic_content_root(working_soup)
    if working_root is not None and working_root is not working_soup:
        working_soup = BeautifulSoup(str(working_root), "html.parser")
    alias_lookup = _canonical_to_aliases(surface)
    sections = _extract_sections(working_soup, alias_lookup)
    table_groups = _extract_table_groups(working_soup)
    specifications = _extract_specifications(working_soup, table_groups)
    promoted = _promote_semantic_fields(
        sections,
        specifications,
        requested_fields or [],
        alias_lookup=alias_lookup,
    )
    coverage = _build_coverage(
        requested_fields or [],
        sections,
        specifications,
        promoted,
        alias_lookup=alias_lookup,
    )
    aggregates = _build_semantic_aggregates(sections, specifications)
    semantic_rows = _build_semantic_rows(sections, specifications, table_groups, aggregates)
    return {
        "sections": sections,
        "specifications": specifications,
        "promoted_fields": promoted,
        "coverage": coverage,
        "aggregates": aggregates,
        "table_groups": table_groups,
        "semantic_rows": semantic_rows,
        "scope": _semantic_scope(page_url, adapter_records or []),
    }


def _semantic_scope(
    page_url: str,
    adapter_records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "url": _semantic_scope_url(page_url),
        "product_ids": sorted(_semantic_scope_product_ids(page_url, adapter_records)),
    }


def _semantic_scope_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if not parsed.netloc:
        return ""
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/').lower()}"


def _semantic_scope_product_ids(
    page_url: str,
    adapter_records: list[dict[str, Any]],
) -> set[str]:
    identifiers: set[str] = set()
    path_parts = [part for part in urlsplit(str(page_url or "").strip()).path.split("/") if part]
    if path_parts:
        identifiers.add(path_parts[-1].lower())
    for record in adapter_records:
        if not isinstance(record, dict):
            continue
        for key in ("sku", "product_id", "job_id", "variant_id", "id", "handle", "url", "source_url"):
            value = str(record.get(key) or "").strip()
            if not value:
                continue
            if key in {"url", "source_url"}:
                scoped = _semantic_scope_url(value)
                if scoped:
                    identifiers.add(scoped)
                continue
            identifiers.add(value.lower())
    return identifiers


def resolve_requested_field_values(
    requested_fields: list[str] | None,
    *,
    surface: str = "",
    existing_record: dict[str, Any] | None = None,
    sections: dict[str, str] | None = None,
    specifications: dict[str, str] | None = None,
    promoted_fields: dict[str, str] | None = None,
) -> dict[str, str]:
    if not requested_fields:
        return {}

    resolved: dict[str, str] = {}
    record = existing_record or {}
    section_data = sections or {}
    spec_data = specifications or {}
    promoted_data = promoted_fields or {}
    alias_lookup = _canonical_to_aliases(surface)

    for field in requested_fields:
        normalized = normalize_requested_field(field)
        if not normalized:
            continue
        if record.get(normalized) not in (None, "", [], {}):
            continue
        if normalized in promoted_data and promoted_data[normalized] not in (None, "", [], {}):
            resolved[normalized] = promoted_data[normalized]
            continue
        matched = _lookup_semantic_value(normalized, promoted_data, alias_lookup)
        if matched not in (None, "", [], {}):
            resolved[normalized] = matched
            continue
        matched = _lookup_semantic_value(normalized, section_data, alias_lookup)
        if matched not in (None, "", [], {}):
            resolved[normalized] = matched
            continue
        matched = _lookup_semantic_value(normalized, spec_data, alias_lookup)
        if matched not in (None, "", [], {}):
            resolved[normalized] = matched
    return resolved


def _promote_semantic_fields(
    sections: dict[str, str],
    specifications: dict[str, str],
    requested_fields: list[str],
    *,
    alias_lookup: dict[str, tuple[str, ...]],
) -> dict[str, str]:
    promoted: dict[str, str] = {}
    for field in requested_fields:
        normalized = normalize_requested_field(field)
        if not normalized:
            continue
        value = _lookup_semantic_value(normalized, sections, alias_lookup)
        if value not in (None, "", [], {}):
            promoted[normalized] = value
            continue
        value = _lookup_semantic_value(normalized, specifications, alias_lookup)
        if value not in (None, "", [], {}):
            promoted[normalized] = value
    return promoted


def _build_coverage(
    requested_fields: list[str],
    sections: dict[str, str],
    specifications: dict[str, str],
    promoted_fields: dict[str, str],
    *,
    alias_lookup: dict[str, tuple[str, ...]],
) -> dict[str, int]:
    if not requested_fields:
        return {"requested": 0, "found": 0}
    normalized_fields = [normalize_requested_field(field) for field in requested_fields]
    normalized_fields = [field for field in normalized_fields if field]
    found = 0
    for field in normalized_fields:
        if field in promoted_fields and promoted_fields[field] not in (None, "", [], {}):
            found += 1
            continue
        if _lookup_semantic_value(field, sections, alias_lookup) not in (None, "", [], {}):
            found += 1
            continue
        if _lookup_semantic_value(field, specifications, alias_lookup) not in (None, "", [], {}):
            found += 1
    return {"requested": len(normalized_fields), "found": found}


def _build_semantic_aggregates(
    sections: dict[str, str],
    specifications: dict[str, str],
) -> dict[str, str]:
    aggregates: dict[str, str] = {}
    spec_lines = [f"{label}: {value}" for label, value in specifications.items() if label and value]
    if spec_lines:
        aggregates["specifications"] = SEMANTIC_AGGREGATE_SEPARATOR.join(spec_lines)
    dimension_lines = [
        f"{label}: {value}"
        for label, value in specifications.items()
        if label and value and any(token in label.lower() for token in DIMENSION_KEYWORDS)
    ]
    if dimension_lines:
        aggregates["dimensions"] = SEMANTIC_AGGREGATE_SEPARATOR.join(dimension_lines)
    feature_values = _collect_feature_values(sections)
    if feature_values:
        aggregates["features"] = SEMANTIC_AGGREGATE_SEPARATOR.join(feature_values)
    return aggregates


def _build_semantic_rows(
    sections: dict[str, str],
    specifications: dict[str, str],
    table_groups: list[dict[str, Any]],
    aggregates: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    product_attributes: dict[str, object] = {}

    def append_row(
        field_name: str,
        value: object,
        *,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        coerced = _coerce_scalar_for_dynamic_row(value)
        if coerced is None:
            return
        row = {"value": coerced, "source": source}
        if metadata:
            row.update(metadata)
        rows.setdefault(field_name, []).append(row)

    for field_name, value in sections.items():
        normalized = normalize_requested_field(field_name)
        if not normalized or value in (None, "", [], {}):
            continue
        coerced = _coerce_scalar_for_dynamic_row(value)
        if coerced is None:
            continue
        if normalized in {"description", "summary", "overview"}:
            append_row("description", coerced, source="semantic_section")
            continue
        if normalized in FEATURE_SECTION_ALIASES:
            append_row("features", coerced, source="semantic_section")
            continue
        if normalized in {"materials", "material_composition", "fabric", "composition"}:
            append_row("materials", coerced, source="semantic_section")
        if not is_noisy_product_attribute_entry(normalized, coerced):
            product_attributes.setdefault(normalized, coerced)

    for field_name, value in specifications.items():
        normalized = normalize_requested_field(field_name)
        if (
            not normalized
            or value in (None, "", [], {})
            or _DYNAMIC_NUMERIC_FIELD_RE.fullmatch(normalized)
            or normalized in JSONLD_TYPE_NOISE
            or not _dynamic_field_name_is_valid(normalized)
        ):
            continue
        coerced = _coerce_scalar_for_dynamic_row(value)
        if coerced is None:
            continue
        append_row(normalized, coerced, source="semantic_spec")
        if not is_noisy_product_attribute_entry(normalized, coerced):
            product_attributes.setdefault(normalized, coerced)

    for group in table_groups:
        if not isinstance(group, dict):
            continue
        group_label = _clean_text(group.get("title")) or _clean_text(group.get("caption"))
        for row in group.get("rows") or []:
            if not isinstance(row, dict):
                continue
            normalized = normalize_requested_field(
                row.get("normalized_key") or row.get("label")
            )
            display_label = _clean_text(row.get("label")) or normalized
            value = row.get("value")
            if (
                not normalized
                or value in (None, "", [], {})
                or _DYNAMIC_NUMERIC_FIELD_RE.fullmatch(normalized)
                or not _dynamic_field_name_is_valid(normalized)
            ):
                continue
            coerced = _coerce_scalar_for_dynamic_row(value)
            if coerced is None:
                continue
            target_fields = [normalized]
            if normalized == "dimensions" and display_label.casefold() == "size":
                target_fields.append("size")
            metadata = {
                "display_label": display_label,
                "group_label": group_label or None,
                "href": _clean_text(row.get("href")) or None,
                "preserve_visible": bool(row.get("preserve_visible")),
                "row_index": row.get("row_index"),
                "table_index": group.get("table_index"),
            }
            for target_field in target_fields:
                append_row(
                    target_field,
                    coerced,
                    source="semantic_spec",
                    metadata=metadata,
                )

    spec_entry_count = len(specifications)
    for aggregate_field in ("specifications", "dimensions"):
        value = aggregates.get(aggregate_field)
        if value in (None, "", [], {}) or spec_entry_count < 2:
            continue
        coerced_agg = _coerce_scalar_for_dynamic_row(value)
        if coerced_agg is not None:
            append_row(aggregate_field, coerced_agg, source="semantic_spec")

    feature_value = aggregates.get("features")
    if feature_value not in (None, "", [], {}):
        coerced_features = _coerce_scalar_for_dynamic_row(feature_value)
        if coerced_features is not None:
            append_row("features", coerced_features, source="semantic_section")

    if product_attributes:
        rows.setdefault("product_attributes", []).append(
            {"value": product_attributes, "source": "semantic_spec"}
        )
    return rows


def _collect_feature_values(sections: dict[str, str]) -> list[str]:
    feature_values = [
        body
        for key, body in sections.items()
        if key in FEATURE_SECTION_ALIASES and body not in (None, "", [], {})
    ]
    if feature_values:
        return feature_values

    inferred: list[str] = []
    for key, body in sections.items():
        if body in (None, "", [], {}):
            continue
        normalized_key = normalize_requested_field(key)
        normalized_body = _clean_text(body)
        lowered_body = normalized_body.lower()
        if normalized_key in {"description", "summary", "specifications", "dimensions", "materials", "care"}:
            continue
        if len(normalized_body) < 24 or len(normalized_body) > 280:
            continue
        if _PRICE_ONLY_TEXT_RE.fullmatch(normalized_body):
            continue
        if _FEATURE_SKIP_PATTERN.search(lowered_body):
            continue
        inferred.append(normalized_body)
    return inferred


def _extract_sections(
    soup: BeautifulSoup,
    alias_lookup: dict[str, tuple[str, ...]],
) -> dict[str, str]:
    sections: dict[str, str] = {}

    selectors = [
        "summary",
        "details > summary",
        "button[aria-controls]",
        "[role='button'][aria-controls]",
        "[role='tab'][aria-controls]",
        "[data-accordion-heading]",
        "[data-tab-heading]",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    ]
    for node in soup.select(",".join(selectors)):
        if not isinstance(node, Tag):
            continue
        label = _label_text(node)
        key = normalize_requested_field(label)
        if not key or not _is_section_label(label) or _is_section_label_blocked(label) or _is_ignored_section_node(node):
            continue
        body = _extract_section_content(node, soup, alias_lookup)
        if _should_skip_section(key, label, body):
            continue
        if body and key not in sections:
            sections[key] = body

    for node in soup.find_all(["p", "div"]):
        if not isinstance(node, Tag) or not _is_prominent_section_label_node(node):
            continue
        label = _label_text(node)
        key = normalize_requested_field(label)
        if not key or _is_section_label_blocked(label) or _is_ignored_section_node(node):
            continue
        body = _extract_section_content(node, soup, alias_lookup)
        if _should_skip_section(key, label, body):
            continue
        if body and key not in sections:
            sections[key] = body

    for details in soup.find_all("details"):
        summary = details.find("summary")
        if not summary:
            continue
        label = _clean_text(summary.get_text(" ", strip=True))
        key = normalize_requested_field(label)
        if not key or _is_section_label_blocked(label):
            continue
        body_parts = []
        for child in details.children:
            if child is summary:
                continue
            if isinstance(child, Tag):
                text = _clean_text(child.get_text(" ", strip=True))
                if text:
                    body_parts.append(text)
        body = " ".join(body_parts).strip()
        if _should_skip_section(key, label, body):
            continue
        if body and key not in sections:
            sections[key] = body

    return sections


def _strip_non_content_nodes(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(_NON_CONTENT_TAGS):
        tag.decompose()


def _semantic_content_root(soup: BeautifulSoup) -> Tag | BeautifulSoup | None:
    h1 = soup.find("h1")
    if not isinstance(h1, Tag):
        return soup.find("main") or soup.find("article") or soup
    for ancestor in h1.parents:
        if not isinstance(ancestor, Tag):
            continue
        if ancestor.name not in {"section", "article", "main", "div"}:
            continue
        text = _clean_text(ancestor.get_text(" ", strip=True))
        if 120 <= len(text) <= 20000:
            return ancestor
    return soup.find("main") or soup.find("article") or soup


def _should_skip_section(key: str, label: str, body: str) -> bool:
    normalized_key = normalize_requested_field(key)
    lowered_label = _clean_text(label).lower()
    lowered_body = _clean_text(body).lower()
    if not lowered_body:
        return True
    if normalized_key and any(
        normalized_key == prefix or normalized_key.startswith(prefix)
        for prefix in _SECTION_KEY_SKIP_PREFIXES
    ):
        return True
    if any(token in lowered_label for token in _SECTION_LABEL_SKIP_TOKENS):
        return True
    if any(phrase in lowered_body for phrase in _SECTION_BODY_SKIP_PHRASES):
        return True
    if _IMAGE_COUNTER_RE.fullmatch(lowered_body):
        return True
    return False


def _extract_specifications(soup: BeautifulSoup, table_groups: list[dict]) -> dict[str, str]:
    specs: dict[str, str] = {}

    for dl in soup.find_all("dl"):
        if _is_ignored_section_node(dl):
            continue
        terms = dl.find_all("dt")
        for dt in terms:
            label = _clean_text(dt.get_text(" ", strip=True))
            dd = dt.find_next_sibling("dd")
            if not dd:
                continue
            value = _clean_text(dd.get_text(" ", strip=True))
            _store_specification(specs, label, value)

    for group in table_groups:
        for row in group.get("rows") or []:
            label = _clean_text(row.get("label"))
            value = _clean_text(row.get("value"))
            _store_specification(specs, label, value, preserve_visible=bool(row.get("preserve_visible")))

    for node in soup.select("[data-label], [data-spec], [data-specification]"):
        label = _clean_text(node.get("data-label") or node.get("data-spec") or node.get("data-specification"))
        if not label:
            continue
        value = _clean_text(node.get_text(" ", strip=True))
        _store_specification(specs, label, value)

    for node in soup.find_all(["li", "p", "div"]):
        if not isinstance(node, Tag) or _is_ignored_section_node(node):
            continue
        pair = _extract_inline_spec_pair(node)
        if pair is None:
            continue
        label, value = pair
        _store_specification(specs, label, value)

    return specs


def _extract_table_groups(soup: BeautifulSoup) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.find_all("table"), start=1):
        if _is_ignored_section_node(table):
            continue
        rows = table.find_all("tr")
        if not rows:
            continue
        section_title = _nearest_table_heading(table)
        caption = _clean_text(table.find("caption").get_text(" ", strip=True)) if table.find("caption") else ""
        header_cells: list[str] = []
        group_rows: list[dict[str, Any]] = []

        for row_index, row in enumerate(rows, start=1):
            cells = row.find_all(["th", "td"], recursive=False)
            if len(cells) < 2:
                continue
            cell_values = [_table_cell_payload(cell) for cell in cells]
            if not any(cell.get("text") for cell in cell_values):
                continue
            if not header_cells and all(cell.name == "th" for cell in cells):
                header_cells = [_clean_text(cell.get("text")) for cell in cell_values]
                continue

            label = _clean_text(cell_values[0].get("text"))
            value_cell = cell_values[1]
            value = _clean_text(value_cell.get("text"))
            if not label:
                continue
            normalized_key = normalize_requested_field(label)
            group_rows.append({
                "row_index": row_index,
                "label": label,
                "normalized_key": normalized_key,
                "value": value,
                "href": value_cell.get("href"),
                "cells": cell_values,
                "preserve_visible": value in {"-", "—", "–"},
            })

        if group_rows:
            groups.append({
                "table_index": table_index,
                "title": section_title or caption or None,
                "caption": caption or None,
                "headers": header_cells or None,
                "rows": group_rows,
            })
    return groups


def _extract_inline_spec_pair(node: Tag) -> tuple[str, str] | None:
    text = _clean_text(node.get_text(" ", strip=True))
    if not text or len(text) < 4 or len(text) > 240 or ":" not in text:
        return None
    label, value = [_clean_text(part) for part in text.split(":", 1)]
    if not label or not value:
        return None
    if len(label) > 80 or len(value) > 180:
        return None
    if label.lower() in {"details", "description", "features", "specifications", "tech specs"}:
        return None
    if any(token in label.lower() for token in SECTION_SKIP_PATTERNS):
        return None
    return label, value


def _store_specification(specs: dict[str, str], label: str, value: str, *, preserve_visible: bool = False) -> None:
    key = normalize_requested_field(label)
    if not key or key in specs:
        return
    if not _should_keep_specification(key, value, preserve_visible=preserve_visible):
        return
    specs[key] = value


_DAY_TIME_KEY_RE = re.compile(
    r"^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:[_\-]\d{1,2})?$",
    re.IGNORECASE,
)


def _should_keep_specification(key: str, value: str, *, preserve_visible: bool = False) -> bool:
    lowered_key = key.lower()
    lowered_value = value.lower()
    if not lowered_key or (not value and not preserve_visible):
        return False
    if lowered_key in SPEC_DROP_LABELS:
        return False
    if _PACK_KEY_RE.fullmatch(lowered_key) or _NUMERIC_KEY_RE.fullmatch(lowered_key) or _DAY_TIME_KEY_RE.fullmatch(lowered_key):
        return False
    if len(lowered_key) <= 1 or len(lowered_key) > 60 or lowered_key.count("_") >= 5:
        return False
    if any(token in lowered_key for token in SPEC_LABEL_BLOCK_PATTERNS):
        return False
    if any(token in lowered_value for token in SECTION_SKIP_PATTERNS):
        return False
    return True


def _table_cell_payload(cell: Tag) -> dict[str, str | None]:
    text = _clean_text(cell.get_text(" ", strip=True))
    link = cell.find("a", href=True)
    href = ""
    if isinstance(link, Tag):
        href = _clean_text(link.get("href"))
    return {
        "text": text or None,
        "href": href or None,
    }


def _nearest_table_heading(table: Tag) -> str:
    for sibling in table.previous_siblings:
        if not isinstance(sibling, Tag):
            continue
        heading = _heading_text_from_node(sibling)
        if heading:
            return heading
        nested_headings = sibling.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        for node in reversed(nested_headings):
            heading = _clean_text(node.get_text(" ", strip=True))
            if heading:
                return heading
    parent = table.parent if isinstance(table.parent, Tag) else None
    steps = 0
    while isinstance(parent, Tag) and steps < 4:
        for sibling in parent.previous_siblings:
            if not isinstance(sibling, Tag):
                continue
            heading = _heading_text_from_node(sibling)
            if heading:
                return heading
        parent = parent.parent if isinstance(parent.parent, Tag) else None
        steps += 1
    return ""


def _heading_text_from_node(node: Tag) -> str:
    if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return _clean_text(node.get_text(" ", strip=True))
    return ""


def _collect_section_body(heading: Tag) -> str:
    parts: list[str] = []
    heading_level = _heading_level(heading.name or "")
    parent = heading.parent
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag):
            sibling_level = _heading_level(sibling.name or "")
            if sibling_level and sibling_level <= heading_level:
                break
            text = _clean_text(sibling.get_text(" ", strip=True))
            if text:
                parts.append(text)
    if parts:
        return " ".join(parts).strip()
    if parent and isinstance(parent, Tag):
        text = _clean_text(parent.get_text(" ", strip=True))
        if text and len(text) > len(_clean_text(heading.get_text(" ", strip=True))):
            return text
    return ""


def _extract_section_content(
    node: Tag,
    soup: BeautifulSoup,
    alias_lookup: dict[str, tuple[str, ...]],
) -> str:
    target_id = _clean_text(node.get("aria-controls"))
    if target_id:
        target = soup.find(id=target_id)
        if isinstance(target, Tag) and not _is_ignored_section_node(target):
            return _section_text(target, label=_label_text(node))

    if node.name == "summary":
        parent = node.parent if isinstance(node.parent, Tag) else None
        if isinstance(parent, Tag) and parent.name == "details":
            return _section_text(parent, label=_label_text(node))

    if _is_prominent_section_label_node(node):
        sibling_body = _collect_labeled_sibling_body(node, alias_lookup)
        if sibling_body:
            return sibling_body

    wrapped = _find_wrapped_section_content(node)
    if wrapped:
        return wrapped

    node_name = str(node.name or "")
    if _HEADING_TAG_RE.fullmatch(node_name) and node_name.lower() != "h1":
        return _collect_section_body(node)

    sibling = node.find_next_sibling()
    collected: list[str] = []
    steps = 0
    while isinstance(sibling, Tag) and steps < 4:
        if sibling.name in {"h1", "h2", "h3", "h4", "h5", "h6", "summary"}:
            break
        if not _is_ignored_section_node(sibling):
            text = _clean_text(sibling.get_text(" ", strip=True))
            if text:
                collected.append(text)
                break
        sibling = sibling.find_next_sibling()
        steps += 1
    return _clean_text(" ".join(collected))


def _heading_level(tag_name: str) -> int:
    match = _HEADING_LEVEL_RE.fullmatch(str(tag_name or ""))
    return int(match.group(1)) if match else 0


def _find_wrapped_section_content(node: Tag) -> str:
    label = _label_text(node)
    container = node
    steps = 0
    while isinstance(container, Tag) and steps < 4:
        for selector in (
            "[data-accordion-content]",
            "[data-content]",
            "[data-tab-content]",
            ".accordion__answer",
            ".tabs__content",
            ".tab-content",
            ".panel",
        ):
            target = container.select_one(selector)
            if isinstance(target, Tag) and not _is_ignored_section_node(target):
                text = _section_text(target, label=label)
                if len(text) >= 12:
                    return text
        container = container.parent if isinstance(container.parent, Tag) else None
        steps += 1
    return ""


def _collect_labeled_sibling_body(
    node: Tag,
    alias_lookup: dict[str, tuple[str, ...]],
) -> str:
    parts: list[str] = []
    sibling = node.find_next_sibling()
    steps = 0
    while isinstance(sibling, Tag) and steps < 20:
        sibling_name = str(sibling.name or "")
        if _HEADING_TAG_RE.fullmatch(sibling_name) or sibling_name.lower() == "summary":
            break
        if _is_major_section_break(sibling, alias_lookup):
            break
        if not _is_ignored_section_node(sibling):
            text = _clean_text(sibling.get_text(" ", strip=True))
            if text:
                parts.append(text)
        sibling = sibling.find_next_sibling()
        steps += 1
    return _clean_text(" ".join(parts))


def _section_text(node: Tag, *, label: str) -> str:
    text = _clean_text(node.get_text(" ", strip=True))
    lowered_label = _clean_text(label).lower()
    if lowered_label and text.lower().startswith(lowered_label):
        text = _clean_text(text[len(lowered_label):])
    return text


def _is_prominent_section_label_node(node: Tag) -> bool:
    text = _clean_text(node.get_text(" ", strip=True))
    lowered = text.lower()
    if not text or len(text) > 80 or not _HAS_ALPHA_RE.search(lowered):
        return False
    if any(token in lowered for token in SECTION_SKIP_PATTERNS):
        return False
    if node.find("a", href=True) or len(text.split()) > 8:
        return False
    has_emphasis = node.find(["b", "strong", "u", "em"]) is not None
    return text.endswith(":") or has_emphasis


def _is_major_section_break(
    node: Tag,
    alias_lookup: dict[str, tuple[str, ...]],
) -> bool:
    if not _is_prominent_section_label_node(node):
        return False
    normalized = normalize_requested_field(_label_text(node))
    return bool(normalized and normalized in alias_lookup)


def _lookup_semantic_value(
    field: str,
    source: dict[str, str],
    alias_lookup: dict[str, tuple[str, ...]],
) -> str | None:
    if not source:
        return None
    normalized = normalize_requested_field(field)
    if normalized in source and source[normalized] not in (None, "", [], {}):
        return source[normalized]

    aliases = alias_lookup.get(normalized, ())
    for alias in aliases:
        if alias in source and source[alias] not in (None, "", [], {}):
            return source[alias]

    for key, value in source.items():
        if value in (None, "", [], {}):
            continue
        normalized_key = normalize_requested_field(key)
        if not normalized_key:
            continue
        for alias in aliases:
            if normalized_key == alias:
                return value
            if (
                normalized_key.startswith(f"{alias}_")
                or normalized_key.endswith(f"_{alias}")
                or f"_{alias}_" in normalized_key
            ):
                return value
    return None


def _is_section_label_blocked(text: str) -> bool:
    lowered = text.lower()
    return not lowered or any(token in lowered for token in SECTION_SKIP_PATTERNS)


def _label_text(node: Tag) -> str:
    for attr in ("aria-label", "title"):
        value = _clean_text(node.get(attr))
        if value:
            return value
    return _clean_text(node.get_text(" ", strip=True))


def _is_section_label(text: str) -> bool:
    lowered = text.lower()
    if not text or len(text) > 80 or not _HAS_ALPHA_RE.search(lowered):
        return False
    if any(token in lowered for token in SECTION_SKIP_PATTERNS):
        return False
    return True


def _is_ignored_section_node(node: Tag) -> bool:
    current: Tag | None = node
    steps = 0
    while isinstance(current, Tag) and steps < 8:
        if current.name in SECTION_ANCESTOR_STOP_TAGS:
            return True
        attrs = " ".join(
            filter(
                None,
                [
                    current.get("id"),
                    " ".join(current.get("class", [])) if isinstance(current.get("class"), list) else str(current.get("class") or ""),
                    current.get("role"),
                ],
            ),
        ).lower()
        if any(token in attrs for token in SECTION_ANCESTOR_STOP_TOKENS):
            return True
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
        steps += 1
    return False


def _clean_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()
