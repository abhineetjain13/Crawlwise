from __future__ import annotations

import csv
import json
from collections.abc import AsyncIterator, Callable
from io import StringIO
from urllib.parse import urlparse

from app.models.crawl import CrawlRecord, CrawlRun
from app.models.user import User
from app.services.crawl_access_service import (
    RECORD_NOT_FOUND_DETAIL,
    RUN_NOT_FOUND_DETAIL,
    require_accessible_record,
)
from app.services.crawl_crud import get_run_records
from app.services.config.extraction_rules import (
    DISCOVERIST_SCHEMA,
    EXPORT_IMAGE_URL_SUFFIXES,
)
from app.services.config.export_settings import (
    EXPORT_PAGING_HEADER,
    EXPORT_PARTIAL_HEADER,
    EXPORT_TOTAL_HEADER,
    MAX_RECORD_PAGE_SIZE,
)
from app.services.export.schema import (
    clean_export_data as _clean_export_data,
    export_record_from_row,
)
from app.services.field_value_core import (
    object_dict as _object_dict,
    object_list as _object_list,
)
from app.services.publish.quality_gate import (
    export_quality_headers,
    export_quality_report,
)
from app.schemas.crawl import CrawlRecordProvenanceResponse
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

RUN_NOT_FOUND_RESPONSE = {
    404: {"description": RUN_NOT_FOUND_DETAIL},
}
RECORD_NOT_FOUND_RESPONSE = {
    404: {"description": RECORD_NOT_FOUND_DETAIL},
}
RECORD_PROVENANCE_NOT_FOUND_RESPONSE = {
    404: {"description": f"{RECORD_NOT_FOUND_DETAIL} or {RUN_NOT_FOUND_DETAIL}"},
}
CSV_MEDIA_TYPE = "text/csv"

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


async def build_export_response(
    session: AsyncSession,
    *,
    run_id: int,
    filename: str,
    media_type: str,
    streamer: ExportStreamer,
) -> StreamingResponse:
    rows, metadata = await collect_export_rows(session, run_id)
    run = await session.get(CrawlRun, run_id)
    quality_report = export_quality_report(run, rows)
    return StreamingResponse(
        streamer(session, run_id),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            **export_headers(metadata),
            **export_quality_headers(quality_report),
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
        media_type=CSV_MEDIA_TYPE,
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
        media_type=CSV_MEDIA_TYPE,
        streamer=stream_export_tables_csv,
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
        media_type=CSV_MEDIA_TYPE,
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
        export_record = export_record_from_row(row)
        yield json.dumps(export_record.data, indent=2)
        first = False
    yield "\n]"


async def stream_export_csv(session: AsyncSession, run_id: int):
    fieldnames: set[str] = set()
    async for row in _stream_export_rows(session, run_id):
        export_record = export_record_from_row(row)
        if not export_record.data:
            continue
        fieldnames.update(export_record.data.keys())
    if not fieldnames:
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
    async for row in _stream_export_rows(session, run_id):
        export_record = export_record_from_row(row)
        if not export_record.data:
            continue
        writer.writerow(export_record.data)
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
    return _clean_export_data(data)


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
    raw_data = _record_export_source(row)
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
        "evidence_refs": evidence_refs,
    }


def export_headers(metadata: dict[str, int | bool]) -> dict[str, str]:
    return {
        EXPORT_PAGING_HEADER: str(metadata["pages_used"]),
        EXPORT_TOTAL_HEADER: str(metadata["total"]),
        EXPORT_PARTIAL_HEADER: "true" if metadata["truncated"] else "false",
    }


def _record_export_source(row: CrawlRecord) -> dict[str, object]:
    raw = row.raw_data if isinstance(row.raw_data, dict) else {}
    if raw:
        return dict(raw)
    return dict(row.data) if isinstance(row.data, dict) else {}


def _sanitize_export_data(data: dict[str, object]) -> dict[str, object]:
    sanitized = dict(data)
    primary_image = _stringify_export_value(sanitized.get("image_url"))
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
    return path.endswith(EXPORT_IMAGE_URL_SUFFIXES)


def _stringify_export_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    return text.replace("\r\n", "\n").replace("\u00a0", " ").strip()


