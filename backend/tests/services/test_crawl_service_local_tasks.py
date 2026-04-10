from __future__ import annotations

import asyncio

import pytest
from app.services import crawl_service
from app.services.crawl_crud import create_crawl_run, get_run
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_track_local_run_task_marks_run_failed_on_background_exception(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com",
            "surface": "ecommerce_detail",
        },
    )
    run.status = "running"
    await db_session.commit()

    async def _boom(_run_id: int) -> None:
        raise RuntimeError("background failure")

    monkeypatch.setattr(crawl_service, "_run_with_local_session", _boom)
    session_factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    monkeypatch.setattr(crawl_service, "SessionLocal", session_factory)

    task = crawl_service._track_local_run_task(int(run.id))

    refreshed = None
    for _ in range(20):
        await asyncio.sleep(0.05)
        async with session_factory() as verification_session:
            refreshed = await get_run(verification_session, run.id)
        if refreshed is not None and refreshed.status == "failed":
            break

    assert task.done()
    assert int(run.id) not in crawl_service._local_run_tasks
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.result_summary["error"] == "RuntimeError: background failure"
