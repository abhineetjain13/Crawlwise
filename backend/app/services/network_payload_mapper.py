from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import jmespath

from app.services.config.network_payload_specs import (
    NETWORK_PAYLOAD_DETAIL_CONTAINER_KEYS,
    NETWORK_PAYLOAD_JOB_SIGNATURE,
    NETWORK_PAYLOAD_LIST_COLLECTION_KEYS,
    NETWORK_PAYLOAD_PRODUCT_SIGNATURE,
    NETWORK_PAYLOAD_SIGNATURE_MIN_MATCH,
    NETWORK_PAYLOAD_SPECS,
)
from app.services.extraction_html_helpers import extract_job_sections, html_to_text
from app.services.field_value_candidates import (
    collect_structured_candidates,
    finalize_candidate_value,
)
from app.services.field_policy import normalize_field_key
from app.services.field_value_core import (
    STRUCTURED_MULTI_FIELDS,
    surface_alias_lookup,
    surface_fields,
)

_GHOST_ROUTE_COMPATIBLE_SURFACES = {
    "ecommerce_detail",
    "job_detail",
}
_DETAIL_URL_IGNORE_TOKENS: frozenset[str] = frozenset(
    {"detail", "details", "dp", "item", "job", "p", "product", "products"}
)


def map_network_payloads_to_fields(
    payloads: list[dict[str, object]] | None,
    *,
    surface: str,
    page_url: str,
    requested_fields: list[str] | None = None,
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
        ghost_mapped = _ghost_route_payload(
            body,
            surface=normalized_surface,
            page_url=page_url,
            requested_fields=requested_fields,
        )
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
    indexed.sort(key=lambda item: (-_payload_priority(item[1], surface=surface), item[0]))
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
    return _finalize_detail_result(result)


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


def _collect_keys(body: object, *, depth: int = 0, limit: int = 2) -> set[str]:
    if depth > limit or not isinstance(body, dict):
        return set()
    keys = {
        normalized
        for key in body.keys()
        if (normalized := normalize_field_key(str(key or "")))
    }
    for value in body.values():
        if isinstance(value, dict):
            keys |= _collect_keys(value, depth=depth + 1, limit=limit)
        elif isinstance(value, list):
            for item in value[:5]:
                if isinstance(item, dict):
                    keys |= _collect_keys(item, depth=depth + 1, limit=limit)
    return keys


def _looks_like_product_api(body: object) -> bool:
    return _matches_signature(body, NETWORK_PAYLOAD_PRODUCT_SIGNATURE)


def _looks_like_job_api(body: object) -> bool:
    return _matches_signature(body, NETWORK_PAYLOAD_JOB_SIGNATURE)


def _body_matches_signature_quick(body: dict[str, object]) -> bool:
    return _matches_signature(body, NETWORK_PAYLOAD_PRODUCT_SIGNATURE, depth=1) or _matches_signature(
        body,
        NETWORK_PAYLOAD_JOB_SIGNATURE,
        depth=1,
    )


def _infer_surface_from_body(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    keys = _collect_keys(body)
    product_score = len(keys & NETWORK_PAYLOAD_PRODUCT_SIGNATURE)
    job_score = len(keys & NETWORK_PAYLOAD_JOB_SIGNATURE)
    if (
        product_score >= NETWORK_PAYLOAD_SIGNATURE_MIN_MATCH
        and product_score >= job_score
    ):
        return "ecommerce_detail"
    if job_score >= NETWORK_PAYLOAD_SIGNATURE_MIN_MATCH:
        return "job_detail"
    return None


def _ghost_route_payload(
    body: object,
    *,
    surface: str,
    page_url: str,
    requested_fields: list[str] | None,
) -> dict[str, Any] | None:
    if _looks_like_multi_record_collection(body):
        return None
    inferred_surface = _infer_surface_from_body(body)
    if not inferred_surface:
        return None
    normalized_surface = str(surface or "").strip().lower()
    if (
        normalized_surface in _GHOST_ROUTE_COMPATIBLE_SURFACES
        and inferred_surface != normalized_surface
    ):
        return None
    if _looks_like_navigation_payload(body):
        return None
    if not _has_detail_anchor(
        body,
        inferred_surface=inferred_surface,
        page_url=page_url,
        requested_fields=requested_fields,
    ):
        return None
    alias_lookup = surface_alias_lookup(inferred_surface, requested_fields)
    candidates: dict[str, list[object]] = {}
    collect_structured_candidates(body, alias_lookup, page_url, candidates)
    result: dict[str, Any] = {}
    for field_name in surface_fields(inferred_surface, requested_fields):
        finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
        if finalized not in (None, "", [], {}):
            if field_name in STRUCTURED_MULTI_FIELDS and not isinstance(finalized, list):
                continue
            result[field_name] = finalized
    url = finalize_candidate_value("url", candidates.get("url", []))
    if url not in (None, "", [], {}):
        result["url"] = url
    result = _finalize_detail_result(result)
    return result or None


def _matches_signature(
    body: object,
    signature: frozenset[str],
    *,
    depth: int = 2,
) -> bool:
    return (
        isinstance(body, dict)
        and len(_collect_keys(body, limit=depth) & signature)
        >= NETWORK_PAYLOAD_SIGNATURE_MIN_MATCH
    )


def _looks_like_multi_record_collection(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    if any(isinstance(body.get(key), dict) for key in NETWORK_PAYLOAD_DETAIL_CONTAINER_KEYS):
        return False
    return _contains_multi_record_collection(body, depth=0)


def _contains_multi_record_collection(body: object, *, depth: int) -> bool:
    if depth > 1 or not isinstance(body, dict):
        return False
    for key, value in body.items():
        normalized_key = str(key or "").strip().lower()
        if normalized_key in NETWORK_PAYLOAD_LIST_COLLECTION_KEYS and _list_looks_like_records(value):
            return True
        if isinstance(value, dict) and _contains_multi_record_collection(value, depth=depth + 1):
            return True
    return False


def _list_looks_like_records(value: object) -> bool:
    if not isinstance(value, list):
        return False
    dict_items = [item for item in value[:5] if isinstance(item, dict)]
    if len(dict_items) < 2:
        return False
    return all(
        _matches_signature(item, NETWORK_PAYLOAD_PRODUCT_SIGNATURE, depth=1)
        or _matches_signature(item, NETWORK_PAYLOAD_JOB_SIGNATURE, depth=1)
        for item in dict_items[:3]
    )


def _looks_like_navigation_payload(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    keys = {str(key or "").strip().lower() for key in _collect_keys(body)}
    if not keys:
        return False
    navigation_hits = len(
        keys
        & {
            "children",
            "footer",
            "href",
            "items",
            "label",
            "links",
            "menu",
            "menus",
            "navigation",
            "slug",
        }
    )
    if navigation_hits < 3:
        return False
    return not _has_minimum_descriptive_text(body)


def _has_minimum_descriptive_text(body: object) -> bool:
    samples: list[str] = []

    def _walk(value: object, *, depth: int = 0) -> None:
        if depth > 2 or len(samples) >= 8:
            return
        if isinstance(value, str):
            cleaned = value.strip()
            if len(cleaned) >= 24 and " " in cleaned:
                samples.append(cleaned)
            return
        if isinstance(value, dict):
            for item in value.values():
                _walk(item, depth=depth + 1)
            return
        if isinstance(value, list):
            for item in value[:8]:
                _walk(item, depth=depth + 1)

    _walk(body)
    return bool(samples)


def _has_detail_anchor(
    body: object,
    *,
    inferred_surface: str,
    page_url: str,
    requested_fields: list[str] | None,
) -> bool:
    if not isinstance(body, dict):
        return False
    alias_lookup = surface_alias_lookup(inferred_surface, requested_fields)
    candidates: dict[str, list[object]] = {}
    collect_structured_candidates(body, alias_lookup, page_url, candidates)
    title = finalize_candidate_value("title", candidates.get("title", []))
    url = finalize_candidate_value("url", candidates.get("url", []))
    if inferred_surface == "ecommerce_detail":
        price = finalize_candidate_value("price", candidates.get("price", []))
        sku = finalize_candidate_value("sku", candidates.get("sku", []))
        brand = finalize_candidate_value("brand", candidates.get("brand", []))
        url_matches_page = _detail_url_matches_page(url, page_url)
        if url not in (None, "", [], {}) and not url_matches_page:
            return False
        informative_fields = (
            field_name
            for field_name, values in candidates.items()
            if field_name not in {"brand", "sku", "title", "url", "vendor"}
            and finalize_candidate_value(field_name, values) not in (None, "", [], {})
        )
        return bool(
            title
            and (sku or brand or url_matches_page)
            and (price or any(True for _ in informative_fields))
        )
    if inferred_surface == "job_detail":
        company = finalize_candidate_value("company", candidates.get("company", []))
        location = finalize_candidate_value("location", candidates.get("location", []))
        apply_url = finalize_candidate_value("apply_url", candidates.get("apply_url", []))
        description = finalize_candidate_value("description", candidates.get("description", []))
        return bool(title and (company or location) and (apply_url or url or description))
    return bool(title and url)


def _finalize_detail_result(result: dict[str, Any]) -> dict[str, Any]:
    description_html = str(result.pop("description_html", "") or "").strip()
    if description_html:
        result.update(extract_job_sections(description_html))
        if "description" not in result:
            result["description"] = html_to_text(description_html)
    if result.get("apply_url") and not result.get("url"):
        result["url"] = result["apply_url"]
    return result


def _detail_url_matches_page(candidate_url: object, page_url: str) -> bool:
    candidate = str(candidate_url or "").strip()
    if not candidate:
        return False
    candidate_parts = urlparse(candidate)
    page_parts = urlparse(page_url)
    candidate_host = str(candidate_parts.hostname or "").strip().lower()
    page_host = str(page_parts.hostname or "").strip().lower()
    if candidate_host and page_host and candidate_host != page_host:
        return False
    candidate_path = str(candidate_parts.path or "").rstrip("/").lower()
    page_path = str(page_parts.path or "").rstrip("/").lower()
    if not candidate_path or not page_path:
        return False
    if candidate_path == page_path:
        return True
    candidate_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", candidate_path)
        if len(token) >= 2 and token not in _DETAIL_URL_IGNORE_TOKENS
    }
    page_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", page_path)
        if len(token) >= 2 and token not in _DETAIL_URL_IGNORE_TOKENS
    }
    if not candidate_tokens or not page_tokens:
        return False
    overlap = candidate_tokens & page_tokens
    return len(overlap) >= min(2, len(candidate_tokens))
