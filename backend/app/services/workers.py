from __future__ import annotations

import asyncio
import logging
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import SessionLocal
from app.models.crawl import CrawlRun
from app.services.crawl_state import CrawlStatus, TERMINAL_STATUSES, normalize_status
from app.services.db_utils import with_retry
from app.services.runtime_metrics import incr

logger = logging.getLogger("app.services.workers")


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


@dataclass
class QueueLeaseConfig:
    worker_id: str
    lease_seconds: int = 120
    heartbeat_seconds: int = 15
    poll_seconds: float = 1.0
    max_concurrency: int = 2
    claim_batch_size: int = 8


@dataclass
class QueueHealthSnapshot:
    pending: int
    running: int
    completed: int
    failed: int
    leased_running: int
    stale_running: int
    oldest_pending_age_seconds: float | None


async def get_queue_health_snapshot(session: AsyncSession) -> QueueHealthSnapshot:
    now = datetime.now(UTC)
    status_counts_result = await session.execute(
        select(CrawlRun.status, func.count(CrawlRun.id)).group_by(CrawlRun.status)
    )
    counts_by_status = {str(status): int(count) for status, count in status_counts_result.all()}

    leased_running_result = await session.execute(
        select(func.count(CrawlRun.id)).where(
            CrawlRun.status == CrawlStatus.RUNNING.value,
            CrawlRun.queue_owner.is_not(None),
            CrawlRun.lease_expires_at.is_not(None),
            CrawlRun.lease_expires_at >= now,
        )
    )
    leased_running = int(leased_running_result.scalar() or 0)

    stale_running_result = await session.execute(
        select(func.count(CrawlRun.id)).where(
            CrawlRun.status == CrawlStatus.RUNNING.value,
            or_(
                CrawlRun.queue_owner.is_(None),
                CrawlRun.lease_expires_at.is_(None),
                CrawlRun.lease_expires_at < now,
            ),
        )
    )
    stale_running = int(stale_running_result.scalar() or 0)

    oldest_pending_result = await session.execute(
        select(func.min(CrawlRun.created_at)).where(
            CrawlRun.status == CrawlStatus.PENDING.value
        )
    )
    oldest_pending_created_at = oldest_pending_result.scalar()
    if oldest_pending_created_at is not None and oldest_pending_created_at.tzinfo is None:
        oldest_pending_created_at = oldest_pending_created_at.replace(tzinfo=UTC)
    oldest_pending_age_seconds = (
        None
        if oldest_pending_created_at is None
        else max(0.0, (now - oldest_pending_created_at).total_seconds())
    )

    return QueueHealthSnapshot(
        pending=counts_by_status.get(CrawlStatus.PENDING.value, 0),
        running=counts_by_status.get(CrawlStatus.RUNNING.value, 0),
        completed=counts_by_status.get(CrawlStatus.COMPLETED.value, 0),
        failed=counts_by_status.get(CrawlStatus.FAILED.value, 0),
        leased_running=leased_running,
        stale_running=stale_running,
        oldest_pending_age_seconds=oldest_pending_age_seconds,
    )


async def claim_runs(
    session: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int,
) -> list[int]:
    now = datetime.now(UTC)
    lease_expiry = now + timedelta(seconds=max(1, int(lease_seconds)))
    base_claimable = or_(
        CrawlRun.status == CrawlStatus.PENDING.value,
        (CrawlRun.status == CrawlStatus.RUNNING.value)
        & CrawlRun.lease_expires_at.is_not(None)
        & (CrawlRun.lease_expires_at < now),
    )
    availability = or_(
        CrawlRun.queue_owner.is_(None),
        CrawlRun.lease_expires_at < now,
    )
    result = await session.execute(
        select(CrawlRun.id)
        .where(base_claimable, availability)
        .order_by(CrawlRun.created_at.asc())
        .limit(max(1, int(limit)))
    )
    candidates = [int(run_id) for run_id in result.scalars().all()]
    claimed: list[int] = []
    for run_id in candidates:
        claim_stmt = (
            update(CrawlRun)
            .where(CrawlRun.id == run_id, base_claimable, availability)
            .values(
                queue_owner=worker_id,
                lease_expires_at=lease_expiry,
                last_heartbeat_at=now,
                last_claimed_at=now,
                claim_count=func.coalesce(CrawlRun.claim_count, 0) + 1,
                status=case(
                    (CrawlRun.status == CrawlStatus.PENDING.value, CrawlStatus.RUNNING.value),
                    else_=CrawlRun.status,
                ),
            )
        )
        update_result = await session.execute(claim_stmt)
        if int(update_result.rowcount or 0) > 0:
            claimed.append(run_id)
    if claimed:
        await session.commit()
        incr("queue_claimed_runs_total", len(claimed))
    return claimed


async def heartbeat_run(
    session: AsyncSession,
    *,
    run_id: int,
    worker_id: str,
    lease_seconds: int,
) -> None:
    now = datetime.now(UTC)
    lease_expiry = now + timedelta(seconds=max(1, int(lease_seconds)))
    result = await session.execute(
        update(CrawlRun)
        .where(
            CrawlRun.id == run_id,
            CrawlRun.queue_owner == worker_id,
            CrawlRun.status == CrawlStatus.RUNNING.value,
        )
        .values(last_heartbeat_at=now, lease_expires_at=lease_expiry)
    )
    if int(result.rowcount or 0) > 0:
        await session.commit()
        incr("queue_heartbeat_updates_total")


async def release_lease(
    session: AsyncSession,
    *,
    run_id: int,
    worker_id: str,
) -> None:
    result = await session.execute(
        update(CrawlRun)
        .where(CrawlRun.id == run_id, CrawlRun.queue_owner == worker_id)
        .values(queue_owner=None, lease_expires_at=None)
    )
    await session.commit()
    if int(result.rowcount or 0) > 0:
        incr("queue_leases_released_total")


async def recover_stale_leases(session: AsyncSession) -> list[int]:
    now = datetime.now(UTC)
    stale_query = (
        select(CrawlRun)
        .where(
            CrawlRun.status == CrawlStatus.RUNNING.value,
            or_(
                CrawlRun.queue_owner.is_(None),
                CrawlRun.lease_expires_at.is_(None),
                CrawlRun.lease_expires_at < now,
            ),
        )
        .order_by(CrawlRun.id.asc())
    )
    result = await session.execute(stale_query)
    stale_runs = list(result.scalars().all())
    stale_ids = [int(run.id) for run in stale_runs]
    if stale_ids:
        for run in stale_runs:
            run.status = CrawlStatus.PENDING.value
            run.queue_owner = None
            run.lease_expires_at = None
            summary = dict(run.result_summary or {})
            summary["queue_recovered"] = True
            run.result_summary = summary
        await session.commit()
        incr("queue_recovered_stale_leases_total", len(stale_ids))
    return stale_ids


async def mark_run_failed_with_retry(
    *,
    run_id: int,
    error_message: str,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> None:
    async with session_factory() as error_session:
        async def _mutation(retry_session: AsyncSession) -> None:
            failed_run = await retry_session.get(CrawlRun, run_id)
            if failed_run is None:
                return
            if normalize_status(failed_run.status) in TERMINAL_STATUSES:
                return
            failed_run.status = CrawlStatus.FAILED.value
            summary = dict(failed_run.result_summary or {})
            summary["error"] = str(error_message or "worker_error")
            summary["extraction_verdict"] = "error"
            failed_run.result_summary = summary

        await with_retry(error_session, _mutation)


class CrawlWorkerLoop:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
        config: QueueLeaseConfig | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config = config or QueueLeaseConfig(worker_id=default_worker_id())
        self._stop_event = asyncio.Event()
        self._loop_task: asyncio.Task | None = None
        self._active: set[asyncio.Task] = set()

    async def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._loop_task is not None:
            await self._loop_task
        if self._active:
            await asyncio.gather(*self._active, return_exceptions=True)

    async def _run_forever(self) -> None:
        from app.services.crawl_service import process_run

        while not self._stop_event.is_set():
            available_slots = max(0, self._config.max_concurrency - len(self._active))
            if available_slots > 0:
                try:
                    async with self._session_factory() as session:
                        claimed = await claim_runs(
                            session,
                            worker_id=self._config.worker_id,
                            limit=min(available_slots, self._config.claim_batch_size),
                            lease_seconds=self._config.lease_seconds,
                        )
                except (
                    SQLAlchemyError,
                    RuntimeError,
                    ValueError,
                    TypeError,
                    OSError,
                ):
                    logger.exception("Queue claim loop failed")
                    incr("queue_claim_failures_total")
                    claimed = []
                for run_id in claimed:
                    task = asyncio.create_task(self._execute_run(run_id, process_run))
                    self._active.add(task)
                    task.add_done_callback(self._active.discard)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(0.1, float(self._config.poll_seconds)),
                )
            except asyncio.TimeoutError:
                pass

    async def _execute_run(self, run_id: int, process_run) -> None:
        heartbeat_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(run_id, heartbeat_stop))
        try:
            async with self._session_factory() as session:
                await process_run(session, run_id)
        except Exception as exc:
            logger.exception("Worker run execution failed for run %s", run_id)
            incr("queue_worker_run_failures_total")
            await mark_run_failed_with_retry(
                run_id=run_id,
                error_message=f"{type(exc).__name__}: {exc}",
                session_factory=self._session_factory,
            )
        finally:
            heartbeat_stop.set()
            await heartbeat_task
            async with self._session_factory() as session:
                await release_lease(
                    session,
                    run_id=run_id,
                    worker_id=self._config.worker_id,
                )

    async def _heartbeat_loop(self, run_id: int, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=max(1, int(self._config.heartbeat_seconds)),
                )
                continue
            except asyncio.TimeoutError:
                pass
            try:
                async with self._session_factory() as session:
                    await heartbeat_run(
                        session,
                        run_id=run_id,
                        worker_id=self._config.worker_id,
                        lease_seconds=self._config.lease_seconds,
                    )
            except Exception:
                logger.exception(
                    "Heartbeat update failed for run %s worker %s",
                    run_id,
                    self._config.worker_id,
                )
