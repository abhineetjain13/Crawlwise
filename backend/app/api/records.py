# Crawl record and export route handlers.
from __future__ import annotations

from typing import Annotated

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.schemas.crawl import CrawlRecordProvenanceResponse, CrawlRecordResponse
from app.services.crawl_access_service import RUN_NOT_FOUND_DETAIL, require_accessible_run
from app.services.crawl_crud import get_run_records
from app.services.record_export_service import (
    MAX_RECORD_PAGE_SIZE,
    RECORD_PROVENANCE_NOT_FOUND_RESPONSE,
    RUN_NOT_FOUND_RESPONSE,
    build_artifacts_json_export_response,
    build_csv_export_response,
    build_discoverist_export_response,
    build_json_export_response,
    build_markdown_export_response,
    build_tables_csv_export_response,
    export_record_provenance,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["records"])


@router.get("/api/crawls/{run_id}/records", responses=RUN_NOT_FOUND_RESPONSE)
async def records_list(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=MAX_RECORD_PAGE_SIZE)] = 20,
) -> PaginatedResponse[CrawlRecordResponse]:
    try:
        await require_accessible_run(session, run_id=run_id, user=current_user)
    except ValueError:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)

    rows, total = await get_run_records(session, run_id, page, limit)
    return PaginatedResponse(
        items=[
            CrawlRecordResponse.model_validate(row, from_attributes=True)
            for row in rows
        ],
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )


@router.get(
    "/api/records/{record_id}/provenance",
    responses=RECORD_PROVENANCE_NOT_FOUND_RESPONSE,
)
async def record_provenance(
    record_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CrawlRecordProvenanceResponse:
    try:
        return await export_record_provenance(
            session,
            record_id=record_id,
            user=current_user,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL) from exc


@router.get("/api/crawls/{run_id}/export/json", responses=RUN_NOT_FOUND_RESPONSE)
async def export_json(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    try:
        await require_accessible_run(session, run_id=run_id, user=current_user)
    except ValueError:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    return await build_json_export_response(session, run_id=run_id)


@router.get("/api/crawls/{run_id}/export/csv", responses=RUN_NOT_FOUND_RESPONSE)
async def export_csv(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    try:
        await require_accessible_run(session, run_id=run_id, user=current_user)
    except ValueError:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    return await build_csv_export_response(session, run_id=run_id)


@router.get("/api/crawls/{run_id}/export/tables.csv", responses=RUN_NOT_FOUND_RESPONSE)
async def export_tables_csv(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    try:
        await require_accessible_run(session, run_id=run_id, user=current_user)
    except ValueError:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    return await build_tables_csv_export_response(session, run_id=run_id)


@router.get("/api/crawls/{run_id}/export/markdown", responses=RUN_NOT_FOUND_RESPONSE)
async def export_markdown(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    try:
        await require_accessible_run(session, run_id=run_id, user=current_user)
    except ValueError:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    return await build_markdown_export_response(session, run_id=run_id)


@router.get(
    "/api/crawls/{run_id}/export/artifacts.json", responses=RUN_NOT_FOUND_RESPONSE
)
async def export_artifacts_json(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    try:
        await require_accessible_run(session, run_id=run_id, user=current_user)
    except ValueError:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    return await build_artifacts_json_export_response(session, run_id=run_id)


@router.get("/api/crawls/{run_id}/export/discoverist", responses=RUN_NOT_FOUND_RESPONSE)
async def export_discoverist(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    try:
        await require_accessible_run(session, run_id=run_id, user=current_user)
    except ValueError:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL)
    return await build_discoverist_export_response(session, run_id=run_id)
