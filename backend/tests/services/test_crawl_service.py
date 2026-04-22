from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.models.crawl import CrawlRecord, ReviewPromotion
from app.models.crawl_domain import CONTROL_REQUEST_KILL, CONTROL_REQUEST_PAUSE
from app.services import crawl_service
from app.services.crawl_crud import (
    commit_selected_fields,
    create_crawl_run,
    delete_run,
)
from app.services.crawl_state import get_control_request, update_run_status
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_running_run(
    db_session: AsyncSession,
    *,
    user_id: int,
    url: str = "https://example.com/jobs/1",
) -> object:
    run = await create_crawl_run(
        db_session,
        user_id,
        {
            "run_type": "crawl",
            "url": url,
            "surface": "job_detail",
        },
    )
    update_run_status(run, "running")
    run.update_summary(celery_task_id=f"crawl-run-{run.id}")
    await db_session.commit()
    await db_session.refresh(run)
    return run


@pytest.mark.asyncio
async def test_create_crawl_run_sets_pending_and_preserves_surface(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
        },
    )

    assert run.id is not None
    assert run.status == "pending"
    assert run.surface == "ecommerce_detail"
    assert run.result_summary["url_count"] == 1


@pytest.mark.asyncio
async def test_create_crawl_run_preserves_raw_additional_fields_and_keeps_domain_fields(
    db_session: AsyncSession,
    test_user,
) -> None:
    seed_run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/seed",
            "surface": "ecommerce_detail",
        },
    )
    db_session.add(
        ReviewPromotion(
            run_id=seed_run.id,
            domain="example.com",
            surface="ecommerce_detail",
            approved_schema={"fields": ["title", "materials"]},
            field_mapping={"material_notes": "materials"},
        )
    )
    await db_session.commit()

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "additional_fields": ["care instructions"],
        },
    )

    assert "materials" in run.requested_fields
    assert "care instructions" in run.requested_fields
    assert "care" not in run.requested_fields
    assert run.settings["requested_fields"] == run.requested_fields


@pytest.mark.asyncio
async def test_create_crawl_run_preserves_exact_custom_additional_field_labels(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "additional_fields": ["Features & Benefits", "Product Story"],
        },
    )

    assert run.requested_fields == ["Features & Benefits", "Product Story"]
    assert run.settings["requested_fields"] == ["Features & Benefits", "Product Story"]


@pytest.mark.asyncio
async def test_delete_run_rejects_active_runs(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
        },
    )

    with pytest.raises(ValueError, match="Cannot delete run"):
        await delete_run(db_session, run)


@pytest.mark.asyncio
async def test_commit_selected_fields_updates_requested_field_metadata(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "additional_fields": ["description", "number_of_keys"],
        },
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url=run.url,
        data={"title": "Widget"},
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    updated_records, updated_fields = await commit_selected_fields(
        db_session,
        run=run,
        items=[
            {"record_id": record.id, "field_name": "description", "value": "Clean text"},
            {"record_id": record.id, "field_name": "number_of_keys", "value": 61},
        ],
    )

    await db_session.refresh(record)
    assert updated_records == 1
    assert updated_fields == 2
    assert record.data["description"] == "Clean text"
    assert record.data["number_of_keys"] == 61
    assert record.source_trace["field_discovery"]["description"]["status"] == "found"
    assert record.source_trace["field_discovery"]["number_of_keys"]["value"] == "61"
    coverage = record.discovered_data["requested_field_coverage"]
    assert coverage["requested"] >= 1
    assert coverage["found"] >= 1
    assert "description" not in coverage["missing"]


@pytest.mark.asyncio
async def test_pause_run_preserves_live_local_task_bookkeeping(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "celery_dispatch_enabled", False)
    run = await _create_running_run(db_session, user_id=test_user.id)
    local_task = asyncio.create_task(asyncio.sleep(60))
    crawl_service._local_run_tasks[run.id] = local_task

    paused = await crawl_service.pause_run(db_session, run)
    await db_session.refresh(paused)

    assert paused.status == "running"
    assert get_control_request(paused) == CONTROL_REQUEST_PAUSE
    assert paused.get_summary(crawl_service.CELERY_TASK_ID_KEY) == f"crawl-run-{run.id}"
    assert crawl_service._local_run_tasks[run.id] is local_task

    crawl_service._local_run_tasks.pop(run.id, None)
    local_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await local_task


@pytest.mark.asyncio
async def test_kill_run_clears_local_task_bookkeeping(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "celery_dispatch_enabled", False)
    run = await _create_running_run(db_session, user_id=test_user.id)
    local_task = asyncio.create_task(asyncio.sleep(60))
    crawl_service._local_run_tasks[run.id] = local_task

    killed = await crawl_service.kill_run(db_session, run)
    await asyncio.sleep(0)
    await db_session.refresh(killed)

    assert killed.status == "killed"
    assert get_control_request(killed) == CONTROL_REQUEST_KILL
    assert killed.get_summary(crawl_service.CELERY_TASK_ID_KEY) is None
    assert run.id not in crawl_service._local_run_tasks
    assert local_task.cancelled()


@pytest.mark.asyncio
async def test_recover_stale_local_runs_clears_task_entries_and_task_ids(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "celery_dispatch_enabled", False)
    pending_run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/jobs/pending",
            "surface": "job_detail",
        },
    )
    pending_run.update_summary(celery_task_id="pending-task")

    running_run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/jobs/running",
            "surface": "job_detail",
        },
    )
    update_run_status(running_run, "running")
    running_run.update_summary(celery_task_id="running-task")
    stale_time = datetime.now(UTC) - timedelta(
        seconds=crawl_service.crawler_runtime_settings.stalled_run_threshold_seconds
        + 30
    )
    running_run.last_heartbeat_at = stale_time
    running_run.updated_at = stale_time
    await db_session.commit()

    finished_pending = asyncio.create_task(asyncio.sleep(0))
    finished_running = asyncio.create_task(asyncio.sleep(0))
    await asyncio.sleep(0)
    crawl_service._local_run_tasks[pending_run.id] = finished_pending
    crawl_service._local_run_tasks[running_run.id] = finished_running

    recovered = await crawl_service.recover_stale_local_runs(db_session)
    await db_session.refresh(pending_run)
    await db_session.refresh(running_run)

    assert recovered == 2
    assert pending_run.status == "killed"
    assert pending_run.get_summary(crawl_service.CELERY_TASK_ID_KEY) is None
    assert "interrupted before processing began" in str(
        pending_run.get_summary("error") or ""
    )
    assert running_run.status == "failed"
    assert running_run.get_summary(crawl_service.CELERY_TASK_ID_KEY) is None
    assert "interrupted by backend restart" in str(
        running_run.get_summary("error") or ""
    )
    assert pending_run.id not in crawl_service._local_run_tasks
    assert running_run.id not in crawl_service._local_run_tasks


@pytest.mark.asyncio
async def test_recover_stale_local_runs_skips_fresh_active_runs(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "celery_dispatch_enabled", False)
    pending_run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/jobs/fresh-pending",
            "surface": "job_detail",
        },
    )
    running_run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/jobs/fresh-running",
            "surface": "job_detail",
        },
    )
    update_run_status(running_run, "running")
    running_run.last_heartbeat_at = datetime.now(UTC)
    await db_session.commit()

    recovered = await crawl_service.recover_stale_local_runs(db_session)
    await db_session.refresh(pending_run)
    await db_session.refresh(running_run)

    assert recovered == 0
    assert pending_run.status == "pending"
    assert running_run.status == "running"


def test_log_background_task_exception_logs_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _boom() -> None:
        raise RuntimeError("write failed")

    async def _exercise() -> None:
        task = asyncio.create_task(_boom())
        await asyncio.sleep(0)
        with caplog.at_level(logging.ERROR):
            crawl_service._log_background_task_exception(
                task,
                "Failed to persist failure state for run 1",
            )

    asyncio.run(_exercise())

    assert "Failed to persist failure state for run 1" in caplog.text


@pytest.mark.asyncio
async def test_run_with_local_session_preserves_original_process_run_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = object()

    class _FakeSessionLocal:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _failing_process_run(active_session, run_id: int) -> None:
        assert active_session is session
        assert run_id == 17
        raise RuntimeError("process exploded")

    async def _failing_mark_run_failed(active_session, run_id: int, message: str) -> None:
        assert active_session is session
        assert run_id == 17
        assert "RuntimeError: process exploded" in message
        raise ValueError("write failed")

    monkeypatch.setattr(crawl_service, "SessionLocal", _FakeSessionLocal)
    monkeypatch.setattr(crawl_service, "_batch_process_run", _failing_process_run)
    monkeypatch.setattr(crawl_service, "_mark_run_failed", _failing_mark_run_failed)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="process exploded") as exc_info:
            await crawl_service._run_with_local_session(17)

    assert str(exc_info.value) == "process exploded"
    assert "Local crawl task failed for run 17" in caplog.text
    assert "Failed to persist failed status for run 17 after process_run error" in caplog.text
