from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.product_intelligence import (
    ProductIntelligenceDiscoveryRequest,
    ProductIntelligenceDiscoveryResponse,
    ProductIntelligenceJobCreate,
    ProductIntelligenceJobDetailResponse,
    ProductIntelligenceJobResponse,
    ProductIntelligenceReviewRequest,
)
from app.services.product_intelligence.service import (
    build_job_payload,
    create_product_intelligence_job,
    discover_product_intelligence_candidates,
    get_product_intelligence_job,
    list_product_intelligence_jobs,
    review_product_intelligence_match,
    run_product_intelligence_job,
)

router = APIRouter(prefix="/api/product-intelligence", tags=["product-intelligence"])
logger = logging.getLogger(__name__)


@router.post("/discover")
async def product_intelligence_discover(
    payload: ProductIntelligenceDiscoveryRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ProductIntelligenceDiscoveryResponse:
    logger.info(
        "Product Intelligence discover provider=%s",
        payload.options.search_provider,
    )
    try:
        response = await discover_product_intelligence_candidates(
            session,
            user=user,
            payload=payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProductIntelligenceDiscoveryResponse.model_validate(response)


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
async def product_intelligence_create_job(
    payload: ProductIntelligenceJobCreate,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ProductIntelligenceJobResponse:
    try:
        job = await create_product_intelligence_job(
            session,
            user=user,
            payload=payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    background_tasks.add_task(run_product_intelligence_job, job.id)
    return ProductIntelligenceJobResponse.model_validate(job, from_attributes=True)


@router.get("/jobs")
async def product_intelligence_list_jobs(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[ProductIntelligenceJobResponse]:
    jobs = await list_product_intelligence_jobs(session, user=user, limit=limit)
    return [
        ProductIntelligenceJobResponse.model_validate(job, from_attributes=True)
        for job in jobs
    ]


@router.get("/jobs/{job_id}")
async def product_intelligence_get_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ProductIntelligenceJobDetailResponse:
    try:
        job = await get_product_intelligence_job(session, user=user, job_id=job_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    payload = await build_job_payload(session, job=job)
    return ProductIntelligenceJobDetailResponse.model_validate(payload)


@router.post("/jobs/{job_id}/matches/{match_id}/review")
async def product_intelligence_review_match(
    job_id: int,
    match_id: int,
    payload: ProductIntelligenceReviewRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    try:
        match = await review_product_intelligence_match(
            session,
            user=user,
            job_id=job_id,
            match_id=match_id,
            action=payload.action,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "match_id": match.id,
        "review_status": match.review_status,
    }
