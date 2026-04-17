# JSON listing/detail extractor.
#
# Handles API responses that return structured JSON directly.
# Searches for arrays of objects that look like product or job records
# and normalizes them into the standard record shape.
#
# JSON records are normalized here, then converted into candidate rows so
# the pipeline can arbitrate them alongside any other extraction evidence.
from __future__ import annotations

from urllib.parse import urljoin, urlparse

from app.services.config.field_mappings import (
    COLLECTION_KEYS,
    INTERNAL_ONLY_FIELDS,
)
from app.services.config.extraction_audit_settings import (
    JSON_ALIAS_VISIT_LIST_LIMIT,
    JSON_CANDIDATE_ARRAY_SAMPLE_SIZE,
    JSON_CANDIDATE_COMMERCE_SCORE,
    JSON_CANDIDATE_JOB_SCORE,
    JSON_CANDIDATE_TITLE_SCORE,
    JSON_CANDIDATE_URL_SCORE,
    JSON_IMAGE_LIST_LIMIT,
    JSON_LISTING_DEFAULT_MAX_RECORDS,
    JSON_LISTING_ALIAS_MAX_DEPTH,
    JSON_LISTING_SEARCH_MAX_DEPTH,
)
from app.services.extract.shared_logic import (
    coerce_scalar_text,
    extract_image_values,
    find_alias_values,
    resolve_slug_url,
)
from app.services.field_alias_policy import get_surface_field_aliases
from app.services.normalizers import validate_value


def extract_json_listing(
    json_data: dict | list,
    page_url: str = "",
    max_records: int = JSON_LISTING_DEFAULT_MAX_RECORDS,
    *,
    surface: str = "",
    requested_fields: list[str] | None = None,
) -> list[dict]:
    """Extract records from a JSON API response.

    Finds the main data array, then normalizes each object into the
    canonical field set for the given surface.
    """
    items = _find_items_array(json_data)
    if not items:
        return []

    normalized_requested_fields = _normalize_requested_fields(requested_fields)
    records = []
    for item in items[:max_records]:
        if not isinstance(item, dict):
            continue
        record = _normalize_item(item, page_url, surface=surface)
        record = _filter_requested_fields(record, normalized_requested_fields)
        if record and any(v for k, v in record.items() if not k.startswith("_")):
            record["_source"] = "json_api"
            records.append(record)

    return records


def extract_json_detail(
    json_data: dict | list,
    page_url: str = "",
    *,
    surface: str = "",
    requested_fields: list[str] | None = None,
) -> list[dict]:
    """Extract a single record from a JSON API response (detail page).

    The detail pipeline performs arbitration after this normalization step
    so JSON candidates participate in the shared reconciliation path.
    """
    normalized_requested_fields = _normalize_requested_fields(requested_fields)
    if isinstance(json_data, list):
        if not json_data:
            return []
        json_data = json_data[0]

    if not isinstance(json_data, dict):
        return []

    record = _normalize_item(json_data, page_url, surface=surface)
    record = _filter_requested_fields(record, normalized_requested_fields)
    if record and any(v for k, v in record.items() if not k.startswith("_")):
        record["_source"] = "json_api"
        return [record]
    return []


def build_json_candidate_rows(
    record: dict,
    *,
    source: str = "json_api",
) -> tuple[dict[str, list[dict]], dict[str, dict[str, object]]]:
    """Convert a normalized JSON record into detail-style candidate rows."""
    candidates: dict[str, list[dict]] = {}
    extraction_audit: dict[str, dict[str, object]] = {}

    for key, value in dict(record or {}).items():
        if key.startswith("_") or value in (None, "", [], {}):
            continue
        row = {"value": value, "source": source}
        candidates[key] = [row]
        extraction_audit[key] = {
            "sources": [
                {
                    "source": source,
                    "status": "produced_candidates",
                    "candidate_count": 1,
                    "row_sources": [source],
                    "value_previews": [" ".join(str(value).split()).strip()[:80]],
                }
            ]
        }

    return candidates, extraction_audit


def _normalize_requested_fields(
    requested_fields: list[str] | None,
) -> set[str] | None:
    if requested_fields is None:
        return None
    normalized = {
        str(field).strip()
        for field in requested_fields
        if isinstance(field, str) and str(field).strip()
    }
    return normalized or None


def _filter_requested_fields(
    record: dict,
    requested_fields: set[str] | None,
) -> dict:
    if requested_fields is None:
        return record
    return {
        key: value
        for key, value in record.items()
        if key.startswith("_") or key in requested_fields
    }


def _find_items_array(
    data: dict | list, max_depth: int = JSON_LISTING_SEARCH_MAX_DEPTH
) -> list[dict]:
    """Find the most likely data array in a JSON response."""
    # If top-level is already a list of objects, use it directly.
    if isinstance(data, list):
        objects = [item for item in data if isinstance(item, dict)]
        if len(objects) >= 1:
            return objects
        return []

    if not isinstance(data, dict) or max_depth <= 0:
        return []

    # Check known collection keys first.
    for key in COLLECTION_KEYS:
        if key in data and isinstance(data[key], list):
            objects = [item for item in data[key] if isinstance(item, dict)]
            if len(objects) >= 1:
                return objects

    # Check "edges" pattern (GraphQL): edges -> node
    if "edges" in data and isinstance(data["edges"], list):
        nodes = [
            edge["node"]
            for edge in data["edges"]
            if isinstance(edge, dict) and isinstance(edge.get("node"), dict)
        ]
        if len(nodes) >= 1:
            return nodes

    # Recurse into dict values looking for the largest array of objects.
    best: list[dict] = []
    best_score = -1
    for key, value in data.items():
        if isinstance(value, dict):
            found = _find_items_array(value, max_depth - 1)
            score = _score_candidate_array(found)
            if score > best_score:
                best = found
                best_score = score
        elif isinstance(value, list) and key != "edges":
            objects = [item for item in value if isinstance(item, dict)]
            score = _score_candidate_array(objects)
            if score > best_score:
                best = objects
                best_score = score

    return best


def _normalize_item(item: dict, page_url: str, *, surface: str = "") -> dict:
    """Map an arbitrary JSON object to canonical fields."""
    record: dict = {}
    consumed_keys: set[str] = set()
    # Flatten one level of nesting for fields like {"company": {"name": "X"}}
    flat = _flatten_one_level(item)
    surface_aliases = get_surface_field_aliases(surface)
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
        "additional_images",
    }

    for canonical, aliases in surface_aliases.items():
        candidate_keys = [canonical, *aliases]
        values = find_alias_values(
            flat,
            candidate_keys,
            max_depth=JSON_LISTING_ALIAS_MAX_DEPTH,
            list_limit=JSON_ALIAS_VISIT_LIST_LIMIT,
        )
        for value in values:
            normalized = _normalize_json_value(
                canonical,
                value,
                page_url=page_url,
                list_join_fields=list_join_fields,
            )
            if normalized in (None, "", [], {}):
                continue

            # FIX: Enforce strict schema validation on JSON API responses
            # to prevent payload pollution
            validated = validate_value(canonical, normalized)
            if validated in (None, "", [], {}):
                continue

            record[canonical] = validated
            consumed_keys.update(key for key in candidate_keys if key in item)
            break

    if "image_url" not in record and record.get("additional_images"):
        primary_image = str(record["additional_images"]).split(",")[0].strip()
        if primary_image:
            record["image_url"] = primary_image

    if "url" not in record:
        handle = flat.get("handle")
        if handle:
            product_url = _derive_product_url(page_url, str(handle))
            if product_url:
                record["url"] = product_url
    raw_slug = flat.get("slug")
    if "url" not in record and raw_slug not in (None, "", [], {}):
        slug_url = resolve_slug_url(str(raw_slug), page_url=page_url)
        if slug_url:
            record["url"] = slug_url

    if (
        record.get("company")
        and "brand" in record
        and record["company"] == record["brand"]
    ):
        record.pop("brand", None)

    # Preserve unmapped scalar fields before applying any surface contract so the
    # contract can remove incompatible fields decisively.
    for key, value in item.items():
        if key in consumed_keys or key.startswith("_") or key in INTERNAL_ONLY_FIELDS:
            continue
        if isinstance(value, (int, float, bool)) or (
            isinstance(value, str) and value.strip()
        ):
            record[key] = value

    inferred_surface = _infer_surface_from_item(
        item, page_url=page_url, normalized=record
    )
    if inferred_surface == "job_listing":
        record = _apply_job_surface_contract(record, item=item, page_url=page_url)

    if record:
        record["_raw_item"] = item
        if inferred_surface:
            record["_surface"] = inferred_surface
    return record


def _score_candidate_array(items: list[dict]) -> int:
    if not items:
        return -1
    sample = items[:JSON_CANDIDATE_ARRAY_SAMPLE_SIZE]
    score = len(items)
    for item in sample:
        keys = {str(key).strip().lower() for key in item}
        if keys & {"title", "name", "job_title", "position"}:
            score += JSON_CANDIDATE_TITLE_SCORE
        if keys & {"url", "href", "link", "positionuri", "apply_url"}:
            score += JSON_CANDIDATE_URL_SCORE
        if keys & {
            "company",
            "company_name",
            "companyname",
            "salary",
            "salarydisplay",
            "jobid",
            "job_id",
            "location",
        }:
            score += JSON_CANDIDATE_JOB_SCORE
        if keys & {"price", "sale_price", "brand", "sku"}:
            score += JSON_CANDIDATE_COMMERCE_SCORE
    return score


def _infer_surface_from_item(item: dict, *, page_url: str, normalized: dict) -> str:
    page_url_lower = str(page_url or "").lower()
    normalized_keys = {str(key).lower() for key in normalized}
    raw_keys = {str(key).lower() for key in item}
    if "jobs" in page_url_lower or "career" in page_url_lower:
        return "job_listing"
    if normalized_keys & {"company", "salary", "job_type", "posted_date", "apply_url"}:
        return "job_listing"
    if raw_keys & {"jobid", "job_id", "salarydisplay", "positionuri", "companyname"}:
        return "job_listing"
    return ""


def _apply_job_surface_contract(record: dict, *, item: dict, page_url: str) -> dict:
    normalized = dict(record)
    if normalized.get("price") not in (None, "", [], {}) and normalized.get(
        "salary"
    ) in (None, "", [], {}):
        normalized["salary"] = normalized.pop("price")
    if normalized.get("apply_url") in (None, "", [], {}) and normalized.get(
        "url"
    ) not in (None, "", [], {}):
        normalized["apply_url"] = normalized["url"]
    if normalized.get("job_id") in (None, "", [], {}):
        for key in (
            "jobId",
            "job_id",
            "id",
            "requisitionNumber",
            "requisition_number",
            "reqId",
        ):
            value = item.get(key)
            if value not in (None, "", [], {}):
                normalized["job_id"] = str(value).strip()
                break
    for field_name in (
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
        normalized.pop(field_name, None)
    return normalized


def _normalize_json_value(
    canonical: str,
    value: object,
    *,
    page_url: str,
    list_join_fields: set[str],
) -> object | None:
    if value in (None, "", [], {}):
        return None

    if canonical == "url":
        text = coerce_scalar_text(value)
        return urljoin(page_url, text) if text and page_url else text or None

    if canonical in {"image_url", "additional_images"}:
        images = extract_image_values(
            value,
            page_url=page_url,
            list_limit=JSON_IMAGE_LIST_LIMIT,
        )
        if not images:
            return None
        return images[0] if canonical == "image_url" else ", ".join(images)

    if isinstance(value, list):
        if canonical in list_join_fields:
            scalar_values = [
                text for item in value if (text := coerce_scalar_text(item))
            ]
            return " | ".join(dict.fromkeys(scalar_values)) if scalar_values else None
        for item in value:
            normalized = _normalize_json_value(
                canonical,
                item,
                page_url=page_url,
                list_join_fields=list_join_fields,
            )
            if normalized not in (None, "", [], {}):
                return normalized
        return None

    if isinstance(value, dict):
        if canonical in {"price", "sale_price", "original_price"}:
            for key in (
                "price",
                "amount",
                "value",
                "lowPrice",
                "minPrice",
                "maxPrice",
                "compareAtPrice",
            ):
                nested = value.get(key)
                if nested not in (None, "", [], {}):
                    return _normalize_json_value(
                        canonical,
                        nested,
                        page_url=page_url,
                        list_join_fields=list_join_fields,
                    )
        for key in (
            "url",
            "href",
            "src",
            "contentUrl",
            "name",
            "title",
            "value",
            "content",
            "text",
            "description",
        ):
            nested = value.get(key)
            if nested in (None, "", [], {}):
                continue
            normalized = _normalize_json_value(
                canonical,
                nested,
                page_url=page_url,
                list_join_fields=list_join_fields,
            )
            if normalized not in (None, "", [], {}):
                return normalized
        return None

    return str(value).strip() if not isinstance(value, (int, float, bool)) else value


def _derive_product_url(page_url: str, handle: str) -> str:
    parsed = urlparse(page_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    if not parsed.path.endswith(".json"):
        return ""
    handle = handle.strip().strip("/")
    if not handle:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/products/{handle}"
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
