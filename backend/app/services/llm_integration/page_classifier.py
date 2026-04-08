from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

from bs4 import BeautifulSoup, Tag
from cachetools import TTLCache

from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.config.extraction_rules import KNOWN_ATS_PLATFORMS
from app.services.extract.source_parsers import extract_json_ld
from app.services.pipeline_config import CARD_SELECTORS_COMMERCE, CARD_SELECTORS_JOBS

logger = logging.getLogger(__name__)


@dataclass
class PageClassification:
    page_type: str
    has_secondary_listing: bool
    wait_selector_hint: str
    reasoning: str
    used_llm: bool
    source: str


_CLASSIFICATION_CACHE: TTLCache[str, PageClassification] = TTLCache(maxsize=512, ttl=300)
_ERROR_TEXT_PATTERNS = (
    re.compile(r"\berror\s*404\b", re.IGNORECASE),
    re.compile(r"\bhttp\s*404\b", re.IGNORECASE),
    re.compile(r"\bpage not found\b", re.IGNORECASE),
    re.compile(r"\berror\s*500\b", re.IGNORECASE),
    re.compile(r"\bhttp\s*500\b", re.IGNORECASE),
    re.compile(r"\bserver error\s*500\b", re.IGNORECASE),
    re.compile(r"\baccess denied\b", re.IGNORECASE),
)
_DETAIL_QUERY_KEYS = frozenset({"id", "product_id", "job_id", "slug", "sku", "item", "item_id", "listing_id"})
_JOB_DETAIL_PATH_RE = re.compile(r"/(?:job|jobs|careers)/[^/?#]*\d", re.IGNORECASE)
_JOB_LISTING_QUERY_KEYS = frozenset({"q", "query", "keywords", "search"})
_COMMERCE_DETAIL_QUERY_KEYS = frozenset({"sku", "product_id", "item", "item_id"})
_COMMERCE_LISTING_QUERY_KEYS = frozenset({"query", "search", "q", "category"})
_LISTING_CARD_CLASS_RE = re.compile(r"(?:product|job|result|listing|item)[-_ ]?(?:card|tile|item)", re.IGNORECASE)
_ADD_TO_CART_RE = re.compile(r"\b(?:add to cart|buy now|add to bag)\b", re.IGNORECASE)
_APPLY_NOW_RE = re.compile(r"\b(?:apply now|submit application)\b", re.IGNORECASE)

_NEXT_DATA_PRODUCT_SIGNALS = (
    '"productId"', '"partNumber"', '"displayName"', '"sku"', '"skuId"', '"price"', '"salePrice"',
    '"listPrice"', '"imageUrl"', '"imageURL"', '"image_url"', '"availability"', '"inStock"',
    '"slug"', '"handle"', '"jobId"', '"jobTitle"', '"companyName"',
)


def _json_ld_listing_count(payload: object, *, _depth: int = 0, _max_depth: int = 3) -> int:
    if _depth > _max_depth:
        return 0
    if isinstance(payload, list):
        return sum(
            _json_ld_listing_count(item, _depth=_depth + 1, _max_depth=_max_depth)
            for item in payload
        )
    if not isinstance(payload, dict):
        return 0

    count = 0
    raw_ld_type = payload.get("@type", "")
    if isinstance(raw_ld_type, str):
        ld_types = {raw_ld_type.lower()}
    elif isinstance(raw_ld_type, (list, tuple, set)):
        ld_types = {
            str(item).lower()
            for item in raw_ld_type
            if isinstance(item, str) and item.strip()
        }
    else:
        ld_types = set()

    if ld_types & {"product", "jobposting"}:
        count += 1
    if "itemlist" in ld_types or "itemListElement" in payload:
        count += len(payload.get("itemListElement", []))

    graph = payload.get("@graph")
    if isinstance(graph, list):
        count += sum(
            _json_ld_listing_count(item, _depth=_depth + 1, _max_depth=_max_depth)
            for item in graph
        )

    main_entity = payload.get("mainEntity")
    if isinstance(main_entity, dict):
        count += _json_ld_listing_count(
            main_entity,
            _depth=_depth + 1,
            _max_depth=_max_depth,
        )

    offers = payload.get("offers")
    if isinstance(offers, dict):
        item_offered = offers.get("itemOffered")
        if isinstance(item_offered, list):
            count += sum(1 for item in item_offered if isinstance(item, dict))

    return count


def _html_has_extractable_listings_from_soup(soup: BeautifulSoup) -> bool:
    product_count = 0
    for node in soup.select("script[type='application/ld+json']"):
        raw = node.string or node.get_text(" ", strip=True) or ""
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        product_count += _json_ld_listing_count(payload)
        if product_count >= 2:
            return True

    next_data_node = soup.select_one("script#__NEXT_DATA__")
    if next_data_node is not None:
        raw_next_data = next_data_node.string or next_data_node.get_text(" ", strip=True) or ""
        signal_hits = sum(raw_next_data.count(key) for key in _NEXT_DATA_PRODUCT_SIGNALS)
        if signal_hits >= 4:
            return True

    return False


def _cache_key(url: str, html: str) -> str:
    return hashlib.sha256(f"{url}\0{html}".encode("utf-8")).hexdigest()


def css_escape(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    escaped: list[str] = []
    for index, char in enumerate(text):
        if char == "\x00":
            escaped.append("\uFFFD")
            continue
        if char.isalnum() or char in {"-", "_"}:
            if index == 0 and char.isdigit():
                escaped.append(f"\\{ord(char):x} ")
            else:
                escaped.append(char)
            continue
        escaped.append(f"\\{ord(char):x} ")
    return "".join(escaped)


def _sanitize_html_snippet_for_prompt(html_text: str) -> str:
    cleaned = re.sub(r"<(script|iframe)\b[^>]*>.*?</\1\s*>", "", str(html_text or ""), flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\son\w+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"ignore\s+previous", lambda match: " ".join(f"`{part}`" for part in match.group(0).split()), cleaned, flags=re.IGNORECASE)
    return cleaned


def _find_repeating_cards(soup: BeautifulSoup) -> tuple[list[Tag], str]:
    best_cards: list[Tag] = []
    best_selector = ""
    for container in soup.select("main, section, ul, ol, div"):
        children = [child for child in container.children if isinstance(child, Tag)]
        if len(children) < 3:
            continue
        grouped: dict[tuple[str, tuple[str, ...]], list[Tag]] = {}
        for child in children:
            key = (child.name, tuple(sorted(child.get("class", []))))
            grouped.setdefault(key, []).append(child)
        for (name, classes), group in grouped.items():
            if len(group) < 3:
                continue
            if sum(1 for item in group[:10] if item.select_one("a[href]")) < 3:
                continue
            if len(group) > len(best_cards):
                best_cards = group
                escaped_name = css_escape(name)
                escaped_classes = ".".join(css_escape(class_name) for class_name in classes if class_name)
                best_selector = f"{escaped_name}.{escaped_classes}" if escaped_classes else escaped_name
    return best_cards, best_selector


def _derive_wait_selector_hint(html: str, hint_surface: str | None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    selectors = CARD_SELECTORS_JOBS if hint_surface == "job_listing" else CARD_SELECTORS_COMMERCE
    for selector in selectors:
        try:
            if len(soup.select(selector)) >= 2:
                return selector
        except (TypeError, ValueError):
            logger.debug("selector %s failed", selector, exc_info=True)
            continue
    cards, selector = _find_repeating_cards(soup)
    return selector if len(cards) >= 2 else ""


def _url_matches_hint(url: str, hint_surface: str | None) -> bool:
    parsed = urlparse(url)
    tokens = "/".join([parsed.path.lower(), parsed.query.lower()])
    listing_hits = sum(token in tokens for token in ("/search", "/category", "page=", "sort=", "filter=", "results"))
    query_keys = {
        str(key or "").strip().lower()
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        if str(key or "").strip()
    }
    detail_hits = sum(token in tokens for token in ("/product", "/products/", "/job", "/jobs/")) + sum(
        1 for key in query_keys if key in _DETAIL_QUERY_KEYS
    )
    if hint_surface in {"ecommerce_listing", "job_listing"}:
        return listing_hits >= 1
    if hint_surface in {"ecommerce_detail", "job_detail"}:
        return detail_hits >= 1
    return False


def _load_cached_classification(url: str, html: str) -> PageClassification | None:
    cached = _CLASSIFICATION_CACHE.get(_cache_key(url, html))
    if cached is None:
        return None
    return PageClassification(**{**cached.__dict__, "source": "cache"})


def _store_cached_classification(url: str, html: str, classification: PageClassification) -> PageClassification:
    _CLASSIFICATION_CACHE[_cache_key(url, html)] = classification
    return classification


def _has_secondary_listing(html: str) -> bool:
    lowered = html.lower()
    return "related products" in lowered or "similar jobs" in lowered or "you may also like" in lowered


def _url_surface(url: str, hint_surface: str | None) -> str | None:
    parsed = urlparse(url)
    path = parsed.path.lower()
    query_keys = {
        str(key or "").strip().lower()
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        if str(key or "").strip()
    }
    host = parsed.netloc.lower()
    host_matches_known_ats = any(
        host == pattern or host.endswith(f".{pattern}") for pattern in KNOWN_ATS_PLATFORMS
    )

    if _JOB_DETAIL_PATH_RE.search(path) or "jobid" in query_keys:
        return "job_detail"
    if any(token in path for token in ("/search-jobs", "/jobs", "/careers")) and (
        any(key in _JOB_LISTING_QUERY_KEYS for key in query_keys) or host_matches_known_ats
    ):
        return "job_listing"
    if any(token in path for token in ("/product/", "/products/", "/p/", "/dp/", "/item/")) or any(
        key in _COMMERCE_DETAIL_QUERY_KEYS for key in query_keys
    ):
        return "ecommerce_detail"
    if any(token in path for token in ("/category/", "/shop/", "/search", "/collections/", "/c/")) or any(
        key in _COMMERCE_LISTING_QUERY_KEYS for key in query_keys
    ):
        return "ecommerce_listing"
    if hint_surface in {"ecommerce_listing", "job_listing", "ecommerce_detail", "job_detail"} and _url_matches_hint(url, hint_surface):
        return hint_surface
    return None


def _json_ld_surface(soup: BeautifulSoup, hint_surface: str | None) -> str | None:
    for payload in extract_json_ld(soup):
        types = payload.get("@type")
        type_values = types if isinstance(types, list) else [types]
        normalized = {str(value or "").strip().lower() for value in type_values if str(value or "").strip()}
        if "product" in normalized:
            return "ecommerce_detail"
        if "jobposting" in normalized:
            return "job_detail"
        if normalized & {"itemlist", "collectionpage", "searchresultspage"}:
            if hint_surface in {"job_listing", "job_detail"}:
                return "job_listing"
            return "ecommerce_listing"
    return None


def _dom_surface(soup: BeautifulSoup, hint_surface: str | None) -> str | None:
    visible_text = " ".join(soup.get_text(" ", strip=True).split())
    if _ADD_TO_CART_RE.search(visible_text):
        return "ecommerce_detail"
    if _APPLY_NOW_RE.search(visible_text):
        return "job_detail"

    listing_markers = 0
    for node in soup.find_all(True):
        classes = " ".join(node.get("class", []))
        if _LISTING_CARD_CLASS_RE.search(classes):
            listing_markers += 1
            if listing_markers > 3:
                return "job_listing" if hint_surface in {"job_listing", "job_detail"} else "ecommerce_listing"

    if _html_has_extractable_listings_from_soup(soup):
        return "job_listing" if hint_surface in {"job_listing", "job_detail"} else "ecommerce_listing"
    return None


def _surface_to_page_type(surface: str | None) -> str:
    if surface == "unknown" or surface is None:
        return "unknown"
    if surface.endswith("_listing"):
        return "listing"
    if surface.endswith("_detail"):
        return "detail"
    return "unknown"


def _classify_by_heuristics(html: str, url: str, hint_surface: str | None) -> PageClassification | None:
    block = detect_blocked_page(html)
    if block.is_blocked and block.provider:
        return PageClassification("challenge", False, "", f"blocked by {block.provider}", False, "deterministic")

    soup = BeautifulSoup(html, "html.parser")
    semantic_error_text = " ".join(
        text.strip()
        for text in (
            soup.title.get_text(" ", strip=True) if soup.title else "",
            soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "",
        )
        if text and text.strip()
    )
    if any(pattern.search(semantic_error_text) for pattern in _ERROR_TEXT_PATTERNS):
        return PageClassification("error", False, "", "page error markers present", False, "deterministic")

    surface = _url_surface(url, hint_surface)
    reasoning = "url decision tree matched"
    if surface is None:
        surface = _json_ld_surface(soup, hint_surface)
        reasoning = "json-ld type matched"
    if surface is None:
        surface = _dom_surface(soup, hint_surface)
        reasoning = "dom action markers matched"
    if surface is None:
        return None

    page_type = _surface_to_page_type(surface)
    return PageClassification(
        page_type,
        _has_secondary_listing(html) if page_type == "detail" else False,
        _derive_wait_selector_hint(html, surface) if page_type == "listing" else "",
        reasoning,
        False,
        "deterministic",
    )


def classify_page(
    *,
    url: str,
    html: str,
    hint_surface: str | None = None,
    content_type: str = "html",
) -> PageClassification:
    cached = _load_cached_classification(url, html)
    if cached is not None:
        return cached
    if content_type == "json":
        return _store_cached_classification(
            url,
            html,
            PageClassification("unknown", False, "", "json content type", False, "deterministic"),
        )
    classification = _classify_by_heuristics(html, url, hint_surface)
    if classification is None:
        classification = PageClassification("unknown", False, "", "deterministic rules inconclusive", False, "deterministic")
    return _store_cached_classification(url, html, classification)
