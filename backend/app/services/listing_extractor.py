from __future__ import annotations

import logging
from typing import Any

from bs4 import BeautifulSoup, Tag
from selectolax.lexbor import LexborHTMLParser

from app.services.config.extraction_rules import (
    EXTRACTION_RULES,
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_DETAIL_PATH_MARKERS,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_WEAK_TITLES,
    NOISE_CONTAINER_REMOVAL_SELECTOR,
)
from app.services.config.selectors import CARD_SELECTORS
from app.services.field_policy import normalize_requested_field
from app.services.field_value_utils import (
    JOB_URL_HINTS,
    PRICE_RE,
    PRODUCT_URL_HINTS,
    RATING_RE,
    REVIEW_COUNT_RE,
    absolute_url,
    add_candidate,
    apply_selector_fallbacks,
    clean_text,
    coerce_field_value,
    coerce_text,
    collect_structured_candidates,
    extract_page_images,
    extract_label_value_pairs,
    finalize_candidate_value,
    finalize_record,
    safe_select,
    same_host,
    surface_alias_lookup,
    surface_fields,
)
from app.services.structured_sources import (
    harvest_js_state_objects,
    parse_embedded_json,
    parse_json_ld,
    parse_microdata,
    parse_opengraph,
)
from app.services.pipeline.pipeline_config import LISTING_FALLBACK_FRAGMENT_LIMIT

logger = logging.getLogger(__name__)


def _prepare_listing_dom(html: str) -> tuple[LexborHTMLParser, str]:
    parser = LexborHTMLParser(html)
    try:
        for node in parser.css(NOISE_CONTAINER_REMOVAL_SELECTOR):
            node.decompose()
    except Exception:
        logger.debug("listing_noise_removal_failed", exc_info=True)
    return parser, parser.html


def _structured_listing_record(
    payload: dict[str, Any],
    page_url: str,
    surface: str,
) -> dict[str, Any]:
    alias_lookup = surface_alias_lookup(surface, None)
    candidates: dict[str, list[object]] = {}
    collect_structured_candidates(payload, alias_lookup, page_url, candidates)
    record: dict[str, Any] = {
        "source_url": page_url,
        "_source": "structured_listing",
    }
    for field_name in surface_fields(surface, None):
        finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
    preferred_title = coerce_text(payload.get("name") or payload.get("title"))
    if preferred_title:
        record["title"] = preferred_title
    if not record.get("url") or not record.get("title"):
        return {}
    return finalize_record(record, surface=surface)


def _extract_structured_listing(
    payloads: list[dict[str, Any]],
    page_url: str,
    surface: str,
    *,
    max_records: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for payload in payloads:
        raw_type = payload.get("@type")
        normalized_type = " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        normalized_type = normalized_type.lower()
        items: list[dict[str, Any]] = []
        if "itemlist" in normalized_type:
            for item in payload.get("itemListElement") or []:
                entry = item.get("item") if isinstance(item, dict) else None
                if isinstance(entry, dict):
                    items.append(entry)
                elif isinstance(item, dict):
                    items.append(item)
        elif any(token in normalized_type for token in ("product", "jobposting")):
            items.append(payload)
        for item in items:
            record = _structured_listing_record(item, page_url, surface)
            url = str(record.get("url") or "")
            if not url or url in seen_urls or url == page_url:
                continue
            seen_urls.add(url)
            records.append(record)
            if len(records) >= max_records:
                return records
    return records


def _listing_title_is_noise(title: str) -> bool:
    lowered = clean_text(title).lower()
    if not lowered:
        return True
    if lowered in LISTING_NAVIGATION_TITLE_HINTS or lowered in LISTING_WEAK_TITLES:
        return True
    if any(lowered.startswith(prefix) for prefix in LISTING_MERCHANDISING_TITLE_PREFIXES):
        return True
    if LISTING_ALT_TEXT_TITLE_PATTERN.search(lowered):
        return True
    return any(pattern.search(lowered) for pattern in LISTING_EDITORIAL_TITLE_PATTERNS)


def _listing_card_html_fragments(
    dom_parser: LexborHTMLParser, *, is_job: bool
) -> list[str]:
    selector_group = "jobs" if is_job else "ecommerce"
    selectors = list(CARD_SELECTORS.get(selector_group) or [])
    fragments: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        try:
            matches = dom_parser.css(selector)
        except Exception:
            matches = []
        for node in matches:
            fragment = str(node.html or "").strip()
            if not fragment or fragment in seen:
                continue
            seen.add(fragment)
            fragments.append(fragment)
    if fragments:
        return fragments
    for node in dom_parser.css("article, li, div"):
        if node.css_first("a[href]") is None:
            continue
        fragment = str(node.html or "").strip()
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        fragments.append(fragment)
        if len(fragments) >= LISTING_FALLBACK_FRAGMENT_LIMIT:
            break
    return fragments


def _card_title_node(card: Tag) -> Tag | None:
    for selector in EXTRACTION_RULES.get("listing_extraction", {}).get("card_title_selectors", []):
        nodes = safe_select(card, str(selector))
        if nodes:
            return nodes[0]
    anchor = card.find("a", href=True)
    return anchor if isinstance(anchor, Tag) else None


def _detail_like_path(url: str, *, is_job: bool) -> bool:
    lowered = url.lower()
    if any(marker in lowered for marker in LISTING_DETAIL_PATH_MARKERS):
        return True
    hints = JOB_URL_HINTS if is_job else PRODUCT_URL_HINTS
    return any(marker in lowered for marker in hints)


def _listing_record_from_card(
    card: Tag,
    page_url: str,
    surface: str,
    *,
    selector_rules: list[dict[str, object]] | None = None,
) -> dict[str, Any] | None:
    is_job = surface.startswith("job_")
    title_node = _card_title_node(card)
    if title_node is None:
        return None
    title = clean_text(
        title_node.get("title")
        or title_node.get("alt")
        or title_node.get_text(" ", strip=True)
    )
    if len(title) < 4 or _listing_title_is_noise(title):
        return None
    link_node = title_node if title_node.name == "a" else title_node.find_parent("a")
    if link_node is None:
        link_node = card.find("a", href=True)
    if link_node is None:
        return None
    url = absolute_url(page_url, link_node.get("href"))
    if not url or not same_host(page_url, url):
        return None
    card_text = clean_text(card.get_text(" ", strip=True))
    if not _detail_like_path(url, is_job=is_job):
        if is_job and not any(token in card_text.lower() for token in ("salary", "remote", "location", "apply")):
            return None
        if not is_job and not PRICE_RE.search(card_text):
            return None
    alias_lookup = surface_alias_lookup(surface, None)
    candidates: dict[str, list[object]] = {"title": [title], "url": [url]}
    apply_selector_fallbacks(
        card,
        page_url,
        surface,
        None,
        candidates,
        selector_rules=selector_rules,
    )
    image_urls = extract_page_images(card, page_url)
    if image_urls:
        add_candidate(candidates, "image_url", image_urls[0])
        add_candidate(candidates, "additional_images", image_urls[1:])
    for label, value in extract_label_value_pairs(card):
        normalized_label = normalize_requested_field(label)
        if not normalized_label:
            normalized_label = clean_text(label).lower().replace(" ", "_")
        canonical = alias_lookup.get(normalized_label)
        if canonical:
            add_candidate(
                candidates,
                canonical,
                coerce_field_value(canonical, value, page_url),
            )
    if not is_job and not candidates.get("price"):
        price_match = PRICE_RE.search(card_text)
        if price_match:
            add_candidate(candidates, "price", price_match.group(0))
    if is_job and not candidates.get("salary"):
        salary_match = PRICE_RE.search(card_text)
        if salary_match:
            add_candidate(candidates, "salary", salary_match.group(0))
    if not candidates.get("rating"):
        rating_match = RATING_RE.search(card_text)
        if rating_match:
            add_candidate(candidates, "rating", rating_match.group(1))
    if not candidates.get("review_count"):
        review_match = REVIEW_COUNT_RE.search(card_text)
        if review_match:
            add_candidate(candidates, "review_count", review_match.group(1))
    record: dict[str, Any] = {"source_url": page_url, "_source": "dom_listing"}
    for field_name in surface_fields(surface, None):
        finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
    cleaned = finalize_record(record, surface=surface)
    if not cleaned.get("url") or not cleaned.get("title"):
        return None
    return cleaned


def extract_listing_records(
    html: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    selector_rules: list[dict[str, object]] | None = None,
) -> list[dict[str, Any]]:
    dom_parser, cleaned_html = _prepare_listing_dom(html)
    soup = BeautifulSoup(cleaned_html, "html.parser")
    js_state_payloads = [
        payload
        for payload in harvest_js_state_objects(soup, cleaned_html).values()
        if isinstance(payload, dict)
    ]

    def _structured_stage() -> list[dict[str, Any]]:
        return _extract_structured_listing(
            [
                *parse_json_ld(soup),
                *parse_microdata(soup, cleaned_html, page_url),
                *parse_opengraph(soup, cleaned_html, page_url),
                *parse_embedded_json(soup, cleaned_html),
                *js_state_payloads,
            ],
            page_url,
            surface,
            max_records=max_records,
        )

    def _dom_stage() -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for fragment in _listing_card_html_fragments(
            dom_parser, is_job=surface.startswith("job_")
        ):
            card_soup = BeautifulSoup(fragment, "html.parser")
            card = card_soup.find(["article", "li", "div"]) or card_soup.find(True)
            if not isinstance(card, Tag):
                continue
            record = _listing_record_from_card(
                card,
                page_url,
                surface,
                selector_rules=selector_rules,
            )
            if record is None:
                continue
            url = str(record.get("url") or "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            records.append(record)
            if len(records) >= max_records:
                break
        return records

    for extractor in (_structured_stage, _dom_stage):
        records = extractor()
        if records:
            return records[:max_records]
    return []
