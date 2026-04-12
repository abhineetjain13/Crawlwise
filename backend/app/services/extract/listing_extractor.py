from __future__ import annotations

import json
import logging
from json import loads as parse_json

from app.services.extract import listing_structured_extractor as _listing_structured_extractor
from app.services.extract.listing_identity import (
    choose_primary_record_set,
    merge_record_sets_on_identity,
    strong_identity_key,
)
from app.services.extract.listing_card_extractor import (  # noqa: F401
    _auto_detect_cards,
    _clean_price_text,
    _compile_case_insensitive_regex,
    _extract_card_color,
    _extract_card_images,
    _extract_color_label_from_node,
    _extract_card_size,
    _extract_from_card,
    _extract_image_candidates,
    _harvest_product_url_from_item,
    _infer_currency_from_page_url,
    _match_line,
    _match_dimensions_line,
    _normalize_listing_title_text,
)
from app.services.extract.listing_item_normalizer import (  # noqa: F401
    _normalize_generic_item,
    _normalize_listing_value,
)
from app.services.extract.listing_normalize import normalize_listing_record
from app.services.extract.listing_structured_extractor import (
    _adapter_candidate_records,
    _extract_items_from_json as _extract_items_from_json_impl,
    _extract_from_comparison_tables,
    _extract_from_inline_object_arrays,
    _extract_from_json_ld,
    _extract_from_next_flight_scripts,
    _extract_from_structured_sources as _extract_from_structured_sources_impl,
    _lookup_next_flight_window_index as _lookup_next_flight_window_index,
    _normalize_ld_item as _normalize_ld_item,
)
from app.services.extract.listing_quality import (
    is_meaningful_listing_record as _assess_meaningful_listing_record,
    is_merchandising_listing_record as _is_merchandising_record_impl,
)
from app.services.extract.listing_quality import (
    is_meaningful_structured_listing_record as _assess_meaningful_structured_listing_record,
)
from app.services.extract.source_parsers import parse_page_sources
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_EMPTY_VALUES = (None, "", [], {})
MIN_VIABLE_RECORDS = 2
MAX_JSON_RECURSION_DEPTH = _listing_structured_extractor.MAX_JSON_RECURSION_DEPTH

# Detail-only fields that should not be extracted on listing pages
DETAIL_ONLY_FIELDS = {"brand", "gtin", "variants", "specifications", "description"}
_LISTING_HOST_TOKEN_STOPWORDS = {
    "www",
    "m",
    "amp",
    "api",
    "cdn",
    "img",
    "images",
    "static",
    "backend",
    "edge",
    "shop",
    "store",
    "merchant",
    "com",
    "net",
    "org",
    "co",
    "io",
    "app",
}
# Listing extraction still enforces the field contract for DOM card records by
# stripping detail-only fields before persistence.
def _enforce_listing_field_contract(records: list[dict], page_type: str) -> list[dict]:
    """Filter listing page records to remove detail-only fields from DOM records.

    If page_type is "listing":
    - For DOM-extracted records (source="listing_card"), drop detail-only fields
    - For structured data records (JSON-LD, __NEXT_DATA__, etc.), preserve all fields
    - Log warning if detail fields were present in DOM records

    Returns filtered records.

    This helper remains part of the production listing extraction path.
    """
    if page_type != "listing":
        return records

    filtered_records = []
    all_dropped_fields: set[str] = set()
    drop_count = 0

    for record in records:
        # Check if this is a DOM-extracted record
        source = record.get("_source", "")
        is_dom_record = "listing_card" in str(source)

        if not is_dom_record:
            # Preserve all fields for structured data records
            filtered_records.append(record)
            continue

        # For DOM records, drop detail-only fields
        dropped_fields = {k for k in record.keys() if k in DETAIL_ONLY_FIELDS}
        filtered_record = {
            k: v for k, v in record.items() if k not in DETAIL_ONLY_FIELDS
        }
        if dropped_fields:
            all_dropped_fields.update(dropped_fields)
            drop_count += 1

        filtered_records.append(filtered_record)

    if drop_count:
        logger.warning(
            "Listing page contract violation: dropped detail-only fields %s from %d DOM records",
            sorted(all_dropped_fields), drop_count,
        )

    return filtered_records


def extract_listing_records(
    html: str,
    surface: str,
    target_fields: set[str],
    page_url: str = "",
    max_records: int = 100,
    xhr_payloads: list[dict] | None = None,
    adapter_records: list[dict] | None = None,
    soup: BeautifulSoup | None = None,
) -> list[dict]:
    page_fragments = _split_paginated_html_fragments(html)
    if len(page_fragments) > 1:
        merged_records: list[dict] = []
        for _index, fragment in enumerate(page_fragments):
            merged_records.extend(
                _extract_listing_records_single_page(
                    fragment,
                    surface,
                    target_fields,
                    page_url=page_url,
                    max_records=max_records,
                    xhr_payloads=xhr_payloads,
                    adapter_records=adapter_records,
                )
            )
            if len(merged_records) >= max_records:
                break
        return _dedupe_listing_records(merged_records)[:max_records]

    return _extract_listing_records_single_page(
        html,
        surface,
        target_fields,
        page_url=page_url,
        max_records=max_records,
        xhr_payloads=xhr_payloads,
        adapter_records=adapter_records,
        soup=soup,
    )


def _extract_listing_records_single_page(
    html: str,
    surface: str,
    target_fields: set[str],
    *,
    page_url: str = "",
    max_records: int = 100,
    xhr_payloads: list[dict] | None = None,
    adapter_records: list[dict] | None = None,
    soup: BeautifulSoup | None = None,
) -> list[dict]:
    soup = soup or BeautifulSoup(html, "html.parser")
    page_sources = parse_page_sources(html, soup=soup)
    adapter_records = adapter_records or []
    xhr_payloads = xhr_payloads or []
    json_ld_records = _extract_from_json_ld(soup, surface, page_url)
    structured_records = _extract_from_structured_sources(
        page_sources=page_sources,
        xhr_payloads=xhr_payloads,
        surface=surface,
        page_url=page_url,
    )
    comparison_table_records = _extract_from_comparison_tables(
        soup,
        surface=surface,
        page_url=page_url,
    )
    raw_record_sets = {
        "structured": structured_records,
        "comparison_table": comparison_table_records,
        "next_flight": [],
        "inline_array": [],
        "json_ld": json_ld_records,
        "adapter": _adapter_candidate_records(adapter_records),
    }
    if _should_run_expensive_listing_fallbacks(
        json_ld_records=json_ld_records,
        structured_records=structured_records,
    ):
        raw_record_sets["next_flight"] = _extract_from_next_flight_scripts(html, page_url)
        raw_record_sets["inline_array"] = _extract_from_inline_object_arrays(
            html, surface, page_url
        )
    raw_record_sets["dom"] = _extract_dom_listing_records(
        soup,
        surface=surface,
        target_fields=target_fields,
        page_url=page_url,
        max_records=max_records,
    )

    normalized_record_sets = _normalize_listing_record_sets(
        raw_record_sets,
        surface=surface,
        page_url=page_url,
        target_fields=target_fields,
    )
    primary_label, primary_records = choose_primary_record_set(
        normalized_record_sets,
        surface=surface,
    )
    if not primary_records:
        return []

    supplemental_sets = [
        records
        for label, records in normalized_record_sets.items()
        if label != primary_label and records
    ]
    merged_records = merge_record_sets_on_identity(primary_records, supplemental_sets)
    return _dedupe_listing_records(merged_records)[:max_records]


def _should_run_expensive_listing_fallbacks(
    *,
    json_ld_records: list[dict],
    structured_records: list[dict],
) -> bool:
    return (
        len(json_ld_records) < MIN_VIABLE_RECORDS
        and len(structured_records) < MIN_VIABLE_RECORDS
    )


def _extract_dom_listing_records(
    soup: BeautifulSoup,
    *,
    surface: str,
    target_fields: set[str],
    page_url: str,
    max_records: int,
) -> list[dict]:
    cards, used_selector = _auto_detect_cards(soup, surface=surface)
    dom_records: list[dict] = []
    for card in cards[:max_records]:
        record = _extract_from_card(card, target_fields, surface, page_url)
        if not record or not _is_meaningful_listing_record(record, surface=surface):
            continue
        record["_source"] = "listing_card"
        if used_selector:
            record["_selector"] = used_selector
        dom_records.append(record)
    page_type = "listing" if "listing" in str(surface or "").lower() else surface
    return _enforce_listing_field_contract(dom_records, page_type)


def _normalize_listing_record_sets(
    raw_record_sets: dict[str, list[dict]],
    *,
    surface: str,
    page_url: str,
    target_fields: set[str],
) -> dict[str, list[dict]]:
    return {
        label: _normalize_record_set(
            records,
            surface=surface,
            page_url=page_url,
            target_fields=target_fields,
        )
        for label, records in raw_record_sets.items()
    }


def _normalize_record_set(
    records: list[dict],
    *,
    surface: str,
    page_url: str,
    target_fields: set[str],
) -> list[dict]:
    normalized: list[dict] = []
    for record in records:
        candidate = normalize_listing_record(
            record,
            surface=surface,
            page_url=page_url,
            target_fields=target_fields,
        )
        if candidate and (
            _is_meaningful_listing_record(candidate, surface=surface)
            or _is_identity_supplement_record(candidate)
        ):
            normalized.append(candidate)
    return normalized


def _is_identity_supplement_record(record: dict) -> bool:
    if not strong_identity_key(record):
        return False
    public_fields = [
        key
        for key, value in record.items()
        if not str(key).startswith("_") and value not in _EMPTY_VALUES
    ]
    return len(public_fields) >= 2


def _split_paginated_html_fragments(html: str) -> list[str]:
    if "<!-- PAGE BREAK:" not in html:
        return [html]
    fragments: list[str] = []
    current_lines: list[str] = []
    for line in html.splitlines():
        if line.strip().startswith("<!-- PAGE BREAK:"):
            if current_lines:
                fragment = "\n".join(current_lines).strip()
                if fragment:
                    fragments.append(fragment)
                current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        fragment = "\n".join(current_lines).strip()
        if fragment:
            fragments.append(fragment)
    return fragments or [html]


def _dedupe_listing_records(records: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for record in records:
        key = _listing_record_join_key(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _listing_record_join_key(record: dict) -> str:
    strong_key = strong_identity_key(record)
    if strong_key:
        return strong_key
    title = str(record.get("title") or "").strip().lower()
    price = str(record.get("price") or "").strip().lower()
    image_url = str(record.get("image_url") or "").strip().lower()
    return f"title:{title}|price:{price}|image:{image_url}"


def _structured_record_join_key(record: dict) -> str:
    return strong_identity_key(record)


def _extract_from_structured_sources(*args, **kwargs):
    kwargs.setdefault("max_json_recursion_depth", MAX_JSON_RECURSION_DEPTH)
    return _extract_from_structured_sources_impl(*args, **kwargs)


def _extract_items_from_json(*args, **kwargs):
    kwargs.setdefault("max_depth", MAX_JSON_RECURSION_DEPTH)
    return _extract_items_from_json_impl(*args, **kwargs)


def _is_merchandising_record(record: dict[str, object]) -> bool:
    return _is_merchandising_record_impl(record)

def _is_meaningful_listing_record(record: dict, *, surface: str = "") -> bool:
    return _assess_meaningful_listing_record(record, surface=surface)


def _is_meaningful_structured_listing_record(
    record: dict, *, surface: str = ""
) -> bool:
    return _assess_meaningful_structured_listing_record(record, surface=surface)


def _estimate_visible_item_count(soup: BeautifulSoup) -> int:
    """Fast estimation of visible product items based on common patterns.
    Used for browser escalation heuristic."""
    # Count product cards by common selectors
    card_selectors = (
        "[class*='product-card']",
        "[class*='product-item']",
        "[class*='listing-card']",
        "[class*='result-item']",
        "[data-component-type='s-search-result']",
        "article[class*='product']",
        "li[class*='product']",
    )
    card_count = 0
    for sel in card_selectors:
        matches = soup.select(sel)
        if len(matches) >= 3:
            card_count = max(card_count, len(matches))

    # Also look for price-like blocks
    price_count = len(soup.select("[class*='price'], [id*='price'], .amount"))

    return max(card_count, price_count // 2 if price_count > 0 else 0)


def _parse_json_script(value: str) -> dict | list | None:
    candidate = str(value or "").strip()
    if candidate.endswith(";"):
        candidate = candidate[:-1].rstrip()
    if not candidate or candidate[0] not in "[{":
        return None
    try:
        parsed = parse_json(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


