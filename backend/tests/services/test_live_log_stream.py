from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.crawl import CrawlRun
from app.services.crawl_crud import get_run_logs
from app.services.pipeline.core import _log


async def test_pipeline_logs_are_visible_across_sessions_while_run_is_active(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    session_factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    monkeypatch.setattr("app.services.crawl_events.SessionLocal", session_factory)

    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com",
        status="running",
        surface="ecommerce_detail",
        settings={},
        requested_fields=[],
        result_summary={},
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    await _log(db_session, run.id, "info", "live log entry")

    async with session_factory() as other_session:
        rows = await get_run_logs(other_session, run.id)

    assert [row.message for row in rows] == ["live log entry"]
