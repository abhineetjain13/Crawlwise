# Local worker process entrypoint.
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.crawl import CrawlRun
from app.services.crawl_state import CrawlStatus, WORKER_PICKUP_STATUSES, update_run_status
from app.services.pipeline_config import WORKER_MAX_CONCURRENT_JOBS
from app.tasks.crawl_tasks import run_crawl_task

logger = logging.getLogger("app.worker")

# Maximum concurrent Playwright browsers to prevent memory exhaustion.
_MAX_CONCURRENT_JOBS = WORKER_MAX_CONCURRENT_JOBS
_job_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_JOBS)


async def _run_claimed_run(run_id: int) -> None:
    async with _job_semaphore:
        try:
            async with SessionLocal() as task_session:
                await run_crawl_task(task_session, run_id)
        except Exception:
            logger.exception("Unhandled error processing run %d", run_id)
            async with SessionLocal() as error_session:
                failed_run = await error_session.get(CrawlRun, run_id)
                if failed_run is not None and failed_run.status in {
                    CrawlStatus.CLAIMED.value,
                    CrawlStatus.RUNNING.value,
                }:
                    update_run_status(failed_run, CrawlStatus.FAILED)
                    summary = dict(failed_run.result_summary or {})
                    summary["error"] = "Unhandled worker exception while processing crawl run"
                    summary["extraction_verdict"] = "error"
                    failed_run.result_summary = summary
                    await error_session.commit()


async def _recover_orphan_runs() -> int:
    """Mark any runs stuck in active worker-owned states from a prior crash as failed.

    Satisfies INV-JOB-04: a worker restart must surface orphaned jobs as FAILED.
    """
    async with SessionLocal() as session:
        orphan_statuses = (CrawlStatus.CLAIMED.value, CrawlStatus.RUNNING.value)
        result = await session.execute(select(CrawlRun).where(CrawlRun.status.in_(orphan_statuses)))
        runs = list(result.scalars().all())
        for run in runs:
            previous_status = run.status
            update_run_status(run, CrawlStatus.FAILED)
            summary = dict(run.result_summary or {})
            summary["error"] = f"Worker restarted - job was orphaned in {previous_status} state"
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
    in_flight_tasks: set[asyncio.Task] = set()

    while True:
        # Harvest exceptions from completed tasks so they don't get silently dropped.
        for task in in_flight_tasks:
            if task.done() and not task.cancelled():
                exc = task.exception() if not task.cancelled() else None
                if exc is not None:
                    logger.error("Background crawl task failed: %s", exc, exc_info=exc)
        in_flight_tasks = {task for task in in_flight_tasks if not task.done()}
        available_slots = max(_MAX_CONCURRENT_JOBS - len(in_flight_tasks), 0)
        if available_slots > 0:
            async with SessionLocal() as session:
                result = await session.execute(
                    select(CrawlRun)
                    .where(CrawlRun.status.in_([status.value for status in WORKER_PICKUP_STATUSES]))
                    .order_by(CrawlRun.created_at.asc())
                    .limit(available_slots)
                    .with_for_update(skip_locked=True)
                )
                runs = list(result.scalars().all())
                for run in runs:
                    update_run_status(run, CrawlStatus.CLAIMED)
                if runs:
                    await session.commit()
                    for run in runs:
                        in_flight_tasks.add(asyncio.create_task(_run_claimed_run(run.id)))
        await asyncio.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    asyncio.run(work_forever())
