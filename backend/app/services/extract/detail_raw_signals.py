from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    DETAIL_BREADCRUMB_CONTAINER_SELECTORS,
    DETAIL_BREADCRUMB_LABEL_PREFIXES,
    DETAIL_BREADCRUMB_ROOT_LABELS,
    DETAIL_BREADCRUMB_SEPARATOR_LABELS,
    DETAIL_BREADCRUMB_SELECTORS,
    DETAIL_GENDER_TERMS,
)
from app.services.field_value_core import clean_text


def gender_from_text(value: object) -> str | None:
    text = clean_text(value).lower().replace("-", " ")
    if not text:
        return None
    padded = f" {text} "
    matches = [
        str(canonical)
        for canonical, terms in DETAIL_GENDER_TERMS.items()
        if any(f" {str(term).lower().replace('-', ' ')} " in padded for term in terms)
    ]
    return matches[0] if len(set(matches)) == 1 else None


def gender_from_detail_context(*values: object) -> str | None:
    return gender_from_text(" ".join(str(value or "") for value in values))


def breadcrumb_category_from_dom(
    soup: BeautifulSoup,
    *,
    current_title: object = None,
    page_url: str = "",
) -> str | None:
    labels = breadcrumb_labels_from_dom(soup, current_title=current_title, page_url=page_url)
    return " > ".join(labels) if labels else None


def breadcrumb_labels_from_dom(
    soup: BeautifulSoup,
    *,
    current_title: object = None,
    page_url: str = "",
) -> list[str]:
    for selector in DETAIL_BREADCRUMB_SELECTORS:
        labels = _clean_breadcrumb_labels(
            node.get_text(" ", strip=True) for node in soup.select(str(selector))
        )
        labels = _trim_breadcrumb_labels(labels, current_title=current_title, page_url=page_url)
        if labels:
            return labels
    for selector in DETAIL_BREADCRUMB_CONTAINER_SELECTORS:
        for container in soup.select(str(selector)):
            labels = _breadcrumb_labels_from_container(container)
            labels = _trim_breadcrumb_labels(labels, current_title=current_title, page_url=page_url)
        if labels:
            return labels
    return []


def _breadcrumb_labels_from_container(container) -> list[str]:
    item_nodes = container.select("li")
    if not item_nodes:
        item_nodes = container.select("a, [aria-current], span, p")
    labels = _clean_breadcrumb_labels(
        node.get_text(" ", strip=True) for node in item_nodes
    )
    if labels:
        return labels
    return _clean_breadcrumb_labels(str(container.get_text(" ", strip=True)).split(">"))


def _clean_breadcrumb_labels(values) -> list[str]:
    return dedupe_adjacent(
        [cleaned for value in values if (cleaned := _clean_breadcrumb_label(value))]
    )


def _clean_breadcrumb_label(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    strip_chars = "".join(DETAIL_BREADCRUMB_SEPARATOR_LABELS) + " \t\n\r"
    text = clean_text(text.strip(strip_chars))
    if not text:
        return ""
    lowered = text.casefold()
    for prefix in tuple(DETAIL_BREADCRUMB_LABEL_PREFIXES or ()):
        if lowered.startswith(str(prefix).casefold()):
            text = clean_text(text[len(str(prefix)) :])
            break
    return text


def _trim_breadcrumb_labels(
    labels: list[str],
    *,
    current_title: object = None,
    page_url: str = "",
) -> list[str]:
    rows = list(labels)
    if not rows:
        return []
    
    first_lower = rows[0].strip().lower()
    is_root = first_lower in DETAIL_BREADCRUMB_ROOT_LABELS
    if not is_root and page_url:
        try:
            from urllib.parse import urlparse
            host = urlparse(page_url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            if first_lower == host or first_lower == host.split(".")[0]:
                is_root = True
        except Exception:
            pass

    if is_root:
        rows = rows[1:]
    title = clean_text(current_title).casefold()
    if len(rows) >= 2 and title and clean_text(rows[-1]).casefold() == title:
        rows = rows[:-1]
    return rows


def dedupe_adjacent(values: list[str]) -> list[str]:
    rows: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if cleaned and (not rows or rows[-1].lower() != cleaned.lower()):
            rows.append(cleaned)
    return rows
