# Listing page extractor — finds repeating cards and extracts N records.
#
# Strategy order:
#   1. JSON-LD item lists (structured data)
#   2. Embedded app state (__NEXT_DATA__, hydrated state)
#   3. Network payloads (XHR/fetch intercepted JSON arrays)
#   4. DOM card detection (CSS selectors + auto-detect)
from __future__ import annotations

import json
from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.services.discover.service import DiscoveryManifest
from app.services.pipeline_config import CARD_SELECTORS_COMMERCE, CARD_SELECTORS_JOBS, COLLECTION_KEYS, FIELD_ALIASES


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
    # --- Strategy 1: Structured data sources (from manifest) ---
    if manifest:
        structured_records = _extract_from_structured_sources(manifest, surface, page_url)
        if len(structured_records) >= 2:
            for r in structured_records:
                r["_source"] = r.get("_source", "structured")
            return structured_records[:max_records]

    # --- Strategy 2: DOM card detection ---
    soup = BeautifulSoup(html, "html.parser")

    # Try embedded JSON-LD even without manifest (direct HTML parse)
    json_ld_records = _extract_from_json_ld(soup, surface, page_url)
    if len(json_ld_records) >= 2:
        return json_ld_records[:max_records]

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

    return records


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

    if len(ld_records) >= 2:
        candidates.append(ld_records)

    # __NEXT_DATA__: search for product/job arrays in page props
    if manifest.next_data:
        next_records = _extract_from_next_data(manifest.next_data, surface, page_url)
        if len(next_records) >= 2:
            candidates.append(next_records)

    # Additional hydrated state blobs discovered from inline scripts
    if manifest._hydrated_states:
        for state in manifest._hydrated_states:
            state_records = _extract_items_from_json(state, surface, page_url)
            if len(state_records) >= 2:
                for r in state_records:
                    r["_source"] = "hydrated_state"
                candidates.append(state_records)

    # Network payloads: look for JSON arrays of items
    for payload in manifest.network_payloads:
        body = payload.get("body")
        if not isinstance(body, (dict, list)):
            continue
        net_records = _extract_items_from_json(body, surface, page_url)
        if len(net_records) >= 2:
            for r in net_records:
                r["_source"] = "network_payload"
            candidates.append(net_records)

    if not candidates:
        return ld_records  # may be 0-1 records

    # Pick the source with the highest average field richness
    return max(candidates, key=_avg_public_field_count)


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
        try:
            data = json.loads(node.string or "{}")
        except json.JSONDecodeError:
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
    image = item.get("image")
    if isinstance(image, list) and image:
        image = image[0]
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl") or ""
    record["image_url"] = image or ""

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
    arrays = _find_object_arrays(next_data, max_depth=5)
    best: list[dict] = []
    for arr in arrays:
        records = _try_normalize_array(arr, surface, page_url)
        if len(records) > len(best):
            best = records
            for r in best:
                r["_source"] = "next_data"
    return best


def _extract_items_from_json(data: dict | list, surface: str, page_url: str, _depth: int = 0) -> list[dict]:
    """Extract items from an arbitrary JSON structure.

    Recursively searches up to 4 levels deep for arrays of objects that
    look like product/job collections.
    """
    if _depth > 4:
        return []

    if isinstance(data, list):
        objects = [item for item in data if isinstance(item, dict)]
        if len(objects) >= 2:
            return _try_normalize_array(objects, surface, page_url)
        return []

    if not isinstance(data, dict):
        return []

    # Check known collection keys at this level
    for key in COLLECTION_KEYS:
        if key in data and isinstance(data[key], list):
            objects = [item for item in data[key] if isinstance(item, dict)]
            if len(objects) >= 2:
                return _try_normalize_array(objects, surface, page_url)

    # Check all values: arrays first, then recurse into dicts
    for value in data.values():
        if isinstance(value, list):
            objects = [item for item in value if isinstance(item, dict)]
            if len(objects) >= 2:
                return _try_normalize_array(objects, surface, page_url)

    for value in data.values():
        if isinstance(value, dict):
            result = _extract_items_from_json(value, surface, page_url, _depth + 1)
            if result:
                return result

    return []


def _try_normalize_array(items: list[dict], surface: str, page_url: str) -> list[dict]:
    """Try to normalize an array of objects into records."""
    records = []
    for item in items:
        record = _normalize_generic_item(item, surface, page_url)
        if record and _is_meaningful_listing_record(record):
            records.append(record)
    return records


def _normalize_generic_item(item: dict, _surface: str, page_url: str) -> dict | None:
    """Map an arbitrary dict to canonical fields using alias matching."""
    record: dict = {}
    flat = item.copy()
    for key, value in item.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                composite = f"{key}_{sub_key}"
                if composite not in flat:
                    flat[composite] = sub_value

    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            value = flat.get(alias)
            if value and not isinstance(value, (dict, list)):
                if canonical == "url" and page_url:
                    value = urljoin(page_url, str(value))
                record[canonical] = str(value).strip() if isinstance(value, str) else value
                break

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

    meaningful_keys = {
        key for key in public_fields
        if key != "url"
    }
    if meaningful_keys:
        return True

    url_value = str(public_fields.get("url") or "").strip()
    if not url_value:
        return False
    return not _looks_like_facet_or_filter_url(url_value)


def _looks_like_facet_or_filter_url(url_value: str) -> bool:
    parsed = urlparse(url_value)
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    facet_keys = {"sv", "facet", "filter", "filters", "color", "size", "material", "sort"}
    if query_keys & facet_keys:
        return True

    path = parsed.path.lower()
    facet_fragments = ("/see-all", "/filter", "/filters", "/facet")
    return any(fragment in path for fragment in facet_fragments) and bool(parsed.query)


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
    """Heuristic: find the largest group of sibling elements with similar structure."""
    best_cards: list[Tag] = []
    best_selector = ""
    # Check common container patterns
    containers = soup.select("ul, ol, div.grid, div.row, div[class*='results'], main, section")
    for container in containers:
        children = [c for c in container.children if isinstance(c, Tag)]
        if len(children) < 3:
            continue
        # Check if children share a common tag + class pattern
        tag_classes: dict[tuple, list[Tag]] = {}
        for child in children:
            key = (child.name, tuple(sorted(child.get("class", []))))
            tag_classes.setdefault(key, []).append(child)
        for key, group in tag_classes.items():
            if len(group) >= 3 and len(group) > len(best_cards):
                best_cards = group
                classes = ".".join(key[1]) if key[1] else ""
                best_selector = f"{key[0]}.{classes}" if classes else key[0]
    return best_cards, best_selector


def _extract_from_card(card: Tag, _target_fields: set[str], surface: str, page_url: str) -> dict:
    """Extract field values from a single listing card element."""
    record: dict = {}

    # Title: first heading or link text
    title_el = card.select_one("h2, h3, h4, a[title], .product-title, .job-title, .card-title")
    if title_el:
        record["title"] = title_el.get_text(" ", strip=True)

    # URL: first link
    link_el = card.select_one("a[href]")
    if link_el:
        href = link_el.get("href", "")
        record["url"] = urljoin(page_url, href) if page_url else href

    # Image
    img_el = card.select_one("img[src]")
    if img_el:
        record["image_url"] = img_el.get("src") or img_el.get("data-src", "")

    # Price (commerce)
    if "ecommerce" in surface:
        price_el = card.select_one(
            "[itemprop='price'], .price, .product-price, .a-price .a-offscreen, "
            ".s-item__price, span[data-price], .amount"
        )
        if price_el:
            record["price"] = price_el.get("content") or price_el.get_text(" ", strip=True)

    # Brand
    brand_el = card.select_one(".brand, [itemprop='brand'], .product-brand")
    if brand_el:
        record["brand"] = brand_el.get_text(strip=True)

    # Rating
    rating_el = card.select_one("[aria-label*='star'], .rating, [itemprop='ratingValue']")
    if rating_el:
        record["rating"] = rating_el.get("content") or rating_el.get("aria-label", "")

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
