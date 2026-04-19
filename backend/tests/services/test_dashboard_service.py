from __future__ import annotations

import pytest

from app.models.crawl import CrawlLog, CrawlRecord, DomainMemory, ReviewPromotion
from app.models.llm import LLMCostLog
from app.services.crawl_crud import create_crawl_run
from app.services.dashboard_service import reset_application_data
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_reset_application_data_clears_state_and_restarts_run_ids(
    db_session: AsyncSession,
    test_user,
    workspace_tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dashboard_service

    artifacts_dir = workspace_tmp_path / "artifacts"
    cookies_dir = workspace_tmp_path / "cookies"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    cookies_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "runs").mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "runs" / "stale.html").write_text("artifact", encoding="utf-8")
    (cookies_dir / "session.json").write_text("cookie", encoding="utf-8")

    monkeypatch.setattr(dashboard_service.settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(dashboard_service.settings, "cookie_store_dir", cookies_dir)
    monkeypatch.setattr(dashboard_service, "_legacy_artifact_paths", lambda: [])

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
        },
    )
    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url=run.url,
            data={"title": "Widget"},
            raw_data={},
            discovered_data={},
            source_trace={},
        )
    )
    db_session.add(CrawlLog(run_id=run.id, level="info", message="hello"))
    db_session.add(
        ReviewPromotion(
            run_id=run.id,
            domain="example.com",
            surface="ecommerce_detail",
            approved_schema={"fields": ["title"]},
            field_mapping={"title": "title"},
        )
    )
    db_session.add(
        LLMCostLog(
            run_id=run.id,
            provider="openai",
            model="gpt-test",
            task_type="extract",
            input_tokens=10,
            output_tokens=20,
            cost_usd=0.01,
            domain="example.com",
        )
    )
    db_session.add(
        DomainMemory(
            domain="example.com",
            surface="ecommerce_detail",
            selectors={"rules": [{"id": 1, "field_name": "title"}]},
        )
    )
    await db_session.commit()

    result = await reset_application_data(db_session)

    assert result["crawl_runs_deleted"] == 1
    assert result["crawl_records_deleted"] == 1
    assert result["crawl_logs_deleted"] == 1
    assert result["review_promotions_deleted"] == 1
    assert result["llm_cost_logs_deleted"] == 1
    assert result["domain_memory_deleted"] == 1
    assert list(artifacts_dir.iterdir()) == []
    assert list(cookies_dir.iterdir()) == []

    for model in (CrawlRecord, CrawlLog, ReviewPromotion, DomainMemory, LLMCostLog):
        remaining = (await db_session.execute(select(model))).scalars().all()
        assert remaining == []

    db_session.expunge_all()

    next_run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/again",
            "surface": "ecommerce_detail",
        },
    )

    assert next_run.id == 1
