# Active jobs route handlers.
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.crawl_crud import active_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/active")
async def jobs_active(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[dict]:
    return await active_jobs(session, user_id=None if user.role == "admin" else user.id)
