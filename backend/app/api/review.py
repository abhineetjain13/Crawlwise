# Review and promotion route handlers.
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.crawl import (
    CrawlRecordResponse,
    CrawlRunResponse,
    ReviewResponse,
    ReviewSaveRequest,
    ReviewSaveResponse,
)
from app.services.crawl_service import get_run
from app.services.review.service import build_review_payload, save_review

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/{run_id}", response_model=ReviewResponse)
async def review_detail(
    run_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ReviewResponse:
    payload = await build_review_payload(session, run_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return ReviewResponse(
        run=CrawlRunResponse.model_validate(payload["run"], from_attributes=True),
        normalized_fields=payload["normalized_fields"],
        discovered_fields=payload["discovered_fields"],
        suggested_mapping=payload["suggested_mapping"],
        selector_memory=payload["selector_memory"],
        records=[CrawlRecordResponse.model_validate(row, from_attributes=True) for row in payload["records"]],
    )


@router.post("/{run_id}/save", response_model=ReviewSaveResponse)
async def review_save(
    run_id: int,
    payload: ReviewSaveRequest,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ReviewSaveResponse:
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    result = await save_review(session, run, [row.model_dump() for row in payload.selections])
    return ReviewSaveResponse.model_validate(result)
