# Crawl record and export route handlers.
from __future__ import annotations

import csv
import json
from typing import Annotated
from io import StringIO
from functools import lru_cache
from pathlib import Path
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
REPO_ROOT = Path(__file__).resolve().parents[3]
INTELLIGENCE_VIEW_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "knowledge_base" / "intelligence-view.json"
)


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
    fieldnames: set[str] = set()
    async for row in _stream_export_rows(session, run_id):
        cleaned = _clean_export_data(row.data)
        fieldnames.update(cleaned.keys())
    ordered_fieldnames = sorted(fieldnames)
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=ordered_fieldnames, extrasaction="ignore")
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    async for row in _stream_export_rows(session, run_id):
        writer.writerow(_clean_export_data(row.data))
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


def _clean_export_data(data: dict) -> dict:
    """Strip empty/null values and internal keys from export data."""
    return {
        k: v for k, v in data.items()
        if v not in (None, "", [], {}) and not str(k).startswith("_")
    }


def _export_headers(metadata: dict[str, int | bool]) -> dict[str, str]:
    return {
        EXPORT_PAGING_HEADER: str(metadata["pages_used"]),
        EXPORT_TOTAL_HEADER: str(metadata["total"]),
        EXPORT_PARTIAL_HEADER: "true" if metadata["truncated"] else "false",
    }


def _record_to_markdown(row: CrawlRecord) -> str:
    data = _clean_export_data(row.data or {})
    source_trace = row.source_trace if isinstance(row.source_trace, dict) else {}
    semantic = source_trace.get("semantic") if isinstance(source_trace.get("semantic"), dict) else {}
    semantic_sections = semantic.get("sections") if isinstance(semantic.get("sections"), dict) else {}
    semantic_specs = semantic.get("specifications") if isinstance(semantic.get("specifications"), dict) else {}

    title = _stringify_markdown_value(data.get("title")) or row.source_url or f"Record {row.id}"
    lines: list[str] = [f"# {title}"]
    if row.source_url:
        lines.extend(["", f"Source URL: {row.source_url}"])

    rendered_section_keys: set[str] = set()
    for field_name, raw_value in data.items():
        if str(field_name).strip().lower() == "title":
            continue
        rendered_value = _stringify_markdown_value(raw_value)
        if not rendered_value:
            continue
        if _is_markdown_long_form(field_name, rendered_value):
            lines.extend(["", f"## {_humanize_field_name(field_name)}", "", _render_markdown_block(rendered_value)])
            rendered_section_keys.add(str(field_name).strip().lower())

    for field_name, raw_value in semantic_sections.items():
        normalized_field = str(field_name).strip().lower()
        if normalized_field in rendered_section_keys:
            continue
        rendered_value = _stringify_markdown_value(raw_value)
        if not rendered_value:
            continue
        lines.extend(["", f"## {_humanize_field_name(field_name)}", "", _render_markdown_block(rendered_value)])

    scalar_rows: list[tuple[str, str]] = []
    for field_name, raw_value in data.items():
        normalized_field = str(field_name).strip().lower()
        if normalized_field == "title":
            continue
        rendered_value = _stringify_markdown_value(raw_value)
        if not rendered_value or normalized_field in rendered_section_keys:
            continue
        scalar_rows.append((_humanize_field_name(field_name), rendered_value))

    if scalar_rows:
        lines.extend(["", "## Output Fields", ""])
        for label, value in scalar_rows:
            lines.append(f"- {label}: {value}")

    if semantic_specs:
        lines.extend(["", "## Details", ""])
        for field_name, raw_value in sorted(semantic_specs.items(), key=lambda item: _humanize_field_name(item[0]).lower()):
            rendered_value = _stringify_markdown_value(raw_value)
            if rendered_value:
                lines.append(f"- {_humanize_field_name(field_name)}: {rendered_value}")

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
    if normalized in _intelligence_long_form_fields():
        return True
    return "\n" in value or len(value) > 180


def _render_markdown_block(value: str) -> str:
    lines = [line.strip() for line in value.split("\n") if line.strip()]
    if not lines:
        return ""
    rendered: list[str] = []
    for line in lines:
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
def _intelligence_long_form_fields() -> frozenset[str]:
    try:
        payload = json.loads(INTELLIGENCE_VIEW_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return frozenset()
    rows = payload.get("long_form_fields") if isinstance(payload, dict) else []
    return frozenset(
        str(value).strip().lower()
        for value in (rows if isinstance(rows, list) else [])
        if str(value).strip()
    )


@lru_cache(maxsize=1)
def _discoverist_schema() -> tuple[str, ...]:
    schema_path = Path(__file__).resolve().parent.parent / "data" / "knowledge_base" / "discoverist_schema.json"
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    return tuple(str(field_name) for field_name in payload if str(field_name).strip())
