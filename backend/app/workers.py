# Local worker process entrypoint.
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.crawl import CrawlRun
from app.services.crawl_state import CrawlStatus, WORKER_PICKUP_STATUSES, update_run_status
from app.tasks.crawl_tasks import run_crawl_task

logger = logging.getLogger("app.worker")

# Maximum concurrent Playwright browsers to prevent memory exhaustion.
_MAX_CONCURRENT_JOBS = 3
_job_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_JOBS)


async def _recover_orphan_runs() -> int:
    """Mark any runs stuck in 'running' from a prior crash as 'failed'.

    Satisfies INV-JOB-04: a worker restart must surface orphaned jobs as FAILED.
    """
    async with SessionLocal() as session:
        result = await session.execute(select(CrawlRun).where(CrawlRun.status == CrawlStatus.RUNNING.value))
        runs = list(result.scalars().all())
        for run in runs:
            update_run_status(run, CrawlStatus.FAILED)
            summary = dict(run.result_summary or {})
            summary["error"] = "Worker restarted — job was orphaned in running state"
            summary["extraction_verdict"] = "error"
            run.result_summary = summary
        if runs:
            await session.commit()
            logger.warning(
                "Recovered %d orphaned run(s) from prior crash: %s",
                len(runs),
                [run.id for run in runs],
            )
        return len(runs)


async def work_forever() -> None:
    # INV-JOB-04: recover jobs orphaned by prior crash
    recovered = await _recover_orphan_runs()
    if recovered:
        logger.info("Startup orphan recovery complete: %d run(s) marked as failed", recovered)

    logger.info("Worker started (poll=%.1fs, max_concurrent=%d)", settings.worker_poll_interval_seconds, _MAX_CONCURRENT_JOBS)

    while True:
        async with SessionLocal() as session:
            result = await session.execute(
                select(CrawlRun)
                .where(CrawlRun.status.in_([status.value for status in WORKER_PICKUP_STATUSES]))
                .order_by(CrawlRun.created_at.asc())
                .limit(1)
            )
            run = result.scalar_one_or_none()
            if run is not None:
                run_id = run.id
                try:
                    async with _job_semaphore:
                        await run_crawl_task(session, run_id)
                except Exception:
                    logger.exception("Unhandled error processing run %d", run_id)
                    try:
                        await session.rollback()
                    except Exception:
                        logger.exception("Rollback failed for run %d", run_id)
        await asyncio.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    asyncio.run(work_forever())
