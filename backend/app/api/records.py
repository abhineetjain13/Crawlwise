# Crawl record and export route handlers.
from __future__ import annotations

import csv
import json
from typing import Annotated
from io import StringIO
from functools import lru_cache
from html import unescape
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.crawl import CrawlRecord
from app.models.user import User
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.schemas.crawl import CrawlRecordProvenanceResponse, CrawlRecordResponse
from app.services.crawl_service import get_run_records
from app.services.pipeline_config import DISCOVERIST_SCHEMA, MARKDOWN_VIEW

router = APIRouter(tags=["records"])
MAX_RECORD_PAGE_SIZE = 1000
EXPORT_PAGING_HEADER = "X-Export-Paging"
EXPORT_TOTAL_HEADER = "X-Export-Total"
EXPORT_PARTIAL_HEADER = "X-Export-Partial"
RUN_NOT_FOUND_DETAIL = "Run not found"
RUN_NOT_FOUND_RESPONSE = {
    404: {"description": RUN_NOT_FOUND_DETAIL},
}
RECORD_NOT_FOUND_DETAIL = "Record not found"
RECORD_NOT_FOUND_RESPONSE = {
    404: {"description": RECORD_NOT_FOUND_DETAIL},
}
RECORD_PROVENANCE_NOT_FOUND_RESPONSE = {
    404: {"description": f"{RECORD_NOT_FOUND_DETAIL} or {RUN_NOT_FOUND_DETAIL}"},
}
_FALLBACK_INTERNAL_FIELDS = frozenset({"page_markdown", "table_markdown", "record_type"})


@router.get("/api/crawls/{run_id}/records", responses=RUN_NOT_FOUND_RESPONSE)
async def records_list(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=MAX_RECORD_PAGE_SIZE)] = 20,
) -> PaginatedResponse[CrawlRecordResponse]:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (current_user.role != "admin" and run.user_id != current_user.id):
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)

    rows, total = await get_run_records(session, run_id, page, limit)
    return PaginatedResponse(
        items=[CrawlRecordResponse.model_validate(row, from_attributes=True) for row in rows],
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )


@router.get("/api/records/{record_id}/provenance", responses=RECORD_PROVENANCE_NOT_FOUND_RESPONSE)
async def record_provenance(
    record_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CrawlRecordProvenanceResponse:
    from app.services.crawl_service import get_run

    record = await session.get(CrawlRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=RECORD_NOT_FOUND_DETAIL)
    run = await get_run(session, record.run_id)
    if run is None or (current_user.role != "admin" and run.user_id != current_user.id):
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    return CrawlRecordProvenanceResponse.model_validate(record, from_attributes=True)


@router.get("/api/crawls/{run_id}/export/json", responses=RUN_NOT_FOUND_RESPONSE)
async def export_json(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (_.role != "admin" and run.user_id != _.id):
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    metadata = await _collect_export_metadata(session, run_id)
    return StreamingResponse(
        _stream_export_json(session, run_id),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=run-{run_id}.json",
            **_export_headers(metadata),
        },
    )


@router.get("/api/crawls/{run_id}/export/csv", responses=RUN_NOT_FOUND_RESPONSE)
async def export_csv(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (_.role != "admin" and run.user_id != _.id):
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    metadata = await _collect_export_metadata(session, run_id)
    return StreamingResponse(
        _stream_export_csv(session, run_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=run-{run_id}.csv",
            **_export_headers(metadata),
        },
    )


@router.get("/api/crawls/{run_id}/export/tables.csv", responses=RUN_NOT_FOUND_RESPONSE)
async def export_tables_csv(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (_.role != "admin" and run.user_id != _.id):
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    metadata = await _collect_export_metadata(session, run_id)
    return StreamingResponse(
        _stream_export_tables_csv(session, run_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=run-{run_id}-tables.csv",
            **_export_headers(metadata),
        },
    )


@router.get("/api/crawls/{run_id}/export/markdown", responses=RUN_NOT_FOUND_RESPONSE)
async def export_markdown(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (_.role != "admin" and run.user_id != _.id):
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    metadata = await _collect_export_metadata(session, run_id)
    return StreamingResponse(
        _stream_export_markdown(session, run_id),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=run-{run_id}.md",
            **_export_headers(metadata),
        },
    )


@router.get("/api/crawls/{run_id}/export/artifacts.json", responses=RUN_NOT_FOUND_RESPONSE)
async def export_artifacts_json(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (_.role != "admin" and run.user_id != _.id):
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    metadata = await _collect_export_metadata(session, run_id)
    return StreamingResponse(
        _stream_export_artifacts_json(session, run_id),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=run-{run_id}-artifacts.json",
            **_export_headers(metadata),
        },
    )


@router.get("/api/crawls/{run_id}/export/discoverist", responses=RUN_NOT_FOUND_RESPONSE)
async def export_discoverist(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (_.role != "admin" and run.user_id != _.id):
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    metadata = await _collect_export_metadata(session, run_id)
    return StreamingResponse(
        _stream_export_discoverist(session, run_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=run-{run_id}-discoverist.csv",
            **_export_headers(metadata),
        },
    )


async def _collect_export_rows(session: AsyncSession, run_id: int) -> tuple[list, dict[str, int | bool]]:
    rows = []
    page = 1
    total = 0

    while True:
        page_rows, total = await get_run_records(session, run_id, page, MAX_RECORD_PAGE_SIZE)
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


async def _collect_export_metadata(session: AsyncSession, run_id: int) -> dict[str, int | bool]:
    _, total = await get_run_records(session, run_id, 1, 1)
    pages_used = max(1, (int(total) + MAX_RECORD_PAGE_SIZE - 1) // MAX_RECORD_PAGE_SIZE)
    return {
        "pages_used": pages_used,
        "total": int(total),
        "returned": int(total),
        "truncated": False,
    }


async def _stream_export_rows(session: AsyncSession, run_id: int):
    page = 1
    while True:
        page_rows, total = await get_run_records(session, run_id, page, MAX_RECORD_PAGE_SIZE)
        if not page_rows:
            return
        for row in page_rows:
            yield row
        if page * MAX_RECORD_PAGE_SIZE >= int(total):
            return
        page += 1


async def _stream_export_json(session: AsyncSession, run_id: int):
    yield "[\n"
    first = True
    async for row in _stream_export_rows(session, run_id):
        if not first:
            yield ",\n"
        yield json.dumps(_clean_export_data(row.data), indent=2)
        first = False
    yield "\n]"


async def _stream_export_csv(session: AsyncSession, run_id: int):
    rows, _ = await _collect_export_rows(session, run_id)
    cleaned_records = [_clean_export_data(row.data if isinstance(row.data, dict) else {}) for row in rows]
    structured_rows = [row for row in cleaned_records if row]
    if not structured_rows:
        return
    fieldnames: set[str] = set()
    for row in structured_rows:
        fieldnames.update(row.keys())
    ordered_fieldnames = sorted(fieldnames)
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=ordered_fieldnames, extrasaction="ignore")
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in structured_rows:
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


async def _stream_export_tables_csv(session: AsyncSession, run_id: int):
    rows, _ = await _collect_export_rows(session, run_id)
    async for chunk in _stream_table_rows_csv(_collect_table_export_rows(rows)):
        yield chunk


async def _stream_table_rows_csv(table_rows: list[dict]) :
    fieldnames: set[str] = set()
    for row in table_rows:
        fieldnames.update(row.keys())
    ordered_fieldnames = sorted(fieldnames)
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=ordered_fieldnames, extrasaction="ignore")
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in table_rows:
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


async def _stream_export_discoverist(session: AsyncSession, run_id: int):
    fieldnames = _discoverist_schema()
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(fieldnames)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    async for row in _stream_export_rows(session, run_id):
        writer.writerow([
            row.source_url if field_name == "source_url" else (row.data or {}).get(field_name, "")
            for field_name in fieldnames
        ])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


async def _stream_export_markdown(session: AsyncSession, run_id: int):
    first = True
    async for row in _stream_export_rows(session, run_id):
        if not first:
            yield "\n\n---\n\n"
        yield _record_to_markdown(row)
        first = False


async def _stream_export_artifacts_json(session: AsyncSession, run_id: int):
    rows, _ = await _collect_export_rows(session, run_id)
    bundles = [_record_artifact_bundle(row) for row in rows]
    yield json.dumps(bundles, indent=2)


def _clean_export_data(data: dict) -> dict:
    """Strip empty/null values and internal keys from export data."""
    return {
        k: v for k, v in data.items()
        if (
            v not in (None, "", [], {})
            and not str(k).startswith("_")
            and str(k) not in _FALLBACK_INTERNAL_FIELDS
        )
    }


def _collect_table_export_rows(rows: list[CrawlRecord]) -> list[dict]:
    flattened: list[dict] = []
    for row in rows:
        for table_row in _artifact_table_rows(row):
            flattened.append(table_row)
    return flattened


def _artifact_table_rows(row: CrawlRecord) -> list[dict]:
    legacy_rows = _legacy_fallback_markdown_rows(row)
    if legacy_rows:
        return legacy_rows
    source_trace = row.source_trace if isinstance(row.source_trace, dict) else {}
    manifest_trace = source_trace.get("manifest_trace") if isinstance(source_trace.get("manifest_trace"), dict) else {}
    tables = manifest_trace.get("tables") if isinstance(manifest_trace.get("tables"), list) else []
    flattened: list[dict] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        headers = table.get("headers") if isinstance(table.get("headers"), list) else []
        header_labels = [
            str((cell.get("text") if isinstance(cell, dict) else "") or "").strip() or f"column_{index + 1}"
            for index, cell in enumerate(headers)
        ]
        for row_index, table_row in enumerate(table.get("rows") or [], start=1):
            if not isinstance(table_row, dict):
                continue
            cells = table_row.get("cells") if isinstance(table_row.get("cells"), list) else []
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
                label = header_labels[index] if index < len(header_labels) else f"column_{index + 1}"
                payload[label] = cell.get("text")
            flattened.append({k: v for k, v in payload.items() if v not in (None, "", [], {})})
    return flattened


def _legacy_fallback_markdown_rows(row: CrawlRecord) -> list[dict]:
    source_trace = row.source_trace if isinstance(row.source_trace, dict) else {}
    if str(source_trace.get("type") or "") != "listing_fallback":
        return []
    data = row.data if isinstance(row.data, dict) else {}
    markdown = _stringify_markdown_value(data.get("page_markdown"))
    if not markdown:
        return []
    rows: list[dict] = []
    current: dict[str, object] | None = None
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^## \[(.+?)\]\((https?://[^)]+)\)$", line)
        if match:
            if current:
                rows.append(current)
            current = {
                "record_id": row.id,
                "source_url": row.source_url,
                "table_caption": "Fallback listing rows",
                "title": match.group(1).strip(),
                "url": match.group(2).strip(),
            }
            continue
        if current is not None and "description" not in current:
            current["description"] = line
    if current:
        rows.append(current)
    return rows


def _record_artifact_bundle(row: CrawlRecord) -> dict[str, object]:
    raw_data = row.data if isinstance(row.data, dict) else {}
    source_trace = row.source_trace if isinstance(row.source_trace, dict) else {}
    manifest_trace = source_trace.get("manifest_trace") if isinstance(source_trace.get("manifest_trace"), dict) else {}
    cleaned = _clean_export_data(raw_data)
    page_summary = {
        "record_id": row.id,
        "source_url": row.source_url,
        "title": cleaned.get("title") or raw_data.get("title"),
        "fallback_type": source_trace.get("type"),
        "markdown_excerpt": _stringify_markdown_value(raw_data.get("page_markdown"))[:500] or None,
    }
    evidence_refs = {
        "json_ld_count": len(manifest_trace.get("json_ld") or []) if isinstance(manifest_trace.get("json_ld"), list) else 0,
        "table_count": len(manifest_trace.get("tables") or []) if isinstance(manifest_trace.get("tables"), list) else 0,
    }
    return {
        "record_id": row.id,
        "source_url": row.source_url,
        "structured_record": cleaned or None,
        "table_rows": _artifact_table_rows(row) or None,
        "page_summary": {k: v for k, v in page_summary.items() if v not in (None, "", [], {})} or None,
        "markdown": {
            "page_markdown": raw_data.get("page_markdown"),
            "table_markdown": raw_data.get("table_markdown"),
        } if raw_data.get("page_markdown") or raw_data.get("table_markdown") else None,
        "evidence_refs": evidence_refs,
    }


def _export_headers(metadata: dict[str, int | bool]) -> dict[str, str]:
    return {
        EXPORT_PAGING_HEADER: str(metadata["pages_used"]),
        EXPORT_TOTAL_HEADER: str(metadata["total"]),
        EXPORT_PARTIAL_HEADER: "true" if metadata["truncated"] else "false",
    }


def _record_to_markdown(row: CrawlRecord) -> str:
    raw_data = row.data if isinstance(row.data, dict) else {}
    data = _clean_export_data(raw_data)
    source_trace = row.source_trace if isinstance(row.source_trace, dict) else {}
    semantic = source_trace.get("semantic") if isinstance(source_trace.get("semantic"), dict) else {}
    semantic_sections = semantic.get("sections") if isinstance(semantic.get("sections"), dict) else {}
    semantic_specs = semantic.get("specifications") if isinstance(semantic.get("specifications"), dict) else {}

    if str(source_trace.get("type") or "") == "listing_fallback":
        title = _stringify_markdown_value(raw_data.get("title")) or row.source_url or f"Record {row.id}"
        page_markdown = _stringify_markdown_value(raw_data.get("page_markdown"))
        if page_markdown:
            return page_markdown if page_markdown.lstrip().startswith("#") else f"# {title}\n\n{page_markdown}"

    title = _stringify_markdown_value(data.get("title")) or row.source_url or f"Record {row.id}"
    lines: list[str] = [f"# {title}"]
    if row.source_url:
        lines.extend(["", f"Source: <{row.source_url}>"])
    record_url = _stringify_markdown_value(data.get("url"))
    if record_url and record_url != row.source_url:
        lines.append(f"Record URL: <{record_url}>")

    rendered_section_keys: set[str] = set()
    scalar_rows: list[tuple[str, object]] = []
    for field_name, raw_value in data.items():
        normalized_field = str(field_name).strip().lower()
        if normalized_field in {"title", "url", "source_url"}:
            continue
        rendered_value = _stringify_markdown_value(raw_value)
        if not rendered_value:
            continue
        if _is_markdown_long_form(field_name, rendered_value):
            lines.extend(["", f"## {_humanize_field_name(field_name)}", "", _render_markdown_block(rendered_value)])
            rendered_section_keys.add(normalized_field)
            continue
        scalar_rows.append((_humanize_field_name(field_name), raw_value))
        rendered_section_keys.add(normalized_field)

    if scalar_rows:
        lines.extend(["", "## Fields", ""])
        for label, value in scalar_rows:
            lines.append(f"- **{label}:** {_render_markdown_inline(value)}")

    for field_name, raw_value in semantic_sections.items():
        normalized_field = str(field_name).strip().lower()
        if normalized_field in rendered_section_keys:
            continue
        rendered_value = _stringify_markdown_value(raw_value)
        if not rendered_value:
            continue
        lines.extend(["", f"## {_humanize_field_name(field_name)}", "", _render_markdown_block(rendered_value)])
        rendered_section_keys.add(normalized_field)

    spec_rows = [
        (_humanize_field_name(field_name), raw_value)
        for field_name, raw_value in sorted(semantic_specs.items(), key=lambda item: _humanize_field_name(item[0]).lower())
        if _stringify_markdown_value(raw_value)
    ]
    if spec_rows:
        lines.extend(["", "## Specifications", ""])
        for label, value in spec_rows:
            lines.append(f"- **{label}:** {_render_markdown_inline(value)}")

    return "\n".join(lines).strip()


def _stringify_markdown_value(value: object) -> str:
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


def _is_markdown_long_form(field_name: object, value: str) -> bool:
    normalized = str(field_name or "").strip().lower()
    if normalized in _markdown_long_form_fields():
        return True
    return "\n" in value or len(value) > 180


def _render_markdown_inline(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = _stringify_markdown_value(value)
        if re.fullmatch(r"https?://\S+", text):
            return f"<{text}>"
        return text
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return f"`{text}`"


def _render_markdown_block(value: str) -> str:
    rendered: list[str] = []
    for raw_line in value.split("\n"):
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


def _humanize_field_name(value: object) -> str:
    normalized = str(value or "").replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return ""
    return normalized[:1].upper() + normalized[1:]


@lru_cache(maxsize=1)
def _markdown_long_form_fields() -> frozenset[str]:
    rows = MARKDOWN_VIEW.get("long_form_fields") if isinstance(MARKDOWN_VIEW, dict) else []
    return frozenset(
        str(value).strip().lower()
        for value in (rows if isinstance(rows, list) else [])
        if str(value).strip()
    )


@lru_cache(maxsize=1)
def _discoverist_schema() -> tuple[str, ...]:
    return tuple(str(field_name) for field_name in DISCOVERIST_SCHEMA if str(field_name).strip())
