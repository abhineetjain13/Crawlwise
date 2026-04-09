from __future__ import annotations

import asyncio
import tempfile

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import hash_password
from app.models.crawl import CrawlRun
from app.models.user import User
from app.services._batch_runtime import _merge_run_summary_patch, _retry_run_update


@pytest.mark.asyncio
async def test_retry_run_update_serializes_concurrent_summary_updates() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_batch_runtime_update_lock.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as setup_session:
                user = User(
                    email="batch-runtime-lock@example.com",
                    hashed_password=hash_password("password123"),
                    role="admin",
                )
                setup_session.add(user)
                await setup_session.commit()
                await setup_session.refresh(user)

                run = CrawlRun(
                    user_id=user.id,
                    run_type="batch",
                    url="https://example.com",
                    status="running",
                    surface="ecommerce_listing",
                    settings={},
                    requested_fields=[],
                    result_summary={},
                )
                setup_session.add(run)
                await setup_session.commit()
                await setup_session.refresh(run)
                run_id = run.id

            async def _apply_progress_patch(
                progress: int,
                record_count: int,
                completed_urls: int,
                verdict: str,
                delay_seconds: float,
            ) -> None:
                async with session_factory() as session:
                    async def _mutation(_retry_session: AsyncSession, retry_run: CrawlRun) -> None:
                        await asyncio.sleep(delay_seconds)
                        retry_run.result_summary = _merge_run_summary_patch(
                            retry_run.result_summary,
                            {
                                "progress": progress,
                                "record_count": record_count,
                                "completed_urls": completed_urls,
                                "processed_urls": completed_urls,
                                "remaining_urls": max(2 - completed_urls, 0),
                                "url_verdicts": [verdict] * completed_urls,
                                "verdict_counts": {verdict: completed_urls},
                            },
                        )

                    await _retry_run_update(session, run_id, _mutation)

            await asyncio.gather(
                _apply_progress_patch(
                    progress=50,
                    record_count=1,
                    completed_urls=1,
                    verdict="success",
                    delay_seconds=0.02,
                ),
                _apply_progress_patch(
                    progress=100,
                    record_count=2,
                    completed_urls=2,
                    verdict="success",
                    delay_seconds=0.005,
                ),
            )

            async with session_factory() as verify_session:
                refreshed = await verify_session.get(CrawlRun, run_id)
                assert refreshed is not None
                summary = dict(refreshed.result_summary or {})
                record_count = int(summary.get("record_count") or 0)
                completed_urls = int(summary.get("completed_urls") or 0)
                processed_urls = int(summary.get("processed_urls") or 0)
                assert processed_urls == completed_urls
                assert summary.get("remaining_urls") == max(record_count - processed_urls, 0)
                assert sorted(list(summary.get("url_verdicts") or [])) == ["success", "success"]
                assert summary.get("verdict_counts") == {"success": 2}
        finally:
            await engine.dispose()

