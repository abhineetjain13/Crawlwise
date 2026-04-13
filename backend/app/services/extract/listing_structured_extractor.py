from __future__ import annotations

import json
import re
from json import loads as parse_json
from urllib.parse import urljoin, urlparse

from app.services.config.crawl_runtime import MAX_JSON_RECURSION_DEPTH
from app.services.config.field_mappings import COLLECTION_KEYS
from app.services.config.extraction_rules import (
    LISTING_FILTER_OPTION_KEYS,
    NEXT_FLIGHT_AVAILABILITY_PATTERN,
    NEXT_FLIGHT_BACK_WINDOW,
    NEXT_FLIGHT_BRAND_PATTERNS,
    NEXT_FLIGHT_FORWARD_WINDOW,
    NEXT_FLIGHT_ORIGINAL_PRICE_PATTERN,
    NEXT_FLIGHT_PAIR_PATTERNS,
    NEXT_FLIGHT_RATING_PATTERN,
    NEXT_FLIGHT_SALE_PRICE_PATTERN,
)
from app.services.extract.listing_identity import (
    choose_primary_record_set,
    merge_record_sets_on_identity,
)
from app.services.extract.listing_quality import (
    filter_relevant_network_record_set,
    has_strong_ecommerce_listing_signal,
    is_meaningful_listing_record,
    is_meaningful_structured_listing_record,
)

import logging

logger = logging.getLogger(__name__)

_EMPTY_VALUES = (None, "", [], {})
MIN_VIABLE_RECORDS = 2
_NEXT_FLIGHT_PAIR_PATTERNS = tuple(
    re.compile(pattern, re.S) for pattern in NEXT_FLIGHT_PAIR_PATTERNS
)
_NEXT_FLIGHT_BRAND_PATTERNS = tuple(
    re.compile(pattern) for pattern in NEXT_FLIGHT_BRAND_PATTERNS
)
_NEXT_FLIGHT_SALE_PRICE_PATTERN = re.compile(NEXT_FLIGHT_SALE_PRICE_PATTERN, re.S)
_NEXT_FLIGHT_ORIGINAL_PRICE_PATTERN = re.compile(
    NEXT_FLIGHT_ORIGINAL_PRICE_PATTERN, re.S
)
_NEXT_FLIGHT_RATING_PATTERN = re.compile(NEXT_FLIGHT_RATING_PATTERN)
_NEXT_FLIGHT_AVAILABILITY_PATTERN = re.compile(NEXT_FLIGHT_AVAILABILITY_PATTERN)


def _extract_from_structured_sources(
    *,
    page_sources: dict[str, object],
    xhr_payloads: list[dict],
    surface: str,
    page_url: str,
    max_json_recursion_depth: int = MAX_JSON_RECURSION_DEPTH,
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
        if is_meaningful_structured_listing_record(record, surface=surface)
    ]
    if ld_records:
        structured_groups.append(ld_records)

    next_data = page_sources.get("next_data")
    if next_data:
        next_records = _extract_from_next_data(next_data, surface, page_url)
        next_records = [
            record
            for record in next_records
            if is_meaningful_structured_listing_record(record, surface=surface)
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
                max_depth=max(max_json_recursion_depth + 4, 8),
            )
            if state_records:
                for r in state_records:
                    r["_source"] = "hydrated_state"
                filtered_state_records = [
                    record
                    for record in state_records
                    if is_meaningful_structured_listing_record(record, surface=surface)
                ]
                if filtered_state_records:
                    structured_groups.append(filtered_state_records)

    for payload in xhr_payloads:
        payload_url = str(payload.get("url") or "").strip()
        body = payload.get("body")
        if not isinstance(body, (dict, list)):
            continue
        net_records = _extract_items_from_json(
            body,
            surface,
            page_url,
            max_depth=max(max_json_recursion_depth + 4, 8),
        )
        if net_records:
            for r in net_records:
                r["_source"] = "network_payload"
            filtered_net_records = [
                record
                for record in net_records
                if is_meaningful_structured_listing_record(record, surface=surface)
            ]
            filtered_net_records = filter_relevant_network_record_set(
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


def _extract_from_comparison_tables(
    soup,
    *,
    surface: str,
    page_url: str,
) -> list[dict]:
    if "job" in str(surface or "").lower():
        return []
    records: list[dict] = []
    for table in soup.select("table"):
        header_row = table.select_one("thead tr.product") or table.select_one("tr.product")
        if header_row is None:
            continue
        header_cells = header_row.find_all(["th", "td"], recursive=False)
        if len(header_cells) < 3:
            continue
        column_records: list[dict] = []
        for cell in header_cells[1:]:
            record = _extract_comparison_table_column_record(cell, page_url=page_url)
            if record:
                column_records.append(record)
        if len(column_records) < MIN_VIABLE_RECORDS:
            continue
        body_rows = list(table.select("tbody tr"))
        for row in body_rows:
            cells = row.find_all(["th", "td"], recursive=False)
            if len(cells) < len(column_records) + 1:
                continue
            label = _normalize_listing_title_text(cells[0].get_text(" ", strip=True))
            if not label:
                continue
            values = [
                _extract_comparison_table_value(cell)
                for cell in cells[1 : len(column_records) + 1]
            ]
            if not any(value for value in values):
                continue
            _apply_comparison_table_row(column_records, label=label, values=values)
        for record in column_records:
            if is_meaningful_listing_record(record, surface=surface):
                record["_source"] = "comparison_table"
                records.append(record)
        if len(records) >= MIN_VIABLE_RECORDS:
            break
    return records


def _extract_comparison_table_column_record(cell, *, page_url: str) -> dict[str, object]:
    from bs4 import Tag
    record: dict[str, object] = {}
    link = cell.select_one("a[href]")
    href = str(link.get("href") or "").strip() if isinstance(link, Tag) else ""
    if href:
        record["url"] = urljoin(page_url, href)
    image = ""
    image_el = cell.select_one("img[src]")
    if isinstance(image_el, Tag):
        image = str(image_el.get("src") or "").strip()
    if image:
        record["image_url"] = urljoin(page_url, image)
    title = ""
    if isinstance(link, Tag):
        title = _normalize_listing_title_text(link.get_text(" ", strip=True))
        if not title:
            title = _normalize_listing_title_text(link.get("aria-label"))
        if not title:
            title = _normalize_listing_title_text(link.get("title"))
    if not title and record.get("url"):
        title = _title_from_product_url(str(record.get("url") or ""))
    if title:
        record["title"] = title
    return record


def _extract_comparison_table_value(cell) -> str:
    text = _normalize_listing_title_text(cell.get_text(" ", strip=True))
    if text:
        return text
    image = cell.select_one("img[alt]")
    if image is not None:
        alt = _normalize_listing_title_text(image.get("alt"))
        if alt and alt.lower() != "dash":
            return alt
    if cell.select_one("img"):
        return "Yes"
    return ""


def _apply_comparison_table_row(
    records: list[dict[str, object]],
    *,
    label: str,
    values: list[str],
) -> None:
    key = _comparison_table_field_name(label)
    for record, value in zip(records, values, strict=False):
        if not value:
            continue
        if key == "price" and "price" not in record:
            record["price"] = value
            continue
        if key == "availability":
            record["availability"] = value
            continue
        summary = str(record.get("description") or "").strip()
        line = f"{label}: {value}"
        record["description"] = f"{summary} | {line}".strip(" |") if summary else line


def _comparison_table_field_name(label: str) -> str:
    lowered = _normalize_listing_title_text(label).lower()
    if "price" in lowered:
        return "price"
    if lowered in {"availability", "in stock", "stock"}:
        return "availability"
    return lowered


def _title_from_product_url(url_value: str) -> str:
    parsed = urlparse(str(url_value or "").strip())
    path = parsed.path.rstrip("/")
    if not path:
        return ""
    segment = path.split("/")[-1]
    segment = re.sub(r"\.[A-Za-z0-9]+$", "", segment)
    segment = re.sub(r"^[pk]\.", "", segment, flags=re.IGNORECASE)
    segment = re.sub(r"[-_]+", " ", segment)
    candidate = _normalize_listing_title_text(segment)
    if not candidate:
        return ""
    words = [part for part in candidate.split() if part]
    if len(words) > 12:
        words = words[:12]
    return " ".join(word.capitalize() if word.islower() else word for word in words)


def _adapter_candidate_records(records: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        candidate = dict(record)
        candidate["_source"] = str(record.get("_source") or "adapter")
        if is_meaningful_listing_record(
            candidate, surface=str(candidate.get("_surface") or "")
        ):
            normalized.append(candidate)
    return normalized


def _extract_from_json_ld(
    soup, surface: str, page_url: str
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
        if is_meaningful_structured_listing_record(record, surface=surface)
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


def _extract_next_data_payload(soup) -> dict | None:
    node = soup.select_one("script#__NEXT_DATA__")
    if node is None:
        return None
    payload = _parse_json_script(node.string or node.get_text(" ", strip=True) or "")
    return payload if isinstance(payload, dict) else None


def _normalize_ld_item(item: dict, surface: str, page_url: str) -> dict | None:
    """Normalize a JSON-LD Product or JobPosting into a flat record."""
    from app.services.extract.listing_card_extractor import (
        _extract_image_candidates,
        _infer_currency_from_page_url,
    )

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
    from app.services.extract.listing_item_normalizer import _normalize_generic_item

    records = []
    for item in items:
        if _looks_like_listing_filter_option(item):
            continue
        record = _normalize_generic_item(item, surface, page_url)
        if (
            record
            and is_meaningful_listing_record(record, surface=surface)
            and (
                "ecommerce" not in str(surface or "").lower()
                or has_strong_ecommerce_listing_signal(record)
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


def _normalized_field_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_listing_title_text(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    text = re.sub(r"\s+([,;:/|])", r"\1", text)
    text = re.sub(r"([(/])\s+", r"\1", text)
    text = re.sub(r"\s+([)])", r"\1", text)
    text = re.sub(r"\s*[,;/|:-]+\s*$", "", text).strip()
    return text


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
    for chunk in decoded_chunks:
        for pair_pattern in _NEXT_FLIGHT_PAIR_PATTERNS:
            for match in pair_pattern.finditer(chunk):
                raw_url = match.group("url")
                title = match.group("title")
                if not title:
                    continue

                start_index = max(0, match.start() - NEXT_FLIGHT_BACK_WINDOW)
                end_index = min(len(chunk), match.end() + NEXT_FLIGHT_FORWARD_WINDOW)
                window = chunk[start_index:end_index]

                resolved_url = urljoin(page_url, raw_url)
                record = records_by_url.setdefault(
                    resolved_url, {"url": resolved_url, "_source": "next_flight"}
                )
                record["title"] = title

                brand_match = None
                for brand_pattern in _NEXT_FLIGHT_BRAND_PATTERNS:
                    brand_match = brand_pattern.search(window)
                    if brand_match:
                        break
                if brand_match:
                    record.setdefault("brand", brand_match.group("brand"))
                if sale_price_match := _NEXT_FLIGHT_SALE_PRICE_PATTERN.search(window):
                    record.setdefault("price", sale_price_match.group("amount"))
                if original_price_match := _NEXT_FLIGHT_ORIGINAL_PRICE_PATTERN.search(
                    window
                ):
                    record.setdefault(
                        "original_price", original_price_match.group("amount")
                    )
                if rating_match := _NEXT_FLIGHT_RATING_PATTERN.search(window):
                    record.setdefault("rating", rating_match.group("rating"))
                    record.setdefault("review_count", rating_match.group("count"))
                if availability_match := _NEXT_FLIGHT_AVAILABILITY_PATTERN.search(
                    window
                ):
                    record.setdefault(
                        "availability", availability_match.group("availability")
                    )

    return [
        record
        for record in records_by_url.values()
        if is_meaningful_listing_record(record, surface="ecommerce_listing")
    ]


def _extract_from_inline_object_arrays(
    html: str,
    surface: str,
    page_url: str,
) -> list[dict]:
    seen: set[str] = set()
    key_pattern = re.compile(
        r'(?P<key>["\']?[A-Za-z_][A-Za-z0-9_-]*["\']?)\s*:\s*\['
    )

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


_MAX_INLINE_LITERAL_SCAN_CHARS = 250_000
_MAX_INLINE_LITERAL_NESTING_DEPTH = 256


def _extract_balanced_literal(text: str, start_index: int) -> str | None:
    if start_index < 0 or start_index >= len(text) or text[start_index] not in "[{":
        return None
    scan_limit = min(len(text), start_index + _MAX_INLINE_LITERAL_SCAN_CHARS)
    script_close_index = text.find("</script", start_index)
    if script_close_index != -1:
        scan_limit = min(scan_limit, script_close_index)
    stack = [text[start_index]]
    in_string = False
    escape = False
    quote_char = ""
    index = start_index + 1

    while index < scan_limit:
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
                if len(stack) > _MAX_INLINE_LITERAL_NESTING_DEPTH:
                    return None
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
    combined: str,
    raw_url: str,
    page_url: str,
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
