# JSON listing/detail extractor.
#
# Handles API responses that return structured JSON directly.
# Searches for arrays of objects that look like product or job records
# and normalizes them into the standard record shape.
from __future__ import annotations

from urllib.parse import urljoin

from app.services.pipeline_config import COLLECTION_KEYS, FIELD_ALIASES, JSON_MAX_SEARCH_DEPTH


def extract_json_listing(
    json_data: dict | list,
    page_url: str = "",
    max_records: int = 100,
) -> list[dict]:
    """Extract records from a JSON API response.

    Finds the main data array, then normalizes each object into the
    canonical field set for the given surface.
    """
    items = _find_items_array(json_data)
    if not items:
        return []

    records = []
    for item in items[:max_records]:
        if not isinstance(item, dict):
            continue
        record = _normalize_item(item, page_url)
        if record and any(v for k, v in record.items() if not k.startswith("_")):
            record["_source"] = "json_api"
            records.append(record)

    return records


def extract_json_detail(
    json_data: dict | list,
    page_url: str = "",
) -> list[dict]:
    """Extract a single record from a JSON API response (detail page)."""
    if isinstance(json_data, list):
        if not json_data:
            return []
        json_data = json_data[0]

    if not isinstance(json_data, dict):
        return []

    record = _normalize_item(json_data, page_url)
    if record and any(v for k, v in record.items() if not k.startswith("_")):
        record["_source"] = "json_api"
        return [record]
    return []


def _find_items_array(data: dict | list, max_depth: int = JSON_MAX_SEARCH_DEPTH) -> list[dict]:
    """Find the most likely data array in a JSON response."""
    # If top-level is already a list of objects, use it directly.
    if isinstance(data, list):
        objects = [item for item in data if isinstance(item, dict)]
        if len(objects) >= 2:
            return objects
        return []

    if not isinstance(data, dict) or max_depth <= 0:
        return []

    # Check known collection keys first.
    for key in COLLECTION_KEYS:
        if key in data and isinstance(data[key], list):
            objects = [item for item in data[key] if isinstance(item, dict)]
            if len(objects) >= 2:
                return objects

    # Check "edges" pattern (GraphQL): edges -> node
    if "edges" in data and isinstance(data["edges"], list):
        nodes = [
            edge["node"]
            for edge in data["edges"]
            if isinstance(edge, dict) and isinstance(edge.get("node"), dict)
        ]
        if len(nodes) >= 2:
            return nodes

    # Recurse into dict values looking for the largest array of objects.
    best: list[dict] = []
    for key, value in data.items():
        if isinstance(value, dict):
            found = _find_items_array(value, max_depth - 1)
            if len(found) > len(best):
                best = found
        elif isinstance(value, list) and key != "edges":
            objects = [item for item in value if isinstance(item, dict)]
            if len(objects) >= 2 and len(objects) > len(best):
                best = objects

    return best


def _normalize_item(item: dict, page_url: str) -> dict:
    """Map an arbitrary JSON object to canonical fields."""
    record: dict = {}
    # Flatten one level of nesting for fields like {"company": {"name": "X"}}
    flat = _flatten_one_level(item)
    list_join_fields = {
        "description",
        "responsibilities",
        "qualifications",
        "benefits",
        "skills",
        "tags",
        "specifications",
        "features",
        "materials",
        "care",
        "dimensions",
    }

    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            value = flat.get(alias)
            if value is not None and value != "" and value != [] and value != {}:
                if canonical == "url" and page_url:
                    value = urljoin(page_url, str(value))
                if isinstance(value, (list, dict)):
                    # For image_url, take first from list
                    if canonical == "image_url" and isinstance(value, list) and value:
                        value = value[0]
                        if isinstance(value, dict):
                            value = value.get("src") or value.get("url") or ""
                    elif isinstance(value, list) and canonical in list_join_fields:
                        scalar_values = [str(item).strip() for item in value if not isinstance(item, (dict, list)) and str(item).strip()]
                        if scalar_values:
                            value = " | ".join(scalar_values)
                        else:
                            continue
                    elif isinstance(value, list):
                        continue
                    else:
                        continue  # skip non-scalar for other fields
                record[canonical] = str(value).strip() if not isinstance(value, (int, float, bool)) else value
                break

    if record:
        record["_raw_item"] = item
    return record


def _flatten_one_level(item: dict) -> dict:
    """Flatten nested dicts one level deep for field matching.

    Example: {"company": {"name": "Acme"}} → {"company_name": "Acme", "company": {"name": "Acme"}}
    """
    flat = dict(item)
    for key, value in item.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                composite = f"{key}_{sub_key}"
                if composite not in flat:
                    flat[composite] = sub_value
    return flat
