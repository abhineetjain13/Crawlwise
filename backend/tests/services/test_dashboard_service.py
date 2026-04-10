from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun
from app.models.llm import LLMCostLog
from app.models.user import User
from app.services import dashboard_service
from app.services.knowledge_base.store import (
    load_field_mappings,
    load_selector_defaults,
    save_domain_mapping,
    save_selector_defaults,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_reset_application_data_clears_rows_and_artifacts(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "backend" / "artifacts"
    cookie_dir = tmp_path / "backend" / "cookie_store"
    legacy_artifacts_dir = tmp_path / "backend" / "backend" / "artifacts"
    for path in (artifacts_dir / "html" / "1", cookie_dir, legacy_artifacts_dir / "diagnostics" / "1"):
        path.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "html" / "1" / "sample.html").write_text("artifact", encoding="utf-8")
    (cookie_dir / "example.com.json").write_text("[]", encoding="utf-8")
    (legacy_artifacts_dir / "diagnostics" / "1" / "sample.json").write_text("{}", encoding="utf-8")

    user = User(email="reset@example.com", hashed_password="hashed", role="admin")
    db_session.add(user)
    await db_session.flush()

    run = CrawlRun(
        user_id=user.id,
        run_type="crawl",
        url="https://example.com",
        status="completed",
        surface="product_detail",
        settings={},
        requested_fields=[],
        result_summary={},
    )
    db_session.add(run)
    await db_session.flush()

    db_session.add(CrawlRecord(run_id=run.id, source_url="https://example.com", data={}, raw_data={}, discovered_data={}, source_trace={}))
    db_session.add(CrawlLog(run_id=run.id, level="INFO", message="done"))
    db_session.add(
        LLMCostLog(
            run_id=run.id,
            provider="groq",
            model="llama-3.3-70b-versatile",
            task_type="cleanup",
            input_tokens=10,
            output_tokens=5,
            cost_usd="0.0001",
            domain="example.com",
        )
    )
    await db_session.commit()

    monkeypatch.setattr("app.services.dashboard_service.settings.artifacts_dir", artifacts_dir)
    monkeypatch.setattr("app.services.dashboard_service.settings.cookie_store_dir", cookie_dir)
    monkeypatch.setattr("app.services.dashboard_service.PROJECT_ROOT", tmp_path)

    await save_domain_mapping("example.com", "product_detail", {"price": "price"})
    await save_selector_defaults(
        "example.com",
        "title",
        [{"css_selector": "h1", "status": "validated", "source": "test"}],
    )

    result = await dashboard_service.reset_application_data(db_session)

    remaining_runs = await db_session.scalar(select(func.count()).select_from(CrawlRun))
    remaining_records = await db_session.scalar(select(func.count()).select_from(CrawlRecord))
    remaining_logs = await db_session.scalar(select(func.count()).select_from(CrawlLog))
    remaining_llm_logs = await db_session.scalar(select(func.count()).select_from(LLMCostLog))

    assert remaining_runs == 0
    assert remaining_records == 0
    assert remaining_logs == 0
    assert remaining_llm_logs == 0
    assert result["artifacts_removed"] == 1
    assert result["legacy_artifacts_removed"] == 1
    assert result["cookies_removed"] == 1
    assert load_field_mappings() == {}
    assert load_selector_defaults() == {}
    assert artifacts_dir.exists()
    assert cookie_dir.exists()
    assert legacy_artifacts_dir.exists()
    assert list(artifacts_dir.iterdir()) == []
    assert list(cookie_dir.iterdir()) == []
    assert list(legacy_artifacts_dir.iterdir()) == []

@pytest.mark.asyncio
async def test_reset_application_data_does_not_create_missing_legacy_artifacts_dir(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "backend" / "artifacts"
    cookie_dir = tmp_path / "backend" / "cookie_store"
    legacy_artifacts_dir = tmp_path / "backend" / "backend" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    cookie_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("app.services.dashboard_service.settings.artifacts_dir", artifacts_dir)
    monkeypatch.setattr("app.services.dashboard_service.settings.cookie_store_dir", cookie_dir)
    monkeypatch.setattr("app.services.dashboard_service.PROJECT_ROOT", tmp_path)

    result = await dashboard_service.reset_application_data(db_session)

    assert result["legacy_artifacts_removed"] == 0
    assert not legacy_artifacts_dir.exists()


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
