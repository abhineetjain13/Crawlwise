from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.security import hash_password
from app.models.crawl import CrawlRun
from app.models.user import User
from app.services.crawl_state import CrawlStatus
from app.services.workers import (
    CrawlWorkerLoop,
    QueueLeaseConfig,
    claim_runs,
    get_queue_health_snapshot,
    heartbeat_run,
    recover_stale_leases,
    release_lease,
)


@pytest.mark.asyncio
async def test_claim_runs_claims_pending_once(db_session: AsyncSession, test_user):
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com",
        surface="ecommerce_detail",
        status=CrawlStatus.PENDING.value,
        settings={},
        requested_fields=[],
        result_summary={},
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    claimed = await claim_runs(
        db_session, worker_id="worker-a", limit=5, lease_seconds=60
    )

    await db_session.refresh(run)
    assert claimed == [run.id]
    assert run.queue_owner == "worker-a"
    assert run.status == CrawlStatus.RUNNING.value


@pytest.mark.asyncio
async def test_recover_stale_leases_requeues_expired_running(db_session: AsyncSession, test_user):
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com",
        surface="ecommerce_detail",
        status=CrawlStatus.RUNNING.value,
        settings={},
        requested_fields=[],
        result_summary={},
        queue_owner="worker-a",
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    recovered = await recover_stale_leases(db_session)

    await db_session.refresh(run)
    assert recovered == [run.id]
    assert run.status == CrawlStatus.PENDING.value
    assert run.queue_owner is None


@pytest.mark.asyncio
async def test_heartbeat_and_release_are_owner_scoped(db_session: AsyncSession, test_user):
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com",
        surface="ecommerce_detail",
        status=CrawlStatus.RUNNING.value,
        settings={},
        requested_fields=[],
        result_summary={},
        queue_owner="worker-a",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=5),
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    initial_lease = run.lease_expires_at

    await heartbeat_run(
        db_session, run_id=run.id, worker_id="worker-b", lease_seconds=60
    )
    await db_session.refresh(run)
    assert run.lease_expires_at == initial_lease

    await heartbeat_run(
        db_session, run_id=run.id, worker_id="worker-a", lease_seconds=60
    )
    await db_session.refresh(run)
    assert run.lease_expires_at is not None and run.lease_expires_at > initial_lease

    await release_lease(db_session, run_id=run.id, worker_id="worker-b")
    await db_session.refresh(run)
    assert run.queue_owner == "worker-a"

    await release_lease(db_session, run_id=run.id, worker_id="worker-a")
    await db_session.refresh(run)
    assert run.queue_owner is None


@pytest.mark.asyncio
async def test_claim_runs_two_workers_only_one_claims_same_pending_run(tmp_path):
    db_path = tmp_path / "workers_race.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        future=True,
        connect_args={"timeout": 30},
    )
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as setup:
            user = User(
                email="workers-race@example.com",
                hashed_password=hash_password("password123"),
                role="admin",
            )
            setup.add(user)
            await setup.commit()
            await setup.refresh(user)
            run = CrawlRun(
                user_id=user.id,
                run_type="crawl",
                url="https://example.com/race",
                surface="ecommerce_detail",
                status=CrawlStatus.PENDING.value,
                settings={},
                requested_fields=[],
                result_summary={},
            )
            setup.add(run)
            await setup.commit()
            await setup.refresh(run)
            run_id = run.id

        gate = asyncio.Event()

        async def _claim(worker_id: str) -> list[int]:
            async with session_factory() as session:
                await gate.wait()
                return await claim_runs(
                    session, worker_id=worker_id, limit=1, lease_seconds=60
                )

        task_a = asyncio.create_task(_claim("worker-a"))
        task_b = asyncio.create_task(_claim("worker-b"))
        gate.set()
        claimed_a, claimed_b = await asyncio.gather(task_a, task_b)

        all_claims = claimed_a + claimed_b
        assert all_claims.count(run_id) == 1
        assert len(all_claims) == 1

        async with session_factory() as verify:
            refreshed = await verify.get(CrawlRun, run_id)
            assert refreshed is not None
            assert refreshed.status == CrawlStatus.RUNNING.value
            assert refreshed.queue_owner in {"worker-a", "worker-b"}
            assert refreshed.claim_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_claim_runs_does_not_directly_claim_running_without_lease(
    db_session: AsyncSession, test_user
):
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/running-no-lease",
        surface="ecommerce_detail",
        status=CrawlStatus.RUNNING.value,
        settings={},
        requested_fields=[],
        result_summary={},
        queue_owner=None,
        lease_expires_at=None,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    claimed = await claim_runs(
        db_session, worker_id="worker-a", limit=5, lease_seconds=60
    )

    await db_session.refresh(run)
    assert claimed == []
    assert run.status == CrawlStatus.RUNNING.value
    assert run.queue_owner is None


@pytest.mark.asyncio
async def test_worker_loop_two_workers_process_each_run_once(tmp_path, monkeypatch):
    db_path = tmp_path / "workers_loop_race.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        future=True,
        connect_args={"timeout": 30},
    )
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    processed: list[int] = []
    processed_lock = asyncio.Lock()
    run_ids: list[int] = []
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as setup:
            user = User(
                email="workers-loop-race@example.com",
                hashed_password=hash_password("password123"),
                role="admin",
            )
            setup.add(user)
            await setup.commit()
            await setup.refresh(user)

            for idx in range(6):
                run = CrawlRun(
                    user_id=user.id,
                    run_type="crawl",
                    url=f"https://example.com/loop/{idx}",
                    surface="ecommerce_detail",
                    status=CrawlStatus.PENDING.value,
                    settings={},
                    requested_fields=[],
                    result_summary={},
                )
                setup.add(run)
                await setup.flush()
                run_ids.append(run.id)
            await setup.commit()

        async def _fake_process_run(session: AsyncSession, run_id: int) -> None:
            run = await session.get(CrawlRun, run_id)
            assert run is not None
            run.status = CrawlStatus.COMPLETED.value
            summary = dict(run.result_summary or {})
            summary["worker_processed"] = True
            run.result_summary = summary
            await session.commit()
            async with processed_lock:
                processed.append(run_id)
            await asyncio.sleep(0.05)

        monkeypatch.setattr("app.services.crawl_service.process_run", _fake_process_run)

        worker_a = CrawlWorkerLoop(
            session_factory=session_factory,
            config=QueueLeaseConfig(
                worker_id="worker-a",
                lease_seconds=5,
                heartbeat_seconds=1,
                poll_seconds=0.05,
                max_concurrency=2,
                claim_batch_size=2,
            ),
        )
        worker_b = CrawlWorkerLoop(
            session_factory=session_factory,
            config=QueueLeaseConfig(
                worker_id="worker-b",
                lease_seconds=5,
                heartbeat_seconds=1,
                poll_seconds=0.05,
                max_concurrency=2,
                claim_batch_size=2,
            ),
        )
        await worker_a.start()
        await worker_b.start()
        try:
            deadline = asyncio.get_event_loop().time() + 10
            while True:
                async with session_factory() as verify:
                    result = await verify.execute(
                        # Keep assertion inputs simple and deterministic.
                        # We only count unresolved rows for the test IDs.
                        select(CrawlRun.id, CrawlRun.status).where(CrawlRun.id.in_(run_ids))
                    )
                    rows = list(result.all())
                unresolved = [
                    status
                    for _, status in rows
                    if status not in {CrawlStatus.COMPLETED.value, CrawlStatus.FAILED.value}
                ]
                if not unresolved:
                    break
                if asyncio.get_event_loop().time() > deadline:
                    pytest.fail("Timed out waiting for worker loops to finish processing")
                await asyncio.sleep(0.05)
        finally:
            await worker_a.stop()
            await worker_b.stop()

        assert sorted(processed) == sorted(run_ids)
        assert len(processed) == len(run_ids)
        assert len(set(processed)) == len(run_ids)

        async with session_factory() as verify:
            result = await verify.execute(select(CrawlRun).where(CrawlRun.id.in_(run_ids)))
            refreshed = list(result.scalars().all())
        assert len(refreshed) == len(run_ids)
        for run in refreshed:
            assert run.status == CrawlStatus.COMPLETED.value
            assert run.claim_count == 1
            assert run.queue_owner is None
            assert run.lease_expires_at is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_queue_health_snapshot_reports_status_and_lease_shape(
    db_session: AsyncSession, test_user
):
    now = datetime.now(UTC)
    runs = [
        CrawlRun(
            user_id=test_user.id,
            run_type="crawl",
            url="https://example.com/health/pending",
            surface="ecommerce_detail",
            status=CrawlStatus.PENDING.value,
            settings={},
            requested_fields=[],
            result_summary={},
            created_at=now - timedelta(seconds=30),
        ),
        CrawlRun(
            user_id=test_user.id,
            run_type="crawl",
            url="https://example.com/health/running-leased",
            surface="ecommerce_detail",
            status=CrawlStatus.RUNNING.value,
            settings={},
            requested_fields=[],
            result_summary={},
            queue_owner="worker-a",
            lease_expires_at=now + timedelta(seconds=60),
        ),
        CrawlRun(
            user_id=test_user.id,
            run_type="crawl",
            url="https://example.com/health/running-stale",
            surface="ecommerce_detail",
            status=CrawlStatus.RUNNING.value,
            settings={},
            requested_fields=[],
            result_summary={},
            queue_owner=None,
            lease_expires_at=None,
        ),
        CrawlRun(
            user_id=test_user.id,
            run_type="crawl",
            url="https://example.com/health/completed",
            surface="ecommerce_detail",
            status=CrawlStatus.COMPLETED.value,
            settings={},
            requested_fields=[],
            result_summary={},
        ),
        CrawlRun(
            user_id=test_user.id,
            run_type="crawl",
            url="https://example.com/health/failed",
            surface="ecommerce_detail",
            status=CrawlStatus.FAILED.value,
            settings={},
            requested_fields=[],
            result_summary={},
        ),
    ]
    db_session.add_all(runs)
    await db_session.commit()

    snapshot = await get_queue_health_snapshot(db_session)

    assert snapshot.pending == 1
    assert snapshot.running == 2
    assert snapshot.completed == 1
    assert snapshot.failed == 1
    assert snapshot.leased_running == 1
    assert snapshot.stale_running == 1
    assert snapshot.oldest_pending_age_seconds is not None
    assert snapshot.oldest_pending_age_seconds >= 1.0
