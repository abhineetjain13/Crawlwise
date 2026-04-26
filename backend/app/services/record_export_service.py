from __future__ import annotations

import csv
import json
import re
from collections.abc import AsyncIterator, Callable
from functools import lru_cache
from html import unescape
from io import StringIO
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from app.models.crawl import CrawlRecord
from app.models.user import User
from app.services.crawl_access_service import (
    RECORD_NOT_FOUND_DETAIL,
    RUN_NOT_FOUND_DETAIL,
    require_accessible_record,
)
from app.services.crawl_crud import get_run_records
from app.services.config.extraction_rules import DISCOVERIST_SCHEMA, MARKDOWN_VIEW
from app.services.field_value_core import _object_dict, _object_list
from app.schemas.crawl import CrawlRecordProvenanceResponse
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

MAX_RECORD_PAGE_SIZE = 1000
EXPORT_PAGING_HEADER = "X-Export-Paging"
EXPORT_TOTAL_HEADER = "X-Export-Total"
EXPORT_PARTIAL_HEADER = "X-Export-Partial"
RUN_NOT_FOUND_RESPONSE = {
    404: {"description": RUN_NOT_FOUND_DETAIL},
}
RECORD_NOT_FOUND_RESPONSE = {
    404: {"description": RECORD_NOT_FOUND_DETAIL},
}
RECORD_PROVENANCE_NOT_FOUND_RESPONSE = {
    404: {"description": f"{RECORD_NOT_FOUND_DETAIL} or {RUN_NOT_FOUND_DETAIL}"},
}
_FALLBACK_INTERNAL_FIELDS = frozenset(
    {"page_markdown", "table_markdown", "record_type"}
)
_IMAGE_URL_SUFFIXES = (
    ".avif",
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
)
_MARKDOWN_HIDDEN_FIELDS = frozenset(
    {
        "product_attributes",
        "selected_variant",
        "variant_axes",
        "variants",
    }
)

ExportStreamer = Callable[[AsyncSession, int], AsyncIterator[str]]


async def collect_export_rows(
    session: AsyncSession, run_id: int
) -> tuple[list[CrawlRecord], dict[str, int | bool]]:
    rows = []
    page = 1
    total = 0

    while True:
        page_rows, total = await get_run_records(
            session, run_id, page, MAX_RECORD_PAGE_SIZE
        )
        rows.extend(page_rows)
        if not page_rows or len(rows) >= total:
            break
        page += 1

    return rows, {
        "pages_used": page if rows else 1,
        "total": total,
        "returned": len(rows),
        "truncated": len(rows) < total,
    }


async def collect_export_metadata(
    session: AsyncSession, run_id: int
) -> dict[str, int | bool]:
    _, total = await get_run_records(session, run_id, 1, 1)
    pages_used = (
        (int(total) + MAX_RECORD_PAGE_SIZE - 1) // MAX_RECORD_PAGE_SIZE
        if total > 0
        else 0
    )
    return {
        "pages_used": max(1, pages_used),
        "total": int(total),
        "returned": int(total),
        "truncated": False,
    }


async def build_export_response(
    session: AsyncSession,
    *,
    run_id: int,
    filename: str,
    media_type: str,
    streamer: ExportStreamer,
) -> StreamingResponse:
    metadata = await collect_export_metadata(session, run_id)
    return StreamingResponse(
        streamer(session, run_id),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            **export_headers(metadata),
        },
    )


async def build_json_export_response(
    session: AsyncSession,
    *,
    run_id: int,
) -> StreamingResponse:
    return await build_export_response(
        session,
        run_id=run_id,
        filename=f"run-{run_id}.json",
        media_type="application/json",
        streamer=stream_export_json,
    )


async def build_csv_export_response(
    session: AsyncSession,
    *,
    run_id: int,
) -> StreamingResponse:
    return await build_export_response(
        session,
        run_id=run_id,
        filename=f"run-{run_id}.csv",
        media_type="text/csv",
        streamer=stream_export_csv,
    )


async def build_tables_csv_export_response(
    session: AsyncSession,
    *,
    run_id: int,
) -> StreamingResponse:
    return await build_export_response(
        session,
        run_id=run_id,
        filename=f"run-{run_id}-tables.csv",
        media_type="text/csv",
        streamer=stream_export_tables_csv,
    )


async def build_markdown_export_response(
    session: AsyncSession,
    *,
    run_id: int,
) -> StreamingResponse:
    return await build_export_response(
        session,
        run_id=run_id,
        filename=f"run-{run_id}.md",
        media_type="text/markdown; charset=utf-8",
        streamer=stream_export_markdown,
    )


async def build_artifacts_json_export_response(
    session: AsyncSession,
    *,
    run_id: int,
) -> StreamingResponse:
    return await build_export_response(
        session,
        run_id=run_id,
        filename=f"run-{run_id}-artifacts.json",
        media_type="application/json",
        streamer=stream_export_artifacts_json,
    )


async def build_discoverist_export_response(
    session: AsyncSession,
    *,
    run_id: int,
) -> StreamingResponse:
    return await build_export_response(
        session,
        run_id=run_id,
        filename=f"run-{run_id}-discoverist.csv",
        media_type="text/csv",
        streamer=stream_export_discoverist,
    )


async def export_record_provenance(
    session: AsyncSession,
    *,
    record_id: int,
    user: User,
) -> CrawlRecordProvenanceResponse:
    record = await require_accessible_record(session, record_id=record_id, user=user)
    return CrawlRecordProvenanceResponse.model_validate(record, from_attributes=True)


async def _stream_export_rows(session: AsyncSession, run_id: int):
    page = 1
    while True:
        page_rows, total = await get_run_records(
            session, run_id, page, MAX_RECORD_PAGE_SIZE
        )
        if not page_rows:
            return
        for row in page_rows:
            yield row
        if page * MAX_RECORD_PAGE_SIZE >= int(total):
            return
        page += 1


async def stream_export_json(session: AsyncSession, run_id: int):
    yield "[\n"
    first = True
    async for row in _stream_export_rows(session, run_id):
        if not first:
            yield ",\n"
        yield json.dumps(
            clean_export_data(row.data if isinstance(row.data, dict) else {}),
            indent=2,
        )
        first = False
    yield "\n]"


async def stream_export_csv(session: AsyncSession, run_id: int):
    structured_rows: list[dict] = []
    fieldnames: set[str] = set()
    async for row in _stream_export_rows(session, run_id):
        cleaned = clean_export_data(row.data if isinstance(row.data, dict) else {})
        if not cleaned:
            continue
        structured_rows.append(cleaned)
        fieldnames.update(cleaned.keys())
    if not structured_rows:
        return
    ordered_fieldnames = sorted(fieldnames)
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ordered_fieldnames, extrasaction="ignore"
    )
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in structured_rows:
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


async def stream_export_tables_csv(session: AsyncSession, run_id: int):
    table_rows: list[dict] = []
    async for row in _stream_export_rows(session, run_id):
        table_rows.extend(artifact_table_rows(row))
    async for chunk in stream_table_rows_csv(table_rows):
        yield chunk


async def stream_table_rows_csv(table_rows: list[dict]):
    fieldnames: set[str] = set()
    for row in table_rows:
        fieldnames.update(row.keys())
    ordered_fieldnames = sorted(fieldnames)
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ordered_fieldnames, extrasaction="ignore"
    )
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in table_rows:
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


async def stream_export_discoverist(session: AsyncSession, run_id: int):
    fieldnames = tuple(
        str(field_name) for field_name in DISCOVERIST_SCHEMA if str(field_name).strip()
    )
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(fieldnames)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    async for row in _stream_export_rows(session, run_id):
        writer.writerow(
            [
                row.source_url
                if field_name == "source_url"
                else (row.data or {}).get(field_name, "")
                for field_name in fieldnames
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


async def stream_export_markdown(session: AsyncSession, run_id: int):
    first = True
    async for row in _stream_export_rows(session, run_id):
        if not first:
            yield "\n\n---\n\n"
        yield record_to_markdown(row)
        first = False


async def stream_export_artifacts_json(session: AsyncSession, run_id: int):
    yield "[\n"
    first = True
    async for row in _stream_export_rows(session, run_id):
        if not first:
            yield ",\n"
        yield json.dumps(record_artifact_bundle(row), indent=2)
        first = False
    yield "\n]"


def clean_export_data(data: dict) -> dict:
    """Strip empty/null values and internal keys from export data."""
    return {
        k: v
        for k, v in data.items()
        if (
            v not in (None, "", [], {})
            and not str(k).startswith("_")
            and str(k) not in _FALLBACK_INTERNAL_FIELDS
        )
    }


def artifact_table_rows(row: CrawlRecord) -> list[dict]:
    source_trace = row.source_trace if isinstance(row.source_trace, dict) else {}
    manifest_trace = source_trace.get("manifest_trace")
    manifest_trace_map = manifest_trace if isinstance(manifest_trace, dict) else {}
    tables = manifest_trace_map.get("tables")
    table_list = tables if isinstance(tables, list) else []
    flattened: list[dict] = []
    for table in table_list:
        if not isinstance(table, dict):
            continue
        header_cells = table.get("headers")
        headers = header_cells if isinstance(header_cells, list) else []
        header_labels = [
            str((cell.get("text") if isinstance(cell, dict) else "") or "").strip()
            or f"column_{index + 1}"
            for index, cell in enumerate(headers)
        ]
        table_rows = _object_list(table.get("rows"))
        for row_index, table_row in enumerate(table_rows, start=1):
            if not isinstance(table_row, dict):
                continue
            table_cells = table_row.get("cells")
            cells = table_cells if isinstance(table_cells, list) else []
            payload: dict[str, object] = {
                "record_id": row.id,
                "source_url": row.source_url,
                "table_index": table.get("table_index"),
                "table_caption": table.get("caption"),
                "table_section_title": table.get("section_title"),
                "table_row_index": table_row.get("row_index") or row_index,
            }
            for index, cell in enumerate(cells):
                if not isinstance(cell, dict):
                    continue
                label = (
                    header_labels[index]
                    if index < len(header_labels)
                    else f"column_{index + 1}"
                )
                payload[label] = cell.get("text")
            flattened.append(
                {k: v for k, v in payload.items() if v not in (None, "", [], {})}
            )
    return flattened


def record_artifact_bundle(row: CrawlRecord) -> dict[str, object]:
    raw_data = _record_markdown_source(row)
    source_trace = row.source_trace if isinstance(row.source_trace, dict) else {}
    manifest_trace = _object_dict(source_trace.get("manifest_trace"))
    cleaned = clean_export_data(raw_data)
    json_ld_rows = _object_list(manifest_trace.get("json_ld"))
    table_rows = _object_list(manifest_trace.get("tables"))
    page_summary = {
        "record_id": row.id,
        "source_url": row.source_url,
        "title": cleaned.get("title") or raw_data.get("title"),
        "fallback_type": source_trace.get("type"),
        "markdown_excerpt": stringify_markdown_value(raw_data.get("page_markdown"))[
            :500
        ]
        or None,
    }
    evidence_refs = {
        "json_ld_count": len(json_ld_rows),
        "table_count": len(table_rows),
    }
    return {
        "record_id": row.id,
        "source_url": row.source_url,
        "structured_record": cleaned or None,
        "table_rows": artifact_table_rows(row) or None,
        "page_summary": {
            k: v for k, v in page_summary.items() if v not in (None, "", [], {})
        }
        or None,
        "markdown": {
            "page_markdown": raw_data.get("page_markdown"),
            "table_markdown": raw_data.get("table_markdown"),
        }
        if raw_data.get("page_markdown") or raw_data.get("table_markdown")
        else None,
        "evidence_refs": evidence_refs,
    }


def export_headers(metadata: dict[str, int | bool]) -> dict[str, str]:
    return {
        EXPORT_PAGING_HEADER: str(metadata["pages_used"]),
        EXPORT_TOTAL_HEADER: str(metadata["total"]),
        EXPORT_PARTIAL_HEADER: "true" if metadata["truncated"] else "false",
    }


def record_to_markdown(row: CrawlRecord) -> str:
    raw_data = _record_markdown_source(row)
    structured_data = row.data if isinstance(row.data, dict) else {}
    data = _sanitize_markdown_export_data(clean_export_data(structured_data))
    source_trace = row.source_trace if isinstance(row.source_trace, dict) else {}
    semantic = _object_dict(source_trace.get("semantic"))
    semantic_sections = _object_dict(semantic.get("sections"))
    semantic_specs = _object_dict(semantic.get("specifications"))

    if str(source_trace.get("type") or "") == "listing_fallback":
        title = (
            stringify_markdown_value(raw_data.get("title"))
            or row.source_url
            or f"Record {row.id}"
        )
        page_markdown = stringify_markdown_value(raw_data.get("page_markdown"))
        if page_markdown:
            return (
                page_markdown
                if page_markdown.lstrip().startswith("#")
                else f"# {title}\n\n{page_markdown}"
            )

    title = (
        stringify_markdown_value(data.get("title"))
        or row.source_url
        or f"Record {row.id}"
    )
    lines: list[str] = [f"# {title}"]
    if row.source_url and not _looks_like_image_asset_url(row.source_url):
        lines.extend(["", f"Source: <{row.source_url}>"])
    record_url = stringify_markdown_value(data.get("url"))
    if record_url and record_url != row.source_url:
        lines.append(f"Record URL: <{record_url}>")

    rendered_section_keys: set[str] = set()
    scalar_rows: list[tuple[str, object]] = []
    for field_name, raw_value in data.items():
        normalized_field = str(field_name).strip().lower()
        if normalized_field in {"title", "url", "source_url"} | _MARKDOWN_HIDDEN_FIELDS:
            continue
        rendered_value = stringify_markdown_value(raw_value)
        if not rendered_value:
            continue
        if is_markdown_long_form(field_name, rendered_value):
            lines.extend(
                [
                    "",
                    f"## {humanize_field_name(field_name)}",
                    "",
                    render_markdown_block(rendered_value),
                ]
            )
            rendered_section_keys.add(normalized_field)
            continue
        scalar_rows.append((humanize_field_name(field_name), raw_value))
        rendered_section_keys.add(normalized_field)

    if scalar_rows:
        lines.extend(["", "## Core Fields", ""])
        for label, value in scalar_rows:
            lines.append(f"- **{label}:** {render_markdown_inline(value)}")

    for field_name, raw_value in semantic_sections.items():
        normalized_field = str(field_name).strip().lower()
        if normalized_field in rendered_section_keys:
            continue
        rendered_value = stringify_markdown_value(raw_value)
        if not rendered_value:
            continue
        lines.extend(
            [
                "",
                f"## {humanize_field_name(field_name)}",
                "",
                render_markdown_block(rendered_value),
            ]
        )
        rendered_section_keys.add(normalized_field)

    spec_rows = [
        (humanize_field_name(field_name), raw_value)
        for field_name, raw_value in sorted(
            semantic_specs.items(),
            key=lambda item: humanize_field_name(item[0]).lower(),
        )
        if stringify_markdown_value(raw_value)
    ]
    if spec_rows:
        lines.extend(["", "## Specifications", ""])
        for label, value in spec_rows:
            lines.append(f"- **{label}:** {render_markdown_inline(value)}")

    page_markdown = stringify_markdown_value(raw_data.get("page_markdown"))
    if page_markdown and str(source_trace.get("type") or "") != "listing_fallback":
        lines.extend(["", render_markdown_block(page_markdown)])

    return "\n".join(lines).strip()


def _record_markdown_source(row: CrawlRecord) -> dict[str, object]:
    raw = row.raw_data if isinstance(row.raw_data, dict) else {}
    if raw:
        return dict(raw)
    return dict(row.data) if isinstance(row.data, dict) else {}


def _sanitize_markdown_export_data(data: dict[str, object]) -> dict[str, object]:
    sanitized = dict(data)
    primary_image = stringify_markdown_value(sanitized.get("image_url"))
    additional_images = _dedupe_image_values(
        sanitized.get("additional_images"),
        primary_image=primary_image,
    )
    if additional_images:
        sanitized["additional_images"] = ", ".join(additional_images)
    else:
        sanitized.pop("additional_images", None)
    return sanitized


def _dedupe_image_values(
    value: object,
    *,
    primary_image: str = "",
) -> list[str]:
    parts: list[str] = []
    seen: set[str] = set()
    primary = str(primary_image or "").strip()
    if primary:
        seen.add(primary.lower())
    if isinstance(value, str):
        candidates: list[object] = [
            part for part in value.split(", ") if part.strip()
        ]
    else:
        candidates = (
            list(value)
            if isinstance(value, (list, tuple, set))
            else [("" if value is None else str(value)).strip()]
        )
    for part in candidates:
        candidate = str(part or "").strip()
        if not candidate:
            continue
        normalized = candidate.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        parts.append(candidate)
    return parts


def _looks_like_image_asset_url(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    path = str(urlparse(text).path or "").strip().lower()
    if not path:
        return False
    return path.endswith(_IMAGE_URL_SUFFIXES)


def stringify_markdown_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    text = unescape(text).replace("\r\n", "\n").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_markdown_long_form(field_name: object, value: str) -> bool:
    normalized = str(field_name or "").strip().lower()
    if normalized in markdown_long_form_fields():
        return True
    return "\n" in value or len(value) > 180


def render_markdown_inline(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = stringify_markdown_value(value)
        if re.fullmatch(r"https?://\S+", text):
            return f"<{text}>"
        return text
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return f"`{text}`"


def render_markdown_block(value: str) -> str:
    normalized_value = _normalize_markdown_block_value(value)
    rendered: list[str] = []
    for raw_line in normalized_value.split("\n"):
        line = raw_line.strip()
        if not line:
            if rendered and rendered[-1] != "":
                rendered.append("")
            continue
        bullet_match = re.match(r"^(?:[•*-]|\d+\.)\s+(.*)$", line)
        if bullet_match:
            rendered.append(f"- {bullet_match.group(1).strip()}")
        else:
            rendered.append(line)
    return "\n".join(rendered)


def _normalize_markdown_block_value(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not _looks_like_html_fragment(text):
        return text
    return _html_fragment_to_markdown_text(text)


def _looks_like_html_fragment(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(re.search(r"<[a-zA-Z][^>]*>", text))


def _html_fragment_to_markdown_text(value: str) -> str:
    soup = BeautifulSoup(str(value or ""), "html.parser")
    for node in soup.find_all("br"):
        node.replace_with("\n")

    lines: list[str] = []
    seen: set[str] = set()
    for node in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"]
    ):
        text = " ".join(node.get_text(" ", strip=True).split()).strip()
        if not text:
            continue
        if node.name == "li":
            text = f"- {text}"
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        lines.append(text)
    if lines:
        return "\n".join(lines)
    return " ".join(soup.get_text(" ", strip=True).split()).strip()


def humanize_field_name(value: object) -> str:
    normalized = str(value or "").replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return ""
    return normalized[:1].upper() + normalized[1:]


@lru_cache(maxsize=1)
def markdown_long_form_fields() -> frozenset[str]:
    rows = (
        MARKDOWN_VIEW.get("long_form_fields") if isinstance(MARKDOWN_VIEW, dict) else []
    )
    return frozenset(
        str(value).strip().lower()
        for value in (rows if isinstance(rows, list) else [])
        if str(value).strip()
    )


