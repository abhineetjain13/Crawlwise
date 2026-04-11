from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch


def manifest(**kwargs) -> dict:
    return kwargs


def run_extract_candidates(
    impl: Callable,
    *,
    url: str,
    surface: str,
    html: str,
    manifest_data: dict | None,
    additional_fields: list[str],
    extraction_contract: list[dict] | None = None,
    resolved_fields: list[str] | None = None,
):
    sources = dict(manifest_data or {})
    page_sources = {
        "next_data": sources.get("next_data"),
        "hydrated_states": sources.get("_hydrated_states")
        or sources.get("hydrated_states")
        or [],
        "embedded_json": sources.get("embedded_json") or [],
        "open_graph": sources.get("open_graph") or {},
        "json_ld": sources.get("json_ld") or [],
        "microdata": sources.get("microdata") or [],
        "tables": sources.get("tables") or [],
        "datalayer": sources.get("datalayer") or {},
    }
    args = (
        url,
        surface,
        html,
        sources.get("network_payloads") or [],
        additional_fields,
        extraction_contract,
        resolved_fields,
        sources.get("adapter_data") or [],
    )
    if any(page_sources.values()):
        with patch(
            "app.services.extract.service.parse_page_sources",
            return_value=page_sources,
        ):
            return impl(*args)
    return impl(*args)


def run_extract_listing_records(
    impl: Callable,
    *,
    html: str,
    surface: str,
    target_fields: set[str],
    page_url: str = "",
    max_records: int = 100,
    manifest_data: dict | None = None,
):
    sources = dict(manifest_data or {})
    page_sources = {
        "next_data": sources.get("next_data"),
        "hydrated_states": sources.get("_hydrated_states")
        or sources.get("hydrated_states")
        or [],
        "embedded_json": sources.get("embedded_json") or [],
        "open_graph": sources.get("open_graph") or {},
        "json_ld": sources.get("json_ld") or [],
        "microdata": sources.get("microdata") or [],
        "tables": sources.get("tables") or [],
    }
    kwargs = {
        "page_url": page_url,
        "max_records": max_records,
        "xhr_payloads": sources.get("network_payloads") or [],
        "adapter_records": sources.get("adapter_data") or [],
    }
    if any(page_sources.values()):
        with patch(
            "app.services.extract.listing_extractor.parse_page_sources",
            return_value=page_sources,
        ):
            return impl(html, surface, target_fields, **kwargs)
    return impl(html, surface, target_fields, **kwargs)
