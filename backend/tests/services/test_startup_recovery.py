from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import recover_stale_inflight_runs
from app.models.crawl import CrawlRun
from app.services.crawl_state import CrawlStatus


@pytest.mark.asyncio
async def test_recover_stale_inflight_runs_requeues_running_for_reclaim(
    db_session: AsyncSession,
    test_user,
):
    running = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/listing",
        surface="ecommerce_listing",
        status=CrawlStatus.RUNNING.value,
        settings={},
        requested_fields=[],
        result_summary={"progress": 42},
    )
    completed = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/pdp",
        surface="ecommerce_detail",
        status=CrawlStatus.COMPLETED.value,
        settings={},
        requested_fields=[],
        result_summary={"progress": 100},
    )
    db_session.add_all([running, completed])
    await db_session.commit()
    await db_session.refresh(running)
    await db_session.refresh(completed)

    recovered_ids = await recover_stale_inflight_runs(db_session)

    await db_session.refresh(running)
    await db_session.refresh(completed)
    assert running.id in recovered_ids
    assert running.status == CrawlStatus.PENDING.value
    assert running.result_summary.get("queue_recovered") is True
    assert completed.id not in recovered_ids
    assert completed.status == CrawlStatus.COMPLETED.value
