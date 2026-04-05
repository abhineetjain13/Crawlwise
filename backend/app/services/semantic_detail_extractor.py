from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.services.pipeline_config import (
    DIMENSION_KEYWORDS,
    FEATURE_SECTION_ALIASES,
    REQUESTED_FIELD_ALIASES,
    SECTION_ANCESTOR_STOP_TAGS,
    SECTION_ANCESTOR_STOP_TOKENS,
    SECTION_SKIP_PATTERNS,
    SEMANTIC_AGGREGATE_SEPARATOR,
    SPEC_DROP_LABELS,
    SPEC_LABEL_BLOCK_PATTERNS,
)
from app.services.requested_field_policy import normalize_requested_field

_CANONICAL_TO_ALIASES: dict[str, set[str]] = {}
for canonical, aliases in REQUESTED_FIELD_ALIASES.items():
    canonical_key = normalize_requested_field(canonical)
    alias_set = _CANONICAL_TO_ALIASES.setdefault(canonical_key, set())
    alias_set.add(canonical_key)
    for alias in aliases:
        alias_key = normalize_requested_field(alias)
        if alias_key:
            alias_set.add(alias_key)

_FEATURE_SKIP_PATTERN = re.compile(
    r"\b(?:shop|review(?:s)?|verified reviewer)\b|read the story",
    re.IGNORECASE,
)


def extract_semantic_detail_data(
    html: str,
    *,
    requested_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Extract page-local semantic content from detail pages.

    The result is intentionally compact and is designed to feed the field
    candidate extractor rather than replace it.
    """
    if not html:
        return {"sections": {}, "specifications": {}, "promoted_fields": {}, "coverage": {}, "aggregates": {}, "table_groups": []}

    soup = BeautifulSoup(html, "html.parser")
    sections = _extract_sections(soup)
    table_groups = _extract_table_groups(soup)
    specifications = _extract_specifications(soup, table_groups)
    promoted = _promote_semantic_fields(sections, specifications, requested_fields or [])
    coverage = _build_coverage(requested_fields or [], sections, specifications, promoted)
    aggregates = _build_semantic_aggregates(sections, specifications)
    return {
        "sections": sections,
        "specifications": specifications,
        "promoted_fields": promoted,
        "coverage": coverage,
        "aggregates": aggregates,
        "table_groups": table_groups,
    }


def resolve_requested_field_values(
    requested_fields: list[str] | None,
    *,
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

    for field in requested_fields:
        normalized = normalize_requested_field(field)
        if not normalized:
            continue
        if record.get(normalized) not in (None, "", [], {}):
            continue
        if normalized in promoted_data and promoted_data[normalized] not in (None, "", [], {}):
            resolved[normalized] = promoted_data[normalized]
            continue
        matched = _lookup_semantic_value(normalized, section_data)
        if matched not in (None, "", [], {}):
            resolved[normalized] = matched
            continue
        matched = _lookup_semantic_value(normalized, spec_data)
        if matched not in (None, "", [], {}):
            resolved[normalized] = matched
            continue
        match = _lookup_semantic_value(normalized, promoted_data)
        if match not in (None, "", [], {}):
            resolved[normalized] = match
    return resolved


def _promote_semantic_fields(
    sections: dict[str, str],
    specifications: dict[str, str],
    requested_fields: list[str],
) -> dict[str, str]:
    promoted: dict[str, str] = {}
    for field in requested_fields:
        normalized = normalize_requested_field(field)
        if not normalized:
            continue
        value = _lookup_semantic_value(normalized, sections)
        if value not in (None, "", [], {}):
            promoted[normalized] = value
            continue
        value = _lookup_semantic_value(normalized, specifications)
        if value not in (None, "", [], {}):
            promoted[normalized] = value
    return promoted


def _build_coverage(
    requested_fields: list[str],
    sections: dict[str, str],
    specifications: dict[str, str],
    promoted_fields: dict[str, str],
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
        if _lookup_semantic_value(field, sections) not in (None, "", [], {}):
            found += 1
            continue
        if _lookup_semantic_value(field, specifications) not in (None, "", [], {}):
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
        if re.fullmatch(r"[$€£]\s?\d[\d,.\s]*", normalized_body):
            continue
        if _FEATURE_SKIP_PATTERN.search(lowered_body):
            continue
        inferred.append(normalized_body)
    return inferred


def _extract_sections(soup: BeautifulSoup) -> dict[str, str]:
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
        body = _extract_section_content(node, soup)
        if body and key not in sections:
            sections[key] = body

    for node in soup.find_all(["p", "div"]):
        if not isinstance(node, Tag) or not _is_prominent_section_label_node(node):
            continue
        label = _label_text(node)
        key = normalize_requested_field(label)
        if not key or _is_section_label_blocked(label) or _is_ignored_section_node(node):
            continue
        body = _extract_section_content(node, soup)
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
        if body and key not in sections:
            sections[key] = body

    return sections


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
    if not text or len(text) < 4:
        return None
    if len(text) > 240:
        return None
    if ":" not in text:
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
    if re.fullmatch(r"pack[_-]?\d+", lowered_key):
        return False
    if re.fullmatch(r"\d+(?:[_-]\d+)*", lowered_key):
        return False
    if _DAY_TIME_KEY_RE.fullmatch(lowered_key):
        return False
    # Drop single-character keys and overly long sentence-like labels
    if len(lowered_key) <= 1 or len(lowered_key) > 60:
        return False
    # Drop keys that look like sentences (4+ words with spaces) — these are
    # section headings or review titles, not specification labels
    if lowered_key.count("_") >= 5:
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


def _extract_section_content(node: Tag, soup: BeautifulSoup) -> str:
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
        sibling_body = _collect_labeled_sibling_body(node)
        if sibling_body:
            return sibling_body

    wrapped = _find_wrapped_section_content(node)
    if wrapped:
        return wrapped

    if re.fullmatch(r"h[2-6]", (node.name or "").lower()):
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
    match = re.fullmatch(r"h([1-6])", tag_name.lower())
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


def _collect_labeled_sibling_body(node: Tag) -> str:
    parts: list[str] = []
    sibling = node.find_next_sibling()
    steps = 0
    while isinstance(sibling, Tag) and steps < 20:
        if re.fullmatch(r"h[1-6]", (sibling.name or "").lower()) or sibling.name == "summary":
            break
        if _is_major_section_break(sibling):
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
    if not text or len(text) > 80:
        return False
    if not re.search(r"[a-z]", lowered):
        return False
    if any(token in lowered for token in SECTION_SKIP_PATTERNS):
        return False
    if node.find("a", href=True):
        return False
    if len(text.split()) > 8:
        return False
    has_emphasis = node.find(["b", "strong", "u", "em"]) is not None
    return text.endswith(":") or has_emphasis


def _is_major_section_break(node: Tag) -> bool:
    if not _is_prominent_section_label_node(node):
        return False
    normalized = normalize_requested_field(_label_text(node))
    return bool(normalized and normalized in _CANONICAL_TO_ALIASES)


def _lookup_semantic_value(field: str, source: dict[str, str]) -> str | None:
    if not source:
        return None
    normalized = normalize_requested_field(field)
    if normalized in source and source[normalized] not in (None, "", [], {}):
        return source[normalized]

    aliases = sorted(_CANONICAL_TO_ALIASES.get(normalized, set()), key=len, reverse=True)
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
    if not text or len(text) > 80:
        return False
    if not re.search(r"[a-z]", lowered):
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
