from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.data_enrichment import (
    DataEnrichmentJobCreate,
    DataEnrichmentJobDetailResponse,
    DataEnrichmentJobResponse,
)
from app.services.data_enrichment.service import (
    build_data_enrichment_job_payload,
    create_data_enrichment_job,
    get_data_enrichment_job,
    list_data_enrichment_jobs,
    run_data_enrichment_job,
)

router = APIRouter(prefix="/api/data-enrichment", tags=["data-enrichment"])


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
async def data_enrichment_create_job(
    payload: DataEnrichmentJobCreate,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DataEnrichmentJobResponse:
    try:
        job = await create_data_enrichment_job(
            session,
            user=user,
            payload=payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    background_tasks.add_task(run_data_enrichment_job, job.id)
    return DataEnrichmentJobResponse.model_validate(job, from_attributes=True)


@router.get("/jobs")
async def data_enrichment_list_jobs(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[DataEnrichmentJobResponse]:
    jobs = await list_data_enrichment_jobs(session, user=user, limit=limit)
    return [
        DataEnrichmentJobResponse.model_validate(job, from_attributes=True)
        for job in jobs
    ]


@router.get("/jobs/{job_id}")
async def data_enrichment_get_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DataEnrichmentJobDetailResponse:
    try:
        job = await get_data_enrichment_job(session, user=user, job_id=job_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    payload = await build_data_enrichment_job_payload(session, job=job)
    return DataEnrichmentJobDetailResponse.model_validate(payload)
