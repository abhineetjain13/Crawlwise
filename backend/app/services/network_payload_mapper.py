from __future__ import annotations

from typing import Any

import jmespath

from app.services.config.network_payload_specs import NETWORK_PAYLOAD_SPECS
from app.services.extraction_html_helpers import extract_job_sections, html_to_text
from app.services.field_value_candidates import (
    collect_structured_candidates,
    finalize_candidate_value,
)
from app.services.field_value_core import (
    STRUCTURED_MULTI_FIELDS,
    surface_alias_lookup,
    surface_fields,
)

# ------------------------------------------------------------------
# Ghost-routing: dynamic API schema inference via key signatures
# ------------------------------------------------------------------
_PRODUCT_SIGNATURE: frozenset[str] = frozenset({
    "price", "sku", "name", "description", "title", "brand",
    "availability", "image", "images", "currency", "vendor",
    "product_type", "category", "compare_at_price", "variants",
    "inventory_quantity", "body_html",
})

_JOB_SIGNATURE: frozenset[str] = frozenset({
    "title", "description", "location", "company", "apply_url",
    "posted_date", "employment_type", "salary", "department",
    "qualifications", "responsibilities", "benefits", "remote",
    "date_posted", "datePosted", "applyUrl", "job_type",
    "content", "absolute_url", "company_name",
})

_SIGNATURE_MIN_MATCH = 3


def map_network_payloads_to_fields(
    payloads: list[dict[str, object]] | None,
    *,
    surface: str,
    page_url: str,
) -> list[dict[str, Any]]:
    normalized_surface = str(surface or "").strip().lower()
    surface_specs = NETWORK_PAYLOAD_SPECS.get(normalized_surface, ())
    rows: list[dict[str, Any]] = []
    for payload in _ordered_payloads(payloads, surface=normalized_surface):
        if not isinstance(payload, dict):
            continue
        body = payload.get("body")
        if not isinstance(body, (dict, list)):
            continue
        if surface_specs:
            mapped = _map_payload_body(body, surface_specs=surface_specs)
            if mapped:
                rows.append(mapped)
                continue
        ghost_mapped = _ghost_route_payload(body, page_url=page_url)
        if ghost_mapped:
            rows.append(ghost_mapped)
    return rows


def _ordered_payloads(
    payloads: list[dict[str, object]] | None,
    *,
    surface: str,
) -> list[dict[str, object]]:
    indexed = [
        (index, payload)
        for index, payload in enumerate(list(payloads or []))
        if isinstance(payload, dict)
    ]
    indexed.sort(
        key=lambda item: (
            -_payload_priority(item[1], surface=surface),
            item[0],
        )
    )
    return [payload for _, payload in indexed]


def _payload_priority(payload: dict[str, object], *, surface: str) -> int:
    endpoint_type = str(payload.get("endpoint_type") or "").strip().lower()
    endpoint_family = str(payload.get("endpoint_family") or "").strip().lower()
    lowered_url = str(payload.get("url") or "").strip().lower()
    score = 0
    if endpoint_type == "graphql":
        score += 30
    elif endpoint_type == "job_api":
        score += 28
    elif endpoint_type == "product_api":
        score += 28
    elif endpoint_type == "generic_json":
        body = payload.get("body")
        if isinstance(body, dict) and _body_matches_signature_quick(body):
            score += 22
        else:
            score += 5

    if endpoint_family and endpoint_family in _configured_endpoint_families(surface):
        score += 20
    for tokens in _configured_endpoint_path_tokens(surface):
        if any(token in lowered_url for token in tokens):
            score += 10
            break
    return score


def _configured_endpoint_families(surface: str) -> set[str]:
    families: set[str] = set()
    for spec in NETWORK_PAYLOAD_SPECS.get(surface, ()):
        raw_families = spec.get("endpoint_families", ())
        if not isinstance(raw_families, tuple):
            continue
        for family in raw_families:
            normalized = str(family or "").strip().lower()
            if normalized:
                families.add(normalized)
    return families


def _configured_endpoint_path_tokens(surface: str) -> list[tuple[str, ...]]:
    token_groups: list[tuple[str, ...]] = []
    for spec in NETWORK_PAYLOAD_SPECS.get(surface, ()):
        raw_tokens = spec.get("endpoint_path_tokens")
        if isinstance(raw_tokens, tuple) and raw_tokens:
            token_groups.append(raw_tokens)
    return token_groups


def _map_payload_body(
    body: object,
    *,
    surface_specs: tuple[dict[str, object], ...],
) -> dict[str, Any]:
    for spec in surface_specs:
        mapped = _map_body_with_spec(body, spec=spec)
        if mapped:
            return mapped
    return {}


def _map_body_with_spec(
    body: object,
    *,
    spec: dict[str, object],
) -> dict[str, Any]:
    required_path_groups = spec.get("required_path_groups", ())
    if not _matches_required_path_groups(body, required_path_groups):
        return {}
    field_paths = spec.get("field_paths", {})
    if not isinstance(field_paths, dict):
        return {}
    mapped = {
        field_name: _first_non_empty_path(body, paths)
        for field_name, paths in field_paths.items()
        if isinstance(field_name, str)
    }
    result = {
        key: value
        for key, value in mapped.items()
        if value not in (None, "", [], {})
    }
    description_html = str(result.pop("description_html", "") or "").strip()
    if description_html:
        result.update(extract_job_sections(description_html))
        if "description" not in result:
            result["description"] = html_to_text(description_html)
    if result.get("apply_url") and not result.get("url"):
        result["url"] = result["apply_url"]
    return result


def _matches_required_path_groups(
    body: object,
    required_path_groups: object,
) -> bool:
    if not isinstance(required_path_groups, tuple):
        return True
    for group in required_path_groups:
        if not isinstance(group, tuple):
            return False
        if _first_non_empty_path(body, group) in (None, "", [], {}):
            return False
    return True


def _first_non_empty_path(body: object, paths: object) -> Any:
    if isinstance(paths, str):
        paths = (paths,)
    if not isinstance(paths, tuple):
        return None
    for path in paths:
        if not isinstance(path, str) or not path.strip():
            continue
        value = jmespath.search(path, body)
        if value not in (None, "", [], {}):
            return value
    return None


# ------------------------------------------------------------------
# Ghost-routing helpers
# ------------------------------------------------------------------


def _collect_keys(body: object, *, depth: int = 0, limit: int = 2) -> set[str]:
    if depth > limit or not isinstance(body, dict):
        return set()
    keys = set(body.keys())
    for value in body.values():
        if isinstance(value, dict):
            keys |= _collect_keys(value, depth=depth + 1, limit=limit)
        elif isinstance(value, list):
            for item in value[:5]:
                if isinstance(item, dict):
                    keys |= _collect_keys(item, depth=depth + 1, limit=limit)
    return keys


def _looks_like_product_api(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    keys = _collect_keys(body)
    return len(keys & _PRODUCT_SIGNATURE) >= _SIGNATURE_MIN_MATCH


def _looks_like_job_api(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    keys = _collect_keys(body)
    return len(keys & _JOB_SIGNATURE) >= _SIGNATURE_MIN_MATCH


def _body_matches_signature_quick(body: dict[str, object]) -> bool:
    keys = set(body.keys())
    for value in body.values():
        if isinstance(value, dict):
            keys |= set(value.keys())
    return (
        len(keys & _PRODUCT_SIGNATURE) >= _SIGNATURE_MIN_MATCH
        or len(keys & _JOB_SIGNATURE) >= _SIGNATURE_MIN_MATCH
    )


def _infer_surface_from_body(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    keys = _collect_keys(body)
    product_score = len(keys & _PRODUCT_SIGNATURE)
    job_score = len(keys & _JOB_SIGNATURE)
    if product_score >= _SIGNATURE_MIN_MATCH and product_score >= job_score:
        return "ecommerce_detail"
    if job_score >= _SIGNATURE_MIN_MATCH:
        return "job_detail"
    return None


def _ghost_route_payload(
    body: object,
    *,
    page_url: str,
) -> dict[str, Any] | None:
    inferred_surface = _infer_surface_from_body(body)
    if not inferred_surface:
        return None
    alias_lookup = surface_alias_lookup(inferred_surface, None)
    candidates: dict[str, list[object]] = {}
    collect_structured_candidates(body, alias_lookup, page_url, candidates)
    result: dict[str, Any] = {}
    for field_name in surface_fields(inferred_surface, None):
        finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
        if finalized not in (None, "", [], {}):
            if field_name in STRUCTURED_MULTI_FIELDS and not isinstance(finalized, list):
                continue
            result[field_name] = finalized
    description_html = str(result.pop("description_html", "") or "").strip()
    if description_html:
        result.update(extract_job_sections(description_html))
        if "description" not in result:
            result["description"] = html_to_text(description_html)
    if result.get("apply_url") and not result.get("url"):
        result["url"] = result["apply_url"]
    return result if result else None
