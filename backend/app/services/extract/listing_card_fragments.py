from __future__ import annotations

import logging
from typing import Callable

from selectolax.lexbor import LexborHTMLParser
from selectolax.lexbor import SelectolaxError

from app.services.config.extraction_rules import (
    LISTING_FALLBACK_CONTAINER_SELECTOR,
    LISTING_STRUCTURE_NEGATIVE_HINTS,
    LISTING_STRUCTURE_POSITIVE_HINTS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS
from app.services.field_value_core import PRICE_RE, clean_text

FragmentScoreFn = Callable[[object], int]
logger = logging.getLogger(__name__)


def listing_selector_group(surface: str) -> str:
    return "jobs" if str(surface or "").strip().lower().startswith("job_") else "ecommerce"


def listing_capture_selectors(surface: str) -> list[str]:
    return [
        *list(CARD_SELECTORS.get(listing_selector_group(surface)) or []),
        LISTING_FALLBACK_CONTAINER_SELECTOR,
    ]


def listing_node_text(node) -> str:
    try:
        return clean_text(str(node.text(separator=" ", strip=True) or ""))
    except (AttributeError, TypeError, ValueError):
        return ""


def listing_node_attr(node, name: str) -> str:
    raw_attrs = getattr(node, "attributes", {}) or {}
    attrs = raw_attrs if isinstance(raw_attrs, dict) else {}
    return str(attrs.get(name) or "").strip()


def listing_node_css(node, selector: str) -> list[object]:
    if not selector:
        return []
    try:
        return list(node.css(selector))
    except SelectolaxError:
        logger.warning("Skipping invalid listing selector: %s", selector)
        return []


def base_listing_fragment_score(node) -> int:
    tag_name = str(getattr(node, "tag", "") or "").strip().lower()
    if tag_name in {"header", "nav", "footer"}:
        return -100
    attrs = getattr(node, "attributes", {}) or {}
    signature = " ".join(
        [
            str(attrs.get("class") or ""),
            str(attrs.get("id") or ""),
            str(attrs.get("role") or ""),
            str(attrs.get("aria-label") or ""),
        ]
    ).lower()
    if any(token in signature for token in LISTING_STRUCTURE_NEGATIVE_HINTS):
        return -10
    score = 0
    if any(token in signature for token in LISTING_STRUCTURE_POSITIVE_HINTS):
        score += 6
    try:
        links = node.css("a[href]")
    except Exception:
        return -100
    link_count = len(links)
    if link_count == 0:
        return -100
    if link_count == 1:
        score += 4
    elif link_count <= 6:
        score += 2
    elif link_count <= 12:
        score -= 1
    else:
        score -= 6
    text = clean_text(str(node.text(strip=True) or ""))
    text_len = len(text)
    if text_len < 12:
        score -= 3
    elif text_len <= 2000:
        score += 3
    else:
        score -= 3
    if PRICE_RE.search(text):
        score += 3
    if tag_name in {"article", "li", "tr", "section"}:
        score += 2
    return score


def select_listing_fragment_nodes(
    parser: LexborHTMLParser,
    *,
    surface: str,
    score_node: FragmentScoreFn | None = None,
    limit: int | None = None,
) -> list[object]:
    scored = _scored_listing_fragment_nodes(
        parser,
        surface=surface,
        score_node=score_node,
    )
    if not scored:
        return []
    rows = scored if limit is None else scored[: max(1, int(limit))]
    return [node for _score, _order, node in rows]


def collect_listing_fragment_html(
    parser: LexborHTMLParser,
    *,
    surface: str,
    seen: set[str],
    byte_budget: int,
    score_node: FragmentScoreFn | None = None,
    limit: int | None = None,
) -> list[str]:
    if byte_budget <= 0:
        return []
    scored = _scored_listing_fragment_nodes(
        parser,
        surface=surface,
        score_node=score_node,
    )
    if limit is not None:
        scored = scored[: max(1, int(limit))]
    fragments: list[str] = []
    used_bytes = 0
    for _score, _order, node in scored:
        fragment = str(getattr(node, "html", "") or "").strip()
        if not fragment or fragment in seen:
            continue
        fragment_bytes = len(fragment.encode("utf-8"))
        if used_bytes + fragment_bytes > byte_budget:
            continue
        seen.add(fragment)
        fragments.append(fragment)
        used_bytes += fragment_bytes
    return fragments


def _scored_listing_fragment_nodes(
    parser: LexborHTMLParser,
    *,
    surface: str,
    score_node: FragmentScoreFn | None,
) -> list[tuple[int, int, object]]:
    scorer = score_node or base_listing_fragment_score
    seen: set[str] = set()
    scored: list[tuple[int, int, object]] = []
    order = 0
    fragment_limit = max(1, int(crawler_runtime_settings.listing_fallback_fragment_limit))
    selectors = list(CARD_SELECTORS.get(listing_selector_group(surface)) or [])
    for selector in selectors:
        try:
            matches = parser.css(selector)
        except Exception:
            matches = []
        for node in matches:
            order += 1
            score = int(scorer(node))
            if score <= 0:
                continue
            fragment = str(getattr(node, "html", "") or "").strip()
            if not fragment or fragment in seen:
                continue
            seen.add(fragment)
            scored.append((score, order, node))
    scanned = 0
    for node in parser.css(LISTING_FALLBACK_CONTAINER_SELECTOR):
        scanned += 1
        if scanned > fragment_limit * 40:
            break
        order += 1
        score = int(scorer(node))
        if score <= 0:
            continue
        fragment = str(getattr(node, "html", "") or "").strip()
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        scored.append((score, order, node))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return scored
