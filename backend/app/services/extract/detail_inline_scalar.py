from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import (
    CData,
    Comment,
    Declaration,
    Doctype,
    NavigableString,
    ProcessingInstruction,
    Script,
    Stylesheet,
    Tag,
    TemplateString,
)

from app.services.config.extraction_rules import (
    DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR,
    INLINE_SCALAR_ALLOWED_FIELDS,
    INLINE_SCALAR_LABEL_MAX_LEN,
    INLINE_SCALAR_VALUE_MAX_LEN,
)
from app.services.field_value_core import clean_text

_NON_TEXT_STRING_NODES = (
    CData,
    Comment,
    Declaration,
    Doctype,
    ProcessingInstruction,
    Script,
    Stylesheet,
    TemplateString,
)


def collect_inline_scalar_rows(
    soup: BeautifulSoup,
    alias_lookup: dict[str, str],
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    root = soup.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR) or soup
    for node in root.find_all(["li", "p", "div", "span"]):
        fragments = _direct_text_fragments(node)
        if len(fragments) != 2:
            continue
        label, value = fragments
        if (
            len(label) > int(INLINE_SCALAR_LABEL_MAX_LEN)
            or len(value) > int(INLINE_SCALAR_VALUE_MAX_LEN)
        ):
            continue
        normalized = alias_lookup.get(label.lower()) or alias_lookup.get(
            re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        )
        if normalized not in INLINE_SCALAR_ALLOWED_FIELDS:
            continue
        key = (normalized, value.casefold())
        if key in seen:
            continue
        seen.add(key)
        rows.append((normalized, value))
    return rows


def _direct_text_fragments(node: Tag) -> list[str]:
    fragments: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString) and not isinstance(
            child, _NON_TEXT_STRING_NODES
        ):
            text = clean_text(child)
        elif isinstance(child, Tag):
            text = clean_text(child.get_text(" ", strip=True))
        else:
            text = ""
        if text:
            fragments.append(text)
    return fragments
