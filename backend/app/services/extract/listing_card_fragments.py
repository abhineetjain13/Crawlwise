from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit
from typing import Callable

from selectolax.lexbor import LexborHTMLParser, SelectolaxError

from app.services.config.extraction_rules import (
    LISTING_CHROME_TEXT_LIMIT,
    LISTING_FALLBACK_CONTAINER_SELECTOR,
    LISTING_NON_LISTING_PATH_TOKENS,
    LISTING_STRUCTURE_NEGATIVE_HINTS,
    LISTING_STRUCTURE_POSITIVE_HINTS,
    LISTING_UTILITY_TITLE_TOKENS,
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
    except (SelectolaxError, ValueError):
        logger.warning("Skipping invalid listing selector: %s", selector, exc_info=True)
        return []


def base_listing_fragment_score(node) -> int:
    tag_name = str(getattr(node, "tag", "") or "").strip().lower()
    if tag_name in {"header", "nav", "footer"}:
        return -100
    signature = _listing_node_signature(node)
    has_positive_signature = any(
        token in signature for token in LISTING_STRUCTURE_POSITIVE_HINTS
    )
    if (
        any(token in signature for token in LISTING_STRUCTURE_NEGATIVE_HINTS)
        and not has_positive_signature
    ):
        return -10
    score = 0
    if has_positive_signature:
        score += 6
    links = _node_listing_links(node)
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
    text = listing_node_text(node)
    text_len = len(text)
    if text_len < 12:
        score -= 3
    elif text_len <= 2000:
        score += 3
    else:
        score -= 3
    has_price = bool(PRICE_RE.search(text))
    if has_price:
        score += 3
    if tag_name in {"article", "li", "tr", "section"}:
        score += 2
    # Strong "product card shape" bonus: a node that has a price, at least one
    # image, and one or more anchors is almost certainly a complete card and
    # should out-rank inner sibling subdivs (productInfo / productPricing)
    # that only carry one of the three signals in isolation.
    if has_price and _node_has_listing_media(node):
        score += 4
    return score


def _node_listing_links(node) -> list[object]:
    links = []
    if listing_node_attr(node, "href"):
        links.append(node)
    links.extend(listing_node_css(node, "a[href]"))
    return links


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
        matches = listing_node_css(parser, selector)
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
    for node in listing_node_css(parser, LISTING_FALLBACK_CONTAINER_SELECTOR):
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


_PRICE_HINT_RE = re.compile(
    r"(?:rs\.?|inr|\$|£|€)\s*\d|\b\d[\d,]{2,}\b",
    re.I,
)

def listing_selector_is_weak(selector: str) -> bool:
    normalized = " ".join(str(selector or "").strip().lower().split())
    return normalized == ".product" or any(
        token in normalized
        for token in (
            "[class*='product' i]",
            '[class*="product" i]',
            "[class*='productcard' i]",
            '[class*="productcard" i]',
            "[data-testid*='product' i]",
            '[data-testid*="product" i]',
            "[data-test*='product' i]",
            '[data-test*="product" i]',
            "[data-component*='product' i]",
            '[data-component*="product" i]',
            "[data-automation*='product' i]",
            '[data-automation*="product" i]',
        )
    )


def heuristic_listing_card_count_from_html(html: str, *, surface: str) -> int:
    if not html:
        return 0
    parser = LexborHTMLParser(html)
    seen: set[str] = set()
    count = 0
    nodes = listing_node_css(parser, LISTING_FALLBACK_CONTAINER_SELECTOR)
    for node in nodes:
        fragment = str(getattr(node, "html", "") or "").strip()
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        if base_listing_fragment_score(node) <= 0:
            continue
        if _node_supports_listing_heuristic(node, surface=surface):
            if _node_contains_nested_listing_candidates(node, surface=surface):
                continue
            count += 1
    return count


def _node_supports_listing_heuristic(node, *, surface: str) -> bool:
    if _node_looks_like_listing_chrome(node):
        return False
    signature = _listing_node_signature(node)
    has_positive_signature = any(
        token in signature for token in LISTING_STRUCTURE_POSITIVE_HINTS
    )
    has_price = _node_text_has_price(node)
    has_detail_link = _node_has_detail_like_link(node, surface=surface)
    has_media = _node_has_listing_media(node)
    if has_detail_link:
        return True
    if has_price and (has_positive_signature or has_media):
        return True
    return has_positive_signature and has_media


def _node_looks_like_listing_chrome(node) -> bool:
    signature = _listing_node_signature(node)
    if any(token in signature for token in LISTING_NON_LISTING_PATH_TOKENS):
        return True
    text = listing_node_text(node)[: int(LISTING_CHROME_TEXT_LIMIT)]
    return any(
        token in text
        for token in (
            *LISTING_UTILITY_TITLE_TOKENS,
            "newsletter",
            "whatsapp",
        )
    )


def _node_contains_nested_listing_candidates(node, *, surface: str) -> bool:
    node_fragment = str(getattr(node, "html", "") or "").strip()
    descendants = listing_node_css(node, LISTING_FALLBACK_CONTAINER_SELECTOR)
    for descendant in descendants:
        if str(getattr(descendant, "html", "") or "").strip() == node_fragment:
            continue
        if base_listing_fragment_score(descendant) <= 0:
            continue
        if _node_supports_listing_heuristic(descendant, surface=surface):
            return True
    return False


def _listing_node_signature(node) -> str:
    attrs = getattr(node, "attributes", {}) or {}
    return " ".join(
        [
            str(attrs.get("class") or ""),
            str(attrs.get("id") or ""),
            str(attrs.get("role") or ""),
            str(attrs.get("aria-label") or ""),
        ]
    ).lower()


def _node_text_has_price(node) -> bool:
    return bool(_PRICE_HINT_RE.search(listing_node_text(node)))


def _node_has_listing_media(node) -> bool:
    return bool(listing_node_css(node, "img, picture img, picture source"))


def _node_has_detail_like_link(node, *, surface: str) -> bool:
    href_tokens = (
        ("/job/", "/jobs/", "/viewjob", "showjob=", "/careers/")
        if str(surface or "").strip().lower().startswith("job_")
        else ("/products/", "/product/", "/p/", "/dp/", "/item/")
    )
    anchors = listing_node_css(node, "a[href]")
    for anchor in anchors[:6]:
        attrs = getattr(anchor, "attributes", {}) or {}
        href = str(attrs.get("href") or "").strip().lower()
        if not href or href.startswith(("#", "javascript:")):
            continue
        if _listing_href_is_structural(href):
            continue
        if any(token in href for token in href_tokens):
            return True
    return False


def _listing_href_is_structural(href: str) -> bool:
    try:
        parsed = urlsplit(href)
    except Exception:
        return False
    segments = [
        segment.strip().lower()
        for segment in str(parsed.path or "").split("/")
        if segment.strip()
    ]
    if not segments:
        return False
    tokenized = [
        {
            token
            for token in re.split(r"[\-\.]+", segment)
            if token
        }
        for segment in segments
    ]
    if tokenized[-1] & set(LISTING_NON_LISTING_PATH_TOKENS):
        return True
    leading = tokenized[:-1] if len(tokenized) <= 2 else []
    return any(tokens & set(LISTING_NON_LISTING_PATH_TOKENS) for tokens in leading)
