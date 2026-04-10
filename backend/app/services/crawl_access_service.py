from __future__ import annotations

from app.models.crawl import CrawlRecord, CrawlRun
from app.models.user import User
from app.services.crawl_crud import get_run
from sqlalchemy.ext.asyncio import AsyncSession

RUN_NOT_FOUND_DETAIL = "Run not found"
RECORD_NOT_FOUND_DETAIL = "Record not found"


def user_can_access_run(*, user: User, run: CrawlRun) -> bool:
    return user.role == "admin" or run.user_id == user.id


async def require_accessible_run(
    session: AsyncSession,
    *,
    run_id: int,
    user: User,
) -> CrawlRun:
    run = await get_run(session, run_id)
    if run is None or not user_can_access_run(user=user, run=run):
        raise ValueError(RUN_NOT_FOUND_DETAIL)
    return run


async def require_accessible_record(
    session: AsyncSession,
    *,
    record_id: int,
    user: User,
) -> CrawlRecord:
    record = await session.get(CrawlRecord, record_id)
    if record is None:
        raise LookupError(RECORD_NOT_FOUND_DETAIL)
    await require_accessible_run(session, run_id=record.run_id, user=user)
    return record
