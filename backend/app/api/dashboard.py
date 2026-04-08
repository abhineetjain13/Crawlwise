# Dashboard route handlers.
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.crawl import CrawlRunResponse, DashboardResponse
from app.services.dashboard_service import (
    build_dashboard,
    build_operational_metrics,
    reset_application_data,
)

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


@router.get("/metrics")
async def dashboard_metrics(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict:
    return await build_operational_metrics(session)
