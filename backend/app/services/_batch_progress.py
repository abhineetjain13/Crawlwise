from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import (
    BatchRunProgressState,
    CrawlRun,
    _merge_run_acquisition_metrics,
)
from app.services.run_summary import merge_run_summary_patch

# Backwards-compatible re-exports for callers and tests that still import the
# progress model and summary merge helpers from the service layer.
_merge_run_summary_patch = merge_run_summary_patch

RetryRunUpdate = Callable[
    [AsyncSession, int, Callable[[AsyncSession, CrawlRun], Awaitable[None]]],
    Awaitable[None],
]


async def persist_batch_progress_patch(
    *,
    state: BatchRunProgressState,
    session: AsyncSession,
    run_id: int,
    retry_run_update: RetryRunUpdate,
    patch: dict[str, object],
) -> None:
    async def _mutation(
        _retry_session: AsyncSession,
        retry_run: CrawlRun,
    ) -> None:
        apply_patch = getattr(retry_run, "apply_batch_progress_patch", None)
        if callable(apply_patch):
            apply_patch(patch)
            return
        retry_run.merge_summary_patch(patch)

    await retry_run_update(session, run_id, _mutation)


async def persist_batch_url_result(
    *,
    state: BatchRunProgressState,
    session: AsyncSession,
    run_id: int,
    retry_run_update: RetryRunUpdate,
    idx: int,
    url: str,
    records_count: int,
    verdict: str,
    url_metrics: dict[str, object],
    error_message: str | None = None,
) -> None:
    state.record_url_result(
        idx=idx,
        records_count=records_count,
        verdict=verdict,
        url_metrics=url_metrics,
    )
    await persist_batch_progress_patch(
        state=state,
        session=session,
        run_id=run_id,
        retry_run_update=retry_run_update,
        patch=state.build_progress_patch(
            current_url=url,
            current_url_index=idx + 1,
            error_message=error_message,
        ),
    )


async def persist_batch_final_summary(
    *,
    state: BatchRunProgressState,
    session: AsyncSession,
    run_id: int,
    retry_run_update: RetryRunUpdate,
    aggregate_verdict: str,
) -> None:
    await persist_batch_progress_patch(
        state=state,
        session=session,
        run_id=run_id,
        retry_run_update=retry_run_update,
        patch=state.build_final_patch(aggregate_verdict),
    )

__all__ = [
    "BatchRunProgressState",
    "RetryRunUpdate",
    "_merge_run_acquisition_metrics",
    "_merge_run_summary_patch",
    "persist_batch_final_summary",
    "persist_batch_progress_patch",
    "persist_batch_url_result",
]
