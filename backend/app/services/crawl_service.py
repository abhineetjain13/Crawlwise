from __future__ import annotations

from uuid import uuid4
from collections.abc import Awaitable, Callable

from app.models.crawl import CrawlRun
from app.tasks import process_run_task
from app.services._batch_runtime import (
    process_run as _batch_process_run,
)
from app.services.crawl_crud import (
    active_jobs,
    commit_llm_suggestions,
    create_crawl_run,
    delete_run,
    get_run,
    get_run_logs,
    get_run_records,
    list_runs,
)
from app.services.crawl_state import (
    TERMINAL_STATUSES,
    CrawlStatus,
    normalize_status,
    update_run_status,
)
from app.services.llm_integration.page_classifier import classify_page
from app.services.pipeline import (
    _log,
    _resolve_listing_surface,
)
from sqlalchemy.ext.asyncio import AsyncSession

# Compatibility exports for tests and existing import paths.
_COMPAT_EXPORTS = (
    active_jobs,
    commit_llm_suggestions,
    create_crawl_run,
    delete_run,
    get_run,
    get_run_logs,
    get_run_records,
    list_runs,
    _resolve_listing_surface,
    classify_page,
)
VERDICT_SUCCESS, VERDICT_PARTIAL, VERDICT_BLOCKED = "success", "partial", "blocked"
VERDICT_SCHEMA_MISS, VERDICT_LISTING_FAILED, VERDICT_EMPTY = "schema_miss", "listing_detection_failed", "empty"
CELERY_TASK_ID_KEY = "celery_task_id"


def _new_task_id(run_id: int) -> str:
    return f"crawl-run-{run_id}-{uuid4().hex}"


def _get_task_id(run: CrawlRun) -> str | None:
    summary = dict(run.result_summary or {})
    task_id = str(summary.get(CELERY_TASK_ID_KEY) or "").strip()
    return task_id or None


def _set_task_id(run: CrawlRun, task_id: str | None) -> None:
    summary = dict(run.result_summary or {})
    if task_id:
        summary[CELERY_TASK_ID_KEY] = task_id
    else:
        summary.pop(CELERY_TASK_ID_KEY, None)
    run.result_summary = summary


async def _load_run_with_normalized_status(
    retry_session: AsyncSession, run_id: int
) -> tuple[CrawlRun, CrawlStatus]:
    retry_run = await retry_session.get(CrawlRun, run_id)
    if retry_run is None:
        raise ValueError("Run not found")
    return retry_run, normalize_status(retry_run.status)


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


async def dispatch_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    loaded_run, current = await _load_run_with_normalized_status(session, int(run.id))
    if current not in {CrawlStatus.PENDING, CrawlStatus.RUNNING}:
        raise ValueError(f"Cannot dispatch run in state: {loaded_run.status}")
    task_id = _new_task_id(int(loaded_run.id))
    _set_task_id(loaded_run, task_id)
    await session.commit()
    process_run_task.apply_async(args=[loaded_run.id], task_id=task_id)
    await session.refresh(run)
    return run


async def pause_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current != CrawlStatus.RUNNING:
            raise ValueError(f"Cannot pause run in state: {retry_run.status}")
        task_id = _get_task_id(retry_run)
        if task_id is None:
            raise ValueError("Cannot pause run without an active Celery task id")
        process_run_task.app.control.revoke(task_id, terminate=True)
        update_run_status(retry_run, CrawlStatus.PAUSED)
        _set_task_id(retry_run, None)
        await _log(
            retry_session,
            retry_run.id,
            "warning",
            "Run paused via Celery task revocation",
        )

    return await _run_control_update(session, run, _operation)


async def resume_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current != CrawlStatus.PAUSED:
            raise ValueError(f"Cannot resume run in state: {retry_run.status}")
        update_run_status(retry_run, CrawlStatus.RUNNING)
        _set_task_id(retry_run, None)
        await _log(retry_session, retry_run.id, "info", "Resume requested")

    updated = await _run_control_update(session, run, _operation)
    return await dispatch_run(session, updated)


async def kill_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current in TERMINAL_STATUSES:
            raise ValueError(f"Cannot kill run in terminal state: {retry_run.status}")
        task_id = _get_task_id(retry_run)
        if task_id:
            process_run_task.app.control.revoke(task_id, terminate=True)
        update_run_status(retry_run, CrawlStatus.KILLED)
        _set_task_id(retry_run, None)
        await _log(
            retry_session,
            retry_run.id,
            "warning",
            "Run killed via Celery task revocation",
        )

    return await _run_control_update(session, run, _operation)


async def cancel_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    return await kill_run(session, run)
