# Dashboard route handlers.
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.crawl import CrawlRunResponse, DashboardResponse
from app.services.dashboard_service import build_dashboard

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def dashboard(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DashboardResponse:
    payload = await build_dashboard(session)
    payload["recent_runs"] = [
        CrawlRunResponse.model_validate(row, from_attributes=True) for row in payload["recent_runs"]
    ]
    return DashboardResponse.model_validate(payload)
