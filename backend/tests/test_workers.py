from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRun
from app.services.crawl_state import CrawlStatus
from app.workers import _recover_orphan_runs


class _SessionOverride:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_recover_orphan_runs_only_marks_stale_active_runs_failed(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
):
    stale_run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/stale",
        status=CrawlStatus.RUNNING.value,
        surface="ecommerce_detail",
        settings={},
        requested_fields=[],
        result_summary={},
        updated_at=datetime.now(UTC) - timedelta(hours=1),
    )
    fresh_run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/fresh",
        status=CrawlStatus.RUNNING.value,
        surface="ecommerce_detail",
        settings={},
        requested_fields=[],
        result_summary={},
        updated_at=datetime.now(UTC),
    )
    db_session.add_all([stale_run, fresh_run])
    await db_session.commit()

    monkeypatch.setattr("app.workers.SessionLocal", lambda: _SessionOverride(db_session))
    monkeypatch.setattr("app.workers.WORKER_ORPHAN_RECOVERY_GRACE_SECONDS", 300)

    recovered = await _recover_orphan_runs()

    assert recovered == 1
    rows = {
        run.url: run
        for run in (
            await db_session.execute(select(CrawlRun).order_by(CrawlRun.id.asc()))
        ).scalars()
    }
    assert rows["https://example.com/stale"].status == CrawlStatus.FAILED.value
    assert rows["https://example.com/fresh"].status == CrawlStatus.RUNNING.value
