# Crawl record and export route handlers.
from __future__ import annotations

import csv
import json
from io import StringIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.schemas.crawl import CrawlRecordResponse
from app.services.crawl_service import get_run_records

router = APIRouter(prefix="/api/crawls", tags=["records"])


@router.get("/{run_id}/records", response_model=PaginatedResponse[CrawlRecordResponse])
async def records_list(
    run_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PaginatedResponse[CrawlRecordResponse]:
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
    rows, _ = await get_run_records(session, run_id, 1, 1000)
    payload = json.dumps([row.data for row in rows], indent=2)
    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=run-{run_id}.json"},
    )


@router.get("/{run_id}/export/csv")
async def export_csv(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    rows, _ = await get_run_records(session, run_id, 1, 1000)
    fieldnames = sorted({key for row in rows for key in row.data.keys()})
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row.data)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=run-{run_id}.csv"},
    )


@router.get("/{run_id}/export/discoverist")
async def export_discoverist(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    rows, _ = await get_run_records(session, run_id, 1, 1000)
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["source_url", "title", "description"])
    for row in rows:
        writer.writerow([row.source_url, row.data.get("title", ""), row.data.get("description", "")])
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=run-{run_id}-discoverist.csv"},
    )
