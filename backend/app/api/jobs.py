# Active jobs route handlers.
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.crawl_service import active_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/active", response_model=list[dict])
async def jobs_active(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    return await active_jobs(session)
