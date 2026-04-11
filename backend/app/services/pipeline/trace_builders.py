"""Trace and manifest builder functions for crawl diagnostics."""

from __future__ import annotations

from app.services.acquisition.acquirer import (
    AcquisitionResult,
    scrub_network_payloads_for_storage,
)
from app.services.extract.source_parsers import parse_page_sources
from app.services.knowledge_base.store import get_canonical_fields
from bs4 import BeautifulSoup

from .field_normalization import _normalize_review_value
from .rendering import (
    _render_fallback_card_group,
    _render_fallback_node_markdown,
    _render_manifest_tables_markdown,
    _should_skip_fallback_node,
)
from .review_helpers import _should_surface_discovered_field
from .utils import (
    _clean_candidate_text,
    _clean_page_text,
    _compact_dict,
    _first_non_empty_text,
)

from .verdict import _review_bucket_fingerprint

_MANIFEST_MAX_ITEMS = 8
_MANIFEST_MAX_DEPTH = 4
_MANIFEST_TEXT_LIMIT = 400
_MANIFEST_TABLE_LIMIT = 3
_MANIFEST_TABLE_ROW_LIMIT = 12
_MANIFEST_TABLE_CELL_LIMIT = 4


def _snapshot_manifest_value(
    value: object,
    *,
    depth: int = 0,
    max_depth: int = _MANIFEST_MAX_DEPTH,
    max_items: int = _MANIFEST_MAX_ITEMS,
    text_limit: int = _MANIFEST_TEXT_LIMIT,
) -> object:
    if value in (None, "", [], {}):
        return None
    if depth >= max_depth:
        return _clean_candidate_text(value, limit=text_limit)
    if isinstance(value, dict):
        snapshot: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                break
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            nested = _snapshot_manifest_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                text_limit=text_limit,
            )
            if nested not in (None, "", [], {}):
                snapshot[normalized_key] = nested
        return snapshot or None
    if isinstance(value, list):
        rows: list[object] = []
        for item in value[:max_items]:
            nested = _snapshot_manifest_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                text_limit=text_limit,
            )
            if nested not in (None, "", [], {}):
                rows.append(nested)
        return rows or None
    return _clean_candidate_text(value, limit=text_limit)


def _snapshot_manifest_tables(tables: object) -> list[dict[str, object]] | None:
    if not isinstance(tables, list):
        return None
    summarized_tables: list[dict[str, object]] = []
    for table in tables[:_MANIFEST_TABLE_LIMIT]:
        if not isinstance(table, dict):
            continue
        summarized_rows: list[dict[str, object]] = []
        for row in list(table.get("rows") or [])[:_MANIFEST_TABLE_ROW_LIMIT]:
            if not isinstance(row, dict):
                continue
            summarized_cells: list[dict[str, object]] = []
            for cell in list(row.get("cells") or [])[:_MANIFEST_TABLE_CELL_LIMIT]:
                if not isinstance(cell, dict):
                    continue
                summarized_cell = _compact_dict(
                    {
                        "text": _clean_candidate_text(cell.get("text"), limit=160),
                        "href": _clean_candidate_text(cell.get("href"), limit=160),
                        "tag": _clean_candidate_text(cell.get("tag"), limit=32),
                    }
                )
                if summarized_cell:
                    summarized_cells.append(summarized_cell)
            if summarized_cells:
                summarized_rows.append(
                    _compact_dict(
                        {
                            "row_index": row.get("row_index"),
                            "cells": summarized_cells,
                        }
                    )
                )
        summarized_table = _compact_dict(
            {
                "table_index": table.get("table_index"),
                "caption": _clean_candidate_text(table.get("caption"), limit=120),
                "section_title": _clean_candidate_text(
                    table.get("section_title"), limit=120
                ),
                "headers": _snapshot_manifest_value(
                    table.get("headers"),
                    max_items=_MANIFEST_TABLE_CELL_LIMIT,
                    text_limit=120,
                ),
                "rows": summarized_rows or None,
            }
        )
        if summarized_table:
            summarized_tables.append(summarized_table)
    return summarized_tables or None


def _build_acquisition_trace(acq: AcquisitionResult) -> dict[str, object]:
    """Build acquisition trace from acquisition result."""
    diagnostics = acq.diagnostics if isinstance(acq.diagnostics, dict) else {}
    browser_diagnostics = (
        diagnostics.get("browser_diagnostics")
        if isinstance(diagnostics.get("browser_diagnostics"), dict)
        else {}
    )
    timing_map = (
        diagnostics.get("timings_ms")
        if isinstance(diagnostics.get("timings_ms"), dict)
        else {}
    )
    return _compact_dict(
        {
            "method": acq.method,
            "browser_attempted": bool(diagnostics.get("browser_attempted")),
            "acquisition": _compact_dict(
                {
                    "final_url": diagnostics.get("curl_final_url")
                    or browser_diagnostics.get("final_url"),
                    "platform_family": str(
                        diagnostics.get("curl_platform_family") or ""
                    ).strip()
                    or None,
                    "browser_attempted": bool(diagnostics.get("browser_attempted")),
                    "browser_used": acq.method == "playwright",
                    "challenge_state": diagnostics.get("browser_challenge_state"),
                    "origin_warmed": diagnostics.get("browser_origin_warmed"),
                    "invalid_surface_page": diagnostics.get("invalid_surface_page"),
                    "promoted_sources": acq.promoted_sources or None,
                    "frame_sources": acq.frame_sources or None,
                    "page_classification": diagnostics.get("page_classification")
                    if isinstance(diagnostics.get("page_classification"), dict)
                    else None,
                    "timings_ms": timing_map or None,
                }
            )
            or None,
        }
    )


def _build_manifest_trace(
    *,
    html: str,
    xhr_payloads: list[dict],
    adapter_records: list[dict],
    semantic: dict | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build manifest trace from page sources."""
    reserved_keys = {"next_data", "tables", "semantic"}
    extra_payload = dict(extra or {})
    # Prevent callers from silently overriding core manifest sections.
    for reserved_key in reserved_keys:
        extra_payload.pop(reserved_key, None)
    scrubbed_payloads = scrub_network_payloads_for_storage(
        [row for row in xhr_payloads if isinstance(row, dict)]
    )
    page_sources = parse_page_sources(html)
    payload = _compact_dict(
        {
            "adapter_data": _snapshot_manifest_value(adapter_records),
            "network_payloads": [
                _compact_dict(
                    {
                        "url": _clean_candidate_text(row.get("url"), limit=240),
                        "status": row.get("status"),
                        "headers": _snapshot_manifest_value(
                            row.get("headers"), max_items=20, text_limit=160
                        ),
                        "body": _snapshot_manifest_value(row.get("body")),
                    }
                )
                for row in scrubbed_payloads
            ]
            or None,
            "next_data": _snapshot_manifest_value(page_sources.get("next_data")),
            "_hydrated_states": _snapshot_manifest_value(
                page_sources.get("hydrated_states")
            ),
            "embedded_json": _snapshot_manifest_value(page_sources.get("embedded_json")),
            "open_graph": _snapshot_manifest_value(
                page_sources.get("open_graph"), max_items=20, text_limit=200
            ),
            "json_ld": _snapshot_manifest_value(page_sources.get("json_ld")),
            "microdata": _snapshot_manifest_value(page_sources.get("microdata")),
            "tables": _snapshot_manifest_tables(page_sources.get("tables")),
            "semantic": _snapshot_manifest_value(semantic),
            **{
                key: _snapshot_manifest_value(value)
                for key, value in extra_payload.items()
            },
        }
    )
    return payload


def _build_review_bucket(
    discovered_fields: dict[str, object],
    *,
    source_trace: dict | None = None,
    fallback_source: str = "deterministic_extraction",
) -> list[dict[str, object]]:
    """Build review bucket from discovered fields."""
    candidate_map = (
        source_trace.get("candidates") if isinstance(source_trace, dict) else {}
    )
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for field_name, value in discovered_fields.items():
        normalized_value = _normalize_review_value(value)
        if normalized_value is None:
            continue
        source = _review_bucket_source_for_field(
            field_name, candidate_map, fallback_source
        )
        if not _should_surface_discovered_field(
            field_name, normalized_value, source=source
        ):
            continue
        entry = _compact_dict(
            {
                "key": str(field_name).strip(),
                "value": normalized_value,
                "source": source,
            }
        )
        fingerprint = (str(entry["key"]), _review_bucket_fingerprint(entry["value"]))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        rows.append(entry)
    return rows


def _review_bucket_source_for_field(
    field_name: str, candidate_map: object, fallback_source: str
) -> str:
    """Get the source label for a field from candidate map."""
    if isinstance(candidate_map, dict):
        rows = candidate_map.get(field_name)
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                source = str(row.get("source") or "").strip()
                if source:
                    return source
    return fallback_source


def _build_field_discovery_summary(
    source_trace: dict,
    candidates: dict[str, list[dict]],
    candidate_values: dict,
    additional_fields: list[str],
    surface: str,
) -> dict:
    """Build a deterministic field discovery summary for additional_fields.

    Populates ``field_discovery`` in source_trace with per-field info:
    which sources contributed, what value was chosen, and which fields
    were not found. This powers markdown-oriented record inspection
    regardless of whether LLM is enabled.
    """
    canonical = set(get_canonical_fields(surface))
    requested = {field for field in additional_fields if field}
    target_fields = canonical | requested
    discovery: dict[str, dict] = {}
    missing: list[str] = []

    for field_name in sorted(
        set(candidates.keys()) | set(candidate_values.keys()) | target_fields
    ):
        rows = candidates.get(field_name, [])
        winning_row = rows[0] if rows and isinstance(rows[0], dict) else {}
        first_row_value = (
            rows[0].get("value") if rows and isinstance(rows[0], dict) else None
        )
        chosen = candidate_values.get(field_name, first_row_value)
        if not rows and field_name in target_fields and chosen in (None, "", [], {}):
            missing.append(field_name)
            discovery[field_name] = _compact_dict(
                {
                    "status": "not_found",
                    "sources": None,
                    "is_canonical": field_name in canonical or None,
                }
            )
            continue
        sources = sorted(
            {str(row.get("source") or "").strip() for row in rows if row.get("source")}
        )
        if field_name not in target_fields and not _should_surface_discovered_field(
            field_name,
            chosen if chosen not in (None, "", [], {}) else first_row_value,
            source=", ".join(sources),
        ):
            continue
        discovery[field_name] = _compact_dict(
            {
                "status": "found",
                "value": _clean_candidate_text(chosen)
                if chosen not in (None, "", [], {})
                else None,
                "sources": sources or None,
                "xpath": winning_row.get("xpath") or winning_row.get("_xpath") or None,
                "css_selector": winning_row.get("css_selector")
                or winning_row.get("_selector")
                or None,
                "is_canonical": field_name in canonical or None,
            }
        )

    source_trace["field_discovery"] = discovery
    source_trace["field_discovery_missing"] = missing
    return source_trace


def _build_legible_listing_fallback_record(
    *,
    url: str,
    html: str,
    xhr_payloads: list[dict],
    adapter_records: list[dict],
) -> dict[str, dict[str, object] | dict[str, int | bool | str]] | None:
    """Build a human-readable fallback record for listing pages."""
    page_sources = parse_page_sources(html)
    tables = list(page_sources.get("tables") or [])
    soup = BeautifulSoup(html or "", "html.parser")
    for selector in (
        "script",
        "style",
        "noscript",
        "svg",
        "iframe",
        "header",
        "footer",
        "nav",
        "aside",
    ):
        for node in soup.select(selector):
            node.decompose()

    title = _first_non_empty_text(
        soup.select_one("main h1"),
        soup.select_one("article h1"),
        soup.select_one("h1"),
    )
    if not title:
        title = _clean_page_text(
            soup.title.string if soup.title and soup.title.string else ""
        )
    description_meta = soup.select_one("meta[name='description']")
    description = _clean_page_text(
        description_meta.get("content", "") if description_meta else ""
    )

    content_root = (
        soup.select_one("main") or soup.select_one("article") or soup.body or soup
    )
    markdown_lines: list[str] = []
    fallback_table_rows: list[dict[str, object]] = []
    total_chars = 0
    card_lines, card_chars, fallback_table_rows = _render_fallback_card_group(
        content_root, page_url=url
    )
    if card_lines:
        markdown_lines.extend(card_lines)
        total_chars += card_chars
    else:
        seen_text: set[str] = set()
        for node in content_root.select("h2, h3, h4, p, li"):
            if _should_skip_fallback_node(node, page_url=url):
                continue
            text = _render_fallback_node_markdown(node, page_url=url)
            if not text or text in seen_text:
                continue
            seen_text.add(text)
            plain_text = _clean_page_text(node.get_text(" ", strip=True))
            if node.name in {"h2", "h3", "h4"} and len(plain_text) <= 140:
                line = f"## {text}"
            elif node.name == "li":
                line = f"- {text}"
            else:
                line = text
            markdown_lines.append(line)
            total_chars += len(plain_text)
            if total_chars >= 2400 or len(markdown_lines) >= 24:
                break

    table_markdown = _render_manifest_tables_markdown(tables)
    if table_markdown:
        markdown_lines.extend(["## Tables", table_markdown])
    enough_text = total_chars >= 180 and len(markdown_lines) >= 3
    has_tables = bool(table_markdown)
    if not enough_text and not has_tables:
        return None

    page_markdown_lines: list[str] = []
    if title:
        page_markdown_lines.append(f"# {title}")
    if description:
        page_markdown_lines.extend(["", description])
    if markdown_lines:
        page_markdown_lines.extend(
            ["", *markdown_lines] if page_markdown_lines else markdown_lines
        )
    page_markdown = "\n".join(page_markdown_lines).strip()

    return _compact_dict(
        {
            "fallback_listing": _compact_dict(
                {
                    "page_markdown": page_markdown or None,
                    "records": fallback_table_rows or None,
                }
            ),
            "diagnostics": _compact_dict(
                {
                    "total_chars": total_chars,
                    "line_count": len(markdown_lines),
                    "has_tables": has_tables,
                }
            ),
        }
    )
