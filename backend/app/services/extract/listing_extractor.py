from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from functools import lru_cache
from json import loads as parse_json
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

from app.services.pipeline_config import (
    CARD_SELECTORS_COMMERCE,
    CARD_SELECTORS_JOBS,
    COLLECTION_KEYS,
    FIELD_ALIASES,
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_CATEGORY_PATH_MARKERS,
    LISTING_COLOR_ACTION_PREFIXES,
    LISTING_COLOR_ACTION_VALUES,
    LISTING_CARD_TITLE_SELECTORS,
    LISTING_DETAIL_PATH_MARKERS,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_FACET_PATH_FRAGMENTS,
    LISTING_FACET_QUERY_KEYS,
    LISTING_FILTER_OPTION_KEYS,
    LISTING_HUB_PATH_SEGMENTS,
    LISTING_IMAGE_EXCLUDE_TOKENS,
    LISTING_JOB_SIGNAL_FIELDS,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    LISTING_MINIMAL_VISUAL_FIELDS,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_NON_LISTING_PATH_TOKENS,
    LISTING_PRODUCT_SIGNAL_FIELDS,
    LISTING_SWATCH_CONTAINER_SELECTORS,
    LISTING_WEAK_METADATA_FIELDS,
    LISTING_WEAK_TITLES,
    MAX_JSON_RECURSION_DEPTH,
    NESTED_CATEGORY_KEYS,
    NESTED_CURRENCY_KEYS,
    NESTED_ORIGINAL_PRICE_KEYS,
    NESTED_PRICE_KEYS,
    NESTED_TEXT_KEYS,
    NESTED_URL_KEYS,
    PAGE_URL_CURRENCY_HINTS,
)
from app.services.extract.listing_identity import (
    choose_primary_record_set,
    merge_record_sets_on_identity,
    merge_listing_record,
    strong_identity_key,
)
from app.services.extract.listing_normalize import normalize_listing_record
from app.services.extract.listing_quality import (
    assess_listing_record_quality,
    is_meaningful_listing_record as _assess_meaningful_listing_record,
    is_meaningful_structured_listing_record as _assess_meaningful_structured_listing_record,
)
from app.services.extract.source_parsers import parse_page_sources
from app.services.config.extraction_rules import PLATFORM_FAMILIES

_EMPTY_VALUES = (None, "", [], {})
MIN_VIABLE_RECORDS = 2

_WEAK_LISTING_TITLES = LISTING_WEAK_TITLES

# Listing page allowed fields - only these fields should be extracted on listing pages
LISTING_PAGE_ALLOWED_FIELDS = {"url", "title", "price", "image_link"}

# Detail-only fields that should not be extracted on listing pages
DETAIL_ONLY_FIELDS = {"brand", "gtin", "variants", "specifications", "description"}
_LISTING_SOCIAL_HOST_SUFFIXES = (
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
)
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
_LISTING_VARIANT_PROMPT_RE = re.compile(
    r"^(?:select|choose|pick)\s+(?:a|an|the|your)?\s*"
    r"(?:size|sizes|color|colors|colour|colours|option|options|variant|variants|"
    r"style|styles|fit|fits|waist|length|width)\b",
    re.IGNORECASE,
)


def _enforce_listing_field_contract(records: list[dict], page_type: str) -> list[dict]:
    """Filter listing page records to remove detail-only fields from DOM records.

    If page_type is "listing":
    - For DOM-extracted records (source="listing_card"), drop detail-only fields
    - For structured data records (JSON-LD, __NEXT_DATA__, etc.), preserve all fields
    - Log warning if detail fields were present in DOM records

    Returns filtered records.

    Note: This function is kept for testing purposes. The actual contract enforcement
    happens inline during DOM extraction in _extract_listing_records_single_page.
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
) -> list[dict]:
    page_fragments = _split_paginated_html_fragments(html)
    if len(page_fragments) > 1:
        merged_records: list[dict] = []
        for index, fragment in enumerate(page_fragments):
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
) -> list[dict]:
    page_sources = parse_page_sources(html)
    adapter_records = adapter_records or []
    xhr_payloads = xhr_payloads or []

    soup = BeautifulSoup(html, "html.parser")
    json_ld_records = _extract_from_json_ld(soup, surface, page_url)
    structured_records = _extract_from_structured_sources(
        page_sources=page_sources,
        xhr_payloads=xhr_payloads,
        surface=surface,
        page_url=page_url,
    )
    should_run_expensive_fallbacks = (
        len(json_ld_records) < MIN_VIABLE_RECORDS
        and len(structured_records) < MIN_VIABLE_RECORDS
    )
    next_flight_records = (
        _extract_from_next_flight_scripts(html, page_url)
        if should_run_expensive_fallbacks
        else []
    )
    inline_array_records = (
        _extract_from_inline_object_arrays(html, surface, page_url)
        if should_run_expensive_fallbacks
        else []
    )
    raw_record_sets = {
        "structured": structured_records,
        "next_flight": next_flight_records,
        "inline_array": inline_array_records,
        "json_ld": json_ld_records,
        "adapter": _adapter_candidate_records(adapter_records),
    }

    cards, used_selector = _auto_detect_cards(soup, surface=surface)
    dom_records: list[dict] = []
    for card in cards[:max_records]:
        record = _extract_from_card(card, target_fields, surface, page_url)
        if record and _is_meaningful_listing_record(record, surface=surface):
            record["_source"] = "listing_card"
            if used_selector:
                record["_selector"] = used_selector
            dom_records.append(record)
    dom_records = _enforce_listing_field_contract(
        dom_records, "listing" if "listing" in str(surface or "").lower() else surface
    )
    raw_record_sets["dom"] = dom_records

    normalized_record_sets = {
        label: _normalize_record_set(
            records,
            surface=surface,
            page_url=page_url,
            target_fields=target_fields,
        )
        for label, records in raw_record_sets.items()
    }
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


# ---------------------------------------------------------------------------
# Structured source extraction
# ---------------------------------------------------------------------------


def _extract_from_structured_sources(
    *,
    page_sources: dict[str, object],
    xhr_payloads: list[dict],
    surface: str,
    page_url: str,
) -> list[dict]:
    """Try JSON-LD, __NEXT_DATA__, hydrated states, and network payloads."""
    structured_groups: list[list[dict]] = []
    ld_records: list[dict] = []
    for payload in page_sources.get("json_ld") or []:
        if isinstance(payload, dict):
            ld_records.extend(
                _extract_ld_records_from_payload(payload, surface, page_url)
            )
    ld_records = [
        record
        for record in ld_records
        if _is_meaningful_structured_listing_record(record, surface=surface)
    ]
    if ld_records:
        structured_groups.append(ld_records)

    next_data = page_sources.get("next_data")
    if next_data:
        next_records = _extract_from_next_data(next_data, surface, page_url)
        next_records = [
            record
            for record in next_records
            if _is_meaningful_structured_listing_record(record, surface=surface)
        ]
        if next_records:
            structured_groups.append(next_records)

    hydrated_states = page_sources.get("hydrated_states") or []
    if hydrated_states:
        for state in hydrated_states:
            state_records = _extract_items_from_json(
                state,
                surface,
                page_url,
                max_depth=max(MAX_JSON_RECURSION_DEPTH + 4, 8),
            )
            if state_records:
                for r in state_records:
                    r["_source"] = "hydrated_state"
                filtered_state_records = [
                    record
                    for record in state_records
                    if _is_meaningful_structured_listing_record(record, surface=surface)
                ]
                if filtered_state_records:
                    structured_groups.append(filtered_state_records)
                    break

    for payload in xhr_payloads:
        payload_url = str(payload.get("url") or "").strip()
        body = payload.get("body")
        if not isinstance(body, (dict, list)):
            continue
        net_records = _extract_items_from_json(
            body,
            surface,
            page_url,
            max_depth=max(MAX_JSON_RECURSION_DEPTH + 4, 8),
        )
        if net_records:
            for r in net_records:
                r["_source"] = "network_payload"
            filtered_net_records = [
                record
                for record in net_records
                if _is_meaningful_structured_listing_record(record, surface=surface)
            ]
            filtered_net_records = _filter_relevant_network_record_set(
                filtered_net_records,
                payload_url=payload_url,
                page_url=page_url,
                surface=surface,
            )
            if filtered_net_records:
                structured_groups.append(filtered_net_records)

    if not structured_groups:
        return []

    # Convert groups to a dict for choose_primary_record_set
    record_sets = {f"group_{i}": group for i, group in enumerate(structured_groups)}
    primary_label, primary_records = choose_primary_record_set(
        record_sets, surface=surface
    )

    if not primary_records:
        return []

    # Merge supplemental groups into primary
    supplemental_sets = [
        records
        for label, records in record_sets.items()
        if label != primary_label and records
    ]
    merged = merge_record_sets_on_identity(primary_records, supplemental_sets)

    return merged if len(merged) >= MIN_VIABLE_RECORDS else []


def _adapter_candidate_records(records: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        candidate = dict(record)
        candidate["_source"] = str(record.get("_source") or "adapter")
        if _is_meaningful_listing_record(
            candidate, surface=str(candidate.get("_surface") or "")
        ):
            normalized.append(candidate)
    return normalized


def _extract_from_json_ld(
    soup: BeautifulSoup, surface: str, page_url: str
) -> list[dict]:
    """Parse JSON-LD from HTML and extract listing items."""
    records: list[dict] = []
    for node in soup.select("script[type='application/ld+json']"):
        data = _parse_json_script(node.string or node.get_text(" ", strip=True) or "")
        if data is None:
            continue

        items = data if isinstance(data, list) else [data]
        for payload in items:
            if not isinstance(payload, dict):
                continue
            records.extend(_extract_ld_records_from_payload(payload, surface, page_url))

    return [
        record
        for record in records
        if _is_meaningful_structured_listing_record(record, surface=surface)
    ]


def _extract_ld_records_from_payload(
    payload: dict,
    surface: str,
    page_url: str,
    *,
    _depth: int = 0,
    _max_depth: int = 2,
) -> list[dict]:
    if _depth > _max_depth:
        return []

    records: list[dict] = []
    ld_type = str(payload.get("@type", "")).strip()

    if ld_type == "ItemList" or "itemListElement" in payload:
        for el in payload.get("itemListElement", []):
            if isinstance(el, dict):
                item = el.get("item", el)
                if isinstance(item, dict):
                    record = _normalize_ld_item(item, surface, page_url)
                    if record:
                        record["_source"] = "json_ld_item_list"
                        records.append(record)
    elif ld_type in ("Product", "JobPosting"):
        record = _normalize_ld_item(payload, surface, page_url)
        if record:
            record["_source"] = "json_ld"
            records.append(record)

    graph = payload.get("@graph")
    if isinstance(graph, list):
        for graph_item in graph:
            if isinstance(graph_item, dict):
                records.extend(
                    _extract_ld_records_from_payload(
                        graph_item,
                        surface,
                        page_url,
                        _depth=_depth + 1,
                        _max_depth=_max_depth,
                    )
                )

    if not records:
        main_entity = payload.get("mainEntity")
        if isinstance(main_entity, dict):
            records.extend(
                _extract_ld_records_from_payload(
                    main_entity,
                    surface,
                    page_url,
                    _depth=_depth + 1,
                    _max_depth=_max_depth,
                )
            )

    if not records:
        offers = payload.get("offers")
        if isinstance(offers, dict):
            item_offered = offers.get("itemOffered")
            if isinstance(item_offered, list):
                for item in item_offered:
                    if isinstance(item, dict):
                        record = _normalize_ld_item(item, surface, page_url)
                        if record:
                            record["_source"] = "json_ld_offers"
                            records.append(record)

    return records


def _extract_next_data_payload(soup: BeautifulSoup) -> dict | None:
    node = soup.select_one("script#__NEXT_DATA__")
    if node is None:
        return None
    payload = _parse_json_script(node.string or node.get_text(" ", strip=True) or "")
    return payload if isinstance(payload, dict) else None


def _normalize_ld_item(item: dict, surface: str, page_url: str) -> dict | None:
    """Normalize a JSON-LD Product or JobPosting into a flat record."""
    record: dict = {}
    record["title"] = _normalize_listing_title_text(item.get("name") or "")

    url = item.get("url") or ""
    if url and page_url:
        url = urljoin(page_url, url)
    record["url"] = url

    # Images
    images = _extract_image_candidates(item.get("image"))
    if images:
        record["image_url"] = images[0]
        if len(images) > 1:
            record["additional_images"] = ", ".join(images[1:])

    if "ecommerce" in surface:
        offers = item.get("offers", {})
        if isinstance(offers, list) and offers:
            offers = offers[0]
        if isinstance(offers, dict):
            record["price"] = _first_present(
                offers.get("price"), offers.get("lowPrice"), ""
            )
            record["currency"] = offers.get("priceCurrency") or ""
            record["availability"] = offers.get("availability") or ""
        record["brand"] = _nested_name(item.get("brand"))
        record["sku"] = item.get("sku") or ""
        record["part_number"] = item.get("mpn") or item.get("partNumber") or ""
        record["description"] = item.get("description") or ""
        record["rating"] = _nested_value(item.get("aggregateRating"), "ratingValue")

    if "job" in surface:
        record["company"] = _nested_name(item.get("hiringOrganization"))
        location = item.get("jobLocation")
        if isinstance(location, dict):
            address = location.get("address", {})
            if isinstance(address, dict):
                record["location"] = (
                    address.get("addressLocality") or address.get("name") or ""
                )
            else:
                record["location"] = str(address)
        elif isinstance(location, str):
            record["location"] = location
        salary = item.get("baseSalary")
        if isinstance(salary, dict):
            val = salary.get("value", {})
            if isinstance(val, dict):
                min_val = val.get("minValue")
                max_val = val.get("maxValue")
                if min_val not in (None, "") and max_val not in (None, ""):
                    record["salary"] = f"{min_val}-{max_val}"
                elif min_val not in (None, ""):
                    record["salary"] = str(min_val)
                elif max_val not in (None, ""):
                    record["salary"] = str(max_val)
                else:
                    record["salary"] = ""
            else:
                record["salary"] = str(val)
        elif salary:
            record["salary"] = str(salary)
        record["description"] = item.get("description") or ""
        record["category"] = item.get("employmentType") or ""

    # Remove empty values
    if "job" in surface:
        # On job surfaces, price is actually salary — migrate it
        if record.get("price") and not record.get("salary"):
            record["salary"] = record.pop("price")
        for commerce_field in (
            "price",
            "sale_price",
            "original_price",
            "currency",
            "image_url",
            "additional_images",
        ):
            record.pop(commerce_field, None)
    elif record.get("price") and not record.get("currency"):
        record["currency"] = _infer_currency_from_page_url(page_url)
    record = {k: v for k, v in record.items() if v not in _EMPTY_VALUES}
    if record:
        record["_raw_item"] = item
    return record if record else None


def _first_present(*values):
    for value in values:
        if value not in _EMPTY_VALUES:
            return value
    return ""


def _nested_name(obj: object) -> str:
    """Extract name from a nested object like {"name": "Acme"} or a plain string."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return obj.get("name") or ""
    return ""


def _nested_value(obj: object, key: str) -> str:
    """Extract a value from a nested object."""
    if isinstance(obj, dict):
        return str(obj.get(key, ""))
    return ""


def _extract_from_next_data(next_data: dict, surface: str, page_url: str) -> list[dict]:
    records = _collect_candidate_record_sets(
        next_data,
        surface,
        page_url,
        depth=0,
        max_depth=max(MAX_JSON_RECURSION_DEPTH + 4, 8),
    )
    if not records:
        return []
    for record in records:
        record["_source"] = "next_data"
    return records


def _extract_items_from_json(
    data: dict | list,
    surface: str,
    page_url: str,
    _depth: int = 0,
    *,
    max_depth: int = MAX_JSON_RECURSION_DEPTH,
) -> list[dict]:
    if _depth > max_depth:
        return []

    records = _collect_candidate_record_sets(
        data,
        surface,
        page_url,
        depth=_depth,
        max_depth=max_depth,
    )
    if not records:
        return []
    return records


def _collect_candidate_record_sets(
    data: object,
    surface: str,
    page_url: str,
    *,
    depth: int,
    max_depth: int,
) -> list[dict]:
    if depth > max_depth or data in (None, "", [], {}):
        return []

    if isinstance(data, list):
        objects = [item for item in data if isinstance(item, dict)]
        if len(objects) >= 2:
            normalized = _try_normalize_array(objects, surface, page_url)
            if normalized:
                return normalized
            for item in objects[:40]:
                state_data = _query_state_data(item)
                if state_data not in (None, "", [], {}):
                    state_records = _collect_candidate_record_sets(
                        state_data,
                        surface,
                        page_url,
                        depth=depth + 1,
                        max_depth=max_depth,
                    )
                    if state_records:
                        return state_records
        for item in data[:40]:
            if isinstance(item, (dict, list)):
                nested_records = _collect_candidate_record_sets(
                    item,
                    surface,
                    page_url,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
                if nested_records:
                    return nested_records
        return []

    if not isinstance(data, dict):
        return []

    for key in COLLECTION_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            objects = [item for item in value if isinstance(item, dict)]
            if len(objects) >= 2:
                normalized = _try_normalize_array(objects, surface, page_url)
                if normalized:
                    return normalized

    state_data = _query_state_data(data)
    if state_data not in (None, "", [], {}):
        state_records = _collect_candidate_record_sets(
            state_data,
            surface,
            page_url,
            depth=depth + 1,
            max_depth=max_depth,
        )
        if state_records:
            return state_records

    for value in data.values():
        if isinstance(value, list):
            objects = [item for item in value if isinstance(item, dict)]
            if len(objects) >= 2:
                normalized = _try_normalize_array(objects, surface, page_url)
                if normalized:
                    return normalized
        if isinstance(value, (dict, list)):
            nested_records = _collect_candidate_record_sets(
                value,
                surface,
                page_url,
                depth=depth + 1,
                max_depth=max_depth,
            )
            if nested_records:
                return nested_records

    return []


def _query_state_data(node: object) -> object | None:
    if not isinstance(node, dict):
        return None
    state = node.get("state")
    if not isinstance(state, dict):
        return None
    return state.get("data")


def _try_normalize_array(items: list[dict], surface: str, page_url: str) -> list[dict]:
    """Try to normalize an array of objects into records."""
    records = []
    for item in items:
        if _looks_like_listing_filter_option(item):
            continue
        record = _normalize_generic_item(item, surface, page_url)
        if (
            record
            and _is_meaningful_listing_record(record, surface=surface)
            and (
                "ecommerce" not in str(surface or "").lower()
                or _has_strong_ecommerce_listing_signal(record)
            )
        ):
            records.append(record)
    return records


def _looks_like_listing_filter_option(item: dict) -> bool:
    normalized_keys = {
        _normalized_field_token(key)
        for key in item.keys()
        if _normalized_field_token(key)
    }
    if not normalized_keys:
        return False
    return normalized_keys.issubset(LISTING_FILTER_OPTION_KEYS)


def _extract_from_next_flight_scripts(html: str, page_url: str) -> list[dict]:
    if "__next_f.push" not in html:
        return []

    decoded_chunks: list[str] = []
    for match in re.finditer(
        r"self\.__next_f\.push\(\[\d+,\s*\"((?:\\.|[^\"\\])*)\"\]\)", html, re.S
    ):
        try:
            decoded = parse_json(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            continue
        if decoded:
            decoded_chunks.append(decoded)

    if not decoded_chunks:
        return []

    records_by_url: dict[str, dict] = {}
    pair_patterns = [
        re.compile(
            r'"displayName":"(?P<title>[^"]+)".{0,900}?"listingUrl":"(?P<url>[^"]+)"',
            re.S,
        ),
        re.compile(
            r'"listingUrl":"(?P<url>[^"]+)".{0,900}?"displayName":"(?P<title>[^"]+)"',
            re.S,
        ),
    ]
    brand_pattern = re.compile(r'"name":"(?P<brand>[^"]+)","__typename":"ManufacturerCuratedBrand"')
    sale_price_pattern = re.compile(r'"priceVariation":"(?:SALE|PRIMARY)".{0,220}?"amount":"(?P<amount>[\d.]+)"', re.S)
    original_price_pattern = re.compile(r'"priceVariation":"PREVIOUS".{0,220}?"amount":"(?P<amount>[\d.]+)"', re.S)
    rating_pattern = re.compile(r'"averageRating":(?P<rating>[\d.]+),"totalCount":(?P<count>\d+)')
    availability_pattern = re.compile(r'"(?:shortInventoryStatusMessage|stockStatus)":"(?P<availability>[^"]+)"')

    # FIX: Process exclusively per-chunk. Do not join chunks into a massive string.
    for chunk in decoded_chunks:
        for pair_pattern in pair_patterns:
            for match in pair_pattern.finditer(chunk):
                raw_url = match.group("url")
                title = match.group("title")
                if not title:
                    continue

                # Isolate the search window around the match inside THIS chunk only
                start_index = max(0, match.start() - 1200)
                end_index = min(len(chunk), match.end() + 2200)
                window = chunk[start_index:end_index]
                
                resolved_url = urljoin(page_url, raw_url)
                record = records_by_url.setdefault(
                    resolved_url, {"url": resolved_url, "_source": "next_flight"}
                )
                record["title"] = title

                if brand_match := brand_pattern.search(window):
                    record.setdefault("brand", brand_match.group("brand"))
                if sale_price_match := sale_price_pattern.search(window):
                    record.setdefault("price", sale_price_match.group("amount"))
                if original_price_match := original_price_pattern.search(window):
                    record.setdefault("original_price", original_price_match.group("amount"))
                if rating_match := rating_pattern.search(window):
                    record.setdefault("rating", rating_match.group("rating"))
                    record.setdefault("review_count", rating_match.group("count"))
                if availability_match := availability_pattern.search(window):
                    record.setdefault("availability", availability_match.group("availability"))

    return [
        record
        for record in records_by_url.values()
        if _is_meaningful_listing_record(record, surface="ecommerce_listing")
    ]


def _extract_from_inline_object_arrays(
    html: str, surface: str, page_url: str
) -> list[dict]:
    seen: set[str] = set()
    key_pattern = re.compile(r'(?P<key>["\']?[A-Za-z_][A-Za-z0-9_-]*["\']?)\s*:\s*\[')

    for match in key_pattern.finditer(html):
        raw_key = str(match.group("key") or "").strip("\"' ")
        if not _looks_like_inline_collection_key(raw_key):
            continue
        array_text = _extract_balanced_literal(html, match.end() - 1)
        if not array_text:
            continue
        fingerprint = f"{raw_key}:{array_text[:200]}"
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        try:
            parsed = parse_json(array_text)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, list):
            continue
        objects = [item for item in parsed if isinstance(item, dict)]
        if len(objects) < 2:
            continue
        normalized = _try_normalize_array(objects, surface, page_url)
        if normalized:
            for record in normalized:
                record["_source"] = "inline_object_array"
            return normalized

    return []


def _looks_like_inline_collection_key(value: str) -> bool:
    normalized = _normalized_field_token(value)
    if not normalized:
        return False
    collection_tokens = {
        _normalized_field_token(token)
        for token in COLLECTION_KEYS
        if _normalized_field_token(token)
    }
    if normalized in collection_tokens:
        return True
    if normalized.startswith("list") and any(
        token in normalized
        for token in ("listing", "result", "product", "item", "record")
    ):
        return True
    return any(
        token in normalized
        for token in ("listingdetails", "searchresults", "productresults")
    )


def _extract_balanced_literal(text: str, start_index: int) -> str | None:
    if start_index < 0 or start_index >= len(text) or text[start_index] not in "[{":
        return None
    stack = [text[start_index]]
    in_string = False
    escape = False
    quote_char = ""
    index = start_index + 1

    while index < len(text):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote_char:
                in_string = False
        else:
            if char in {'"', "'"}:
                in_string = True
                quote_char = char
            elif char in "[{":
                stack.append(char)
            elif char in "]}":
                if not stack:
                    return None
                opening = stack.pop()
                if (opening, char) not in {("[", "]"), ("{", "}")}:
                    return None
                if not stack:
                    return text[start_index : index + 1]
        index += 1
    return None


def _lookup_next_flight_window_index(
    combined: str, raw_url: str, page_url: str
) -> int | None:
    candidates: list[str] = []
    for candidate in (
        str(raw_url or "").strip(),
        urljoin(page_url, str(raw_url or "").strip()),
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    raw_path = urlparse(str(raw_url or "").strip()).path.strip()
    if raw_path and raw_path not in candidates:
        candidates.append(raw_path)

    for candidate in candidates:
        lookup_index = combined.find(candidate)
        if lookup_index != -1:
            return lookup_index
    return None


def _normalize_generic_item(item: dict, _surface: str, page_url: str) -> dict | None:
    """Map an arbitrary dict to canonical fields using alias matching."""
    if _looks_like_listing_variant_option(item, surface=_surface):
        return None
    product_search_record = _normalize_product_search_item(item, page_url=page_url)
    if product_search_record:
        product_search_record["_raw_item"] = item
        return product_search_record

    record: dict = {}

    for canonical, aliases in FIELD_ALIASES.items():
        values = [
            *_preferred_generic_item_values(item, canonical, surface=_surface),
            *_find_alias_values(item, [canonical, *aliases], max_depth=4),
        ]
        for value in values:
            normalized = _normalize_listing_value(canonical, value, page_url=page_url)
            if normalized in (None, "", [], {}):
                continue
            record[canonical] = normalized
            break

    if record.get("image_url") in (None, "", [], {}) and record.get(
        "additional_images"
    ) not in (
        None,
        "",
        [],
        {},
    ):
        image_candidates = [
            part.strip()
            for part in str(record["additional_images"]).split(",")
            if part.strip()
        ]
        if image_candidates:
            record["image_url"] = image_candidates[0]
            if len(image_candidates) > 1:
                record["additional_images"] = ", ".join(image_candidates[1:])
            else:
                record.pop("additional_images", None)

    if record.get("url") in (None, "", [], {}) and record.get("slug") not in (
        None,
        "",
        [],
        {},
    ):
        slug_url = _resolve_slug_url(str(record["slug"]), page_url=page_url)
        if slug_url:
            record["url"] = slug_url

    if "ecommerce" in str(_surface or "").lower() and record.get("url") in (
        None,
        "",
        [],
        {},
    ):
        harvested = _harvest_product_url_from_item(item, page_url=page_url)
        if harvested:
            record["url"] = harvested

    record = _apply_surface_record_contract(
        record, surface=_surface, raw_item=item, page_url=page_url
    )

    if (
        "job" not in str(_surface or "").lower()
        and record.get("price") not in (None, "", [], {})
        and record.get("currency")
        in (
            None,
            "",
            [],
            {},
        )
    ):
        inferred_currency = _infer_currency_from_page_url(page_url)
        if inferred_currency:
            record["currency"] = inferred_currency

    slug_url = _resolve_slug_url(str(record.get("slug") or ""), page_url=page_url)
    if (
        "ecommerce" in _surface
        and record.get("url") in (None, "", [], {})
        and not slug_url
        and record.get("price") in (None, "", [], {})
    ):
        return None

    if record:
        record["_raw_item"] = item
    return record if record else None


def _apply_surface_record_contract(
    record: dict,
    *,
    surface: str,
    raw_item: dict | None = None,
    page_url: str = "",
) -> dict:
    if not record:
        return record

    is_job_surface = "job" in str(surface or "").lower()
    if not is_job_surface:
        return record

    if (
        record.get("price") not in _EMPTY_VALUES
        and record.get("salary") in _EMPTY_VALUES
    ):
        record["salary"] = record.pop("price")
    if record.get("title"):
        normalized_title = _normalize_listing_title_text(record.get("title"))
        if normalized_title:
            record["title"] = normalized_title
    if record.get("job_id") in _EMPTY_VALUES:
        inferred_job_id = _extract_generic_job_identifier(raw_item or {})
        if inferred_job_id:
            record["job_id"] = inferred_job_id
    if record.get("url") in _EMPTY_VALUES:
        synthesized_url = _synthesize_job_detail_url(raw_item or {}, page_url=page_url)
        if synthesized_url:
            record["url"] = synthesized_url
            record.setdefault("apply_url", synthesized_url)

    for commerce_field in (
        "price",
        "sale_price",
        "original_price",
        "currency",
        "image_url",
        "additional_images",
        "sku",
        "part_number",
        "brand",
        "availability",
        "rating",
        "review_count",
    ):
        record.pop(commerce_field, None)
    return record


def _preferred_generic_item_values(
    item: dict, canonical: str, surface: str = ""
) -> list[object]:
    if canonical == "title":
        preferred_keys = (
            "name",
            "title",
            "productName",
            "product_name",
            "headline",
            "job_title",
        )
        return [
            item[key]
            for key in preferred_keys
            if key in item and item[key] not in (None, "", [], {})
        ]
    if canonical == "location" and "job" in str(surface or "").lower():
        preferred_values: list[object] = []
        direct_location = item.get("location")
        if direct_location not in (None, "", [], {}):
            preferred_values.append(direct_location)
        locations = item.get("locations")
        if isinstance(locations, list):
            for location in locations:
                if isinstance(location, dict) and location.get("name") not in (
                    None,
                    "",
                    [],
                    {},
                ):
                    preferred_values.append(location["name"])
                    break
                if location not in (None, "", [], {}):
                    preferred_values.append(location)
                    break
        return preferred_values
    if canonical == "url":
        preferred_keys = (
            "product_full_url",
            "product_short_url",
            "productUrl",
            "product_url",
            "detailUrl",
            "detail_url",
            "applyUrl",
            "apply_url",
            "url",
            "href",
        )
        return [
            item[key]
            for key in preferred_keys
            if key in item and item[key] not in (None, "", [], {})
        ]
    if canonical == "image_url":
        preferred_keys = (
            "imageUrl",
            "image_url",
            "primaryImage",
            "primary_image",
            "product_images",
        )
        return [
            item[key]
            for key in preferred_keys
            if key in item and item[key] not in (None, "", [], {})
        ]
    if canonical == "job_id" and "job" in str(surface or "").lower():
        preferred_keys = (
            "jobId",
            "job_id",
            "jobID",
            "requisitionId",
            "requisition_id",
            "reqId",
            "req_id",
            "postingId",
            "posting_id",
            "openingId",
            "opening_id",
            "id",
        )
        return [
            item[key]
            for key in preferred_keys
            if key in item and item[key] not in (None, "", [], {})
        ]
    if canonical == "category" and "job" in str(surface or "").lower():
        preferred_keys = ("jobCategoryName", "jobCategory", "categoryName", "category")
        return [
            item[key]
            for key in preferred_keys
            if key in item and item[key] not in (None, "", [], {})
        ]
    if canonical == "posted_date" and "job" in str(surface or "").lower():
        preferred_keys = ("postedDate", "PostedDate", "publishDate", "datePosted")
        return [
            item[key]
            for key in preferred_keys
            if key in item and item[key] not in (None, "", [], {})
        ]
    if canonical == "description" and "job" in str(surface or "").lower():
        preferred_keys = ("briefDescription", "BriefDescription", "description", "summary")
        return [
            item[key]
            for key in preferred_keys
            if key in item and item[key] not in (None, "", [], {})
        ]
    return []


def _extract_generic_job_identifier(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    for key in (
        "Id",
        "jobId",
        "job_id",
        "jobID",
        "OpportunityId",
        "opportunityId",
        "requisitionId",
        "requisition_id",
        "RequisitionNumber",
        "reqId",
        "req_id",
        "postingId",
        "posting_id",
        "openingId",
        "opening_id",
        "id",
    ):
        value = item.get(key)
        if value not in _EMPTY_VALUES:
            return " ".join(str(value).split()).strip()
    return ""


def _synthesize_job_detail_url(item: dict, *, page_url: str) -> str:
    if not isinstance(item, dict):
        return ""
    # FIX: Removed dangerous hardcoded _JOB_URL_SYNTHESIS_STRATEGIES dispatch.
    # Site-specific URL synthesis must be handled by proper Adapters (e.g. SaaSHRAdapter).
    return _default_job_detail_url_synthesis(item, page_url=page_url)


def _clean_identifier(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _default_job_detail_url_synthesis(item: dict, *, page_url: str) -> str:
    del item, page_url
    return ""


def _looks_like_listing_variant_option(item: dict, *, surface: str) -> bool:
    if "ecommerce" not in str(surface or "").lower():
        return False
    if any(
        item.get(key) not in (None, "", [], {})
        for key in ("name", "title", "productName", "product_name", "headline")
    ):
        return False

    detail_link = item.get("detailPageLink")
    detail_href = detail_link.get("href") if isinstance(detail_link, dict) else ""
    variant_label = str(
        item.get("label")
        or item.get("labelEn")
        or item.get("labelFr")
        or item.get("color")
        or item.get("colorName")
        or ""
    ).strip()
    variant_id = str(
        item.get("skuId") or item.get("commercialCode") or item.get("twelvenc") or ""
    ).strip()
    image = item.get("image")
    image_src = image.get("src") if isinstance(image, dict) else str(image or "")
    has_swatch_image = "color-swatches" in str(image_src or "").lower()
    has_assets = isinstance(item.get("assets"), list) and bool(item.get("assets"))
    has_price = item.get("price") not in (None, "", [], {})

    return bool(
        detail_href
        and variant_label
        and variant_id
        and has_price
        and (has_swatch_image or has_assets)
    )


def _normalize_product_search_item(item: dict, *, page_url: str) -> dict | None:
    typename = str(item.get("__typename") or "").strip()
    product_number = str(
        item.get("productNumber") or item.get("productKey") or ""
    ).strip()
    name = str(item.get("name") or "").strip()
    attributes = item.get("attributes")
    if (
        typename != "Product"
        or not product_number
        or not name
        or not isinstance(attributes, list)
    ):
        return None

    record: dict[str, object] = {
        "title": name,
        "sku": product_number,
        "description": str(item.get("description") or "").strip() or None,
        "brand": _nested_name(item.get("brand")) or None,
        "url": _product_search_detail_url(item, page_url=page_url) or None,
    }

    image_candidates = _extract_image_candidates(
        _product_search_images(item), page_url=page_url
    )
    if image_candidates:
        record["image_url"] = image_candidates[0]
        if len(image_candidates) > 1:
            record["additional_images"] = ", ".join(image_candidates[1:])

    attribute_values = _product_search_attribute_map(attributes)
    materials = attribute_values.get("material")
    if materials:
        record["materials"] = materials
    dimensions = _product_search_dimensions(attributes)
    if dimensions:
        record["dimensions"] = dimensions
    packaging = attribute_values.get("packaging")
    if packaging:
        record["size"] = packaging

    return {
        key: value for key, value in record.items() if value not in (None, "", [], {})
    } or None


def _product_search_detail_url(item: dict, *, page_url: str) -> str:
    page_origin = ""
    parsed = urlparse(page_url)
    if parsed.scheme and parsed.netloc:
        page_origin = f"{parsed.scheme}://{parsed.netloc}"
    raw_url_candidates = [
        item.get("url"),
        item.get("productUrl"),
        item.get("href"),
    ]
    for candidate in raw_url_candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        return urljoin(page_url, text) if page_origin else text

    brand_key = ""
    brand = item.get("brand")
    if isinstance(brand, dict):
        brand_key = (
            str(brand.get("key") or brand.get("erpKey") or brand.get("name") or "")
            .strip()
            .lower()
        )
    product_key = (
        str(item.get("productKey") or item.get("productNumber") or "").strip().lower()
    )
    if not page_origin or not brand_key or not product_key:
        return ""
    locale_match = re.search(r"/([A-Za-z]{2})/([A-Za-z]{2})/", page_url)
    locale_prefix = (
        f"/{locale_match.group(1)}/{locale_match.group(2)}" if locale_match else ""
    )
    return f"{page_origin}{locale_prefix}/product/{brand_key}/{product_key}"


def _product_search_images(item: dict) -> list[dict | str]:
    images = item.get("images")
    if not isinstance(images, list):
        return []
    normalized: list[dict | str] = []
    for image in images:
        if isinstance(image, dict):
            normalized.append(
                {
                    "url": image.get("largeUrl")
                    or image.get("mediumUrl")
                    or image.get("smallUrl")
                    or image.get("url"),
                }
            )
        elif isinstance(image, str):
            normalized.append(image)
    return normalized


def _product_search_attribute_map(attributes: list[object]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        label = str(attribute.get("label") or "").strip().lower()
        if not label:
            continue
        values = attribute.get("values")
        if not isinstance(values, list):
            continue
        normalized_values = [
            " ".join(str(value or "").replace("&#160;", " ").split()).strip()
            for value in values
            if str(value or "").strip()
        ]
        if normalized_values:
            mapped[label] = " | ".join(normalized_values)
    return mapped


def _product_search_dimensions(attributes: list[object]) -> str:
    dimension_rows: list[str] = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        label = " ".join(
            str(attribute.get("label") or "").replace("&#160;", " ").split()
        ).strip()
        values = attribute.get("values")
        if not label or not isinstance(values, list):
            continue
        if not re.search(
            r"(?:\b(?:o\.d\.|i\.d\.|height|width|depth|diameter|length|thread|size)\b|×)",
            label,
            re.I,
        ):
            continue
        normalized_values = [
            " ".join(str(value or "").replace("&#160;", " ").split()).strip()
            for value in values
            if str(value or "").strip()
        ]
        if normalized_values:
            dimension_rows.append(f"{label}: {' | '.join(normalized_values)}")
    return " | ".join(dimension_rows)


def _is_noise_title(title: str) -> bool:
    """Check if a title is likely navigation, editorial, or UI noise."""
    t = str(title).strip().lower()
    if not t:
        return True

    # 1. Navigation hints (Home, Login, etc.)
    if t in LISTING_NAVIGATION_TITLE_HINTS:
        return True

    # 2. Merchandising prefixes (Shop All, Discover, etc.)
    if t.startswith(LISTING_MERCHANDISING_TITLE_PREFIXES):
        return True

    # 3. Editorial/Ad patterns
    if any(p.search(t) for p in LISTING_EDITORIAL_TITLE_PATTERNS):
        return True

    # 4. Alt text patterns (Front View, Close-up, etc.)
    if LISTING_ALT_TEXT_TITLE_PATTERN and LISTING_ALT_TEXT_TITLE_PATTERN.search(t):
        return True

    # 5. Weak standalone titles
    if t in _WEAK_LISTING_TITLES:
        return True

    return False


def _is_merchandising_record(record: dict) -> bool:
    """Reject fragments that are clearly merchandising or navigation fragments."""
    title = str(record.get("title") or "").strip()
    if not title:
        has_detail_url = bool(str(record.get("url") or "").strip())
        has_visual = record.get("image_url") not in (None, "", [], {})
        has_pricing = record.get("price") not in (None, "", [], {})
        has_company = record.get("company") not in (None, "", [], {})
        return not (has_detail_url and (has_visual or has_pricing or has_company))

    if _is_noise_title(title):
        return True

    return False


def _is_meaningful_listing_record(record: dict, *, surface: str = "") -> bool:
    return _assess_meaningful_listing_record(record, surface=surface)


def _is_meaningful_structured_listing_record(
    record: dict, *, surface: str = ""
) -> bool:
    return _assess_meaningful_structured_listing_record(record, surface=surface)


def _has_strong_ecommerce_listing_signal(record: dict) -> bool:
    public_fields = {
        key: value
        for key, value in record.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    if not public_fields:
        return False

    url_value = str(public_fields.get("url") or "").strip()
    if url_value and _looks_like_detail_record_url(url_value):
        return True

    strong_fields = {
        "price",
        "sale_price",
        "original_price",
        "image_url",
        "additional_images",
        "brand",
        "availability",
        "rating",
        "review_count",
        "color",
        "size",
        "dimensions",
        "materials",
        "part_number",
    }
    if set(public_fields) & strong_fields:
        return True

    if {"sku", "part_number"} & set(public_fields) and {
        "brand",
        "image_url",
        "price",
    } & set(public_fields):
        return True

    return False


def _looks_like_facet_or_filter_url(url_value: str) -> bool:
    parsed = urlparse(url_value)
    query_keys = {
        key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    }
    if query_keys & LISTING_FACET_QUERY_KEYS:
        return True

    path = parsed.path.lower()
    return any(fragment in path for fragment in LISTING_FACET_PATH_FRAGMENTS) and bool(
        parsed.query
    )


def _looks_like_category_url(url_value: str) -> bool:
    """Detect category/hub/navigation URLs that link to sub-categories, not items."""
    parsed = urlparse(str(url_value or "").strip())
    path = parsed.path.lower().rstrip("/")
    if not path:
        return False
    # Paths like /products/cell-culture, /categories/electronics are category hubs.
    # Paths like /product/sigma/nuc101 or /products/detail/123 are NOT.
    for prefix in LISTING_DETAIL_PATH_MARKERS:
        if prefix in path:
            return False
    segments = [s for s in path.split("/") if s]
    # Need at least 2 path segments to be a category (e.g., /products/electronics)
    if len(segments) < 2:
        return False
    # Check if any segment is a category directory marker and has a
    # human-readable sub-category slug after it (no SKU/ID patterns).
    last = segments[-1]
    for i, seg in enumerate(segments[:-1]):
        if seg in LISTING_CATEGORY_PATH_MARKERS and i + 1 < len(segments):
            # The segment after the marker should be a readable slug, not an item ID
            if re.fullmatch(r"[a-z][a-z0-9\-]+", last) and len(last) < 60:
                return True
    return False


def _looks_like_listing_hub_url(url_value: str) -> bool:
    parsed = urlparse(str(url_value or "").strip())
    path = parsed.path.lower().rstrip("/")
    if not path:
        return bool(parsed.query)
    if _looks_like_facet_or_filter_url(url_value) or _looks_like_category_url(
        url_value
    ):
        return True
    if _looks_like_detail_record_url(url_value):
        return False
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return True
    normalized_segments = [segment.lower().replace("-", "") for segment in segments]
    if any(segment in LISTING_HUB_PATH_SEGMENTS for segment in normalized_segments):
        return True
    if len(segments) <= 2 and parsed.query:
        return True
    return False


def _looks_like_detail_record_url(url_value: str) -> bool:
    lowered = str(url_value or "").lower()
    if not lowered.startswith("http"):
        return False
    if _looks_like_facet_or_filter_url(lowered):
        return False
    if _looks_like_category_url(lowered):
        return False
    return any(marker in lowered for marker in LISTING_DETAIL_PATH_MARKERS)


def _filter_relevant_network_record_set(
    records: list[dict],
    *,
    payload_url: str,
    page_url: str,
    surface: str,
) -> list[dict]:
    if not records or "job" in str(surface or "").lower():
        return records
    if _is_social_listing_url(payload_url):
        return []
    if _hosts_look_related(payload_url, page_url):
        return records

    relevant_records = [
        record
        for record in records
        if _record_url_matches_listing_page(record, page_url=page_url)
    ]
    if len(relevant_records) >= MIN_VIABLE_RECORDS:
        return relevant_records
    return []


def _record_url_matches_listing_page(record: dict, *, page_url: str) -> bool:
    record_url = str(record.get("url") or record.get("apply_url") or "").strip()
    if not record_url:
        return False
    if _is_social_listing_url(record_url):
        return False
    if not _hosts_look_related(record_url, page_url):
        return False
    has_primary_listing_data = any(
        record.get(field_name) not in _EMPTY_VALUES
        for field_name in ("title", "price", "brand")
    )
    return _looks_like_detail_record_url(record_url) or has_primary_listing_data


def _is_social_listing_url(value: str) -> bool:
    host = urlparse(str(value or "").strip()).netloc.lower()
    if not host:
        return False
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in _LISTING_SOCIAL_HOST_SUFFIXES
    )


def _hosts_look_related(left: str, right: str) -> bool:
    def _host_like_value(value: str) -> str:
        raw = str(value or "").strip().lower()
        parsed_host = urlparse(raw).netloc.lower()
        if parsed_host:
            return parsed_host
        if re.fullmatch(r"[a-z0-9.-]+", raw) and "." in raw and ".." not in raw:
            return raw
        return ""

    left_host = _host_like_value(left)
    right_host = _host_like_value(right)
    if not left_host or not right_host:
        return False
    if left_host == right_host:
        return True
    if left_host.endswith(f".{right_host}") or right_host.endswith(f".{left_host}"):
        return True
    left_tokens = _listing_host_tokens(left_host)
    right_tokens = _listing_host_tokens(right_host)
    return len(left_tokens & right_tokens) >= 2


def _listing_host_tokens(host: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(host or "").lower())
        if len(token) >= 2 and token not in _LISTING_HOST_TOKEN_STOPWORDS
    }


def _looks_like_navigation_or_action_title(title: str, url: str = "") -> bool:
    lowered = (title or "").strip().lower()
    if not lowered:
        return True
    if lowered in LISTING_NAVIGATION_TITLE_HINTS:
        return True
    if re.fullmatch(r"(?:next|previous|prev|back)(?:\s+\W+)?", lowered):
        return True
    if re.fullmatch(r"[a-z0-9.-]+\.(?:com|net|org|io|co|ai|in|uk)", lowered):
        return True
    lowered_url = url.lower().strip()
    if lowered in {"login", "log in", "sign in"} and "/login" in lowered_url:
        return True
    return False


def _looks_like_alt_text_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(title or "")).strip()
    if not normalized:
        return False
    word_count = len(re.findall(r"[A-Za-z]{2,}", normalized))
    if (
        word_count >= 12
        and LISTING_ALT_TEXT_TITLE_PATTERN
        and LISTING_ALT_TEXT_TITLE_PATTERN.search(normalized)
    ):
        return True
    if len(normalized) >= 95 and ("," in normalized or ";" in normalized):
        return True
    return False


def _looks_like_editorial_or_taxonomy_title(
    title: str, url: str = "", price: str = ""
) -> bool:
    lowered = title.lower().strip()
    if not lowered:
        return True
    if any(pattern.search(lowered) for pattern in LISTING_EDITORIAL_TITLE_PATTERNS):
        return True
    if lowered.startswith(LISTING_MERCHANDISING_TITLE_PREFIXES) and not price:
        return True
    if re.search(r"\(\d+\)\s*$", title):  # Category headers with counts like (12)
        return True
    return False


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


def is_listing_like_record(record: dict) -> bool:
    """Soft record-quality signal for choosing among candidate record sets."""
    title = str(record.get("title") or "").strip()
    url = str(record.get("url") or "").strip()
    price = str(record.get("price") or "").strip()
    image = str(record.get("image_url") or record.get("image") or "").strip()
    salary = str(record.get("salary") or "").strip()
    company = str(record.get("company") or "").strip()

    if title and _looks_like_navigation_or_action_title(title, url):
        return False
    if title and _looks_like_alt_text_title(title):
        return False
    if title and _looks_like_editorial_or_taxonomy_title(title, url, price):
        return False

    evidence = 0
    if title:
        evidence += 1
    if price or salary:
        evidence += 2
    if image:
        evidence += 1
    if company:
        evidence += 1
    if _looks_like_detail_record_url(url):
        evidence += 2
    elif url and not _looks_like_listing_hub_url(url):
        evidence += 1

    return evidence >= 2


# ---------------------------------------------------------------------------
# DOM card detection (original strategy, now a fallback)
# ---------------------------------------------------------------------------


def _auto_detect_cards(soup: BeautifulSoup, surface: str = "") -> tuple[list[Tag], str]:
    """Find repeated record roots around detail links, then fall back to container scans."""
    repeated_link_cards, repeated_selector = _detect_repeated_link_card_roots(
        soup,
        surface=surface,
    )
    if repeated_link_cards:
        return repeated_link_cards, repeated_selector

    soup_copy = deepcopy(soup)
    for noise_el in soup_copy.select(
        "aside, nav, [class*='filter' i], [class*='facet' i], "
        "[class*='sidebar' i], [class*='breadcrumb' i], "
        "[class*='navigation' i], [class*='menu' i], footer, header"
    ):
        noise_el.decompose()

    best_cards: list[Tag] = []
    best_selector = ""
    best_score: tuple[float, int] = (_MIN_CARD_SIGNAL_RATIO, 0)

    PRIMARY_CONTAINER_SELECTOR = (
        "ul, ol, div.grid, div.row, div[class*='results'], "
        "div[class*='product'], div[class*='listing'], div[class*='search'], "
        "div[class*='tile'], div[class*='card']"
    )
    FALLBACK_CONTAINER_SELECTOR = "main, section"

    def _scan_containers(containers: list[Tag]) -> None:
        nonlocal best_cards, best_selector, best_score
        min_group_size = 2
        for container in containers:
            children = [c for c in container.children if isinstance(c, Tag)]
            if len(children) < min_group_size:
                continue
            tag_classes: dict[tuple, list[Tag]] = {}
            for child in children:
                key = (child.name, tuple(sorted(child.get("class", []))))
                tag_classes.setdefault(key, []).append(child)
            for key, group in tag_classes.items():
                if len(group) < min_group_size:
                    continue
                score = _card_group_score(group, surface=surface)
                if score > best_score:
                    best_cards = group
                    best_score = score
                    classes = ".".join(key[1]) if key[1] else ""
                    best_selector = f"{key[0]}.{classes}" if classes else key[0]

    _scan_containers(soup_copy.select(PRIMARY_CONTAINER_SELECTOR))
    if not best_cards:
        _scan_containers(soup_copy.select(FALLBACK_CONTAINER_SELECTOR))

    if best_cards:
        return best_cards, best_selector

    selectors = (
        CARD_SELECTORS_COMMERCE
        if "commerce" in surface or "ecommerce" in surface
        else CARD_SELECTORS_JOBS
    )
    for selector in selectors:
        found = soup_copy.select(selector)
        if len(found) >= 2:
            return found, selector
    return best_cards, best_selector


def _card_group_score(group: list[Tag], surface: str = "") -> tuple[float, int]:
    """Score a candidate card group by product-like signals.

    Returns (signal_ratio, count) so groups with higher signal density win,
    with count as a tiebreaker.
    """
    signals = 0.0
    normalized_surface = str(surface or "").lower()
    is_commerce = "commerce" in normalized_surface
    is_job = "job" in normalized_surface
    for el in group[:30]:  # sample first 30
        has_link = bool(el.select_one("a[href]"))
        has_image = bool(el.select_one("img, picture, [style*='background-image']"))
        has_price = bool(
            el.select_one("[itemprop='price'], .price, [class*='price'], .amount")
        )
        has_heading = bool(el.select_one("h1, h2, h3, h4, h5, [class*='title' i]"))
        text = el.get_text(" ", strip=True)
        has_substantial_text = len(text) > 40
        has_multi_elements = (
            len([child for child in el.children if isinstance(child, Tag)]) > 1
        )
        if not has_link:
            continue
        if is_commerce:
            if has_image and has_price:
                signals += 1.0
            elif has_image or has_price:
                signals += 0.5
        elif is_job:
            if has_heading and has_multi_elements:
                signals += 1.0
            elif has_heading or has_substantial_text:
                signals += 0.6
        elif has_image or has_price:
            signals += 1.0
        elif has_substantial_text and has_multi_elements:
            signals += 0.4
    sample_size = min(len(group), 30)
    ratio = signals / sample_size if sample_size > 0 else 0.0
    return (ratio, len(group))


_MIN_CARD_SIGNAL_RATIO = 0.45
_PRICE_LIKE_RE = re.compile(r"^[\s$£€¥₹]?\d[\d,.\s]*$")


def _detect_repeated_link_card_roots(
    soup: BeautifulSoup,
    *,
    surface: str,
) -> tuple[list[Tag], str]:
    min_group_size = 2
    grouped: dict[tuple[str, tuple[str, ...]], list[Tag]] = {}

    for link in soup.select("a[href]"):
        href = str(link.get("href") or "").strip()
        if not _looks_like_card_link_href(href):
            continue
        current: Tag | None = link
        for _depth in range(4):
            current = current.parent if isinstance(current.parent, Tag) else None
            if not isinstance(current, Tag) or current.name in {"body", "html"}:
                break
            signature = (
                current.name,
                tuple(
                    sorted(
                        class_name
                        for class_name in current.get("class", [])
                        if class_name
                    )
                ),
            )
            grouped.setdefault(signature, []).append(current)

    best_cards: list[Tag] = []
    best_selector = ""
    best_score: tuple[float, int] = (_MIN_CARD_SIGNAL_RATIO, 0)
    for signature, group in grouped.items():
        deduped = _dedupe_card_tags(group)
        if len(deduped) < min_group_size:
            continue
        score = _card_group_score(deduped, surface=surface)
        if score > best_score:
            best_cards = deduped
            class_selector = ".".join(signature[1])
            best_selector = (
                f"{signature[0]}.{class_selector}" if class_selector else signature[0]
            )
            best_score = score
    return best_cards, best_selector


def _dedupe_card_tags(tags: list[Tag]) -> list[Tag]:
    deduped: list[Tag] = []
    seen: set[int] = set()
    for tag in tags:
        identity = id(tag)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(tag)
    return deduped


def _looks_like_card_link_href(href: str) -> bool:
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    lowered = href.lower()
    if _looks_like_facet_or_filter_url(lowered):
        return False
    if any(marker in lowered for marker in LISTING_DETAIL_PATH_MARKERS):
        return True
    parsed = urlparse(lowered)
    path = parsed.path.strip("/")
    if not path:
        return False
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        return False
    if _looks_like_category_url(f"https://example.com/{path}"):
        return False
    return not _looks_like_listing_hub_url(f"https://example.com/{path}")


def _best_card_link(card: Tag, page_url: str) -> str:
    fallback = ""
    for link_el in card.select("a[href]"):
        href = str(link_el.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        resolved = urljoin(page_url, href) if page_url else href
        if not fallback:
            fallback = resolved
        parsed_path = urlparse(resolved).path.lower()
        if any(marker in parsed_path for marker in LISTING_DETAIL_PATH_MARKERS):
            return resolved
    return fallback


def _extract_from_card(
    card: Tag, _target_fields: set[str], surface: str, page_url: str
) -> dict:
    """Extract field values from a single listing card element."""
    record: dict = {}
    is_job_surface = "job" in surface

    if "ecommerce" in surface:
        _extract_ecommerce_price_fields(card, record)

    _extract_card_title(card, record)
    if "title" not in record and "job" not in surface:
        inferred_title = _infer_listing_title_from_links(card)
        if inferred_title:
            record["title"] = _normalize_listing_title_text(inferred_title)

    url = _best_card_link(card, page_url)
    if url:
        record["url"] = url
    if "title" not in record:
        inferred_title = _infer_job_title_from_links(card)
        if inferred_title:
            record["title"] = _normalize_listing_title_text(inferred_title)

    if not is_job_surface:
        _extract_card_image_fields(card, record, page_url=page_url)

    # Brand
    brand_el = card.select_one(".brand, [itemprop='brand'], .product-brand")
    if brand_el:
        record["brand"] = brand_el.get_text(strip=True)

    # Rating
    rating_el = card.select_one(
        "[aria-label*='star'], .rating, [itemprop='ratingValue']"
    )
    if rating_el:
        record["rating"] = (
            rating_el.get("content")
            or rating_el.get("aria-label", "")
            or rating_el.get_text(" ", strip=True)
        )

    review_count_el = card.select_one(
        "[itemprop='reviewCount'], [aria-label*='review'], .review-count, .count"
    )
    if review_count_el:
        record["review_count"] = (
            review_count_el.get("content")
            or review_count_el.get("aria-label", "")
            or review_count_el.get_text(" ", strip=True)
        )

    card_text_lines = _card_text_lines(card)
    identifier_fields = _extract_card_identifiers(card, card_text_lines)
    for field_name, value in identifier_fields.items():
        if value:
            record[field_name] = value
    if "ecommerce" in surface:
        color_text = _extract_card_color(card, card_text_lines)
        if color_text:
            record["color"] = color_text

        size_text = _extract_card_size(card_text_lines)
        if size_text:
            record["size"] = size_text

        dimensions_text = _match_dimensions_line(card_text_lines)
        if dimensions_text:
            record["dimensions"] = dimensions_text
        if record.get("price") and not record.get("currency"):
            inferred_currency = _infer_currency_from_page_url(page_url)
            if inferred_currency:
                record["currency"] = inferred_currency

    if is_job_surface:
        _extract_job_card_fields(card, record, card_text_lines=card_text_lines)
        if record.get("url") and not record.get("apply_url"):
            record["apply_url"] = str(record["url"])
        record.pop("image_url", None)
        record.pop("additional_images", None)

    return record


def _extract_ecommerce_price_fields(card: Tag, record: dict) -> None:
    price_el = card.select_one(
        "[itemprop='price'], .price, .product-price, .a-price .a-offscreen, "
        ".s-item__price, span[data-price], .amount, [class*='price']"
    )
    if price_el:
        raw_price = price_el.get("content") or price_el.get_text(" ", strip=True)
        record["price"] = _clean_price_text(raw_price)
    original_price_el = card.select_one(
        ".original-price, .compare-price, .was-price, .strike, s, del, [data-original-price]"
    )
    if original_price_el:
        raw_op = original_price_el.get("content") or original_price_el.get_text(
            " ", strip=True
        )
        record["original_price"] = _clean_price_text(raw_op)


def _extract_card_title(card: Tag, record: dict) -> None:
    for selector in LISTING_CARD_TITLE_SELECTORS:
        title_el = card.select_one(selector)
        if not title_el:
            continue
        if title_el.name == "meta":
            continue
        text = _extract_listing_title_text(title_el)
        if (
            text
            and not _PRICE_LIKE_RE.match(text)
            and not _LISTING_VARIANT_PROMPT_RE.match(text)
        ):
            record["title"] = _normalize_listing_title_text(text)
            record["_selector_title"] = selector
            return


def _extract_listing_title_text(node: Tag) -> str:
    text = node.get_text(" ", strip=True)
    if text:
        return text
    for attr in ("alt", "title", "aria-label", "content"):
        value = " ".join(str(node.get(attr) or "").split()).strip()
        if value:
            return value
    if node.name != "img":
        image = node.select_one("img[alt], img[title]")
        if image is not None:
            return _extract_listing_title_text(image)
    return ""


def _extract_card_image_fields(card: Tag, record: dict, *, page_url: str) -> None:
    img_el = card.select_one("[itemprop='image']")
    if img_el:
        src = img_el.get("src") or img_el.get("data-src") or img_el.get("content", "")
        if src:
            record["image_url"] = urljoin(page_url, src) if page_url else src
    if "image_url" not in record:
        images = _extract_card_images(card, page_url)
        if images:
            record["image_url"] = images[0]
            if len(images) > 1:
                record["additional_images"] = ", ".join(images[1:])


def _extract_job_card_fields(
    card: Tag,
    record: dict,
    *,
    card_text_lines: list[str],
) -> None:
    metadata_fields = _extract_job_metadata_fields(card)
    company_el = card.select_one(
        ".company, .companyName, [data-testid='company-name'], [data-testid*='company-name'], "
        "[data-testid*='listing-company-name'], [itemprop='publisher'] [itemprop='name'], "
        "[itemprop='hiringOrganization'] [itemprop='name']"
    )
    if company_el:
        company_value = company_el.get("content") or company_el.get_text(
            " ", strip=True
        )
        company_value = " ".join(str(company_value or "").split()).strip()
        if company_value:
            record["company"] = company_value
    location_el = card.select_one(
        ".location, .companyLocation, [data-testid='text-location'], [data-testid*='job-location'], "
        "[data-testid*='listing-job-location'], [itemprop='jobLocation']"
    )
    if location_el:
        location_value = location_el.get("content") or location_el.get_text(
            " ", strip=True
        )
        location_value = " ".join(str(location_value or "").split()).strip()
        if location_value:
            record["location"] = location_value
    salary_el = card.select_one(
        ".salary, .salary-snippet-container, [data-testid*='salary']"
    )
    if salary_el:
        salary_value = " ".join(salary_el.get_text(" ", strip=True).split()).strip()
        if salary_value:
            record["salary"] = salary_value
    for field_name, value in metadata_fields.items():
        if value:
            record.setdefault(field_name, value)
    if not record.get("company") and not record.get("department"):
        inferred_company = _infer_job_company(
            card_text_lines, title=record.get("title")
        )
        if inferred_company:
            record["company"] = inferred_company
    if not record.get("location"):
        inferred_location = _infer_job_location(
            card_text_lines, title=record.get("title")
        )
        if inferred_location:
            record["location"] = inferred_location
    if not record.get("salary"):
        inferred_salary = _infer_job_salary(card_text_lines)
        if inferred_salary:
            record["salary"] = inferred_salary
    inferred_job_type = _infer_job_type(card_text_lines)
    if inferred_job_type:
        record.setdefault("job_type", inferred_job_type)
    inferred_posted_date = _infer_job_posted_date(card_text_lines)
    if inferred_posted_date:
        record.setdefault("posted_date", inferred_posted_date)


def _normalize_listing_value(
    canonical: str, value: object, *, page_url: str
) -> object | None:
    if value in (None, "", [], {}):
        return None
    if canonical == "url":
        if isinstance(value, list):
            valid_urls: list[str] = []
            for item in value:
                normalized_item = _normalize_listing_value(
                    canonical, item, page_url=page_url
                )
                text = str(normalized_item or "").strip()
                if text and not any(token in text for token in ("[{", "{", "[")):
                    valid_urls.append(text)
            deduped_urls = list(dict.fromkeys(valid_urls))
            return deduped_urls[0] if len(deduped_urls) == 1 else None
        resolved = (
            _coerce_nested_text(value, keys=NESTED_URL_KEYS)
            if isinstance(value, dict)
            else value
        )
        text = str(resolved or "").strip()
        if not text or any(token in text for token in ("[{", "{", "[")):
            return None
        if text and page_url and not text.startswith(("http://", "https://", "/")):
            parsed = urlparse(page_url)
            origin = (
                f"{parsed.scheme}://{parsed.netloc}/"
                if parsed.scheme and parsed.netloc
                else page_url
            )
            if "/" not in text or _looks_like_product_short_path(text):
                return urljoin(origin, text)
        return urljoin(page_url, text) if text and page_url else text or None
    if canonical == "image_url":
        images = _extract_image_candidates(value, page_url=page_url)
        return images[0] if images else None
    if canonical == "additional_images":
        images = _extract_image_candidates(value, page_url=page_url)
        if not images:
            return None
        return ", ".join(images[1:] if len(images) > 1 else images)
    if canonical in {"price", "sale_price"} and isinstance(value, dict):
        nested = _coerce_nested_text(value, keys=NESTED_PRICE_KEYS)
        return str(nested).strip() if nested not in (None, "", [], {}) else None
    if canonical == "original_price" and isinstance(value, dict):
        nested = _coerce_nested_text(value, keys=NESTED_ORIGINAL_PRICE_KEYS)
        return str(nested).strip() if nested not in (None, "", [], {}) else None
    if canonical == "currency" and isinstance(value, dict):
        nested = _coerce_nested_text(value, keys=NESTED_CURRENCY_KEYS)
        return str(nested).strip() if nested not in (None, "", [], {}) else None
    if canonical in {"title", "brand"} and isinstance(value, dict):
        nested = _coerce_nested_text(value, keys=NESTED_TEXT_KEYS)
        return str(nested).strip() if nested not in (None, "", [], {}) else None
    if canonical == "category" and isinstance(value, dict):
        nested = _coerce_nested_category(value)
        return nested or None
    if isinstance(value, list):
        scalar_values = []
        for item in value:
            normalized = _normalize_listing_value(canonical, item, page_url=page_url)
            if normalized in (None, "", [], {}):
                continue
            scalar_values.append(str(normalized).strip())
        return ", ".join(scalar_values) if scalar_values else None
    if isinstance(value, dict):
        nested = _coerce_nested_text(value, keys=NESTED_TEXT_KEYS)
        if nested in (None, "", [], {}):
            return None
        return str(nested).strip()
    return str(value).strip() if isinstance(value, str) else value


def _extract_image_candidates(value: object, *, page_url: str = "") -> list[str]:
    if value in (None, "", [], {}):
        return []
    raw_items: list[object]
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]

    images: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        candidate = ""
        if isinstance(item, dict):
            media_type = str(item.get("type") or "").strip().upper()
            if media_type == "VIDEO":
                continue
            candidate = str(
                item.get("url") or item.get("contentUrl") or item.get("src") or ""
            ).strip()
        else:
            candidate = str(item).strip()
        if not candidate:
            continue
        resolved = urljoin(page_url, candidate) if page_url else candidate
        if (
            urlparse(resolved)
            .path.lower()
            .endswith(
                (".woff", ".woff2", ".ttf", ".otf", ".eot", ".css", ".js", ".map")
            )
        ):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        images.append(resolved)
    return images


def _find_alias_values(
    data: object, aliases: list[str], *, max_depth: int
) -> list[object]:
    alias_tokens = {
        _normalized_field_token(alias)
        for alias in aliases
        if _normalized_field_token(alias)
    }
    if not alias_tokens or max_depth <= 0:
        return []

    values: list[object] = []

    def _visit(node: object, depth: int) -> None:
        if depth <= 0 or node in (None, "", [], {}):
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if _normalized_field_token(key) in alias_tokens and value not in (
                    None,
                    "",
                    [],
                    {},
                ):
                    values.append(value)
            for key, value in node.items():
                _visit(value, depth - 1)
            return
        if isinstance(node, list):
            for item in node[:30]:
                _visit(item, depth - 1)

    _visit(data, max_depth)
    return values


def _normalized_field_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _looks_like_product_short_path(value: str) -> bool:
    return bool(
        re.match(
            r"^p(?:/|[.-])[A-Za-z0-9][A-Za-z0-9._/-]*$", str(value or "").strip(), re.I
        )
    )


def _resolve_slug_url(slug: str, *, page_url: str) -> str:
    text = str(slug or "").strip()
    if not text or not page_url:
        return ""
    parsed = urlparse(page_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    if text.startswith(("http://", "https://", "/")):
        return urljoin(page_url, text)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    return urljoin(origin, text)


_PRODUCT_URL_TEMPLATE_KEYS = (
    "urlTemplate",
    "productUrlTemplate",
    "pdpUrlTemplate",
    "itemUrlPattern",
    "urlPattern",
)


def _harvest_product_url_from_item(item: dict, *, page_url: str) -> str:
    """Resolve PDP URLs from nested link objects, templates, or URL-shaped payload keys."""
    if not isinstance(item, dict) or not page_url:
        return ""
    direct = _coerce_listing_product_url_candidate(
        _first_href_from_nested_link(item), page_url
    )
    if direct:
        return direct
    for key in _PRODUCT_URL_TEMPLATE_KEYS:
        tpl = item.get(key)
        if not isinstance(tpl, str) or "{" not in tpl:
            continue
        ident = _primary_commerce_identifier(item)
        if not ident:
            continue
        try:
            filled = tpl.format(
                sku=ident,
                id=ident,
                ID=ident,
                productId=ident,
                product_id=ident,
            )
        except (KeyError, ValueError, IndexError):
            filled = (
                tpl.replace("{sku}", ident)
                .replace("{id}", ident)
                .replace("{ID}", ident)
                .replace("{productId}", ident)
                .replace("{product_id}", ident)
                .replace("{0}", ident)
            )
            # Validate that all placeholders were replaced
            if "{" in filled or "}" in filled or re.search(r"\{[^}]+\}", filled):
                # Unknown placeholders remain, skip this template
                continue
        resolved = _coerce_listing_product_url_candidate(filled, page_url)
        if resolved:
            return resolved
    return _scan_payload_for_product_url(item, page_url, depth=0)


def _primary_commerce_identifier(item: dict) -> str:
    for key in (
        "sku",
        "product_id",
        "productId",
        "item_id",
        "itemId",
        "articleNumber",
        "part_number",
        "styleNumber",
    ):
        val = item.get(key)
        if val not in (None, "", [], {}):
            return str(val).strip()
    return ""


def _first_href_from_nested_link(item: dict) -> str:
    for key in ("link", "links", "urlInfo", "productLink"):
        node = item.get(key)
        if isinstance(node, dict):
            for hk in ("href", "url", "path", "pathname"):
                v = node.get(hk)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return ""


def _coerce_listing_product_url_candidate(text: str, page_url: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    lower = text.lower()
    if any(
        frag in lower
        for frag in ("/product", "/p/", "/pd/", "/item/", "/products/", "/pdps/")
    ):
        return urljoin(page_url, text)
    return ""


def _scan_payload_for_product_url(item: object, page_url: str, depth: int) -> str:
    if depth > 6 or not page_url:
        return ""
    if isinstance(item, dict):
        for k, v in item.items():
            ks = str(k)
            kl = ks.lower()
            if isinstance(v, str) and v.strip():
                if any(
                    token in kl
                    for token in (
                        "producturl",
                        "pdpurl",
                        "itemurl",
                        "canonicalurl",
                        "detailurl",
                        "product_url",
                        "pdp_url",
                    )
                ):
                    got = _coerce_listing_product_url_candidate(v, page_url)
                    if got:
                        return got
            nested = _scan_payload_for_product_url(v, page_url, depth + 1)
            if nested:
                return nested
    elif isinstance(item, list):
        for el in item[:40]:
            nested = _scan_payload_for_product_url(el, page_url, depth + 1)
            if nested:
                return nested
    return ""


def _coerce_nested_text(value: object, *, keys: tuple[str, ...]) -> object | None:
    if not isinstance(value, dict):
        return value
    for key in keys:
        nested = value.get(key)
        if nested not in (None, "", [], {}):
            return nested
    for nested in value.values():
        if isinstance(nested, dict):
            resolved = _coerce_nested_text(nested, keys=keys)
            if resolved not in (None, "", [], {}):
                return resolved
    return None


def _coerce_nested_category(value: dict) -> str:
    for key in NESTED_CATEGORY_KEYS:
        nested = value.get(key)
        if isinstance(nested, list):
            parts = [str(part).strip() for part in nested if str(part).strip()]
            if parts:
                return " | ".join(parts)
        if nested not in (None, "", [], {}):
            return str(nested).strip()
    return ""


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


def _extract_card_images(card: Tag, page_url: str) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()
    swatch_containers = {
        id(node)
        for selector in LISTING_SWATCH_CONTAINER_SELECTORS
        for node in card.select(selector)
    }
    for img_el in card.select("img"):
        parent = img_el.parent
        skip_image = False
        while parent and parent is not card:
            if id(parent) in swatch_containers:
                skip_image = True
                break
            parent = parent.parent
        if skip_image:
            continue
        src = (
            img_el.get("src")
            or img_el.get("data-src")
            or img_el.get("data-original")
            or img_el.get("srcset", "").split(",")[0].strip().split(" ")[0]
        )
        if not src:
            continue
        resolved = urljoin(page_url, src) if page_url else src
        lowered_resolved = resolved.lower()
        if any(token in lowered_resolved for token in LISTING_IMAGE_EXCLUDE_TOKENS):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        images.append(resolved)
    return images


_PRICE_WITH_CURRENCY_RE = re.compile(r"[\$£€¥₹]\s*\d[\d,.\s]*")
_PRICE_EXTRACT_RE = re.compile(r"[\$£€¥₹]?\s*\d[\d,.\s]*")
_MEASUREMENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:\"|in|cm|mm|ft)\b", re.I)
_DIMENSION_TOKEN_RE = re.compile(
    r"\b(?:h\s*x|w\s*x|d\s*x|height|width|depth|diameter)\b", re.I
)


@lru_cache(maxsize=64)
def _compile_case_insensitive_regex(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


def _clean_price_text(raw: str) -> str:
    """Extract the price portion from a string that may include surrounding text."""
    raw = raw.strip()
    # Prefer match with currency symbol
    m = _PRICE_WITH_CURRENCY_RE.search(raw)
    if m:
        return m.group(0).strip()
    m = _PRICE_EXTRACT_RE.search(raw)
    return m.group(0).strip() if m else raw


def _card_text_lines(card: Tag) -> list[str]:
    lines: list[str] = []
    for text in card.stripped_strings:
        cleaned = " ".join(str(text).split()).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _match_line(lines: list[str], pattern: str) -> str:
    regex = _compile_case_insensitive_regex(pattern)
    for line in lines:
        if regex.search(line):
            return line
    return ""


def _match_dimensions_line(lines: list[str]) -> str:
    for line in lines:
        if _DIMENSION_TOKEN_RE.search(line):
            return line
        if _MEASUREMENT_RE.search(line):
            return line
    return ""


def _infer_job_title_from_links(card: Tag) -> str:
    for link_el in card.select("a[href]"):
        href = str(link_el.get("href") or "").strip()
        if not href:
            continue
        candidate = link_el.get_text(" ", strip=True)
        if not candidate:
            continue
        candidate = re.sub(r"\([0-9a-f]{24,}\)$", "", candidate, flags=re.I).strip()
        if not candidate or len(candidate) < 4:
            continue
        if _PRICE_LIKE_RE.match(candidate):
            continue
        if candidate.lower() in {"apply now", "easy apply", "company logo", "save job"}:
            continue
        if _looks_like_detail_record_url(href):
            return candidate
    for link_el in card.select("a[href]"):
        href = str(link_el.get("href") or "").strip()
        if not href:
            continue
        candidate = str(link_el.get("aria-label") or "").strip()
        candidate = re.sub(r"(?i)^view details for\s+", "", candidate).strip()
        candidate = re.sub(r"\([0-9a-f]{24,}\)$", "", candidate, flags=re.I).strip()
        if not candidate or len(candidate) < 4:
            continue
        if candidate.lower() in {"apply now", "easy apply", "company logo", "save job"}:
            continue
        if _looks_like_detail_record_url(href):
            return candidate
    return ""


def _infer_listing_title_from_links(card: Tag) -> str:
    for link_el in card.select("a[href]"):
        candidate = link_el.get_text(" ", strip=True)
        if not candidate or len(candidate) < 3:
            continue
        if _PRICE_LIKE_RE.match(candidate):
            continue
        if _looks_like_navigation_or_action_title(
            candidate, str(link_el.get("href") or "")
        ):
            continue
        return candidate
    for link_el in card.select("a[aria-label]"):
        candidate = str(link_el.get("aria-label") or "").strip()
        if not candidate or len(candidate) < 3:
            continue
        if _looks_like_navigation_or_action_title(
            candidate, str(link_el.get("href") or "")
        ):
            continue
        return candidate
    return ""


def _infer_job_company(lines: list[str], *, title: object = None) -> str:
    title_text = str(title or "").strip()
    for line in lines:
        if not line or line == title_text:
            continue
        if line.startswith((",", ";", ":", "-", "/")):
            continue
        if _infer_job_location([line], title=title):
            continue
        if _infer_job_salary([line]):
            continue
        if _infer_job_type([line]):
            continue
        if _infer_job_posted_date([line]):
            continue
        lowered = line.lower()
        if lowered in {
            "apply now",
            "save job",
            "sponsored",
            "today",
            "yesterday",
            "no comments",
        }:
            continue
        if lowered in {
            "location",
            "locations",
            "posted on",
            "posted",
            "job id",
            "job number",
            "requisition",
        }:
            continue
        if re.search(r"(?i)\b\d+\s+locations?\b", line):
            continue
        if re.match(r"^[A-Z]{2,4}\s*-\s*[A-Za-z]", line):
            continue
        if any(
            token in lowered
            for token in (
                "comment",
                "read more",
                "purpose:",
                "responsible for",
                "responsibilities",
            )
        ):
            continue
        if re.fullmatch(r"[A-Z]\d{4,}", line):
            continue
        if lowered.endswith(":") and len(line) <= 40:
            continue
        if len(line) <= 60:
            return line
    return ""


def _infer_job_location(lines: list[str], *, title: object = None) -> str:
    title_text = str(title or "").strip()
    for line in lines:
        lowered = line.lower()
        if not line or line == title_text:
            continue
        if line.startswith((",", ";", ":", "-", "/")):
            continue
        if title_text and title_text.lower() in lowered:
            continue
        if lowered == "multiple locations":
            return line
        if re.search(r"(?i)\b\d+\s+locations?\b", line):
            return line
        if re.match(r"^[A-Z]{2,4}\s*-\s*[A-Za-z]", line):
            return line
        if any(token in lowered for token in ("remote", "hybrid", "on-site", "onsite")):
            return line
        if any(
            token in lowered
            for token in (
                "purpose:",
                "responsible for",
                "responsibilities",
                "read more",
                "comment",
            )
        ):
            continue
        if len(line) > 80:
            continue
        if (
            "," in line
            and re.search(r"[A-Za-z].*,\s*[A-Za-z]", line)
            and not _infer_job_salary([line])
            and not _infer_job_posted_date([line])
        ):
            return line
    return ""


def _infer_job_salary(lines: list[str]) -> str:
    salary_pattern = re.compile(
        r"(?i)(?:(?:[$€£₹]|usd|eur|gbp|inr)\s*\d.*(?:/|\bper\b)\s*(?:hr|wk|mo|yr|hour|day|week|month|year)\b)|"
        r"(?:(?:[$€£₹]|usd|eur|gbp|inr)\s*\d[\d,.\s]*/(?:hr|wk|mo|yr)\b(?:\s*est)?)|"
        r"(?:(?:[$€£₹]|usd|eur|gbp|inr)\s*\d.*(?:salary|compensation|annual))|"
        r"(?:\d[\d,]*(?:\.\d+)?\s*(?:/|\bper\b)\s*(?:hr|wk|mo|yr|hour|day|week|month|year)\b)"
    )
    for line in lines:
        match = salary_pattern.search(line)
        if match:
            return " ".join(match.group(0).split()).strip()
    return ""


def _extract_job_metadata_fields(card: Tag) -> dict[str, str]:
    fields: dict[str, str] = {}

    for container in card.select("dt"):
        label = " ".join(container.get_text(" ", strip=True).split()).strip()
        value_node = container.find_next("dd")
        value = (
            " ".join(value_node.get_text(" ", strip=True).split()).strip()
            if value_node is not None
            else ""
        )
        if not label or not value:
            continue
        _assign_job_metadata_field(fields, label=label, value=value)

    for container in card.select("p, div, span"):
        icon = container.find(["img", "i"], recursive=False)
        if icon is None:
            continue
        text = " ".join(container.get_text(" ", strip=True).split()).strip()
        if not text or len(text) > 120:
            continue
        marker = " ".join(
            part
            for part in (
                icon.get("src"),
                icon.get("alt"),
                icon.get("title"),
                icon.get("aria-label"),
                " ".join(icon.get("class", [])),
            )
            if part
        )
        _assign_job_metadata_field(fields, label=marker, value=text)

    return fields


def _assign_job_metadata_field(
    fields: dict[str, str], *, label: str, value: str
) -> None:
    normalized_label = re.sub(r"[^a-z0-9]+", " ", str(label or "").lower()).strip()
    normalized_value = " ".join(str(value or "").split()).strip()
    if not normalized_label or not normalized_value:
        return

    if any(
        token in normalized_label for token in ("location", "map marker", "address")
    ):
        fields.setdefault("location", normalized_value)
        return
    if any(token in normalized_label for token in ("job location",)):
        fields.setdefault("location", normalized_value)
        return
    if any(
        token in normalized_label for token in ("salary", "pay", "compensation")
    ) or (len(normalized_value) <= 40 and _infer_job_salary([normalized_value])):
        fields.setdefault("salary", normalized_value)
        return
    if any(
        token in normalized_label
        for token in ("employment type", "job type", "suitcase", "shift")
    ):
        fields.setdefault(
            "job_type", _infer_job_type([normalized_value]) or normalized_value
        )
        return
    if any(
        token in normalized_label
        for token in ("department", "division", "team", "category", "sitemap")
    ):
        fields.setdefault("department", normalized_value)
        return
    if any(
        token in normalized_label
        for token in ("job number", "job id", "requisition", "identifier")
    ):
        fields.setdefault("job_id", normalized_value)
        return
    if "start" in normalized_label:
        fields.setdefault("start_date", normalized_value.removeprefix("Start:").strip())


def _infer_job_type(lines: list[str]) -> str:
    job_type_pattern = re.compile(
        r"(?i)\b(full[- ]?time|part[- ]?time|contract|temporary|internship|intern|freelance|permanent)\b"
    )
    for line in lines:
        match = job_type_pattern.search(line)
        if match:
            return match.group(1)
    return ""


def _infer_job_posted_date(lines: list[str]) -> str:
    posted_pattern = re.compile(
        r"(?i)\b(posted\s+\d+\s+(?:minute|hour|day|week|month)s?\s+ago|"
        r"posted\s+(?:today|yesterday)|today|yesterday|\d+\s+(?:minute|hour|day|week|month)s?\s+ago)\b"
    )
    for line in lines:
        match = posted_pattern.search(line)
        if match:
            return match.group(0)
    return ""


def _normalize_listing_title_text(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    text = re.sub(r"\s+([,;:/|])", r"\1", text)
    text = re.sub(r"([(/])\s+", r"\1", text)
    text = re.sub(r"\s+([)])", r"\1", text)
    text = re.sub(r"\s*[,;/|:-]+\s*$", "", text).strip()
    return text


def _extract_card_color(card: Tag, lines: list[str]) -> str:
    swatch_selectors = [
        "[data-color]",
        "[data-color-name]",
        "[data-testid*='color' i]",
        "[aria-label*='color' i]",
        "[title*='color' i]",
        "[class*='swatch'] [aria-label]",
        "[class*='swatch'][aria-label]",
        "[role='radio'][aria-label]",
        "button[aria-label]",
    ]
    for selector in swatch_selectors:
        for node in card.select(selector):
            color = _extract_color_label_from_node(node)
            if color:
                return color

    # Fallback: try to extract value after "Color:" or "Colors:" label
    # Avoid returning just the label itself (e.g., "2 colors" or "Color")
    color_line = _match_line(lines, r"\bcolors?\b")
    if color_line:
        # Try to extract actual color value after colon
        match = re.search(r"(?i)colors?\s*[:\-]\s*(.+)", color_line)
        if match:
            color_value = match.group(1).strip()
            # Filter out generic phrases like "2 colors", "multiple colors"
            if not re.match(r"^\d+\s+colors?$", color_value, re.I):
                return color_value
    return ""


_GENERIC_SIZE_VALUE_RE = re.compile(r"^(multiple|various)\s+sizes?$", re.I)
_SIZE_VALUE_SIGNAL_RE = re.compile(
    r"\b(?:[SMLX]{1,3}|[0-9]+(?:\.[0-9]+)?(?:\s*(?:in|cm|mm|oz|lb|kg|g))?)\b",
    re.I,
)


def _extract_card_size(lines: list[str]) -> str:
    size_line = _match_line(lines, r"\bsizes?\b")
    if not size_line:
        return ""
    match = re.search(r"(?i)sizes?\s*[:\-]\s*(.+)", size_line)
    if match:
        size_value = match.group(1).strip()
        if not _GENERIC_SIZE_VALUE_RE.match(size_value):
            return size_value
        return ""
    if _SIZE_VALUE_SIGNAL_RE.search(size_line):
        cleaned = re.sub(r"(?i)^sizes?\s*[:\-]?\s*", "", size_line).strip()
        if cleaned and cleaned.lower() not in {"size", "sizes"}:
            return cleaned
    return ""


def _extract_color_label_from_node(node: Tag) -> str:
    candidate_values = [
        node.get("data-color"),
        node.get("data-color-name"),
        node.get("aria-label"),
        node.get("title"),
        node.get_text(" ", strip=True),
    ]
    for raw_value in candidate_values:
        text = " ".join(str(raw_value or "").split()).strip()
        if not text:
            continue
        text = re.sub(r"(?i)^(selected\s+)?colors?\s*[:\-]\s*", "", text).strip()
        text = re.sub(
            r"(?i)^(view|select|choose)\s+colors?\s*[:\-]?\s*", "", text
        ).strip()
        text = re.sub(r"(?i)\b(?:button|swatch|option)$", "", text).strip(" -,:;/")
        if not text:
            continue
        lowered = text.lower()
        if lowered in {"color", "colors", "select color", "choose color"}:
            continue
        if "fits your vehicle" in lowered:
            continue
        if lowered in LISTING_COLOR_ACTION_VALUES or any(
            lowered.startswith(prefix) for prefix in LISTING_COLOR_ACTION_PREFIXES
        ):
            continue
        if len(text) > 40:
            continue
        return text
    return ""


def _extract_card_identifiers(card: Tag, lines: list[str]) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    selector_map = {
        "part_number": (
            "[data-testid='product-part-number']",
            "[data-testid*='part-number' i]",
        ),
        "sku": (
            "[data-testid='product-sku-number']",
            "[data-testid*='sku-number' i]",
            "[itemprop='sku']",
        ),
    }
    for field_name, selectors in selector_map.items():
        for selector in selectors:
            node = card.select_one(selector)
            if node is None:
                continue
            text = " ".join(node.get_text(" ", strip=True).split())
            match = re.search(r"#\s*([A-Z0-9-]+)\b", text, re.I)
            if match:
                identifiers[field_name] = match.group(1)
                break

    joined_lines = " ".join(lines)
    if not identifiers.get("part_number"):
        match = re.search(r"(?i)\bpart\s*#\s*([A-Z0-9-]+)\b", joined_lines)
        if match:
            identifiers["part_number"] = match.group(1)
    if not identifiers.get("sku"):
        match = re.search(r"(?i)\bsku\s*#\s*([A-Z0-9-]+)\b", joined_lines)
        if match:
            identifiers["sku"] = match.group(1)
    if not identifiers.get("job_id"):
        match = re.search(
            r"(?i)\b(?:job\s*(?:id|number)|requisition(?:\s*(?:id|number))?|req(?:uisition)?\s*#?)[:#\s-]*([A-Z]?\d{4,})\b",
            joined_lines,
        )
        if match:
            identifiers["job_id"] = match.group(1)
    if not identifiers.get("job_id"):
        for line in lines:
            candidate = str(line or "").strip()
            if re.fullmatch(r"[A-Z]?\d{4,}", candidate):
                identifiers["job_id"] = candidate
                break
    detail_link = card.select_one("a[href]")
    href = (
        str(detail_link.get("href") or "").strip()
        if isinstance(detail_link, Tag)
        else ""
    )
    if href and not identifiers.get("id"):
        tail = urlparse(href).path.rstrip("/").split("/")[-1]
        if re.fullmatch(r"[0-9]{4,}", tail):
            identifiers["id"] = tail
            lowered_href = href.lower()
            if "job" in lowered_href or "career" in lowered_href:
                identifiers.setdefault("job_id", tail)
    return identifiers


def _infer_currency_from_page_url(page_url: str) -> str:
    lowered = str(page_url or "").strip().lower()
    if not lowered:
        return ""
    for token, currency in PAGE_URL_CURRENCY_HINTS.items():
        if token in lowered:
            return currency
    return ""
