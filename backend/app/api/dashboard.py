# Dashboard route handlers.
from __future__ import annotations

from typing import Annotated

from app.core.dependencies import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.crawl import CrawlRunResponse, DashboardResponse
from app.services.dashboard_service import (
    build_dashboard,
    build_operational_metrics,
    reset_application_data,
    reset_crawl_data,
    reset_data_enrichment,
    reset_domain_memory,
    reset_product_intelligence,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DashboardResponse:
    payload = await build_dashboard(
        session, user_id=None if user.role == "admin" else user.id
    )
    payload["recent_runs"] = [
        CrawlRunResponse.model_validate(row, from_attributes=True)
        for row in payload["recent_runs"]
    ]
    return DashboardResponse.model_validate(payload)


@router.post("/reset-data")
async def dashboard_reset_data(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict:
    return await reset_application_data(session)


@router.post("/reset-crawl-data")
async def dashboard_reset_crawl_data(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict:
    return await reset_crawl_data(session)


@router.post("/reset-domain-memory")
async def dashboard_reset_domain_memory(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict:
    return await reset_domain_memory(session)


@router.post("/reset-product-intelligence")
async def dashboard_reset_product_intelligence(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict:
    return await reset_product_intelligence(session)


@router.post("/reset-data-enrichment")
async def dashboard_reset_data_enrichment(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    confirm: Annotated[str | None, Query()] = None,
) -> dict:
    if confirm != "data-enrichment":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirm=data-enrichment is required",
        )
    return await reset_data_enrichment(session)


@router.get("/metrics")
async def dashboard_metrics(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict:
    return await build_operational_metrics(session)
