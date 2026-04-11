# JSON listing/detail extractor.
#
# Handles API responses that return structured JSON directly.
# Searches for arrays of objects that look like product or job records
# and normalizes them into the standard record shape.
#
# Fields are routed through FieldDecisionEngine for unified arbitration
# with the same sanitization/ranking logic used by HTML extraction.
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from app.services.config.field_mappings import (
    INTERNAL_ONLY_FIELDS,
    COLLECTION_KEYS,
    get_surface_field_aliases,
)
from app.services.config.crawl_runtime import JSON_MAX_SEARCH_DEPTH
from app.services.normalizers import validate_value

logger = logging.getLogger(__name__)


def extract_json_listing(
    json_data: dict | list,
    page_url: str = "",
    max_records: int = 100,
    *,
    surface: str = "",
    requested_fields: list[str] | None = None,
) -> list[dict]:
    """Extract records from a JSON API response.

    Finds the main data array, then normalizes each object into the
    canonical field set for the given surface.  Each record's fields are
    routed through ``FieldDecisionEngine`` for unified sanitization and
    ranking consistent with the HTML extraction path.
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
        record = _arbitrate_record_fields(record, page_url=page_url)
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

    Fields are routed through ``FieldDecisionEngine`` for unified
    sanitization and ranking consistent with the HTML extraction path.
    """
    normalized_requested_fields = _normalize_requested_fields(requested_fields)
    if isinstance(json_data, list):
        if not json_data:
            return []
        json_data = json_data[0]

    if not isinstance(json_data, dict):
        return []

    record = _normalize_item(json_data, page_url, surface=surface)
    record = _arbitrate_record_fields(record, page_url=page_url)
    record = _filter_requested_fields(record, normalized_requested_fields)
    if record and any(v for k, v in record.items() if not k.startswith("_")):
        record["_source"] = "json_api"
        return [record]
    return []


def _arbitrate_record_fields(record: dict, *, page_url: str) -> dict:
    """Route each field in *record* through FieldDecisionEngine.

    This ensures JSON-extracted fields go through the same sanitization,
    noise filtering, and validation that HTML-extracted candidates receive.
    JSON candidates are injected with source ``"json_api"`` so they rank
    at the top of the source hierarchy (preserving JSON-first priority).

    Internal fields (``_``-prefixed) are passed through unchanged.
    """
    from app.services.extract.field_decision import FieldDecisionEngine

    if not record:
        return record

    engine = FieldDecisionEngine(base_url=page_url)
    arbitrated: dict = {}

    for key, value in record.items():
        # Pass through internal metadata fields untouched
        if key.startswith("_"):
            arbitrated[key] = value
            continue

        if value in (None, "", [], {}):
            continue

        # Build a single-candidate row list for the engine
        row = {"value": value, "source": "json_api"}
        decision = engine.decide_from_rows(key, [row])

        if decision.accepted and decision.value not in (None, "", [], {}):
            arbitrated[key] = decision.value
        else:
            logger.debug(
                "FieldDecisionEngine rejected JSON field %s: %s",
                key,
                decision.rejection_reason or "rejected",
            )

    return arbitrated


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
    data: dict | list, max_depth: int = JSON_MAX_SEARCH_DEPTH
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
        values = _find_alias_values(flat, candidate_keys, max_depth=4)
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
        slug_url = _derive_slug_url(page_url, str(raw_slug))
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
    sample = items[:5]
    score = len(items)
    for item in sample:
        keys = {str(key).strip().lower() for key in item}
        if keys & {"title", "name", "job_title", "position"}:
            score += 3
        if keys & {"url", "href", "link", "positionuri", "apply_url"}:
            score += 3
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
            score += 4
        if keys & {"price", "sale_price", "brand", "sku"}:
            score += 2
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
        text = _coerce_scalar_text(value)
        return urljoin(page_url, text) if text and page_url else text or None

    if canonical in {"image_url", "additional_images"}:
        images = _extract_image_values(value, page_url=page_url)
        if not images:
            return None
        return images[0] if canonical == "image_url" else ", ".join(images)

    if isinstance(value, list):
        if canonical in list_join_fields:
            scalar_values = [
                text for item in value if (text := _coerce_scalar_text(item))
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


def _find_alias_values(
    data: object, aliases: list[str], max_depth: int
) -> list[object]:
    alias_tokens = {
        _normalized_field_token(alias)
        for alias in aliases
        if _normalized_field_token(alias)
    }
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
                _visit(value, depth - 1)
            return
        if isinstance(node, list):
            for item in node[:40]:
                _visit(item, depth - 1)

    _visit(data, max_depth)
    return values


def _normalized_field_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _coerce_scalar_text(value: object) -> str:
    if isinstance(value, dict):
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
            if nested not in (None, "", [], {}):
                return _coerce_scalar_text(nested)
        return ""
    if isinstance(value, list):
        for item in value:
            text = _coerce_scalar_text(item)
            if text:
                return text
        return ""
    return str(value).strip() if value not in (None, "", [], {}) else ""


def _extract_image_values(value: object, *, page_url: str) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()

    def _append(candidate: str) -> None:
        resolved = urljoin(page_url, candidate) if candidate and page_url else candidate
        if not resolved or resolved in seen:
            return
        seen.add(resolved)
        images.append(resolved)

    def _visit(node: object) -> None:
        if node in (None, "", [], {}):
            return
        if isinstance(node, dict):
            for key in ("src", "url", "contentUrl", "image", "thumbnail"):
                candidate = node.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    _append(candidate.strip())
            for nested in node.values():
                if nested is not node:
                    _visit(nested)
            return
        if isinstance(node, list):
            for item in node[:20]:
                _visit(item)
            return
        text = str(node).strip()
        if text:
            _append(text)

    _visit(value)
    return images


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


def _derive_slug_url(page_url: str, slug: str) -> str:
    parsed = urlparse(page_url)
    text = str(slug or "").strip()
    if not text or not parsed.scheme or not parsed.netloc:
        return ""
    if text.startswith(("http://", "https://", "/")):
        return urljoin(page_url, text)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    return urljoin(origin, text)


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
