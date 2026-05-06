from __future__ import annotations

import asyncio
import logging
import weakref
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.crawl import CrawlRun
from app.tasks import process_run_task
from app.services._batch_runtime import process_run as _batch_process_run
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.crawl_state import (
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    TERMINAL_STATUSES,
    CrawlStatus,
    set_control_request,
    update_run_status,
)
from app.services.pipeline.runtime_helpers import log_event, mark_run_failed
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

VERDICT_SUCCESS, VERDICT_PARTIAL, VERDICT_BLOCKED = "success", "partial", "blocked"
VERDICT_ERROR, VERDICT_SCHEMA_MISS, VERDICT_LISTING_FAILED, VERDICT_EMPTY = (
    "error",
    "schema_miss",
    "listing_detection_failed",
    "empty",
)
CELERY_TASK_ID_KEY = "celery_task_id"
logger = logging.getLogger(__name__)
_local_run_tasks: weakref.WeakValueDictionary[int, asyncio.Task[None]] = (
    weakref.WeakValueDictionary()
)


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


def _get_live_local_run_task(run_id: int) -> asyncio.Task[None] | None:
    task = _local_run_tasks.get(run_id)
    if task is None:
        return None
    if task.done():
        _local_run_tasks.pop(run_id, None)
        return None
    return task


def _clear_local_run_task(
    run_id: int, *, expected_task: asyncio.Task[None] | None = None
) -> None:
    task = _local_run_tasks.get(run_id)
    if task is None:
        return
    if expected_task is not None and task is not expected_task:
        return
    _local_run_tasks.pop(run_id, None)


def _as_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _heartbeat_checkpoint(
    *,
    last_heartbeat_at: datetime | None,
    updated_at: datetime | None,
    created_at: datetime | None,
) -> datetime | None:
    return (
        _as_utc_datetime(last_heartbeat_at)
        or _as_utc_datetime(updated_at)
        or _as_utc_datetime(created_at)
    )


def _summary_task_id(summary: object) -> str | None:
    if not isinstance(summary, dict):
        return None
    task_id = str(summary.get(CELERY_TASK_ID_KEY) or "").strip()
    return task_id or None


def _should_recover_stale_run(
    *,
    status: CrawlStatus,
    summary: object,
    last_heartbeat_at: datetime | None,
    updated_at: datetime | None,
    created_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if status == CrawlStatus.PENDING and _summary_task_id(summary):
        return True
    reference_time = _heartbeat_checkpoint(
        last_heartbeat_at=last_heartbeat_at,
        updated_at=updated_at,
        created_at=created_at,
    )
    if reference_time is None:
        return True
    current_time = now or datetime.now(UTC)
    return (
        current_time - reference_time
    ).total_seconds() >= crawler_runtime_settings.stalled_run_threshold_seconds


async def _recover_stale_local_run(
    session: AsyncSession,
    run_id: int,
    *,
    target_status: CrawlStatus,
    error_message: str,
    extraction_verdict: str,
    log_level: str,
) -> bool:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return False
    if run.status_value in TERMINAL_STATUSES:
        if _get_task_id(run) is None:
            return False
        _set_task_id(run, None)
        await session.commit()
        return False
    if run.status_value != CrawlStatus.PENDING and target_status == CrawlStatus.KILLED:
        return False
    if run.status_value != CrawlStatus.RUNNING and target_status == CrawlStatus.FAILED:
        return False
    _set_task_id(run, None)
    run.update_summary(
        error=error_message,
        extraction_verdict=extraction_verdict,
    )
    update_run_status(run, target_status)
    await log_event(session, run.id, log_level, error_message)
    await session.commit()
    return True


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


async def _run_with_local_session(run_id: int) -> None:
    async with SessionLocal() as session:
        try:
            await _batch_process_run(session, run_id)
        except Exception as exc:
            logger.error(
                "Local crawl task failed for run %s",
                run_id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            try:
                await mark_run_failed(session, run_id, f"{type(exc).__name__}: {exc}")
            except Exception:
                logger.exception(
                    "Failed to persist failed status for run %s after process_run error",
                    run_id,
                )
            raise


def _track_local_run_task(run_id: int) -> asyncio.Task[None]:
    _clear_local_run_task(run_id)
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
            logger.debug("Local crawl task failure already persisted for run %s", run_id)
        _clear_local_run_task(run_id, expected_task=completed_task)

    task.add_done_callback(_cleanup)
    return task


def _log_background_task_exception(
    task: asyncio.Task[None],
    message: str,
) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("%s: cancelled", message)
    except Exception:
        logger.exception(message)


async def _dispatch_run_locally(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    await recover_stale_local_runs(session)
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
        local_task = _get_live_local_run_task(run_id)
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
        local_task = _get_live_local_run_task(run_id)
        if local_task is not None:
            set_control_request(retry_run, CONTROL_REQUEST_KILL)
            _clear_local_run_task(run_id, expected_task=local_task)
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
        select(
            CrawlRun.id,
            CrawlRun.status,
            CrawlRun.result_summary,
            CrawlRun.last_heartbeat_at,
            CrawlRun.updated_at,
            CrawlRun.created_at,
        ).where(
            CrawlRun.status.in_(
                [
                    CrawlStatus.PENDING.value,
                    CrawlStatus.RUNNING.value,
                ]
            )
        )
    )
    recovered = 0
    for (
        run_id,
        status_value,
        result_summary,
        last_heartbeat_at,
        updated_at,
        created_at,
    ) in result.all():
        status = CrawlStatus(str(status_value or "").strip().lower())
        if not _should_recover_stale_run(
            status=status,
            summary=result_summary,
            last_heartbeat_at=last_heartbeat_at,
            updated_at=updated_at,
            created_at=created_at,
        ):
            continue
        _clear_local_run_task(int(run_id))
        if status == CrawlStatus.PENDING:
            recovered += int(
                await _recover_stale_local_run(
                    session,
                    int(run_id),
                    target_status=CrawlStatus.KILLED,
                    error_message="Local dev runner was interrupted before processing began",
                    extraction_verdict=VERDICT_BLOCKED,
                    log_level="warning",
                )
            )
            continue
        recovered += int(
            await _recover_stale_local_run(
                session,
                int(run_id),
                target_status=CrawlStatus.FAILED,
                error_message="Local dev runner was interrupted by backend restart or process termination",
                extraction_verdict=VERDICT_ERROR,
                log_level="error",
            )
        )
    return recovered
