from __future__ import annotations

import pytest
from app.models.crawl import CrawlRun
from app.services.crawl_service import CELERY_TASK_ID_KEY, dispatch_run
from types import SimpleNamespace
from unittest.mock import AsyncMock


def _make_run(*, run_id: int, status: str) -> CrawlRun:
    return CrawlRun(
        id=run_id,
        user_id=1,
        run_type="crawl",
        url="https://example.com",
        status=status,
        surface="ecommerce_detail",
        settings={},
        requested_fields=[],
        result_summary={},
    )


@pytest.mark.asyncio
async def test_dispatch_run_enqueues_celery_task_and_persists_task_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, object] = {}
    monkeypatch.setattr(
        "app.services.crawl_service.settings.celery_dispatch_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.services.crawl_service.settings.legacy_inprocess_runner_enabled",
        False,
    )

    def _fake_apply_async(*, args, task_id):
        recorded["args"] = list(args)
        recorded["task_id"] = task_id
        return None

    monkeypatch.setattr(
        "app.services.crawl_service.process_run_task.apply_async",
        _fake_apply_async,
    )

    run = _make_run(run_id=7, status="pending")
    session = SimpleNamespace(
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )

    async def _load_run_with_status(_session, _run_id):
        return run, "pending"

    monkeypatch.setattr(
        "app.services.crawl_service._load_run_with_normalized_status",
        _load_run_with_status,
    )

    dispatched = await dispatch_run(session, run)
    task_id = dispatched.result_summary.get(CELERY_TASK_ID_KEY)
    assert task_id
    assert recorded == {
        "args": [7],
        "task_id": task_id,
    }
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(run)


@pytest.mark.asyncio
async def test_dispatch_run_rejects_terminal_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.crawl_service.settings.celery_dispatch_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.services.crawl_service.process_run_task.apply_async",
        lambda **_kwargs: None,
    )

    run = _make_run(run_id=9, status="completed")
    session = SimpleNamespace(
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )

    async def _load_run_with_status(_session, _run_id):
        return run, "completed"

    monkeypatch.setattr(
        "app.services.crawl_service._load_run_with_normalized_status",
        _load_run_with_status,
    )

    with pytest.raises(ValueError, match="Cannot dispatch run in state"):
        await dispatch_run(session, run)


@pytest.mark.asyncio
async def test_dispatch_run_falls_back_to_local_runner_when_celery_enqueue_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_run(run_id=11, status="pending")
    session = SimpleNamespace(
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )

    async def _load_run_with_status(_session, _run_id):
        return run, "pending"

    recorded: dict[str, object] = {}

    def _raise_apply_async(**_kwargs):
        raise RuntimeError("redis down")

    def _fake_track_local_run_task(run_id: int):
        recorded["run_id"] = run_id
        return None

    monkeypatch.setattr(
        "app.services.crawl_service._load_run_with_normalized_status",
        _load_run_with_status,
    )
    monkeypatch.setattr(
        "app.services.crawl_service.process_run_task.apply_async",
        _raise_apply_async,
    )
    monkeypatch.setattr(
        "app.services.crawl_service._track_local_run_task",
        _fake_track_local_run_task,
    )
    monkeypatch.setattr(
        "app.services.crawl_service.settings.celery_dispatch_enabled",
        True,
    )
    monkeypatch.setattr(
        "app.services.crawl_service.settings.legacy_inprocess_runner_enabled",
        True,
    )

    dispatched = await dispatch_run(session, run)
    task_id = dispatched.result_summary.get(CELERY_TASK_ID_KEY)
    assert task_id
    assert recorded == {"run_id": 11}
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(run)
