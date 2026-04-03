# Review and promotion route handlers.
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.crawl import (
    CrawlRecordResponse,
    CrawlRunResponse,
    ReviewResponse,
    ReviewSelectorPreviewRequest,
    ReviewSelectorPreviewResponse,
    ReviewSaveRequest,
    ReviewSaveResponse,
)
from app.services.crawl_service import get_run
from app.services.review.service import build_review_payload, load_review_html, preview_selectors, save_review

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/{run_id}", response_model=ReviewResponse)
async def review_detail(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReviewResponse:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    payload = await build_review_payload(session, run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return ReviewResponse(
        run=CrawlRunResponse.model_validate(payload["run"], from_attributes=True),
        normalized_fields=payload["normalized_fields"],
        discovered_fields=payload["discovered_fields"],
        canonical_fields=payload["canonical_fields"],
        domain_mapping=payload["domain_mapping"],
        suggested_mapping=payload["suggested_mapping"],
        selector_memory=payload["selector_memory"],
        selector_suggestions=payload["selector_suggestions"],
        records=[CrawlRecordResponse.model_validate(row, from_attributes=True) for row in payload["records"]],
    )


@router.get("/{run_id}/artifact-html", response_class=HTMLResponse)
async def review_artifact_html(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HTMLResponse:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    html_text = await load_review_html(session, run_id)
    if not html_text:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No HTML artifact found")
    return HTMLResponse(content=html_text)


@router.post("/{run_id}/save", response_model=ReviewSaveResponse)
async def review_save(
    run_id: int,
    payload: ReviewSaveRequest,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReviewSaveResponse:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    selections = [row.model_dump() for row in payload.selections]
    for extra_field in payload.extra_fields:
        name = str(extra_field or "").strip()
        if not name:
            continue
        selections.append({
            "source_field": name,
            "output_field": name,
            "selected": True,
        })
    result = await save_review(session, run, selections)
    return ReviewSaveResponse.model_validate(result)


@router.post("/{run_id}/selector-preview", response_model=ReviewSelectorPreviewResponse)
async def review_selector_preview(
    run_id: int,
    payload: ReviewSelectorPreviewRequest,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReviewSelectorPreviewResponse:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    preview = await preview_selectors(session, run_id, [row.model_dump() for row in payload.selectors])
    if preview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return ReviewSelectorPreviewResponse(
        records=[CrawlRecordResponse.model_validate(row) for row in preview["records"]],
    )
