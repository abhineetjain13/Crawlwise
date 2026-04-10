from __future__ import annotations

from pathlib import Path

import pytest
from app.core.dependencies import get_db, require_admin
from app.main import app
from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun, ReviewPromotion
from app.models.llm import LLMCostLog
from app.models.user import User
from app.services.knowledge_base.store import (
    get_domain_mapping,
    get_selector_defaults,
    save_domain_mapping,
    save_selector_defaults,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_dashboard_reset_data_endpoint_clears_db_artifacts_and_learned_state(
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

    admin = User(email="api-reset@example.com", hashed_password="hashed", role="admin")
    db_session.add(admin)
    await db_session.flush()

    run = CrawlRun(
        user_id=admin.id,
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
    db_session.add(ReviewPromotion(run_id=run.id, domain="example.com", surface="product_detail", approved_schema={}, field_mapping={}))
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

    await save_domain_mapping("example.com", "product_detail", {"price": "price"})
    await save_selector_defaults(
        "example.com",
        "title",
        [{"css_selector": "h1", "status": "validated", "source": "test"}],
    )

    monkeypatch.setattr("app.services.dashboard_service.settings.artifacts_dir", artifacts_dir)
    monkeypatch.setattr("app.services.dashboard_service.settings.cookie_store_dir", cookie_dir)
    monkeypatch.setattr("app.services.dashboard_service.PROJECT_ROOT", tmp_path)

    async def _override_get_db():
        yield db_session

    async def _override_require_admin() -> User:
        return admin

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_admin] = _override_require_admin

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/api/dashboard/reset-data")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "crawl_runs_deleted": 1,
        "crawl_records_deleted": 1,
        "crawl_logs_deleted": 1,
        "review_promotions_deleted": 1,
        "llm_cost_logs_deleted": 1,
        "artifacts_removed": 1,
        "legacy_artifacts_removed": 1,
        "cookies_removed": 1,
        "knowledge_base_reset": True,
    }

    assert await db_session.scalar(select(func.count()).select_from(CrawlRun)) == 0
    assert await db_session.scalar(select(func.count()).select_from(CrawlRecord)) == 0
    assert await db_session.scalar(select(func.count()).select_from(CrawlLog)) == 0
    assert await db_session.scalar(select(func.count()).select_from(ReviewPromotion)) == 0
    assert await db_session.scalar(select(func.count()).select_from(LLMCostLog)) == 0
    assert get_domain_mapping("example.com", "product_detail") == {}
    assert get_selector_defaults("example.com", "title") == []
    assert artifacts_dir.exists()
    assert cookie_dir.exists()
    assert legacy_artifacts_dir.exists()
    assert list(artifacts_dir.iterdir()) == []
    assert list(cookie_dir.iterdir()) == []
    assert list(legacy_artifacts_dir.iterdir()) == []
