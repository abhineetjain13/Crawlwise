# Review and promotion route handlers.
from __future__ import annotations

from typing import Annotated

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.crawl import (
    CrawlRunResponse,
    ReviewResponse,
    ReviewSaveRequest,
    ReviewSaveResponse,
    serialize_crawl_record_responses,
)
from app.services.crawl_crud import get_run
from app.services.review import build_review_payload, load_review_html, save_review
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/review", tags=["review"])

RUN_NOT_FOUND_DETAIL = "Run not found"


@router.get("/{run_id}")
async def review_detail(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReviewResponse:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    payload = await build_review_payload(session, run_id)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    return ReviewResponse(
        run=CrawlRunResponse.model_validate(payload["run"], from_attributes=True),
        normalized_fields=payload["normalized_fields"],
        discovered_fields=payload["discovered_fields"],
        canonical_fields=payload["canonical_fields"],
        domain_mapping=payload["domain_mapping"],
        suggested_mapping=payload["suggested_mapping"],
        records=serialize_crawl_record_responses(payload["records"]),
    )


@router.get("/{run_id}/artifact-html", response_class=HTMLResponse)
async def review_artifact_html(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    html_text = await load_review_html(session, run_id)
    if not html_text:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No HTML artifact found"
        )
    return HTMLResponse(content=html_text)


@router.post("/{run_id}/save")
async def review_save(
    run_id: int,
    payload: ReviewSaveRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReviewSaveResponse:
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_DETAIL
        )
    selections = [row.model_dump() for row in payload.selections]
    for extra_field in payload.extra_fields:
        name = str(extra_field or "").strip()
        if not name:
            continue
        selections.append(
            {
                "source_field": name,
                "output_field": name,
                "selected": True,
            }
        )
    result = await save_review(session, run, selections)
    return ReviewSaveResponse.model_validate(result)
