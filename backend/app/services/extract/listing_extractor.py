# Listing page extractor — finds repeating cards and extracts N records.
#
# Strategy order:
#   1. JSON-LD item lists (structured data)
#   2. Embedded app state (__NEXT_DATA__, hydrated state)
#   3. Network payloads (XHR/fetch intercepted JSON arrays)
#   4. DOM card detection (CSS selectors + auto-detect)
from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.services.pipeline_config import (
    CARD_SELECTORS_COMMERCE,
    CARD_SELECTORS_JOBS,
    COLLECTION_KEYS,
    FIELD_ALIASES,
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_CATEGORY_PATH_MARKERS,
    LISTING_COLOR_ACTION_PREFIXES,
    LISTING_COLOR_ACTION_VALUES,
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
from app.services.discover import DiscoveryManifest, discover_sources
from app.services.xpath_service import bs4_tag_to_xpath, simplify_xpath
_EMPTY_VALUES = (None, "", [], {})
_NUMERIC_ONLY_RE = re.compile(r"^\s*\(?\s*[\d,]+\s*\)?\s*$")
_FILTER_COUNT_RE = re.compile(r"^\s*\(\s*\d[\d,]*\s*\)\s*$")

_WEAK_LISTING_TITLES = LISTING_WEAK_TITLES


def extract_listing_records(
    html: str,
    surface: str,
    target_fields: set[str],
    page_url: str = "",
    max_records: int = 100,
    manifest: DiscoveryManifest | None = None,
) -> list[dict]:
    """Extract multiple records from a listing/category page.

    Uses a structured-data-first strategy:
    1. JSON-LD item lists
    2. Embedded app state (__NEXT_DATA__)
    3. Network payloads
    4. DOM card detection (CSS selectors + auto-detect heuristic)

    Returns:
        List of dicts, one per detected item. Each dict includes
        ``_source`` indicating which strategy produced it.
    """
    page_fragments = _split_paginated_html_fragments(html)
    if len(page_fragments) > 1:
        merged_records: list[dict] = []
        for index, fragment in enumerate(page_fragments):
            fragment_manifest = (
                manifest if index == 0 else discover_sources(html=fragment)
            )
            merged_records.extend(
                _extract_listing_records_single_page(
                    fragment,
                    surface,
                    target_fields,
                    page_url=page_url,
                    max_records=max_records,
                    manifest=fragment_manifest,
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
        manifest=manifest,
    )


def _extract_listing_records_single_page(
    html: str,
    surface: str,
    target_fields: set[str],
    *,
    page_url: str = "",
    max_records: int = 100,
    manifest: DiscoveryManifest | None = None,
) -> list[dict]:
    if manifest is None:
        manifest = discover_sources(html=html)

    candidate_sets: list[list[dict]] = []

    # --- Strategy 1: Structured data sources (from manifest) ---
    if manifest:
        structured_records = _extract_from_structured_sources(
            manifest, surface, page_url
        )
        if len(structured_records) >= 1:
            for record in structured_records:
                record["_source"] = record.get("_source", "structured")
            candidate_sets.append(structured_records)

    next_flight_records = _extract_from_next_flight_scripts(html, page_url)
    if len(next_flight_records) >= 1:
        candidate_sets.append(next_flight_records)

    inline_array_records = _extract_from_inline_object_arrays(html, surface, page_url)
    if len(inline_array_records) >= 1:
        candidate_sets.append(inline_array_records)

    # --- Strategy 2: DOM card detection ---
    soup = BeautifulSoup(html, "html.parser")

    # Try embedded JSON-LD even without manifest (direct HTML parse)
    json_ld_records = _extract_from_json_ld(soup, surface, page_url)
    if len(json_ld_records) >= 2:
        candidate_sets.append(json_ld_records)

    next_data = _extract_next_data_payload(soup)
    if next_data:
        next_data_records = _extract_from_next_data(next_data, surface, page_url)
        if len(next_data_records) >= 2:
            candidate_sets.append(next_data_records)

    selectors = (
        CARD_SELECTORS_COMMERCE
        if "commerce" in surface or "ecommerce" in surface
        else CARD_SELECTORS_JOBS
    )
    if "commerce" in surface or "ecommerce" in surface:
        selectors = [*selectors, "tr.shortcut_navigable", "tr[class*='listing']", "tr[class*='item']"]

    cards: list[Tag] = []
    used_selector = ""
    for sel in selectors:
        found = soup.select(sel)
        if len(found) >= 2:  # need at least 2 to confirm it's a repeating pattern
            cards = found
            used_selector = sel
            break

    # Fallback: auto-detect repeating siblings
    if not cards:
        cards, used_selector = _auto_detect_cards(soup, surface=surface)

    records = []
    for card in cards[:max_records]:
        record = _extract_from_card(card, target_fields, surface, page_url)
        if record and _is_meaningful_listing_record(record):
            record["_source"] = "listing_card"
            record["_selector"] = used_selector
            records.append(record)

    if records:
        candidate_sets.append(records)

    if not candidate_sets:
        return []
    best_records = max(candidate_sets, key=_listing_record_set_sort_key)
    merged_records = _merge_listing_candidate_sets(candidate_sets)
    if merged_records and _listing_record_set_sort_key(
        merged_records
    ) > _listing_record_set_sort_key(best_records):
        return merged_records[:max_records]
    return best_records[:max_records]


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
    url = str(record.get("url") or "").strip().lower()
    if url:
        return f"url:{url}"
    title = str(record.get("title") or "").strip().lower()
    price = str(record.get("price") or "").strip().lower()
    image_url = str(record.get("image_url") or "").strip().lower()
    return f"title:{title}|price:{price}|image:{image_url}"


def _merge_listing_candidate_sets(candidate_sets: list[list[dict]]) -> list[dict]:
    merged_by_key: dict[str, dict] = {}
    ordered_keys: list[str] = []
    normalized_sets = [records for records in candidate_sets if records]
    for records in normalized_sets:
        for record in records:
            key = _listing_record_join_key(record)
            if not key:
                continue
            existing = merged_by_key.get(key)
            if existing is None:
                merged_by_key[key] = dict(record)
                ordered_keys.append(key)
                continue
            merged_by_key[key] = _merge_listing_record(existing, record)
    merged_records = [merged_by_key[key] for key in ordered_keys]
    positional_merges = _merge_listing_candidate_sets_by_position(normalized_sets)
    if not positional_merges:
        return merged_records
    if not merged_records:
        return positional_merges
    if (
        len(positional_merges) >= 2
        and len(positional_merges) <= len(merged_records)
        and _avg_public_field_count(positional_merges) > _avg_public_field_count(merged_records)
    ):
        return positional_merges
    if _listing_record_set_sort_key(positional_merges) >= _listing_record_set_sort_key(
        merged_records
    ):
        return positional_merges
    return _dedupe_listing_records(merged_records + positional_merges)


def _merge_listing_candidate_sets_by_position(
    candidate_sets: list[list[dict]],
) -> list[dict]:
    if len(candidate_sets) < 2:
        return []
    best_records: list[dict] = []
    best_score: tuple[int, int, int, int, int, float, int, int] = (0, 0, 0, 0, 0, 0.0, 0, 0)
    for left_index, left in enumerate(candidate_sets):
        for right in candidate_sets[left_index + 1 :]:
            merged = _merge_listing_pair_by_position(left, right)
            if not merged:
                continue
            score = _listing_record_set_sort_key(merged)
            if score > best_score:
                best_records = merged
                best_score = score
    return best_records


def _merge_listing_pair_by_position(
    primary_records: list[dict], secondary_records: list[dict]
) -> list[dict]:
    if not primary_records or not secondary_records:
        return []
    max_len = max(len(primary_records), len(secondary_records))
    min_len = min(len(primary_records), len(secondary_records))
    if min_len < 2:
        return []
    if max_len - min_len > 2:
        return []
    if min_len / max_len < 0.7:
        return []
    merged: list[dict] = []
    for index in range(min_len):
        record = _merge_listing_record(primary_records[index], secondary_records[index])
        if _is_meaningful_listing_record(record):
            merged.append(record)
    return merged


def _merge_listing_record(primary: dict, secondary: dict) -> dict:
    merged = dict(primary)
    primary_source = str(primary.get("_source") or "").strip()
    secondary_source = str(secondary.get("_source") or "").strip()
    for key, value in secondary.items():
        if key.startswith("_"):
            continue
        if _should_prefer_listing_value(key, merged.get(key), value):
            merged[key] = value
    if (
        primary_source
        and secondary_source
        and secondary_source not in primary_source.split(", ")
    ):
        merged["_source"] = ", ".join([primary_source, secondary_source])
    elif not primary_source and secondary_source:
        merged["_source"] = secondary_source
    return merged


def _should_prefer_listing_value(
    field_name: str, existing: object, candidate: object
) -> bool:
    if candidate in (None, "", [], {}):
        return False
    if existing in (None, "", [], {}):
        return True
    existing_text = str(existing or "").strip()
    candidate_text = str(candidate or "").strip()
    if field_name in {"description", "category"}:
        return len(candidate_text) > len(existing_text)
    if field_name == "additional_images":
        existing_count = len(
            [part for part in existing_text.split(",") if part.strip()]
        )
        candidate_count = len(
            [part for part in candidate_text.split(",") if part.strip()]
        )
        return candidate_count > existing_count
    if field_name == "url":
        return _looks_like_detail_record_url(candidate_text) and not _looks_like_detail_record_url(
            existing_text
        )
    if field_name in {"title", "brand"}:
        return len(candidate_text) > len(existing_text)
    return False


# ---------------------------------------------------------------------------
# Structured source extraction
# ---------------------------------------------------------------------------


def _extract_from_structured_sources(
    manifest: DiscoveryManifest,
    surface: str,
    page_url: str,
) -> list[dict]:
    """Try JSON-LD, __NEXT_DATA__, hydrated states, and network payloads.

    All sources are collected and the richest result (highest average
    public-field count per record) is returned.  This prevents sparse
    JSON-LD ItemLists from short-circuiting richer hydrated-state data.
    """
    candidates: list[list[dict]] = []

    # JSON-LD: look for ItemList or arrays of Product/JobPosting
    ld_records: list[dict] = []
    for payload in manifest.json_ld:
        if isinstance(payload, dict):
            ld_records.extend(_extract_ld_records_from_payload(payload, surface, page_url))
    ld_records = [record for record in ld_records if _is_meaningful_structured_listing_record(record)]

    if ld_records:
        candidates.append(ld_records)

    # __NEXT_DATA__: search for product/job arrays in page props
    if manifest.next_data:
        next_records = _extract_from_next_data(manifest.next_data, surface, page_url)
        next_records = [record for record in next_records if _is_meaningful_structured_listing_record(record)]
        if next_records:
            candidates.append(next_records)

    # Additional hydrated state blobs discovered from inline scripts
    if manifest._hydrated_states:
        for state in manifest._hydrated_states:
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
                    record for record in state_records if _is_meaningful_structured_listing_record(record)
                ]
                if filtered_state_records:
                    candidates.append(filtered_state_records)

    # Network payloads: look for JSON arrays of items
    for payload in manifest.network_payloads:
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
                record for record in net_records if _is_meaningful_structured_listing_record(record)
            ]
            if filtered_net_records:
                candidates.append(filtered_net_records)

    if not candidates:
        return ld_records  # may be 0-1 records

    merged = _merge_structured_record_sets(candidates)
    if merged:
        return merged
    return max(candidates, key=_listing_record_set_sort_key)


def _merge_structured_record_sets(record_sets: list[list[dict]]) -> list[dict]:
    merged_by_key: dict[str, dict] = {}
    ordered_keys: list[str] = []
    for records in record_sets:
        for record in records:
            key = _structured_join_key(record)
            if not key:
                continue
            existing = merged_by_key.get(key)
            if existing is None:
                merged_by_key[key] = {
                    **record,
                    "_sources": [str(record.get("_source") or "structured")],
                }
                ordered_keys.append(key)
                continue
            for field_name, value in record.items():
                if field_name == "_source":
                    continue
                if existing.get(field_name) in (None, "", [], {}) and value not in (
                    None,
                    "",
                    [],
                    {},
                ):
                    existing[field_name] = value
            source_label = str(record.get("_source") or "structured")
            existing_sources = existing.setdefault("_sources", [])
            if source_label not in existing_sources:
                existing_sources.append(source_label)

    merged_records: list[dict] = []
    for key in ordered_keys:
        record = merged_by_key[key]
        sources = list(record.pop("_sources", []))
        if sources:
            record["_source"] = ", ".join(sources)
        merged_records.append(record)
    return merged_records


def _structured_join_key(record: dict) -> str:
    for field_name in ("sku", "url"):
        value = str(record.get(field_name) or "").strip().lower()
        if value:
            return f"{field_name}:{value}"
    title = str(record.get("title") or "").strip().lower()
    price = str(record.get("price") or "").strip().lower()
    if title and price:
        return f"title_price:{title}|{price}"
    salary = str(record.get("salary") or "").strip().lower()
    if title and salary:
        return f"title_salary:{title}|{salary}"
    return ""


def _avg_public_field_count(records: list[dict]) -> float:
    """Average number of non-internal, non-empty fields per record."""
    if not records:
        return 0.0
    total = sum(
        sum(
            1
            for k, v in r.items()
            if not str(k).startswith("_") and v not in (None, "", [], {})
        )
        for r in records
    )
    return total / len(records)


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

    return [record for record in records if _is_meaningful_structured_listing_record(record)]


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
    record["title"] = item.get("name") or ""

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
            record["price"] = _first_present(offers.get("price"), offers.get("lowPrice"), "")
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
        for commerce_field in ("price", "sale_price", "original_price", "currency"):
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
    """Search __NEXT_DATA__ for arrays of product/job objects."""
    candidates = _collect_candidate_record_sets(
        next_data,
        surface,
        page_url,
        depth=0,
        max_depth=max(MAX_JSON_RECURSION_DEPTH + 4, 8),
    )
    if not candidates:
        return []
    best = max(candidates, key=_listing_record_set_sort_key)
    for record in best:
        record["_source"] = "next_data"
    return best


def _extract_items_from_json(
    data: dict | list,
    surface: str,
    page_url: str,
    _depth: int = 0,
    *,
    max_depth: int = MAX_JSON_RECURSION_DEPTH,
) -> list[dict]:
    """Extract items from an arbitrary JSON structure.

    Recursively searches up to ``max_depth`` levels deep for arrays of
    objects that look like product/job collections.
    """
    if _depth > max_depth:
        return []

    candidate_sets = _collect_candidate_record_sets(
        data,
        surface,
        page_url,
        depth=_depth,
        max_depth=max_depth,
    )
    if not candidate_sets:
        return []
    return max(candidate_sets, key=_listing_record_set_sort_key)


def _collect_candidate_record_sets(
    data: object,
    surface: str,
    page_url: str,
    *,
    depth: int,
    max_depth: int,
) -> list[list[dict]]:
    if depth > max_depth or data in (None, "", [], {}):
        return []

    candidate_sets: list[list[dict]] = []

    if isinstance(data, list):
        objects = [item for item in data if isinstance(item, dict)]
        if len(objects) >= 2:
            normalized = _try_normalize_array(objects, surface, page_url)
            if normalized:
                candidate_sets.append(normalized)
            for item in objects[:40]:
                state_data = _query_state_data(item)
                if state_data not in (None, "", [], {}):
                    candidate_sets.extend(
                        _collect_candidate_record_sets(
                            state_data,
                            surface,
                            page_url,
                            depth=depth + 1,
                            max_depth=max_depth,
                        )
                    )
        for item in data[:40]:
            if isinstance(item, (dict, list)):
                candidate_sets.extend(
                    _collect_candidate_record_sets(
                        item,
                        surface,
                        page_url,
                        depth=depth + 1,
                        max_depth=max_depth,
                    )
                )
        return candidate_sets

    if not isinstance(data, dict):
        return []

    for key in COLLECTION_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            objects = [item for item in value if isinstance(item, dict)]
            if len(objects) >= 2:
                normalized = _try_normalize_array(objects, surface, page_url)
                if normalized:
                    candidate_sets.append(normalized)

    state_data = _query_state_data(data)
    if state_data not in (None, "", [], {}):
        candidate_sets.extend(
            _collect_candidate_record_sets(
                state_data,
                surface,
                page_url,
                depth=depth + 1,
                max_depth=max_depth,
            )
        )

    for value in data.values():
        if isinstance(value, list):
            objects = [item for item in value if isinstance(item, dict)]
            if len(objects) >= 2:
                normalized = _try_normalize_array(objects, surface, page_url)
                if normalized:
                    candidate_sets.append(normalized)
        if isinstance(value, (dict, list)):
            candidate_sets.extend(
                _collect_candidate_record_sets(
                    value,
                    surface,
                    page_url,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )

    return candidate_sets


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
        if record and _is_meaningful_listing_record(record):
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
            decoded = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            continue
        if decoded:
            decoded_chunks.append(decoded)

    if not decoded_chunks:
        return []

    combined = "\n".join(decoded_chunks)
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
    brand_pattern = re.compile(
        r'"name":"(?P<brand>[^"]+)","__typename":"ManufacturerCuratedBrand"'
    )
    sale_price_pattern = re.compile(
        r'"priceVariation":"(?:SALE|PRIMARY)".{0,220}?"amount":"(?P<amount>[\d.]+)"',
        re.S,
    )
    original_price_pattern = re.compile(
        r'"priceVariation":"PREVIOUS".{0,220}?"amount":"(?P<amount>[\d.]+)"', re.S
    )
    rating_pattern = re.compile(
        r'"averageRating":(?P<rating>[\d.]+),"totalCount":(?P<count>\d+)'
    )
    availability_pattern = re.compile(
        r'"(?:shortInventoryStatusMessage|stockStatus)":"(?P<availability>[^"]+)"'
    )

    for chunk in decoded_chunks:
        for pair_pattern in pair_patterns:
            for match in pair_pattern.finditer(chunk):
                raw_url = match.group("url")
                title = match.group("title")
                if not title:
                    continue

                lookup_index = _lookup_next_flight_window_index(
                    combined, raw_url, page_url
                )
                if lookup_index is None:
                    continue
                window_start = max(0, lookup_index - 1200)
                window_end = min(len(combined), lookup_index + 2200)
                window = combined[window_start:window_end]
                resolved_url = urljoin(page_url, raw_url)
                record = records_by_url.setdefault(
                    resolved_url, {"url": resolved_url, "_source": "next_flight"}
                )
                record["title"] = title

                brand_match = brand_pattern.search(window)
                if brand_match:
                    record.setdefault("brand", brand_match.group("brand"))

                sale_price_match = sale_price_pattern.search(window)
                if sale_price_match:
                    record.setdefault("price", sale_price_match.group("amount"))

                original_price_match = original_price_pattern.search(window)
                if original_price_match:
                    record.setdefault(
                        "original_price", original_price_match.group("amount")
                    )

                rating_match = rating_pattern.search(window)
                if rating_match:
                    record.setdefault("rating", rating_match.group("rating"))
                    record.setdefault("review_count", rating_match.group("count"))

                availability_match = availability_pattern.search(window)
                if availability_match:
                    record.setdefault(
                        "availability", availability_match.group("availability")
                    )

    return [
        record
        for record in records_by_url.values()
        if _is_meaningful_listing_record(record)
    ]


def _extract_from_inline_object_arrays(
    html: str, surface: str, page_url: str
) -> list[dict]:
    candidates: list[list[dict]] = []
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
            parsed = json.loads(array_text)
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
            candidates.append(normalized)

    if not candidates:
        return []
    return max(candidates, key=_listing_record_set_sort_key)


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
            *_preferred_generic_item_values(item, canonical),
            *_find_alias_values(item, [canonical, *aliases], max_depth=4),
        ]
        for value in values:
            normalized = _normalize_listing_value(canonical, value, page_url=page_url)
            if normalized in (None, "", [], {}):
                continue
            record[canonical] = normalized
            break

    if record.get("url") in (None, "", [], {}) and record.get("slug") not in (
        None,
        "",
        [],
        {},
    ):
        slug_url = _resolve_slug_url(str(record["slug"]), page_url=page_url)
        if slug_url:
            record["url"] = slug_url

    is_job_surface = "job" in str(_surface or "").lower()
    if is_job_surface:
        # On job surfaces, price is almost always a salary — migrate it
        if record.get("price") not in (None, "", [], {}) and record.get("salary") in (None, "", [], {}):
            record["salary"] = record.pop("price")
        # Never emit commerce fields on job surfaces
        for commerce_field in ("price", "sale_price", "original_price", "currency"):
            record.pop(commerce_field, None)
    elif record.get("price") not in (None, "", [], {}) and record.get("currency") in (
        None,
        "",
        [],
        {},
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


def _preferred_generic_item_values(item: dict, canonical: str) -> list[object]:
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
    return []


def _looks_like_listing_variant_option(item: dict, *, surface: str) -> bool:
    if "ecommerce" not in str(surface or "").lower():
        return False
    if any(item.get(key) not in (None, "", [], {}) for key in ("name", "title", "productName", "product_name", "headline")):
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
        item.get("skuId")
        or item.get("commercialCode")
        or item.get("twelvenc")
        or ""
    ).strip()
    image = item.get("image")
    image_src = image.get("src") if isinstance(image, dict) else str(image or "")
    has_swatch_image = "color-swatches" in str(image_src or "").lower()
    has_assets = isinstance(item.get("assets"), list) and bool(item.get("assets"))
    has_price = item.get("price") not in (None, "", [], {})

    return bool(detail_href and variant_label and variant_id and has_price and (has_swatch_image or has_assets))


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
    if (
        LISTING_ALT_TEXT_TITLE_PATTERN
        and LISTING_ALT_TEXT_TITLE_PATTERN.search(t)
    ):
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


def _is_meaningful_listing_record(record: dict) -> bool:
    """Reject repeated nav/facet links that do not contain any item data."""
    if _is_merchandising_record(record):
        return False
        
    public_fields = {
        key: value
        for key, value in record.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    if not public_fields:
        return False

    meaningful_keys = {key for key in public_fields if key != "url"}
    has_price_or_img = "price" in meaningful_keys or "image_url" in meaningful_keys

    raw_title = public_fields.get("title")
    if raw_title is not None:
        title_str = str(raw_title).strip()
        if _FILTER_COUNT_RE.match(title_str):
            return False
        if isinstance(raw_title, (int, float)) and not isinstance(raw_title, bool):
            return False
        if _NUMERIC_ONLY_RE.match(title_str) and not has_price_or_img:
            return False

    raw_price = public_fields.get("price")
    url_value = str(public_fields.get("url") or "").strip()
    if (
        raw_price in (0, "0", "$0", "0.00", "$0.00")
        and not url_value
        and not public_fields.get("title")
        and len(public_fields) <= 2
    ):
        return False

    if meaningful_keys == LISTING_MINIMAL_VISUAL_FIELDS and not url_value:
        return False

    product_signal_keys = meaningful_keys & LISTING_PRODUCT_SIGNAL_FIELDS
    job_signal_keys = meaningful_keys & LISTING_JOB_SIGNAL_FIELDS

    # Reject records that are just category/navigation links with only a title
    # (no price, sku, brand, rating, or other product signals)
    if url_value and _looks_like_category_url(url_value):
        if not product_signal_keys:
            return False
    if url_value and _looks_like_facet_or_filter_url(url_value):
        if not product_signal_keys:
            return False

    # Stricter generic hub guard for bare links with zero product signals
    if (
        url_value
        and not product_signal_keys
        and meaningful_keys.issubset(LISTING_MINIMAL_VISUAL_FIELDS)
    ):
        parsed = urlparse(url_value)
        path = parsed.path.rstrip("/")
        segments = [s for s in path.split("/") if s]
        # Links to root or top-level dirs (/shop, /brands) without query params are hubs
        if len(segments) <= 1 and not parsed.query:
            return False
        # Reject known B2B / employer / site-nav path tokens that are never listing items
        path_token_set = {s.lower().replace("-", "") for s in segments}
        if path_token_set & LISTING_NON_LISTING_PATH_TOKENS:
            return False
        if not _looks_like_detail_record_url(url_value) and _looks_like_listing_hub_url(url_value):
            return False
    if (
        url_value
        and not product_signal_keys
        and meaningful_keys.issubset(LISTING_WEAK_METADATA_FIELDS)
        and _looks_like_listing_hub_url(url_value)
    ):
        return False

    if job_signal_keys and not record.get("title") and not record.get("salary"):
        return False

    if meaningful_keys:
        return True

    return False


def _is_meaningful_structured_listing_record(record: dict) -> bool:
    if not _is_meaningful_listing_record(record):
        return False
    public_fields = {
        key: value
        for key, value in record.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    field_names = set(public_fields)
    if field_names in ({"title"}, {"url"}, {"title", "url"}):
        return False
    return True


def _looks_like_facet_or_filter_url(url_value: str) -> bool:
    parsed = urlparse(url_value)
    query_keys = {
        key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    }
    if query_keys & LISTING_FACET_QUERY_KEYS:
        return True

    path = parsed.path.lower()
    return any(fragment in path for fragment in LISTING_FACET_PATH_FRAGMENTS) and bool(parsed.query)


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
    if _looks_like_facet_or_filter_url(url_value) or _looks_like_category_url(url_value):
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
    if word_count >= 12 and LISTING_ALT_TEXT_TITLE_PATTERN and LISTING_ALT_TEXT_TITLE_PATTERN.search(normalized):
        return True
    if len(normalized) >= 95 and ("," in normalized or ";" in normalized):
        return True
    return False


def _looks_like_editorial_or_taxonomy_title(title: str, url: str = "", price: str = "") -> bool:
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
        "[class*='product-card']", "[class*='product-item']", 
        "[class*='listing-card']", "[class*='result-item']",
        "[data-component-type='s-search-result']",
        "article[class*='product']", "li[class*='product']"
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


from dataclasses import dataclass

@dataclass
class RecordSetDiagnostics:
    record_count: int = 0
    unique_url_count: int = 0
    strong_identity_count: int = 0
    priced_count: int = 0
    imaged_count: int = 0
    detail_url_count: int = 0
    avg_field_count: float = 0.0
    source_bonus: int = 0


def _listing_record_set_sort_key(
    records: list[dict],
) -> tuple[int, int, int, int, int, float, int, int]:
    diag = RecordSetDiagnostics()
    diag.record_count = len(records)
    diag.strong_identity_count = sum(1 for record in records if is_listing_like_record(record))
    diag.detail_url_count = sum(
        1 for record in records if _looks_like_detail_record_url(str(record.get("url") or ""))
    )
    diag.priced_count = sum(1 for record in records if record.get("price") not in _EMPTY_VALUES)
    diag.imaged_count = sum(
        1
        for record in records
        if record.get("image_url") not in _EMPTY_VALUES or record.get("image") not in _EMPTY_VALUES
    )
    diag.unique_url_count = len(
        {
            str(record.get("url") or "").strip()
            for record in records
            if str(record.get("url") or "").strip()
        }
    )
    diag.avg_field_count = _avg_public_field_count(records)

    if records and records[0].get("_source") == "listing_card" and diag.record_count >= 3:
        diag.source_bonus = 1

    return (
        diag.priced_count,
        diag.detail_url_count,
        diag.imaged_count,
        diag.strong_identity_count,
        diag.unique_url_count,
        diag.avg_field_count,
        diag.source_bonus,
        diag.record_count,
    )


def _find_object_arrays(data: object, max_depth: int = 5) -> list[list[dict]]:
    """Recursively find all arrays of dicts with 2+ items."""
    results: list[list[dict]] = []
    if max_depth <= 0:
        return results

    if isinstance(data, list):
        objects = [item for item in data if isinstance(item, dict)]
        if len(objects) >= 2:
            results.append(objects)
        for item in data:
            if isinstance(item, (dict, list)):
                results.extend(_find_object_arrays(item, max_depth - 1))
    elif isinstance(data, dict):
        for value in data.values():
            if isinstance(value, (dict, list)):
                results.extend(_find_object_arrays(value, max_depth - 1))

    return results


# ---------------------------------------------------------------------------
# DOM card detection (original strategy, now a fallback)
# ---------------------------------------------------------------------------


def _auto_detect_cards(soup: BeautifulSoup, surface: str = "") -> tuple[list[Tag], str]:
    """Heuristic: find the best group of sibling elements that look like product cards.

    Scores candidate groups by product-like signals (link + image + price text)
    rather than pure element count to avoid selecting navigation lists.
    """
    for noise_el in soup.select(
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
        for container in containers:
            children = [c for c in container.children if isinstance(c, Tag)]
            if len(children) < 3:
                continue
            tag_classes: dict[tuple, list[Tag]] = {}
            for child in children:
                key = (child.name, tuple(sorted(child.get("class", []))))
                tag_classes.setdefault(key, []).append(child)
            for key, group in tag_classes.items():
                if len(group) < 3:
                    continue
                score = _card_group_score(group, surface=surface)
                if score > best_score:
                    best_cards = group
                    best_score = score
                    classes = ".".join(key[1]) if key[1] else ""
                    best_selector = f"{key[0]}.{classes}" if classes else key[0]

    _scan_containers(soup.select(PRIMARY_CONTAINER_SELECTOR))
    if not best_cards:
        _scan_containers(soup.select(FALLBACK_CONTAINER_SELECTOR))
    return best_cards, best_selector


def _card_group_score(group: list[Tag], surface: str = "") -> tuple[float, int]:
    """Score a candidate card group by product-like signals.

    Returns (signal_ratio, count) so groups with higher signal density win,
    with count as a tiebreaker.
    """
    signals = 0.0
    normalized_surface = str(surface or "").lower()
    is_commerce = "commerce" in normalized_surface
    for el in group[:30]:  # sample first 30
        has_link = bool(el.select_one("a[href]"))
        has_image = bool(el.select_one("img, picture, [style*='background-image']"))
        has_price = bool(
            el.select_one("[itemprop='price'], .price, [class*='price'], .amount")
        )
        text = el.get_text(" ", strip=True)
        has_substantial_text = len(text) > 40
        has_multi_elements = len(
            [child for child in el.children if isinstance(child, Tag)]
        ) > 1
        if not has_link:
            continue
        if is_commerce:
            if has_image and has_price:
                signals += 1.0
            elif has_image or has_price:
                signals += 0.5
        elif has_image or has_price:
            signals += 1.0
        elif has_substantial_text and has_multi_elements:
            signals += 0.4
    sample_size = min(len(group), 30)
    ratio = signals / sample_size if sample_size > 0 else 0.0
    return (ratio, len(group))


_MIN_CARD_SIGNAL_RATIO = 0.45
_PRICE_LIKE_RE = re.compile(r"^[\s$£€¥₹]?\d[\d,.\s]*$")


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

    # Price (extract early so we can exclude price-like headings from title)
    if "ecommerce" in surface:
        price_el = card.select_one(
            "[itemprop='price'], .price, .product-price, .a-price .a-offscreen, "
            ".s-item__price, span[data-price], .amount, [class*='price']"
        )
        if price_el:
            raw_price = price_el.get("content") or price_el.get_text(" ", strip=True)
            record["price"] = _clean_price_text(raw_price)
            record["_xpath_price"] = simplify_xpath(bs4_tag_to_xpath(price_el))
        original_price_el = card.select_one(
            ".original-price, .compare-price, .was-price, .strike, s, del, [data-original-price]"
        )
        if original_price_el:
            raw_op = original_price_el.get("content") or original_price_el.get_text(
                " ", strip=True
            )
            record["original_price"] = _clean_price_text(raw_op)
            record["_xpath_original_price"] = simplify_xpath(bs4_tag_to_xpath(original_price_el))

    # Title: prefer itemprop, then class-based, then headings — skip price-like text
    title_selectors = [
        ".item_description_title",
        "[itemprop='name']",
        ".product-title",
        ".job-title",
        ".card-title",
        "a.title",
        ".title",
        "h2 a",
        "h3 a",
        "h4 a",
        "h2",
        "h3",
        "h4",
        "a[title]",
    ]
    for sel in title_selectors:
        title_el = card.select_one(sel)
        if title_el:
            text = title_el.get_text(" ", strip=True)
            if text and not _PRICE_LIKE_RE.match(text):
                record["title"] = text
                record["_xpath_title"] = simplify_xpath(bs4_tag_to_xpath(title_el))
                record["_selector_title"] = sel
                break
    if "title" not in record and "job" not in surface:
        inferred_title = _infer_listing_title_from_links(card)
        if inferred_title:
            record["title"] = inferred_title

    url = _best_card_link(card, page_url)
    if url:
        record["url"] = url
    if "title" not in record:
        inferred_title = _infer_job_title_from_links(card)
        if inferred_title:
            record["title"] = inferred_title

    # Image: prefer itemprop, then standard patterns
    img_el = card.select_one("[itemprop='image']")
    if img_el:
        src = img_el.get("src") or img_el.get("data-src") or img_el.get("content", "")
        if src:
            record["image_url"] = urljoin(page_url, src) if page_url else src
            record["_xpath_image_url"] = simplify_xpath(bs4_tag_to_xpath(img_el))
    if "image_url" not in record:
        images = _extract_card_images(card, page_url)
        if images:
            record["image_url"] = images[0]
            if len(images) > 1:
                record["additional_images"] = ", ".join(images[1:])

    # Brand
    brand_el = card.select_one(".brand, [itemprop='brand'], .product-brand")
    if brand_el:
        record["brand"] = brand_el.get_text(strip=True)
        record["_xpath_brand"] = simplify_xpath(bs4_tag_to_xpath(brand_el))

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
        record["_xpath_rating"] = simplify_xpath(bs4_tag_to_xpath(rating_el))

    review_count_el = card.select_one(
        "[itemprop='reviewCount'], [aria-label*='review'], .review-count, .count"
    )
    if review_count_el:
        record["review_count"] = (
            review_count_el.get("content")
            or review_count_el.get("aria-label", "")
            or review_count_el.get_text(" ", strip=True)
        )
        record["_xpath_review_count"] = simplify_xpath(bs4_tag_to_xpath(review_count_el))

    card_text_lines = _card_text_lines(card)
    identifier_fields = _extract_card_identifiers(card, card_text_lines)
    for field_name, value in identifier_fields.items():
        if value:
            record[field_name] = value
    if "ecommerce" in surface:
        color_text = _extract_card_color(card, card_text_lines)
        if color_text:
            record["color"] = color_text
        size_text = _match_line(card_text_lines, r"\bsizes?\b")
        if size_text:
            record["size"] = size_text
        dimensions_text = _match_dimensions_line(card_text_lines)
        if dimensions_text:
            record["dimensions"] = dimensions_text
        if record.get("price") and not record.get("currency"):
            inferred_currency = _infer_currency_from_page_url(page_url)
            if inferred_currency:
                record["currency"] = inferred_currency

    # Job fields
    if "job" in surface:
        company_el = card.select_one(
            ".company, .companyName, [data-testid='company-name']"
        )
        if company_el:
            record["company"] = company_el.get_text(strip=True)
        location_el = card.select_one(
            ".location, .companyLocation, [data-testid='text-location']"
        )
        if location_el:
            record["location"] = location_el.get_text(strip=True)
        salary_el = card.select_one(".salary, .salary-snippet-container")
        if salary_el:
            record["salary"] = salary_el.get_text(strip=True)
        if not record.get("company"):
            inferred_company = _infer_job_company(card_text_lines, title=record.get("title"))
            if inferred_company:
                record["company"] = inferred_company
        if not record.get("location"):
            inferred_location = _infer_job_location(card_text_lines, title=record.get("title"))
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
        if record.get("url") and not record.get("apply_url"):
            record["apply_url"] = str(record["url"])

    return record


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
        if urlparse(resolved).path.lower().endswith(
            (".woff", ".woff2", ".ttf", ".otf", ".eot", ".css", ".js", ".map")
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
        parsed = json.loads(candidate)
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
        if any(
            token in lowered_resolved for token in LISTING_IMAGE_EXCLUDE_TOKENS
        ):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        images.append(resolved)
    return images


_PRICE_WITH_CURRENCY_RE = re.compile(r"[\$£€¥₹]\s*\d[\d,.\s]*")
_PRICE_EXTRACT_RE = re.compile(r"[\$£€¥₹]?\s*\d[\d,.\s]*")


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
    regex = re.compile(pattern, re.I)
    for line in lines:
        if regex.search(line):
            return line
    return ""


def _match_dimensions_line(lines: list[str]) -> str:
    measurement_regex = re.compile(r"\b\d+(?:\.\d+)?\s*(?:\"|in|cm|mm|ft)\b", re.I)
    dimension_token_regex = re.compile(
        r"\b(?:h\s*x|w\s*x|d\s*x|height|width|depth|diameter)\b", re.I
    )
    for line in lines:
        lowered = line.lower()
        if dimension_token_regex.search(lowered):
            return line
        if measurement_regex.search(line):
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
        if _looks_like_navigation_or_action_title(candidate, str(link_el.get("href") or "")):
            continue
        return candidate
    for link_el in card.select("a[aria-label]"):
        candidate = str(link_el.get("aria-label") or "").strip()
        if not candidate or len(candidate) < 3:
            continue
        if _looks_like_navigation_or_action_title(candidate, str(link_el.get("href") or "")):
            continue
        return candidate
    return ""


def _infer_job_company(lines: list[str], *, title: object = None) -> str:
    title_text = str(title or "").strip()
    for line in lines:
        if not line or line == title_text:
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
        if lowered in {"apply now", "save job", "sponsored", "today", "yesterday"}:
            continue
        if len(line) <= 80:
            return line
    return ""


def _infer_job_location(lines: list[str], *, title: object = None) -> str:
    title_text = str(title or "").strip()
    for line in lines:
        lowered = line.lower()
        if not line or line == title_text:
            continue
        if title_text and title_text.lower() in lowered:
            continue
        if lowered == "multiple locations":
            return line
        if any(token in lowered for token in ("remote", "hybrid", "on-site", "onsite")):
            return line
        if "," in line and not _infer_job_salary([line]) and not _infer_job_posted_date([line]):
            return line
    return ""


def _infer_job_salary(lines: list[str]) -> str:
    salary_pattern = re.compile(
        r"(?i)(?:(?:[$€£₹]|usd|eur|gbp|inr)\s*\d.*(?:/|\bper\b)\s*(?:hour|day|week|month|year)\b)|"
        r"(?:(?:[$€£₹]|usd|eur|gbp|inr)\s*\d.*(?:salary|compensation|annual))|"
        r"(?:\d[\d,]*(?:\.\d+)?\s*(?:/|\bper\b)\s*(?:hour|day|week|month|year)\b)"
    )
    for line in lines:
        if salary_pattern.search(line):
            return line
    return ""


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
    return _match_line(lines, r"\bcolors?\b")


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
    return identifiers


def _infer_currency_from_page_url(page_url: str) -> str:
    lowered = str(page_url or "").strip().lower()
    if not lowered:
        return ""
    for token, currency in PAGE_URL_CURRENCY_HINTS.items():
        if token in lowered:
            return currency
    return ""
