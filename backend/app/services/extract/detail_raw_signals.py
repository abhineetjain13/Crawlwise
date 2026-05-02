from __future__ import annotations

from difflib import SequenceMatcher
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    DETAIL_BREADCRUMB_CONTAINER_SELECTORS,
    DETAIL_BREADCRUMB_LABEL_PREFIXES,
    DETAIL_BREADCRUMB_ROOT_LABELS,
    DETAIL_BREADCRUMB_SEPARATOR_LABELS,
    DETAIL_BREADCRUMB_SELECTORS,
    DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO,
    DETAIL_CATEGORY_UI_TOKENS,
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
    current_title: str | None = None,
    page_url: str = "",
) -> str | None:
    labels = breadcrumb_labels_from_dom(soup, current_title=current_title, page_url=page_url)
    return " > ".join(labels) if labels else None


def breadcrumb_labels_from_dom(
    soup: BeautifulSoup,
    *,
    current_title: str | None = None,
    page_url: str = "",
) -> list[str]:
    for selector in DETAIL_BREADCRUMB_SELECTORS:
        nodes = soup.select(str(selector))
        if not nodes:
            continue
        # Group by closest nav, ul, ol, or generic div parent to avoid flattening multiple breadcrumbs
        groups = {}
        for node in nodes:
            parent = node.parent
            while parent and parent.name not in ("nav", "ul", "ol", "div", "section"):
                parent = parent.parent
            if not parent:
                parent = node.parent
            groups.setdefault(id(parent), []).append(node)
        for group_nodes in groups.values():
            labels = _clean_breadcrumb_labels(
                node.get_text(" ", strip=True) for node in group_nodes
            )
            labels = _trim_breadcrumb_labels(labels, current_title=current_title, page_url=page_url)
            if labels:
                return labels
    for selector in DETAIL_BREADCRUMB_CONTAINER_SELECTORS:
        for container in soup.select(str(selector)):
            container_labels = _breadcrumb_labels_from_container(container)
            container_labels = _trim_breadcrumb_labels(container_labels, current_title=current_title, page_url=page_url)
            if container_labels:
                return container_labels
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
    current_title: str | None = None,
    page_url: str = "",
) -> list[str]:
    rows = list(labels)
    if not rows:
        return []

    root_labels = {
        clean_text(label).casefold()
        for label in tuple(DETAIL_BREADCRUMB_ROOT_LABELS or ())
        if clean_text(label)
    }

    def _is_root_label(text: str) -> bool:
        lowered = clean_text(text).casefold()
        if lowered in root_labels:
            return True
        if page_url:
            try:
                host = urlparse(page_url).netloc.casefold()
                if host.startswith("www."):
                    host = host[4:]
                if lowered == host or lowered == host.split(".")[0]:
                    return True
            except ValueError:
                pass
        return False

    if len(rows) > 1 and _is_root_label(rows[-1]) and not _is_root_label(rows[0]):
        rows.reverse()

    category_ui_tokens = {
        clean_text(token).casefold()
        for token in tuple(DETAIL_CATEGORY_UI_TOKENS or ())
        if clean_text(token)
    }
    rows = [
        row
        for row in rows
        if not _is_root_label(row)
        and clean_text(row).casefold() not in category_ui_tokens
    ]
    if not rows:
        return []
    title = clean_text(current_title).casefold()
    if len(rows) >= 1 and title and _breadcrumb_label_matches_title(rows[-1], title):
        rows = rows[:-1]
    return rows


def _breadcrumb_label_matches_title(label: object, title: str) -> bool:
    label_normalized = _breadcrumb_title_key(label)
    title_normalized = _breadcrumb_title_key(title)
    if not label_normalized or not title_normalized:
        return False
    if len(label_normalized) < 8:
        return False
    if label_normalized == title_normalized:
        return True
    return (
        SequenceMatcher(None, label_normalized, title_normalized).ratio()
        >= float(DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO)
    )


def _breadcrumb_title_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_text(value).casefold())


def dedupe_adjacent(values: list[str]) -> list[str]:
    rows: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if cleaned and (not rows or rows[-1].lower() != cleaned.lower()):
            rows.append(cleaned)
    return rows
