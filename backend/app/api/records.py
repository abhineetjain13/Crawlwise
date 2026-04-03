# Crawl record and export route handlers.
from __future__ import annotations

import csv
import json
from io import StringIO
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.schemas.crawl import CrawlRecordResponse
from app.services.crawl_service import get_run_records

router = APIRouter(prefix="/api/crawls", tags=["records"])
MAX_RECORD_PAGE_SIZE = 1000
EXPORT_PAGING_HEADER = "X-Export-Paging"
EXPORT_TOTAL_HEADER = "X-Export-Total"
EXPORT_PARTIAL_HEADER = "X-Export-Partial"


@router.get("/{run_id}/records", response_model=PaginatedResponse[CrawlRecordResponse])
async def records_list(
    run_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=MAX_RECORD_PAGE_SIZE),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[CrawlRecordResponse]:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (current_user.role != "admin" and run.user_id != current_user.id):
        raise HTTPException(status_code=404, detail="Run not found")
        
    rows, total = await get_run_records(session, run_id, page, limit)
    return PaginatedResponse(
        items=[CrawlRecordResponse.model_validate(row, from_attributes=True) for row in rows],
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )


@router.get("/{run_id}/export/json")
async def export_json(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (_.role != "admin" and run.user_id != _.id):
        raise HTTPException(status_code=404, detail="Run not found")
    rows, metadata = await _collect_export_rows(session, run_id)
    payload = json.dumps([_clean_export_data(row.data) for row in rows], indent=2)
    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=run-{run_id}.json",
            **_export_headers(metadata),
        },
    )


@router.get("/{run_id}/export/csv")
async def export_csv(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (_.role != "admin" and run.user_id != _.id):
        raise HTTPException(status_code=404, detail="Run not found")
    rows, metadata = await _collect_export_rows(session, run_id)
    clean_rows = [_clean_export_data(row.data) for row in rows]
    fieldnames = sorted({key for r in clean_rows for key in r.keys()})
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for r in clean_rows:
        writer.writerow(r)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=run-{run_id}.csv",
            **_export_headers(metadata),
        },
    )


@router.get("/{run_id}/export/discoverist")
async def export_discoverist(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    from app.services.crawl_service import get_run
    run = await get_run(session, run_id)
    if run is None or (_.role != "admin" and run.user_id != _.id):
        raise HTTPException(status_code=404, detail="Run not found")
    rows, metadata = await _collect_export_rows(session, run_id)
    buffer = StringIO()
    writer = csv.writer(buffer)
    fieldnames = _discoverist_schema()
    writer.writerow(fieldnames)
    for row in rows:
        writer.writerow([
            row.source_url if field_name == "source_url" else (row.data or {}).get(field_name, "")
            for field_name in fieldnames
        ])
    return StreamingResponse(
        iter([buffer.getvalue()]),
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


@lru_cache(maxsize=1)
def _discoverist_schema() -> tuple[str, ...]:
    schema_path = Path(__file__).resolve().parent.parent / "data" / "knowledge_base" / "discoverist_schema.json"
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    return tuple(str(field_name) for field_name in payload if str(field_name).strip())
