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

from app.services.discover.service import DiscoveryManifest
from app.services.pipeline_config import (
    CARD_SELECTORS_COMMERCE,
    CARD_SELECTORS_JOBS,
    COLLECTION_KEYS,
    FIELD_ALIASES,
    MAX_JSON_RECURSION_DEPTH,
    NESTED_CATEGORY_KEYS,
    NESTED_CURRENCY_KEYS,
    NESTED_ORIGINAL_PRICE_KEYS,
    NESTED_PRICE_KEYS,
    NESTED_TEXT_KEYS,
    NESTED_URL_KEYS,
)


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
    candidate_sets: list[list[dict]] = []

    # --- Strategy 1: Structured data sources (from manifest) ---
    if manifest:
        structured_records = _extract_from_structured_sources(manifest, surface, page_url)
        if len(structured_records) >= 2:
            for record in structured_records:
                record["_source"] = record.get("_source", "structured")
            candidate_sets.append(structured_records)

    next_flight_records = _extract_from_next_flight_scripts(html, page_url)
    if len(next_flight_records) >= 2:
        candidate_sets.append(next_flight_records)

    # --- Strategy 2: DOM card detection ---
    soup = BeautifulSoup(html, "html.parser")

    # Try embedded JSON-LD even without manifest (direct HTML parse)
    json_ld_records = _extract_from_json_ld(soup, surface, page_url)
    if len(json_ld_records) >= 2:
        candidate_sets.append(json_ld_records)

    selectors = CARD_SELECTORS_COMMERCE if "commerce" in surface or "ecommerce" in surface else CARD_SELECTORS_JOBS

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
        cards, used_selector = _auto_detect_cards(soup)

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
    return max(candidate_sets, key=_listing_record_set_sort_key)[:max_records]


# ---------------------------------------------------------------------------
# Structured source extraction
# ---------------------------------------------------------------------------

def _extract_from_structured_sources(
    manifest: DiscoveryManifest, surface: str, page_url: str,
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
        if not isinstance(payload, dict):
            continue
        ld_type = payload.get("@type", "")

        if ld_type == "ItemList" or "itemListElement" in payload:
            elements = payload.get("itemListElement", [])
            for el in elements:
                if isinstance(el, dict):
                    item = el.get("item", el)
                    if isinstance(item, dict):
                        record = _normalize_ld_item(item, surface, page_url)
                        if record:
                            record["_source"] = "json_ld_item_list"
                            ld_records.append(record)

        elif ld_type in ("Product", "JobPosting"):
            record = _normalize_ld_item(payload, surface, page_url)
            if record:
                record["_source"] = "json_ld"
                ld_records.append(record)

    if ld_records:
        candidates.append(ld_records)

    # __NEXT_DATA__: search for product/job arrays in page props
    if manifest.next_data:
        next_records = _extract_from_next_data(manifest.next_data, surface, page_url)
        if next_records:
            candidates.append(next_records)

    # Additional hydrated state blobs discovered from inline scripts
    if manifest._hydrated_states:
        for state in manifest._hydrated_states:
            state_records = _extract_items_from_json(state, surface, page_url)
            if state_records:
                for r in state_records:
                    r["_source"] = "hydrated_state"
                candidates.append(state_records)

    # Network payloads: look for JSON arrays of items
    for payload in manifest.network_payloads:
        body = payload.get("body")
        if not isinstance(body, (dict, list)):
            continue
        net_records = _extract_items_from_json(body, surface, page_url)
        if net_records:
            for r in net_records:
                r["_source"] = "network_payload"
            candidates.append(net_records)

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
                merged_by_key[key] = {**record, "_sources": [str(record.get("_source") or "structured")]}
                ordered_keys.append(key)
                continue
            for field_name, value in record.items():
                if field_name == "_source":
                    continue
                if existing.get(field_name) in (None, "", [], {}) and value not in (None, "", [], {}):
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
    return ""


def _avg_public_field_count(records: list[dict]) -> float:
    """Average number of non-internal, non-empty fields per record."""
    if not records:
        return 0.0
    total = sum(
        sum(1 for k, v in r.items() if not str(k).startswith("_") and v not in (None, "", [], {}))
        for r in records
    )
    return total / len(records)


def _extract_from_json_ld(soup: BeautifulSoup, surface: str, page_url: str) -> list[dict]:
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
            ld_type = payload.get("@type", "")
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

    return records


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
            record["price"] = offers.get("price") or offers.get("lowPrice") or ""
            record["availability"] = offers.get("availability") or ""
        record["brand"] = _nested_name(item.get("brand"))
        record["sku"] = item.get("sku") or ""
        record["description"] = item.get("description") or ""
        record["rating"] = _nested_value(item.get("aggregateRating"), "ratingValue")

    if "job" in surface:
        record["company"] = _nested_name(item.get("hiringOrganization"))
        location = item.get("jobLocation")
        if isinstance(location, dict):
            address = location.get("address", {})
            if isinstance(address, dict):
                record["location"] = address.get("addressLocality") or address.get("name") or ""
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
    record = {k: v for k, v in record.items() if v}
    if record:
        record["_raw_item"] = item
    return record if record else None


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
        record = _normalize_generic_item(item, surface, page_url)
        if record and _is_meaningful_listing_record(record):
            records.append(record)
    return records


def _extract_from_next_flight_scripts(html: str, page_url: str) -> list[dict]:
    if "__next_f.push" not in html:
        return []

    decoded_chunks: list[str] = []
    for match in re.finditer(r"self\.__next_f\.push\(\[\d+,\s*\"((?:\\.|[^\"\\])*)\"\]\)", html, re.S):
        try:
            decoded = json.loads(f"\"{match.group(1)}\"")
        except json.JSONDecodeError:
            continue
        if decoded:
            decoded_chunks.append(decoded)

    if not decoded_chunks:
        return []

    combined = "\n".join(decoded_chunks)
    records_by_url: dict[str, dict] = {}
    pair_patterns = [
        re.compile(r'"displayName":"(?P<title>[^"]+)".{0,900}?"listingUrl":"(?P<url>[^"]+)"', re.S),
        re.compile(r'"listingUrl":"(?P<url>[^"]+)".{0,900}?"displayName":"(?P<title>[^"]+)"', re.S),
    ]
    brand_pattern = re.compile(r'"name":"(?P<brand>[^"]+)","__typename":"ManufacturerCuratedBrand"')
    sale_price_pattern = re.compile(r'"priceVariation":"(?:SALE|PRIMARY)".{0,220}?"amount":"(?P<amount>[\d.]+)"', re.S)
    original_price_pattern = re.compile(r'"priceVariation":"PREVIOUS".{0,220}?"amount":"(?P<amount>[\d.]+)"', re.S)
    rating_pattern = re.compile(r'"averageRating":(?P<rating>[\d.]+),"totalCount":(?P<count>\d+)')
    availability_pattern = re.compile(r'"(?:shortInventoryStatusMessage|stockStatus)":"(?P<availability>[^"]+)"')

    for chunk in decoded_chunks:
        for pair_pattern in pair_patterns:
            for match in pair_pattern.finditer(chunk):
                raw_url = match.group("url")
                title = match.group("title")
                if not title:
                    continue

                lookup_index = _lookup_next_flight_window_index(combined, raw_url, page_url)
                if lookup_index is None:
                    continue
                window_start = max(0, lookup_index - 1200)
                window_end = min(len(combined), lookup_index + 2200)
                window = combined[window_start:window_end]
                resolved_url = urljoin(page_url, raw_url)
                record = records_by_url.setdefault(resolved_url, {"url": resolved_url, "_source": "next_flight"})
                record["title"] = title

                brand_match = brand_pattern.search(window)
                if brand_match:
                    record.setdefault("brand", brand_match.group("brand"))

                sale_price_match = sale_price_pattern.search(window)
                if sale_price_match:
                    record.setdefault("price", sale_price_match.group("amount"))

                original_price_match = original_price_pattern.search(window)
                if original_price_match:
                    record.setdefault("original_price", original_price_match.group("amount"))

                rating_match = rating_pattern.search(window)
                if rating_match:
                    record.setdefault("rating", rating_match.group("rating"))
                    record.setdefault("review_count", rating_match.group("count"))

                availability_match = availability_pattern.search(window)
                if availability_match:
                    record.setdefault("availability", availability_match.group("availability"))

    return [
        record
        for record in records_by_url.values()
        if _is_meaningful_listing_record(record)
    ]


def _lookup_next_flight_window_index(combined: str, raw_url: str, page_url: str) -> int | None:
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
    record: dict = {}

    for canonical, aliases in FIELD_ALIASES.items():
        values = _find_alias_values(item, [canonical, *aliases], max_depth=4)
        for value in values:
            normalized = _normalize_listing_value(canonical, value, page_url=page_url)
            if normalized in (None, "", [], {}):
                continue
            record[canonical] = normalized
            break

    if record.get("url") in (None, "", [], {}) and record.get("slug") not in (None, "", [], {}):
        slug_url = _resolve_slug_url(str(record["slug"]), page_url=page_url)
        if slug_url:
            record["url"] = slug_url

    if "ecommerce" in _surface and record.get("url") in (None, "", [], {}) and record.get("price") in (None, "", [], {}):
        return None

    if record:
        record["_raw_item"] = item
    return record if record else None


def _is_meaningful_listing_record(record: dict) -> bool:
    """Reject repeated nav/facet links that do not contain any item data."""
    public_fields = {
        key: value
        for key, value in record.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    if not public_fields:
        return False

    url_value = str(public_fields.get("url") or "").strip()
    meaningful_keys = {key for key in public_fields if key != "url"}
    if meaningful_keys == {"title", "image_url"} and not url_value:
        return False
    if meaningful_keys:
        return True

    return False


def _looks_like_facet_or_filter_url(url_value: str) -> bool:
    parsed = urlparse(url_value)
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    facet_keys = {"sv", "facet", "filter", "filters", "color", "size", "material", "sort"}
    if query_keys & facet_keys:
        return True

    path = parsed.path.lower()
    facet_fragments = ("/see-all", "/filter", "/filters", "/facet")
    return any(fragment in path for fragment in facet_fragments) and bool(parsed.query)


def _looks_like_detail_record_url(url_value: str) -> bool:
    lowered = str(url_value or "").lower()
    if not lowered.startswith("http"):
        return False
    if _looks_like_facet_or_filter_url(lowered):
        return False
    detail_markers = ("/pdp/", "/product/", "/products/", "/dp/", "/p/", "piid=")
    return any(marker in lowered for marker in detail_markers)


def _listing_record_set_sort_key(records: list[dict]) -> tuple[int, int, int, float, int]:
    detail_urls = sum(1 for record in records if _looks_like_detail_record_url(str(record.get("url") or "")))
    priced = sum(1 for record in records if record.get("price") not in (None, "", [], {}))
    reviewed = sum(1 for record in records if record.get("rating") not in (None, "", [], {}))
    unique_urls = len({
        str(record.get("url") or "").strip()
        for record in records
        if str(record.get("url") or "").strip()
    })
    return (priced, detail_urls, reviewed, _avg_public_field_count(records), unique_urls)


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

def _auto_detect_cards(soup: BeautifulSoup) -> tuple[list[Tag], str]:
    """Heuristic: find the best group of sibling elements that look like product cards.

    Scores candidate groups by product-like signals (link + image + price text)
    rather than pure element count to avoid selecting navigation lists.
    """
    best_cards: list[Tag] = []
    best_selector = ""
    best_score: tuple[float, int] = (0.0, 0)

    containers = soup.select(
        "ul, ol, div.grid, div.row, div[class*='results'], "
        "div[class*='product'], div[class*='listing'], div[class*='search'], "
        "div[class*='tile'], div[class*='card'], main, section"
    )
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
            score = _card_group_score(group)
            if score > best_score:
                best_cards = group
                best_score = score
                classes = ".".join(key[1]) if key[1] else ""
                best_selector = f"{key[0]}.{classes}" if classes else key[0]
    return best_cards, best_selector


def _card_group_score(group: list[Tag]) -> tuple[float, int]:
    """Score a candidate card group by product-like signals.

    Returns (signal_ratio, count) so groups with higher signal density win,
    with count as a tiebreaker.
    """
    signals = 0
    for el in group[:30]:  # sample first 30
        has_link = bool(el.select_one("a[href]"))
        has_image = bool(el.select_one("img, picture, [style*='background-image']"))
        has_price = bool(el.select_one(
            "[itemprop='price'], .price, [class*='price'], .amount"
        ))
        text = el.get_text(" ", strip=True)
        has_substantial_text = len(text) > 20
        # A card should have at least a link + one of (image, price, substantial text)
        if has_link and (has_image or has_price or has_substantial_text):
            signals += 1
    sample_size = min(len(group), 30)
    ratio = signals / sample_size if sample_size > 0 else 0.0
    return (ratio, len(group))


_PRICE_LIKE_RE = re.compile(r"^[\s$£€¥₹]?\d[\d,.\s]*$")


def _extract_from_card(card: Tag, _target_fields: set[str], surface: str, page_url: str) -> dict:
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
        original_price_el = card.select_one(
            ".original-price, .compare-price, .was-price, .strike, s, del, [data-original-price]"
        )
        if original_price_el:
            raw_op = original_price_el.get("content") or original_price_el.get_text(" ", strip=True)
            record["original_price"] = _clean_price_text(raw_op)

    # Title: prefer itemprop, then class-based, then headings — skip price-like text
    title_selectors = [
        "[itemprop='name']",
        ".product-title", ".job-title", ".card-title", "a.title", ".title",
        "h2 a", "h3 a", "h4 a",
        "h2", "h3", "h4",
        "a[title]",
    ]
    for sel in title_selectors:
        title_el = card.select_one(sel)
        if title_el:
            text = title_el.get_text(" ", strip=True)
            if text and not _PRICE_LIKE_RE.match(text):
                record["title"] = text
                break

    # URL: first link
    link_el = card.select_one("a[href]")
    if link_el:
        href = link_el.get("href", "")
        record["url"] = urljoin(page_url, href) if page_url else href

    # Image: prefer itemprop, then standard patterns
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

    # Brand
    brand_el = card.select_one(".brand, [itemprop='brand'], .product-brand")
    if brand_el:
        record["brand"] = brand_el.get_text(strip=True)

    # Rating
    rating_el = card.select_one("[aria-label*='star'], .rating, [itemprop='ratingValue']")
    if rating_el:
        record["rating"] = rating_el.get("content") or rating_el.get("aria-label", "") or rating_el.get_text(" ", strip=True)

    review_count_el = card.select_one("[itemprop='reviewCount'], [aria-label*='review'], .review-count, .count")
    if review_count_el:
        record["review_count"] = review_count_el.get("content") or review_count_el.get("aria-label", "") or review_count_el.get_text(" ", strip=True)

    card_text_lines = _card_text_lines(card)
    if "ecommerce" in surface:
        color_text = _match_line(card_text_lines, r"\bcolors?\b")
        if color_text:
            record["color"] = color_text
        size_text = _match_line(card_text_lines, r"\bsizes?\b")
        if size_text:
            record["size"] = size_text
        dimensions_text = _match_dimensions_line(card_text_lines)
        if dimensions_text:
            record["dimensions"] = dimensions_text

    # Job fields
    if "job" in surface:
        company_el = card.select_one(".company, .companyName, [data-testid='company-name']")
        if company_el:
            record["company"] = company_el.get_text(strip=True)
        location_el = card.select_one(".location, .companyLocation, [data-testid='text-location']")
        if location_el:
            record["location"] = location_el.get_text(strip=True)
        salary_el = card.select_one(".salary, .salary-snippet-container")
        if salary_el:
            record["salary"] = salary_el.get_text(strip=True)

    return record


def _normalize_listing_value(canonical: str, value: object, *, page_url: str) -> object | None:
    if value in (None, "", [], {}):
        return None
    if canonical == "url":
        resolved = _coerce_nested_text(value, keys=NESTED_URL_KEYS) if isinstance(value, dict) else value
        text = str(resolved or "").strip()
        if text and page_url and not text.startswith(("http://", "https://", "/")) and _looks_like_product_short_path(text):
            parsed = urlparse(page_url)
            origin = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else page_url
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
            candidate = str(item.get("url") or item.get("contentUrl") or item.get("src") or "").strip()
        else:
            candidate = str(item).strip()
        if not candidate:
            continue
        resolved = urljoin(page_url, candidate) if page_url else candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        images.append(resolved)
    return images


def _find_alias_values(data: object, aliases: list[str], *, max_depth: int) -> list[object]:
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
                if _normalized_field_token(key) in alias_tokens and value not in (None, "", [], {}):
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
    return bool(re.match(r"^p(?:/|[.-])[A-Za-z0-9][A-Za-z0-9._/-]*$", str(value or "").strip(), re.I))


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
    for img_el in card.select("img"):
        src = (
            img_el.get("src")
            or img_el.get("data-src")
            or img_el.get("data-original")
            or img_el.get("srcset", "").split(",")[0].strip().split(" ")[0]
        )
        if not src:
            continue
        resolved = urljoin(page_url, src) if page_url else src
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
    dimension_token_regex = re.compile(r"\b(?:h\s*x|w\s*x|d\s*x|height|width|depth|diameter)\b", re.I)
    for line in lines:
        lowered = line.lower()
        if dimension_token_regex.search(lowered):
            return line
        if measurement_regex.search(line):
            return line
    return ""
