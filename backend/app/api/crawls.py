# Crawl run route handlers.
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import LogEntryResponse, PaginatedResponse, PaginationMeta
from app.schemas.crawl import CrawlCreate, CrawlRunResponse
from app.services.crawl_service import (
    cancel_run,
    create_crawl_run,
    get_run,
    get_run_logs,
    list_runs,
    parse_csv_urls,
)

router = APIRouter(prefix="/api/crawls", tags=["crawls"])


@router.post("", response_model=dict)
async def crawls_create(
    payload: CrawlCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    data = payload.model_dump()
    # For batch runs, store URLs in settings so worker can access them
    if payload.run_type == "batch" and payload.urls:
        data.setdefault("settings", {})["urls"] = payload.urls
    run = await create_crawl_run(session, user.id, data)
    return {"run_id": run.id}


@router.post("/csv", response_model=dict)
async def crawls_create_csv(
    file: UploadFile = File(...),
    surface: str = Form(...),
    additional_fields: str = Form(default=""),
    settings_json: str = Form(default="{}"),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Create a crawl run from an uploaded CSV file."""
    import json

    content = (await file.read()).decode("utf-8", errors="ignore")
    urls = parse_csv_urls(content)
    if not urls:
        raise HTTPException(status_code=400, detail="No valid URLs found in CSV")

    extra_fields = [f.strip() for f in additional_fields.split(",") if f.strip()]
    try:
        crawl_settings = json.loads(settings_json)
    except json.JSONDecodeError:
        crawl_settings = {}
    crawl_settings["csv_content"] = content

    data = {
        "run_type": "csv",
        "url": urls[0],
        "urls": urls,
        "surface": surface,
        "settings": crawl_settings,
        "additional_fields": extra_fields,
    }
    data["settings"]["urls"] = urls
    run = await create_crawl_run(session, user.id, data)
    return {"run_id": run.id, "url_count": len(urls)}


@router.get("", response_model=PaginatedResponse[CrawlRunResponse])
async def crawls_list(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    run_type: str = "",
    status_value: str = Query(default="", alias="status"),
    url_search: str = "",
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PaginatedResponse[CrawlRunResponse]:
    rows, total = await list_runs(session, page, limit, status_value, run_type, url_search)
    return PaginatedResponse(
        items=[CrawlRunResponse.model_validate(row, from_attributes=True) for row in rows],
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )


@router.get("/{run_id}", response_model=CrawlRunResponse)
async def crawls_detail(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CrawlRunResponse:
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return CrawlRunResponse.model_validate(run, from_attributes=True)


@router.post("/{run_id}/cancel", response_model=dict)
async def crawls_cancel(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    updated = await cancel_run(session, run)
    return {"run_id": updated.id, "status": updated.status}


@router.get("/{run_id}/logs", response_model=list[LogEntryResponse])
async def crawls_logs(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[LogEntryResponse]:
    rows = await get_run_logs(session, run_id)
    return [LogEntryResponse.model_validate(row, from_attributes=True) for row in rows]
