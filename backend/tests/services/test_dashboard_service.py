from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from app.models.crawl import CrawlRun
from app.models.user import User
from app.services import dashboard_service
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_build_operational_metrics_reports_runtime_and_duration_stats(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="metrics@example.com", hashed_password="hashed", role="admin")
    db_session.add(user)
    await db_session.flush()

    now = datetime.now(UTC)
    completed_run = CrawlRun(
        user_id=user.id,
        run_type="crawl",
        url="https://example.com/completed",
        status="completed",
        surface="ecommerce_listing",
        settings={},
        requested_fields=[],
        result_summary={},
        created_at=now - timedelta(minutes=10),
        completed_at=now - timedelta(minutes=5),
    )
    long_running_run = CrawlRun(
        user_id=user.id,
        run_type="crawl",
        url="https://example.com/active",
        status="running",
        surface="ecommerce_listing",
        settings={},
        requested_fields=[],
        result_summary={},
        created_at=now - timedelta(minutes=45),
        updated_at=now - timedelta(minutes=3),
    )
    active_with_stage = CrawlRun(
        user_id=user.id,
        run_type="crawl",
        url="https://example.com/active-stage",
        status="running",
        surface="ecommerce_listing",
        settings={},
        requested_fields=[],
        result_summary={"current_stage": "extract"},
        created_at=now - timedelta(minutes=5),
        updated_at=now - timedelta(seconds=20),
    )
    db_session.add(completed_run)
    db_session.add(long_running_run)
    db_session.add(active_with_stage)
    await db_session.commit()

    monkeypatch.setattr(
        "app.services.dashboard_service.runtime_metrics_snapshot",
        AsyncMock(return_value={
            "db_lock_errors_total": 3,
            "db_lock_retries_total": 2,
            "browser_launch_failures_total": 1,
            "proxy_exhaustion_total": 4,
        }),
    )

    metrics = await dashboard_service.build_operational_metrics(db_session)

    assert metrics["runtime_counters"]["db_lock_errors_total"] == 3
    assert metrics["runtime_counters"]["db_lock_retries_total"] == 2
    assert metrics["runtime_counters"]["browser_launch_failures_total"] == 1
    assert metrics["runtime_counters"]["proxy_exhaustion_total"] == 4
    assert (
        metrics["run_duration"]["active_long_running_threshold_seconds"] == 30 * 60
    )
    assert metrics["run_duration"]["active_long_running_count"] == 1
    assert metrics["run_duration"]["average_duration_seconds"] > 0
    assert metrics["active_health"]["stalled_run_threshold_seconds"] == 120
    assert metrics["active_health"]["active_without_stage_count"] == 1
    assert metrics["active_health"]["active_stalled_no_progress_count"] == 1
