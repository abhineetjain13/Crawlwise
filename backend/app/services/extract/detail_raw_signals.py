from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    DETAIL_BREADCRUMB_ROOT_LABELS,
    DETAIL_BREADCRUMB_SELECTORS,
    DETAIL_GENDER_TERMS,
)
from app.services.field_value_core import clean_text, text_or_none


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


def breadcrumb_category_from_dom(soup: BeautifulSoup) -> str | None:
    return " > ".join(labels) if (labels := breadcrumb_labels_from_dom(soup)) else None


def breadcrumb_labels_from_dom(soup: BeautifulSoup) -> list[str]:
    for selector in DETAIL_BREADCRUMB_SELECTORS:
        labels = dedupe_adjacent([
            text
            for node in soup.select(str(selector))
            if (text := text_or_none(node.get_text(" ", strip=True)))
        ])
        if labels and labels[0].strip().lower() in DETAIL_BREADCRUMB_ROOT_LABELS:
            labels = labels[1:]
        if len(labels) >= 2:
            labels = labels[:-1]
        if labels:
            return labels
    return []


def dedupe_adjacent(values: list[str]) -> list[str]:
    rows: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if cleaned and (not rows or rows[-1].lower() != cleaned.lower()):
            rows.append(cleaned)
    return rows
