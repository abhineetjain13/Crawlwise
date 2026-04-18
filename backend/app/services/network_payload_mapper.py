from __future__ import annotations

from typing import Any

import jmespath

from app.services.config.network_payload_specs import NETWORK_PAYLOAD_SPECS
from app.services.extraction_html_helpers import extract_job_sections, html_to_text


def map_network_payloads_to_fields(
    payloads: list[dict[str, object]] | None,
    *,
    surface: str,
    page_url: str,
) -> list[dict[str, Any]]:
    del page_url
    normalized_surface = str(surface or "").strip().lower()
    surface_specs = NETWORK_PAYLOAD_SPECS.get(normalized_surface, ())
    if not surface_specs:
        return []
    rows: list[dict[str, Any]] = []
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        body = payload.get("body")
        if not isinstance(body, (dict, list)):
            continue
        mapped = _map_payload_body(body, surface_specs=surface_specs)
        if mapped:
            rows.append(mapped)
    return rows


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
