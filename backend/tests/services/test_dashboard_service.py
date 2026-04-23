from __future__ import annotations

import pytest

from app.models.crawl import (
    CrawlLog,
    CrawlRecord,
    CrawlRun,
    DomainCookieMemory,
    DomainFieldFeedback,
    DomainMemory,
    DomainRunProfile,
    ReviewPromotion,
)
from app.models.llm import LLMCostLog
from app.services.crawl_crud import create_crawl_run
from app.services.dashboard_service import (
    reset_application_data,
    reset_crawl_data,
    reset_domain_memory,
)
from sqlalchemy import select
from app.core.database import SessionLocal
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_split_reset_crawl_data_and_domain_memory_preserve_the_other_scope(
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
    db_session.add(
        DomainRunProfile(
            domain="example.com",
            surface="ecommerce_detail",
            profile={"fetch_profile": {"fetch_mode": "browser_only"}},
        )
    )
    db_session.add(
        DomainCookieMemory(
            domain="example.com",
            storage_state={"cookies": [{"name": "session", "value": "1"}], "origins": []},
            state_fingerprint="abc",
        )
    )
    db_session.add(
        DomainFieldFeedback(
            domain="example.com",
            surface="ecommerce_detail",
            field_name="price",
            action="reject",
            source_kind="selector",
            source_value=".price",
            payload={},
        )
    )
    await db_session.commit()

    result = await reset_crawl_data(db_session)

    assert result["crawl_runs_deleted"] == 1
    assert result["crawl_records_deleted"] == 1
    assert result["crawl_logs_deleted"] == 1
    assert result["review_promotions_deleted"] == 1
    assert result["llm_cost_logs_deleted"] == 1
    assert list(artifacts_dir.iterdir()) == []
    assert list(cookies_dir.iterdir()) == []

    for model in (CrawlRecord, CrawlLog, ReviewPromotion, LLMCostLog):
        remaining = (await db_session.execute(select(model))).scalars().all()
        assert remaining == []
    assert (await db_session.execute(select(DomainMemory))).scalars().all() != []
    assert (await db_session.execute(select(DomainRunProfile))).scalars().all() != []
    assert (await db_session.execute(select(DomainCookieMemory))).scalars().all() != []
    assert (await db_session.execute(select(DomainFieldFeedback))).scalars().all() != []

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

    memory_reset = await reset_domain_memory(db_session)

    assert memory_reset["domain_memory_deleted"] == 1
    assert memory_reset["domain_run_profiles_deleted"] == 1
    assert memory_reset["domain_cookie_memory_deleted"] == 1
    assert memory_reset["domain_field_feedback_deleted"] == 1
    for model in (DomainMemory, DomainRunProfile, DomainCookieMemory, DomainFieldFeedback):
        remaining = (await db_session.execute(select(model))).scalars().all()
        assert remaining == []


@pytest.mark.asyncio
async def test_reset_application_data_rolls_back_when_domain_memory_reset_fails(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dashboard_service

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
    db_session.add(
        DomainMemory(
            domain="example.com",
            surface="ecommerce_detail",
            selectors={"rules": [{"id": 1, "field_name": "title"}]},
        )
    )
    await db_session.commit()

    async def _boom(session: AsyncSession) -> None:
        del session
        raise RuntimeError("domain memory reset failed")

    monkeypatch.setattr(dashboard_service, "_reset_domain_memory_tables", _boom)

    with pytest.raises(RuntimeError, match="domain memory reset failed"):
        await reset_application_data(db_session)

    assert (await db_session.execute(select(CrawlRun))).scalars().all() != []
    assert (await db_session.execute(select(CrawlRecord))).scalars().all() != []
    assert (await db_session.execute(select(DomainMemory))).scalars().all() != []


@pytest.mark.asyncio
async def test_resets_commit_when_session_already_has_an_open_transaction(
    db_session: AsyncSession,
    test_user,
) -> None:
    target_url = "https://reset-commit.example.com/product/widget"
    target_domain = "reset-commit.example.com"
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": target_url,
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
    db_session.add(
        DomainMemory(
            domain=target_domain,
            surface="ecommerce_detail",
            selectors={"rules": [{"id": 1, "field_name": "title"}]},
        )
    )
    await db_session.commit()

    # Simulate request-scoped auth/dependency work that already opened a transaction.
    await db_session.execute(select(CrawlRun).limit(1))
    assert db_session.in_transaction()

    await reset_crawl_data(db_session)
    await reset_domain_memory(db_session)

    async with SessionLocal() as verification_session:
        surviving_run = (
            await verification_session.execute(
                select(CrawlRun).where(CrawlRun.url == target_url)
            )
        ).scalar_one_or_none()
        surviving_record = (
            await verification_session.execute(
                select(CrawlRecord).where(CrawlRecord.source_url == target_url)
            )
        ).scalar_one_or_none()
        surviving_memory = (
            await verification_session.execute(
                select(DomainMemory).where(DomainMemory.domain == target_domain)
            )
        ).scalar_one_or_none()
        assert surviving_run is None
        assert surviving_record is None
        assert surviving_memory is None
