# Local worker process entrypoint.
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.schema_bootstrap import ensure_dev_schema
from app.models.crawl import CrawlRun
from app.tasks.crawl_tasks import run_crawl_task


async def work_forever() -> None:
    await ensure_dev_schema(engine)
    while True:
        async with SessionLocal() as session:
            result = await session.execute(
                select(CrawlRun)
                .where(CrawlRun.status == "pending")
                .order_by(CrawlRun.created_at.asc())
                .limit(1)
            )
            run = result.scalar_one_or_none()
            if run is not None:
                await run_crawl_task(session, run.id)
        await asyncio.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(work_forever())
