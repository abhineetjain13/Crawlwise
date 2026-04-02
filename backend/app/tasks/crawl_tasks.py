# Task wrappers for local worker execution.
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.crawl_service import process_run


async def run_crawl_task(session: AsyncSession, run_id: int) -> None:
    await process_run(session, run_id)
