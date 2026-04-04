from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun
from app.models.llm import LLMCostLog
from app.models.user import User
from app.services import dashboard_service


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

    async def _noop_reset_learned_state() -> None:
        return None

    monkeypatch.setattr("app.services.dashboard_service.reset_learned_state", _noop_reset_learned_state)

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
    assert artifacts_dir.exists()
    assert cookie_dir.exists()
    assert legacy_artifacts_dir.exists()
    assert list(artifacts_dir.iterdir()) == []
    assert list(cookie_dir.iterdir()) == []
    assert list(legacy_artifacts_dir.iterdir()) == []
