from __future__ import annotations

import asyncio
import logging
from uuid import uuid4
from collections.abc import Awaitable, Callable

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.crawl import CrawlRun
from app.tasks import process_run_task
from app.services._batch_runtime import (
    process_run as _batch_process_run,
)
from app.services.crawl_state import (
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    TERMINAL_STATUSES,
    CrawlStatus,
    set_control_request,
    update_run_status,
)
from app.services.pipeline.core import (
    _mark_run_failed,
)
from app.services.pipeline.runtime_helpers import log_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

VERDICT_SUCCESS, VERDICT_PARTIAL, VERDICT_BLOCKED = "success", "partial", "blocked"
VERDICT_SCHEMA_MISS, VERDICT_LISTING_FAILED, VERDICT_EMPTY = (
    "schema_miss",
    "listing_detection_failed",
    "empty",
)
CELERY_TASK_ID_KEY = "celery_task_id"
logger = logging.getLogger(__name__)
_local_run_tasks: dict[int, asyncio.Task[None]] = {}
_log = log_event


def _new_task_id(run_id: int) -> str:
    return f"crawl-run-{run_id}-{uuid4().hex}"


def _get_task_id(run: CrawlRun) -> str | None:
    task_id = str(run.get_summary(CELERY_TASK_ID_KEY) or "").strip()
    return task_id or None


def _set_task_id(run: CrawlRun, task_id: str | None) -> None:
    if task_id:
        run.update_summary(**{CELERY_TASK_ID_KEY: task_id})
    else:
        run.remove_summary_keys(CELERY_TASK_ID_KEY)


async def _load_run_with_normalized_status(
    retry_session: AsyncSession, run_id: int
) -> tuple[CrawlRun, CrawlStatus]:
    retry_run = await retry_session.get(CrawlRun, run_id)
    if retry_run is None:
        raise ValueError("Run not found")
    return retry_run, retry_run.status_value


async def _run_control_update(
    session: AsyncSession,
    run: CrawlRun,
    operation: Callable[[AsyncSession, CrawlRun, CrawlStatus], Awaitable[None]],
) -> CrawlRun:
    run_id = int(run.id)
    loaded_run, current = await _load_run_with_normalized_status(session, run_id)
    await operation(session, loaded_run, current)
    await session.commit()
    await session.refresh(run)
    return run


async def process_run(session: AsyncSession, run_id: int) -> None:
    """Compatibility wrapper so test patches on crawl_service symbols still apply."""
    await _batch_process_run(session, run_id)


async def _run_with_local_session(run_id: int) -> None:
    async with SessionLocal() as session:
        await process_run(session, run_id)


def _track_local_run_task(run_id: int) -> asyncio.Task[None]:
    task = asyncio.create_task(_run_with_local_session(run_id))
    _local_run_tasks[run_id] = task

    def _cleanup(completed_task: asyncio.Task[None]) -> None:
        try:
            exc = completed_task.exception()
        except asyncio.CancelledError:
            exc = None
        except Exception:
            logger.exception(
                "Failed to inspect local crawl task completion for run %s", run_id
            )
            exc = None
        if exc is not None:
            logger.error(
                "Local crawl task failed for run %s",
                run_id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

            async def _record_failure() -> None:
                async with SessionLocal() as session:
                    await _mark_run_failed(
                        session, run_id, f"{type(exc).__name__}: {exc}"
                    )

            asyncio.create_task(_record_failure())
        _local_run_tasks.pop(run_id, None)

    task.add_done_callback(_cleanup)
    return task


async def _dispatch_run_locally(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    loaded_run, current = await _load_run_with_normalized_status(session, int(run.id))
    if current not in {CrawlStatus.PENDING, CrawlStatus.RUNNING}:
        raise ValueError(f"Cannot dispatch run in state: {loaded_run.status}")
    task_id = _new_task_id(int(loaded_run.id))
    _set_task_id(loaded_run, task_id)
    await session.commit()
    _track_local_run_task(int(loaded_run.id))
    await session.refresh(run)
    return run


async def dispatch_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    if not settings.celery_dispatch_enabled:
        return await _dispatch_run_locally(session, run)

    loaded_run, current = await _load_run_with_normalized_status(session, int(run.id))
    if current not in {CrawlStatus.PENDING, CrawlStatus.RUNNING}:
        raise ValueError(f"Cannot dispatch run in state: {loaded_run.status}")
    task_id = _new_task_id(int(loaded_run.id))
    _set_task_id(loaded_run, task_id)
    await session.commit()
    try:
        process_run_task.apply_async(args=[loaded_run.id], task_id=task_id)
    except Exception as exc:
        if not settings.legacy_inprocess_runner_enabled:
            raise
        logger.warning(
            "Celery enqueue failed for run %s; falling back to in-process execution: %s",
            loaded_run.id,
            exc,
        )
        _track_local_run_task(int(loaded_run.id))
    await session.refresh(run)
    return run


async def pause_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    run_id = int(run.id)

    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current != CrawlStatus.RUNNING:
            raise ValueError(f"Cannot pause run in state: {retry_run.status}")
        task_id = _get_task_id(retry_run)
        local_task = _local_run_tasks.get(run_id)
        if local_task is not None:
            set_control_request(retry_run, CONTROL_REQUEST_PAUSE)
            await log_event(
                retry_session,
                retry_run.id,
                "warning",
                "Pause requested; crawl will stop at the next checkpoint",
            )
            return
        else:
            if task_id is None:
                raise ValueError("Cannot pause run without an active Celery task id")
            process_run_task.app.control.revoke(task_id, terminate=True)
        update_run_status(retry_run, CrawlStatus.PAUSED)
        _set_task_id(retry_run, None)
        await log_event(
            retry_session,
            retry_run.id,
            "warning",
            "Run pause requested",
        )

    return await _run_control_update(session, run, _operation)


async def resume_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current != CrawlStatus.PAUSED:
            raise ValueError(f"Cannot resume run in state: {retry_run.status}")
        update_run_status(retry_run, CrawlStatus.RUNNING)
        set_control_request(retry_run, None)
        _set_task_id(retry_run, None)
        await log_event(retry_session, retry_run.id, "info", "Resume requested")

    updated = await _run_control_update(session, run, _operation)
    return await dispatch_run(session, updated)


async def kill_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    run_id = int(run.id)

    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current in TERMINAL_STATUSES:
            raise ValueError(f"Cannot kill run in terminal state: {retry_run.status}")
        task_id = _get_task_id(retry_run)
        local_task = _local_run_tasks.get(run_id)
        if local_task is not None:
            set_control_request(retry_run, CONTROL_REQUEST_KILL)
            local_task.cancel()
            update_run_status(retry_run, CrawlStatus.KILLED)
            _set_task_id(retry_run, None)
            await log_event(
                retry_session,
                retry_run.id,
                "warning",
                "Run kill requested; local task cancelled",
            )
            return
        elif task_id:
            process_run_task.app.control.revoke(task_id, terminate=True)
        update_run_status(retry_run, CrawlStatus.KILLED)
        _set_task_id(retry_run, None)
        await log_event(
            retry_session,
            retry_run.id,
            "warning",
            "Run kill requested",
        )

    return await _run_control_update(session, run, _operation)


async def cancel_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    return await kill_run(session, run)


async def recover_stale_local_runs(session: AsyncSession) -> int:
    if settings.celery_dispatch_enabled:
        return 0

    result = await session.execute(
        select(CrawlRun).where(
            CrawlRun.status.in_(
                [
                    CrawlStatus.PENDING.value,
                    CrawlStatus.RUNNING.value,
                ]
            )
        )
    )
    recovered = 0
    for run in result.scalars().all():
        _local_run_tasks.pop(int(run.id), None)
        _set_task_id(run, None)
        if run.status_value == CrawlStatus.PENDING:
            update_run_status(run, CrawlStatus.KILLED)
            run.update_summary(
                error="Local dev runner was interrupted before processing began",
                extraction_verdict=VERDICT_BLOCKED,
            )
            await session.commit()
        else:
            await _mark_run_failed(
                session,
                int(run.id),
                "Local dev runner was interrupted by backend restart or process termination",
            )
        recovered += 1
    return recovered
