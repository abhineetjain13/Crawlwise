from __future__ import annotations

import logging
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.services.config.extraction_rules import EXTRACTION_RULES
from app.services.field_policy import normalize_field_key, normalize_requested_field

from app.services.field_value_candidates import add_candidate
from app.services.field_value_core import (
    IMAGE_FIELDS,
    URL_FIELDS,
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_urls,
    surface_alias_lookup,
    surface_fields,
)

logger = logging.getLogger(__name__)


def safe_select(root: BeautifulSoup | Tag, selector: str) -> list[Tag]:
    if not selector:
        return []
    try:
        return [node for node in root.select(selector) if isinstance(node, Tag)]
    except Exception:
        logger.debug("Invalid selector %s", selector, exc_info=True)
        return []


def extract_node_value(node: Tag, field_name: str, page_url: str) -> object | None:
    if field_name in IMAGE_FIELDS:
        urls = extract_urls(
            node.get("content")
            or node.get("src")
            or node.get("data-src")
            or node.get("data-image")
            or node.get("href")
            or node.get("srcset")
            or "",
            page_url,
        )
        if field_name == "additional_images":
            return urls or None
        return urls[0] if urls else None
    if field_name in URL_FIELDS:
        urls = extract_urls(
            node.get("href") or node.get("content") or node.get("data-apply-url") or "",
            page_url,
        )
        return urls[0] if urls else None
    if node.name == "meta":
        return coerce_field_value(field_name, node.get("content"), page_url)
    for attr_name in ("content", "value", "datetime", "data-value", "data-price", "data-availability"):
        attr_value = node.get(attr_name)
        if attr_value not in (None, "", [], {}):
            return coerce_field_value(field_name, attr_value, page_url)
    return coerce_field_value(field_name, node.get_text(" ", strip=True), page_url)


def extract_selector_values(
    root: BeautifulSoup | Tag,
    selector: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    values: list[object] = []
    for node in safe_select(root, selector)[:12]:
        value = extract_node_value(node, field_name, page_url)
        if value in (None, "", [], {}):
            continue
        values.append(value)
    return values


def extract_page_images(root: BeautifulSoup | Tag, page_url: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for node in root.find_all("img"):
        candidate = absolute_url(
            page_url,
            node.get("src") or node.get("data-src") or node.get("data-original") or "",
        )
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        values.append(candidate)
    return values[:12]


def extract_label_value_pairs(root: BeautifulSoup | Tag) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for tr in root.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = clean_text(cells[0].get_text(" ", strip=True))
        value = clean_text(cells[1].get_text(" ", strip=True))
        if label and value:
            rows.append((label, value))
    for dt in root.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        label = clean_text(dt.get_text(" ", strip=True))
        value = clean_text(dd.get_text(" ", strip=True))
        if label and value:
            rows.append((label, value))
    for node in root.find_all(["li", "p", "div", "span"]):
        text = clean_text(node.get_text(" ", strip=True))
        if ":" not in text:
            continue
        label, value = text.split(":", 1)
        label = clean_text(label)
        value = clean_text(value)
        if not label or not value:
            continue
        if len(label) > 40 or len(value) > 250:
            continue
        rows.append((label, value))
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, value in rows:
        key = (label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, value))
    return deduped


def extract_heading_sections(root: BeautifulSoup | Tag) -> dict[str, str]:
    sections: dict[str, str] = {}
    for heading in root.find_all(["h2", "h3", "h4", "h5", "strong"]):
        heading_text = clean_text(heading.get_text(" ", strip=True))
        if len(heading_text) < 3 or len(heading_text) > 60:
            continue
        values: list[str] = []
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in {"h1", "h2", "h3", "h4", "h5"}:
                break
            text = clean_text(
                sibling.get_text(" ", strip=True) if isinstance(sibling, Tag) else str(sibling)
            )
            if not text:
                continue
            values.append(text)
            if len(values) >= 4 or sum(len(item) for item in values) >= 1000:
                break
        if values:
            sections[heading_text] = " ".join(values)
    return sections


def apply_selector_fallbacks(
    root: BeautifulSoup | Tag,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    candidates: dict[str, list[object]],
    selector_rules: list[dict[str, object]] | None = None,
) -> None:
    fields = surface_fields(surface, requested_fields)
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    for row in list(selector_rules or []):
        if not isinstance(row, dict):
            continue
        field_name = normalize_field_key(str(row.get("field_name") or ""))
        if field_name not in fields or not bool(row.get("is_active", True)):
            continue
        for selector_key in ("css_selector", "xpath", "regex"):
            selector = str(row.get(selector_key) or "").strip()
            if not selector:
                continue
            for value in extract_selector_values(root, selector, field_name, page_url):
                add_candidate(candidates, field_name, value)
    dom_patterns = dict(EXTRACTION_RULES.get("dom_patterns") or {})
    for field_name in fields:
        selector = str(dom_patterns.get(field_name) or "").strip()
        if not selector:
            continue
        for value in extract_selector_values(root, selector, field_name, page_url):
            add_candidate(candidates, field_name, value)
    for label, value in extract_label_value_pairs(root):
        normalized_label = normalize_requested_field(label) or normalize_field_key(label)
        canonical = alias_lookup.get(normalized_label)
        if canonical:
            add_candidate(
                candidates,
                canonical,
                coerce_field_value(canonical, value, page_url),
            )
