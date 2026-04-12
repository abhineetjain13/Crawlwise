from __future__ import annotations

import asyncio
import json
import re

from app.services.config.extraction_audit_settings import (
    SOURCE_PARSER_DATALAYER_FIELD_WEIGHTS,
    SOURCE_PARSER_EMBEDDED_BLOB_LIST_SAMPLE_SIZE,
    SOURCE_PARSER_EMBEDDED_BLOB_MAX_DEPTH,
    SOURCE_PARSER_EMBEDDED_BLOB_STRONG_ONLY_THRESHOLD,
    SOURCE_PARSER_EMBEDDED_BLOB_STRONG_SIGNAL_THRESHOLD,
    SOURCE_PARSER_EMBEDDED_BLOB_SUPPORTING_SIGNAL_THRESHOLD,
    SOURCE_PARSER_EMBEDDED_BLOB_WEAK_SIGNAL_THRESHOLD,
    SOURCE_PARSER_PREVIOUS_HEADING_LIMIT,
)
from app.services.config.extraction_rules import HYDRATED_STATE_PATTERNS
from app.services.extract.shared_json_helpers import (
    extract_balanced_json_fragment,
    parse_json_fragment,
)
from bs4 import BeautifulSoup, Tag

_DATALAYER_PUSH_RE = re.compile(r"dataLayer\.push\s*\(")
_REACT_CREATE_ELEMENT_RE = re.compile(r"createElement\s*\(")
_APOLLO_STATE_META_NAME_RE = re.compile(r"apollo[-_]state", re.IGNORECASE)
_NEXT_BOOTSTRAP_CHILD_RE = re.compile(
    r"self\.__next_f\.push\(\s*\[(?:.|\n)*?({.*?}|\[.*?\])(?:.|\n)*?\]\s*\)"
)
_HYDRATED_ASSIGNMENT_PATTERNS = tuple(
    re.compile(rf"(?:window\.)?{re.escape(pattern)}\s*=\s*", re.DOTALL)
    for pattern in HYDRATED_STATE_PATTERNS
)
_EMBEDDED_BLOB_PAYLOAD_KEY = "_blob_payload"
_EMBEDDED_BLOB_FAMILY_KEY = "_blob_family"
_EMBEDDED_BLOB_ORIGIN_KEY = "_blob_origin"
_APPROVED_EMBEDDED_ATTR_TOKENS = (
    "product",
    "item",
    "variant",
    "offer",
    "inventory",
    "price",
    "sku",
    "spec",
    "detail",
    "gallery",
    "media",
)
_APPROVED_EMBEDDED_SCRIPT_ID_TOKENS = _APPROVED_EMBEDDED_ATTR_TOKENS
_PRODUCT_CONTAINER_KEYS = {
    "product": "product_json",
    "products": "product_json",
    "item": "product_json",
    "items": "product_json",
    "pdp": "product_json",
    "productdetail": "product_detail_json",
    "productdetails": "product_detail_json",
    "detail": "product_detail_json",
    "variant": "variant_json",
    "variants": "variant_json",
    "offer": "offer_json",
    "offers": "offer_json",
    "inventory": "inventory_json",
    "media": "media_json",
    "gallery": "media_json",
    "images": "media_json",
    "image": "media_json",
    "specifications": "spec_json",
    "specs": "spec_json",
    "attributes": "spec_json",
    "details": "spec_json",
}
_PRODUCT_STRONG_SIGNAL_KEYS = {
    "price",
    "saleprice",
    "sale_price",
    "originalprice",
    "original_price",
    "compareatprice",
    "compare_at_price",
    "currency",
    "pricecurrency",
    "price_currency",
    "brand",
    "brandname",
    "sku",
    "mpn",
    "availability",
    "category",
    "images",
    "image",
    "media",
    "gallery",
}
_PRODUCT_SUPPORTING_SIGNAL_KEYS = {
    "name",
    "title",
    "description",
}


def parse_page_sources(
    html: str,
    *,
    soup: BeautifulSoup | None = None,
) -> dict[str, object]:
    soup = soup if soup is not None else BeautifulSoup(html or "", "html.parser")
    hydrated_states, hydrated_script_ids = extract_hydrated_states(soup)
    # Extract Apollo state from meta tags used by GraphQL-driven apps
    apollo_state = extract_apollo_state_from_meta(soup)
    if apollo_state:
        hydrated_states.append(apollo_state)
    next_data = extract_next_data(soup)
    if next_data is None and hydrated_states:
        next_data = {"_hydrated_states": hydrated_states}
    elif next_data is not None and hydrated_states:
        next_data = {**dict(next_data), "_hydrated_states": hydrated_states}
    return {
        "next_data": next_data,
        "hydrated_states": hydrated_states,
        "embedded_json": extract_embedded_json(soup, seen_script_ids=hydrated_script_ids),
        "open_graph": extract_open_graph(soup),
        "json_ld": extract_json_ld(soup),
        "microdata": extract_microdata(soup),
        "tables": extract_tables(soup),
        "datalayer": parse_datalayer(html),
    }


async def parse_page_sources_async(
    html: str,
    *,
    soup: BeautifulSoup | None = None,
) -> dict[str, object]:
    """Async wrapper for CPU-bound page source parsing.

    Any provided ``soup`` is ignored so the worker thread always parses a fresh
    BeautifulSoup instance and does not share mutable parser state.
    """
    _ = soup
    return await asyncio.to_thread(parse_page_sources, html, soup=None)


def extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    results = []
    for node in soup.select("script[type='application/ld+json']"):
        # FIX: Do not use get_text() as it strips HTML tags inside valid JSON strings,
        # corrupting the payload. Use the raw inner strings.
        raw_text = node.string
        if not raw_text:
            raw_text = "".join(node.strings)
            
        data = parse_json_fragment(raw_text.strip())
        results.extend(_flatten_json_ld_payloads(data))
    return results


def parse_datalayer(html: str) -> dict[str, object]:
    """Extract Google Tag Manager dataLayer from page HTML.
    
    Supports:
    - GA4 schema: dataLayer.push({ecommerce: {items: [...]}})
    - UA schema: dataLayer.push({ecommerce: {detail: {...}}})
    
    Returns dict with extracted fields:
    - price, sale_price, discount_amount, availability, price_currency, category
    
    Returns empty dict if dataLayer absent or malformed.
    """
    # Preserve first-match semantics across dataLayer pushes.
    for push_index, match in enumerate(_DATALAYER_PUSH_RE.finditer(html)):
        start_pos = match.end()
        # Extract balanced JSON fragment starting from the opening brace
        json_fragment = extract_balanced_json_fragment(html[start_pos:])
        
        if not json_fragment:
            continue
        
        parsed = parse_json_fragment(json_fragment)
        if not isinstance(parsed, dict):
            continue
        
        ecommerce = parsed.get("ecommerce")
        if not isinstance(ecommerce, dict):
            continue
        result = _extract_datalayer_ecommerce_payload(ecommerce)
        if not result:
            continue
        return {**result, "_selected_push_index": push_index}

    return {}


async def parse_datalayer_async(html: str) -> dict[str, object]:
    """Async wrapper for CPU-bound dataLayer parsing."""
    return await asyncio.to_thread(parse_datalayer, html)


def _extract_datalayer_ecommerce_payload(ecommerce: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}

    items = ecommerce.get("items")
    if isinstance(items, list) and items:
        item = items[0]
        if isinstance(item, dict):
            if "price" in item:
                result["price"] = item["price"]
            if "discount" in item:
                discount_value = item["discount"]
                if isinstance(discount_value, str) and "%" in discount_value:
                    result["discount_percentage"] = discount_value.replace("%", "").strip()
                else:
                    price_val: float | None = None
                    disc_val: float | None = None
                    try:
                        if "price" in item:
                            price_val = float(item["price"])
                    except (TypeError, ValueError):
                        price_val = None
                    try:
                        disc_val = float(discount_value)
                    except (TypeError, ValueError):
                        disc_val = None
                    if _datalayer_discount_looks_like_percentage(
                        discount_value,
                        price_value=price_val,
                        discount_value_numeric=disc_val,
                        price_currency=str(
                            item.get("currency") or ecommerce.get("currencyCode") or ""
                        )
                        or None,
                    ):
                        result["discount_percentage"] = discount_value
                    else:
                        result["discount_amount"] = discount_value
                        if price_val is not None and disc_val is not None and price_val >= 0 and disc_val >= 0:
                            result["sale_price"] = max(0, price_val - disc_val)
            if "item_category" in item:
                result["category"] = item["item_category"]
                result["google_product_category"] = item["item_category"]
            if "currency" in item:
                result["price_currency"] = item["currency"]
            availability_value = item.get("availability") or item.get("itemAvailability")
            if availability_value not in (None, "", [], {}):
                result["availability"] = availability_value

    detail = ecommerce.get("detail")
    if isinstance(detail, dict):
        products = detail.get("products")
        if isinstance(products, list) and products:
            product = products[0]
            if isinstance(product, dict):
                if "price" in product:
                    result["price"] = product["price"]
                if "category" in product:
                    result["category"] = product["category"]
                    result["google_product_category"] = product["category"]
                availability_value = product.get("availability") or product.get(
                    "itemAvailability"
                )
                if availability_value not in (None, "", [], {}):
                    result["availability"] = availability_value

    if "currencyCode" in ecommerce:
        result["price_currency"] = ecommerce["currencyCode"]

    return result


def _datalayer_discount_looks_like_percentage(
    raw_discount: object,
    *,
    price_value: float | None,
    discount_value_numeric: float | None,
    price_currency: str | None = None,
) -> bool:
    if discount_value_numeric is None or discount_value_numeric <= 0:
        return False
    if discount_value_numeric > 100:
        return False
    if price_value is None or price_value <= 0:
        return False
    raw_text = str(raw_discount or "").strip()
    if "%" in raw_text:
        return True
    if not re.fullmatch(r"-?\d+(?:\.0+)?", raw_text):
        return False
    currency = str(price_currency or "").strip().upper()
    if currency in {"JPY", "KRW"}:
        return False
    # If discount exceeds price, it's almost certainly a percentage.
    if discount_value_numeric > price_value:
        return True
    if discount_value_numeric < price_value * 0.5:
        return True
    return False

def _score_datalayer_payload(
    result: dict[str, object], *, push_index: int
) -> tuple[int, int, int]:
    populated_fields = {
        key
        for key, value in result.items()
        if key != "_selected_push_index" and value not in (None, "", [], {})
    }
    weighted_score = sum(
        weight
        for key, weight in SOURCE_PARSER_DATALAYER_FIELD_WEIGHTS.items()
        if key in populated_fields
    )
    result["_selected_push_index"] = push_index
    return weighted_score, len(populated_fields), push_index


def extract_apollo_state_from_meta(soup: BeautifulSoup) -> dict | None:
    """Extract Apollo GraphQL state from meta tags used by GraphQL-driven apps."""
    for node in soup.find_all("meta", attrs={"name": _APOLLO_STATE_META_NAME_RE}):
        content = node.get("content")
        if content:
            parsed = parse_json_fragment(str(content))
            if isinstance(parsed, dict):
                return parsed
    return None


def extract_next_data(soup: BeautifulSoup) -> dict | None:
    node = soup.select_one("script#__NEXT_DATA__")
    if node and node.string:
        parsed = parse_json_fragment(node.string)
        return parsed if isinstance(parsed, dict) else None
    return None


def extract_hydrated_states(soup: BeautifulSoup) -> tuple[list[dict | list], set[str]]:
    blobs: list[dict | list] = []
    seen: set[str] = set()
    seen_script_ids: set[str] = set()
    for node in soup.find_all("script"):
        if node.get("src"):
            continue
        script_type = str(node.get("type") or "").lower()
        if script_type == "application/ld+json":
            continue
        text = node.string or node.get_text(" ", strip=True) or ""
        if not text:
            continue
        parsed_blobs: list[dict | list] = []
        candidate_texts = [text, *_extract_next_bootstrap_children(text)]
        for candidate_text in candidate_texts:
            parsed = (
                parse_json_fragment(candidate_text)
                if script_type == "application/json"
                else None
            )
            if parsed is None:
                parsed = _parse_hydrated_assignment(candidate_text)
            if parsed is None:
                parsed = _parse_react_create_element_props(candidate_text)
            if parsed is not None:
                parsed_blobs.append(parsed)
        for parsed in parsed_blobs:
            fingerprint = json.dumps(parsed, sort_keys=True, default=str)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            blobs.append(parsed)
            seen_script_ids.add(_normalized_script_identifier(node, text, fingerprint))
    return blobs, seen_script_ids


def extract_embedded_json(
    soup: BeautifulSoup, seen_script_ids: set[str] | None = None
) -> list[dict[str, object]]:
    blobs: list[dict[str, object]] = []
    seen: set[str] = set()
    seen_script_ids = set(seen_script_ids or ())
    for node in soup.find_all("script"):
        if node.get("src"):
            continue
        script_type = str(node.get("type") or "").lower()
        script_id = str(node.get("id") or "").lower()
        text = node.string or node.get_text(" ", strip=True) or ""
        if not text or script_type == "application/ld+json":
            continue
        should_probe_script = script_type == "application/json" or any(
            token in script_id for token in _APPROVED_EMBEDDED_SCRIPT_ID_TOKENS
        )
        if should_probe_script:
            for candidate_text in [text]:
                parsed = parse_json_fragment(candidate_text)
                if parsed is None:
                    continue
                fingerprint = json.dumps(parsed, sort_keys=True, default=str)
                if (
                    _normalized_script_identifier(node, text, fingerprint)
                    in seen_script_ids
                ):
                    continue
                family = _classify_embedded_blob_family(
                    parsed,
                    attr_or_id_hint=script_id,
                )
                if not family:
                    continue
                _append_unique_embedded_blob(
                    blobs,
                    seen,
                    parsed,
                    family=family,
                    origin="script",
                )
    for node in soup.find_all(True):
        if not isinstance(node, Tag):
            continue
        for attr_name, attr_value in node.attrs.items():
            if not str(attr_name or "").startswith("data-"):
                continue
            attr_name_lower = str(attr_name).lower()
            if not any(
                token in attr_name_lower for token in _APPROVED_EMBEDDED_ATTR_TOKENS
            ):
                continue
            if isinstance(attr_value, list):
                attr_text = " ".join(str(item) for item in attr_value)
            else:
                attr_text = str(attr_value or "")
            parsed = parse_json_fragment(attr_text)
            if parsed is None:
                continue
            family = _classify_embedded_blob_family(
                parsed,
                attr_or_id_hint=attr_name_lower,
            )
            if not family:
                continue
            _append_unique_embedded_blob(
                blobs,
                seen,
                parsed,
                family=family,
                origin="data_attr",
            )
    return blobs


def extract_open_graph(soup: BeautifulSoup) -> dict[str, object]:
    payload: dict[str, object] = {}
    for node in soup.select("meta[property], meta[name]"):
        key = str(node.get("property") or node.get("name") or "").strip()
        if key.lower().startswith(("og:", "twitter:")):
            value = node.get("content")
            if value not in (None, "", [], {}):
                payload[key] = value
    return payload


def extract_microdata(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    for node in soup.select("[itemscope]"):
        item: dict[str, object] = {}
        item_type = node.get("itemtype")
        if item_type:
            item["@type"] = item_type
        # Find direct properties - exclude those inside nested itemscopes
        nested_scopes = {nested for nested in node.select("[itemscope]")}
        for prop in node.select("[itemprop]"):
            # Skip if this prop is inside a nested itemscope
            if any(prop in scope.descendants for scope in nested_scopes if scope != node):
                continue
            prop_name = str(prop.get("itemprop") or "").strip()
            if not prop_name:
                continue
            if prop.name == "meta":
                value = prop.get("content")
            elif prop.name in {"a", "link"} and prop.get("href"):
                value = prop.get("href")
            elif prop.name in {"img", "source"} and prop.get("src"):
                value = prop.get("src")
            else:
                value = prop.get_text(" ", strip=True)
            if value not in (None, "", [], {}):
                item[prop_name] = value
        if item:
            items.append(item)
    return items


def extract_tables(soup: BeautifulSoup) -> list[dict]:
    tables: list[dict] = []
    for table_index, table in enumerate(soup.find_all("table"), start=1):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = []
        body_rows = []
        first_row_cells = rows[0].find_all(["th", "td"])
        if any(cell.name == "th" for cell in first_row_cells):
            headers = [_serialize_table_cell(cell, index) for index, cell in enumerate(first_row_cells, start=1)]
            data_rows = rows[1:]
        else:
            data_rows = rows
        for row_index, row in enumerate(data_rows, start=1):
            cells = row.find_all(["td", "th"])
            serialized_cells = [_serialize_table_cell(cell, index) for index, cell in enumerate(cells, start=1)]
            if any(cell.get("text") for cell in serialized_cells):
                body_rows.append({"row_index": row_index, "cells": serialized_cells})
        if headers or body_rows:
            tables.append(
                {
                    "table_index": table_index,
                    "caption": table.find("caption").get_text(" ", strip=True) if table.find("caption") else None,
                    "section_title": _nearest_section_heading(table),
                    "headers": headers,
                    "rows": body_rows,
                }
            )
    return tables


def _flatten_json_ld_payloads(payload: dict | list | None) -> list[dict]:
    flattened: list[dict] = []
    if isinstance(payload, list):
        for item in payload:
            flattened.extend(_flatten_json_ld_payloads(item))
        return flattened
    if not isinstance(payload, dict):
        return flattened
    graph = payload.get("@graph")
    if isinstance(graph, list):
        flattened.extend(item for item in graph if isinstance(item, dict))
        payload = {key: value for key, value in payload.items() if key != "@graph"}
    if any(key != "@context" for key in payload):
        flattened.append(payload)
    return flattened


def _append_unique_blob(blobs: list[dict | list], seen: set[str], parsed: dict | list) -> None:
    fingerprint = json.dumps(parsed, sort_keys=True, default=str)
    if fingerprint in seen:
        return
    seen.add(fingerprint)
    blobs.append(parsed)


def _append_unique_embedded_blob(
    blobs: list[dict[str, object]],
    seen: set[str],
    parsed: dict | list,
    *,
    family: str,
    origin: str,
) -> None:
    fingerprint = json.dumps(parsed, sort_keys=True, default=str)
    if fingerprint in seen:
        return
    seen.add(fingerprint)
    blobs.append(
        {
            _EMBEDDED_BLOB_PAYLOAD_KEY: parsed,
            _EMBEDDED_BLOB_FAMILY_KEY: family,
            _EMBEDDED_BLOB_ORIGIN_KEY: origin,
        }
    )


def _classify_embedded_blob_family(
    parsed: dict | list,
    *,
    attr_or_id_hint: str = "",
) -> str | None:
    normalized_hint = _normalize_embedded_blob_hint(attr_or_id_hint)
    hinted_family = _family_from_hint(normalized_hint)
    if hinted_family and _payload_supports_embedded_family(parsed, hinted_family):
        return hinted_family
    return _infer_embedded_blob_family(parsed)


def _family_from_hint(hint: str) -> str | None:
    for token, family in _PRODUCT_CONTAINER_KEYS.items():
        if token in hint:
            return family
    return None


def _infer_embedded_blob_family(
    parsed: dict | list,
    *,
    max_depth: int = SOURCE_PARSER_EMBEDDED_BLOB_MAX_DEPTH,
    _visited: set[int] | None = None,
) -> str | None:
    if max_depth < 0:
        return None
    if isinstance(parsed, list):
        visited = _visited or set()
        payload_id = id(parsed)
        if payload_id in visited:
            return None
        visited = set(visited)
        visited.add(payload_id)
        for item in parsed[:SOURCE_PARSER_EMBEDDED_BLOB_LIST_SAMPLE_SIZE]:
            family = _infer_embedded_blob_family(item, max_depth=max_depth - 1, _visited=visited)
            if family:
                return family
        return None
    if not isinstance(parsed, dict):
        return None

    visited = _visited or set()
    payload_id = id(parsed)
    if payload_id in visited:
        return None
    visited = set(visited)
    visited.add(payload_id)

    normalized_key_map = {
        _normalize_embedded_blob_hint(key): key
        for key in parsed.keys()
    }
    normalized_keys = set(normalized_key_map)
    for key, family in _PRODUCT_CONTAINER_KEYS.items():
        original_key = normalized_key_map.get(key)
        if original_key is not None and _payload_supports_embedded_family(
            parsed.get(original_key),
            family,
            max_depth=max_depth - 1,
            _visited=visited,
        ):
            return family

    strong_signal_count = len(normalized_keys & _PRODUCT_STRONG_SIGNAL_KEYS)
    supporting_signal_count = len(normalized_keys & _PRODUCT_SUPPORTING_SIGNAL_KEYS)
    if "specifications" in normalized_keys or "specs" in normalized_keys:
        return "spec_json"
    if {"image", "images", "media", "gallery"} & normalized_keys and (
        {"price", "brand", "sku"} & normalized_keys or "name" in normalized_keys
    ):
        return "media_json"
    if "availability" in normalized_keys and (
        {"price", "sku", "inventory"} & normalized_keys
    ):
        return "inventory_json"
    if (
        strong_signal_count >= SOURCE_PARSER_EMBEDDED_BLOB_STRONG_SIGNAL_THRESHOLD
        and supporting_signal_count
        >= SOURCE_PARSER_EMBEDDED_BLOB_SUPPORTING_SIGNAL_THRESHOLD
    ):
        return "product_json"
    if strong_signal_count >= SOURCE_PARSER_EMBEDDED_BLOB_STRONG_ONLY_THRESHOLD:
        return "product_json"
    if (
        strong_signal_count >= SOURCE_PARSER_EMBEDDED_BLOB_WEAK_SIGNAL_THRESHOLD
        and supporting_signal_count
        >= SOURCE_PARSER_EMBEDDED_BLOB_SUPPORTING_SIGNAL_THRESHOLD
    ):
        return "product_json"
    return None


def _payload_supports_embedded_family(
    payload: object,
    family: str,
    *,
    max_depth: int = SOURCE_PARSER_EMBEDDED_BLOB_MAX_DEPTH,
    _visited: set[int] | None = None,
) -> bool:
    if max_depth < 0:
        return False
    if family == "spec_json":
        return isinstance(payload, (dict, list))
    if family == "media_json":
        return isinstance(payload, (dict, list))
    if family in {"product_json", "product_detail_json", "variant_json", "offer_json", "inventory_json"}:
        return _has_embedded_product_signals(payload, max_depth=max_depth - 1, _visited=_visited)
    return False


def _normalize_embedded_blob_hint(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _has_embedded_product_signals(
    payload: object,
    *,
    max_depth: int = SOURCE_PARSER_EMBEDDED_BLOB_MAX_DEPTH,
    _visited: set[int] | None = None,
) -> bool:
    if max_depth < 0:
        return False
    family = _infer_embedded_blob_family(payload, max_depth=max_depth, _visited=_visited)
    return family in {
        "product_json",
        "product_detail_json",
        "variant_json",
        "offer_json",
        "inventory_json",
        "media_json",
        "spec_json",
    }


def _parse_hydrated_assignment(text: str) -> dict | list | None:
    for assignment_pattern in _HYDRATED_ASSIGNMENT_PATTERNS:
        match = assignment_pattern.search(text)
        if not match:
            continue
        fragment = extract_balanced_json_fragment(text[match.end():])
        if not fragment:
            continue
        parsed = parse_json_fragment(fragment)
        if parsed is not None:
            return parsed
    return None


def _parse_react_create_element_props(text: str) -> dict | list | None:
    for match in _REACT_CREATE_ELEMENT_RE.finditer(text):
        args_start = match.end()
        args_end = _find_matching_delimiter(text, args_start - 1, "(", ")")
        if args_end == -1:
            continue
        args = _split_top_level_arguments(text[args_start:args_end])
        if len(args) < 2:
            continue
        props_fragment = extract_balanced_json_fragment(args[1].strip())
        if not props_fragment:
            continue
        parsed = parse_json_fragment(props_fragment)
        if parsed is not None:
            return parsed
    return None


def _extract_next_bootstrap_children(text: str) -> list[str]:
    matches = _NEXT_BOOTSTRAP_CHILD_RE.findall(text)
    return [match for match in matches if isinstance(match, str)]


def _find_matching_delimiter(text: str, start_index: int, opening: str, closing: str) -> int:
    depth = 0
    current_string_char = ""
    escape = False
    template_expression_depth = 0
    for index in range(start_index, len(text)):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if current_string_char:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if current_string_char == "`":
                if char == "$" and next_char == "{":
                    template_expression_depth = 1 if template_expression_depth == 0 else template_expression_depth + 1
                    continue
                if char == "{" and template_expression_depth > 0 and (index == 0 or text[index - 1] != "$"):
                    template_expression_depth += 1
                    continue
                if char == "}" and template_expression_depth > 0:
                    template_expression_depth -= 1
                    continue
                if char == "`" and template_expression_depth == 0:
                    current_string_char = ""
                continue
            if char == current_string_char:
                current_string_char = ""
            continue
        if char in {'"', "'", "`"}:
            current_string_char = char
            continue
        if char == opening:
            depth += 1
            continue
        if char == closing:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _split_top_level_arguments(text: str) -> list[str]:
    args: list[str] = []
    start = 0
    paren_depth = 0
    brace_depth = 0
    bracket_depth = 0
    in_string = ""
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = ""
            continue
        if char in {'"', "'", "`"}:
            in_string = char
            continue
        if char == "(":
            paren_depth += 1
            continue
        if char == ")":
            paren_depth = max(0, paren_depth - 1)
            continue
        if char == "{":
            brace_depth += 1
            continue
        if char == "}":
            brace_depth = max(0, brace_depth - 1)
            continue
        if char == "[":
            bracket_depth += 1
            continue
        if char == "]":
            bracket_depth = max(0, bracket_depth - 1)
            continue
        if char == "," and paren_depth == 0 and brace_depth == 0 and bracket_depth == 0:
            args.append(text[start:index].strip())
            start = index + 1
    trailing = text[start:].strip()
    if trailing:
        args.append(trailing)
    return args


def _normalized_script_identifier(node: Tag, text: str, fingerprint: str) -> str:
    return f"{node.get('id') or ''}|{node.get('type') or ''}|{hash(text)}|{fingerprint[:64]}"


def _serialize_table_cell(cell: Tag, cell_index: int) -> dict[str, object]:
    href = None
    link = cell.find("a", href=True)
    if link is not None:
        href = link.get("href")
    return {
        "cell_index": cell_index,
        "text": cell.get_text(" ", strip=True),
        "href": href,
        "tag": cell.name,
    }


def _nearest_section_heading(node: Tag) -> str | None:
    for previous in node.find_all_previous(
        ["h1", "h2", "h3", "h4", "h5", "h6"],
        limit=SOURCE_PARSER_PREVIOUS_HEADING_LIMIT,
    ):
        text = previous.get_text(" ", strip=True)
        if text:
            return text
    return None
