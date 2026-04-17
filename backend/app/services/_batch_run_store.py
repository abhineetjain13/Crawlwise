from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.models.crawl import CrawlRun
from app.services.crawl_state import CrawlStatus, update_run_status
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
_RUN_UPDATE_LOCK_RETRY_DELAYS_SECONDS = (0.0, 0.05, 0.1, 0.2, 0.5)
_LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"
_LOCK_NOT_AVAILABLE_ERROR_CODES = {"1205", "1222", "3572"}
_LOCK_NOT_AVAILABLE_MESSAGE_FRAGMENTS = (
    "could not obtain lock",
    "lock not available",
    "could not acquire lock",
    "database is locked",
    "database table is locked",
    "lock wait timeout exceeded",
    "nowait is set",
)
_TRANSIENT_CONNECTION_ERROR_NAMES = {
    "ConnectionDoesNotExistError",
    "ConnectionFailureError",
    "InterfaceError",
    "InternalClientError",
}
_TRANSIENT_CONNECTION_MESSAGE_FRAGMENTS = (
    "connection does not exist",
    "connection is closed",
    "server closed the connection unexpectedly",
    "terminating connection due to administrator command",
    "closed the connection unexpectedly",
)

RunMutation = Callable[[AsyncSession, CrawlRun], Awaitable[None]]


async def retry_run_update(
    session: AsyncSession,
    run_id: int,
    mutate: RunMutation,
) -> None:
    await session.flush()
    for attempt, delay_seconds in enumerate(
        _RUN_UPDATE_LOCK_RETRY_DELAYS_SECONDS,
        start=1,
    ):
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        try:
            run_missing = False
            async with session.begin_nested():
                result = await session.execute(
                    select(CrawlRun).where(CrawlRun.id == run_id).with_for_update(nowait=True)
                )
                run = result.scalar_one_or_none()
                if run is None:
                    run_missing = True
                else:
                    await mutate(session, run)
            if run_missing:
                await session.commit()
                return
            await session.commit()
            return
        except OperationalError as exc:
            if _is_retryable_run_update_error(exc) and attempt < len(
                _RUN_UPDATE_LOCK_RETRY_DELAYS_SECONDS
            ):
                logger.debug(
                    "Retrying crawl run update after transient database error for run_id=%s (attempt=%s)",
                    run_id,
                    attempt,
                )
                await session.rollback()
                continue
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise


def _is_lock_not_available_error(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)
    for attr_name in ("sqlstate", "pgcode"):
        code = str(getattr(orig, attr_name, "") or "").strip()
        if code == _LOCK_NOT_AVAILABLE_SQLSTATE:
            return True
    args = getattr(orig, "args", ())
    if args:
        code = str(args[0] or "").strip()
        if code in _LOCK_NOT_AVAILABLE_ERROR_CODES:
            return True
    message = " ".join(
        part
        for part in (
            str(orig or "").strip(),
            str(exc or "").strip(),
        )
        if part
    ).lower()
    return any(fragment in message for fragment in _LOCK_NOT_AVAILABLE_MESSAGE_FRAGMENTS)


def _is_transient_connection_error(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)
    candidates = [orig, exc]
    for candidate in candidates:
        if candidate is None:
            continue
        if type(candidate).__name__ in _TRANSIENT_CONNECTION_ERROR_NAMES:
            return True
    message = " ".join(
        part
        for part in (
            str(orig or "").strip(),
            str(exc or "").strip(),
        )
        if part
    ).lower()
    return any(fragment in message for fragment in _TRANSIENT_CONNECTION_MESSAGE_FRAGMENTS)


def _is_retryable_run_update_error(exc: OperationalError) -> bool:
    return _is_lock_not_available_error(exc) or _is_transient_connection_error(exc)


@dataclass(slots=True)
class BatchRunStore:
    session: AsyncSession

    async def apply(self, run_id: int, mutate: RunMutation) -> None:
        await retry_run_update(self.session, run_id, mutate)

    async def start_or_resume_run(self, run: CrawlRun) -> None:
        started = False

        async def _mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            nonlocal started
            if retry_run.status_value == CrawlStatus.PENDING:
                update_run_status(retry_run, CrawlStatus.RUNNING)
                started = True

        await self.apply(run.id, _mutation)
        await self.session.refresh(run)
        if started:
            await self._log(run.id, "info", "Pipeline started")
        else:
            await self._log(run.id, "info", "Pipeline resumed")

    async def ensure_correlation_id(self, run: CrawlRun, correlation_id: str) -> None:
        async def _mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            retry_run.update_summary(correlation_id=correlation_id)

        await self.apply(run.id, _mutation)
        await self.session.refresh(run)

    async def stamp_llm_snapshot(
        self,
        run: CrawlRun,
        llm_snapshot: dict[str, object],
    ) -> None:
        async def _mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            retry_run.settings = retry_run.settings_view.with_updates(
                llm_config_snapshot=llm_snapshot
            ).as_dict()

        await self.apply(run.id, _mutation)
        await self.session.refresh(run)

    async def persist_resolved_url_list(self, run: CrawlRun, url_list: list[str]) -> None:
        async def _mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            retry_run.update_summary(resolved_url_list=url_list)

        await self.apply(run.id, _mutation)
        await self.session.refresh(run)

    async def finalize_run(
        self,
        run_id: int,
        *,
        summary_patch: dict[str, object],
        aggregate_verdict: str,
    ) -> None:
        from app.services.pipeline.runtime_helpers import STAGE_SAVE
        from app.services.publish import (
            VERDICT_BLOCKED,
            VERDICT_EMPTY,
            VERDICT_ERROR,
            VERDICT_LISTING_FAILED,
            VERDICT_PARTIAL,
            VERDICT_SCHEMA_MISS,
            VERDICT_SUCCESS,
        )

        async def _mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            current_status = retry_run.status_value
            if current_status == CrawlStatus.RUNNING:
                if aggregate_verdict == VERDICT_SUCCESS:
                    update_run_status(retry_run, CrawlStatus.COMPLETED)
                elif aggregate_verdict in {
                    VERDICT_ERROR,
                    VERDICT_PARTIAL,
                    VERDICT_EMPTY,
                    VERDICT_BLOCKED,
                    VERDICT_SCHEMA_MISS,
                    VERDICT_LISTING_FAILED,
                }:
                    update_run_status(retry_run, CrawlStatus.FAILED)
            retry_run.merge_summary_patch(
                {
                    **summary_patch,
                    "current_stage": STAGE_SAVE,
                }
            )

        await self.apply(run_id, _mutation)

    async def mark_proxy_exhausted(self, run_id: int, error_message: str) -> None:
        from app.services.pipeline.runtime_helpers import log_event

        async def _mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            update_run_status(retry_run, CrawlStatus.PROXY_EXHAUSTED)
            retry_run.merge_summary_patch(
                {
                    "error": error_message,
                    "extraction_verdict": "proxy_exhausted",
                }
            )
            await log_event(retry_session, retry_run.id, "error", error_message)

        await self.apply(run_id, _mutation)

    async def _log(self, run_id: int, level: str, message: str) -> None:
        from app.services.pipeline.runtime_helpers import log_event

        await log_event(self.session, run_id, level, message)
        await self.session.commit()
