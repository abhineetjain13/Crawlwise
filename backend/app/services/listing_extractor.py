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
)
from app.services.config.selectors import CARD_SELECTORS
from app.services.extraction_context import (
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.field_policy import normalize_requested_field
from app.services.field_value_utils import (
    PRICE_RE,
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
from app.services.config.surface_hints import detail_path_hints
from app.services.pipeline.pipeline_config import LISTING_FALLBACK_FRAGMENT_LIMIT

logger = logging.getLogger(__name__)


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
    if not record.get("url"):
        fallback_url = _structured_listing_url(payload, page_url)
        if fallback_url:
            record["url"] = fallback_url
    if not record.get("url") or not record.get("title"):
        return {}
    return finalize_record(record, surface=surface)


def _structured_listing_url(payload: dict[str, Any], page_url: str) -> str | None:
    for key in ("url", "link", "href"):
        resolved = absolute_url(page_url, payload.get(key))
        if resolved:
            return resolved
    author = payload.get("author")
    if isinstance(author, dict):
        for key in ("url", "link", "href"):
            resolved = absolute_url(page_url, author.get(key))
            if resolved:
                return resolved
    return None


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
        for item in _structured_listing_items(payload):
            record = _structured_listing_record(item, page_url, surface)
            url = str(record.get("url") or "")
            if not url or url in seen_urls or url == page_url:
                continue
            seen_urls.add(url)
            records.append(record)
            if len(records) >= max_records:
                return records
    return records


def _structured_listing_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for candidate in _listing_payload_candidates(payload):
        if not isinstance(candidate, dict):
            continue
        raw_type = candidate.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        ).lower()
        if "itemlist" in normalized_type:
            for item in candidate.get("itemListElement") or []:
                entry = item.get("item") if isinstance(item, dict) else None
                if isinstance(entry, dict):
                    items.append(entry)
                elif isinstance(item, dict):
                    items.append(item)
        elif any(token in normalized_type for token in ("product", "jobposting")):
            items.append(candidate)
        elif _looks_like_untyped_listing_payload(candidate):
            items.append(candidate)
    return items


def _listing_payload_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = [payload]
    main_entity = payload.get("mainEntity")
    if isinstance(main_entity, dict):
        candidates.append(main_entity)
    elif isinstance(main_entity, list):
        candidates.extend(item for item in main_entity if isinstance(item, dict))
    return candidates


def _allow_embedded_json_listing_payloads(payloads: list[dict[str, Any]]) -> bool:
    if len(payloads) >= 2:
        return True
    for payload in payloads:
        raw_type = payload.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        ).lower()
        if "itemlist" in normalized_type:
            return True
        if isinstance(payload.get("itemListElement"), list) and payload.get("itemListElement"):
            return True
        main_entity = payload.get("mainEntity")
        if not isinstance(main_entity, dict):
            continue
        main_entity_type = main_entity.get("@type")
        normalized_main_entity_type = (
            " ".join(main_entity_type)
            if isinstance(main_entity_type, list)
            else str(main_entity_type or "")
        ).lower()
        if "itemlist" in normalized_main_entity_type:
            return True
        if isinstance(main_entity.get("itemListElement"), list) and main_entity.get("itemListElement"):
            return True
    return False


def _looks_like_untyped_listing_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    has_title = bool(coerce_text(payload.get("name") or payload.get("title")))
    if not has_title:
        return False
    if any(payload.get(key) for key in ("url", "link", "href")):
        return True
    author = payload.get("author")
    if isinstance(author, dict) and any(author.get(key) for key in ("url", "link", "href")):
        return True
    return bool(payload.get("price") or payload.get("offers"))


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
    hints = detail_path_hints("job_detail" if is_job else "ecommerce_detail")
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
    image_urls = extract_page_images(card, page_url, surface=surface)
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
    record: dict[str, Any] = {
        "source_url": page_url,
        "_source": "dom_listing",
    }
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
    context = prepare_extraction_context(html)
    dom_parser = context.dom_parser

    def _structured_stage() -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for source_name, source_payloads in collect_structured_source_payloads(
            context,
            page_url=page_url,
        ):
            if source_name == "js_state":
                continue
            payload_list = list(source_payloads)
            if source_name == "embedded_json" and not _allow_embedded_json_listing_payloads(
                payload_list
            ):
                continue
            payloads.extend(payload_list)
        return _extract_structured_listing(
            payloads,
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
