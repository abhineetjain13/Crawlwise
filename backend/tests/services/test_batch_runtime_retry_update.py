from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError


@pytest.fixture
def batch_runtime_module(monkeypatch: pytest.MonkeyPatch):
    pipeline_core = types.ModuleType("app.services.pipeline.core")
    pipeline_core.STAGE_FETCH = "FETCH"
    pipeline_core.STAGE_SAVE = "SAVE"
    pipeline_core._log = AsyncMock()
    pipeline_core._mark_run_failed = AsyncMock()
    pipeline_core._process_single_url = AsyncMock()
    pipeline_core._set_stage = AsyncMock()
    monkeypatch.setitem(sys.modules, "app.services.pipeline.core", pipeline_core)

    import app.services._batch_runtime as batch_runtime_module

    return importlib.reload(batch_runtime_module)


class _FakeLockError(Exception):
    sqlstate = "55P03"

    def __str__(self) -> str:
        return "could not obtain lock on row in relation crawl_runs"


class _FakeConnectionDoesNotExistError(Exception):
    def __str__(self) -> str:
        return "connection does not exist"


class _FakeResult:
    def __init__(self, run) -> None:
        self._run = run

    def scalar_one_or_none(self):
        return self._run


class _FakeNestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_retry_run_update_retries_fast_on_lock_contention(
    monkeypatch: pytest.MonkeyPatch,
    batch_runtime_module,
) -> None:
    _retry_run_update = batch_runtime_module._retry_run_update
    run = SimpleNamespace(id=17, updated=False)
    session = SimpleNamespace(
        begin_nested=lambda: _FakeNestedTransaction(),
        commit=AsyncMock(),
        flush=AsyncMock(),
        rollback=AsyncMock(),
        execute=AsyncMock(
            side_effect=[
                OperationalError("SELECT", {}, _FakeLockError()),
                _FakeResult(run),
            ]
        ),
    )
    sleep = AsyncMock()
    monkeypatch.setattr("app.services._batch_runtime.asyncio.sleep", sleep)

    async def _mutate(_session, retry_run) -> None:
        retry_run.updated = True

    await _retry_run_update(session, run.id, _mutate)

    assert run.updated is True
    session.flush.assert_awaited_once()
    assert session.execute.await_count == 2
    assert session.rollback.await_count == 1
    assert session.commit.await_count == 1
    sleep.assert_awaited_once_with(0.05)


@pytest.mark.asyncio
async def test_retry_run_update_does_not_retry_non_lock_operational_errors(
    monkeypatch: pytest.MonkeyPatch,
    batch_runtime_module,
) -> None:
    _retry_run_update = batch_runtime_module._retry_run_update
    session = SimpleNamespace(
        begin_nested=lambda: _FakeNestedTransaction(),
        commit=AsyncMock(),
        flush=AsyncMock(),
        rollback=AsyncMock(),
        execute=AsyncMock(
            side_effect=OperationalError("SELECT", {}, RuntimeError("connection lost"))
        ),
    )
    sleep = AsyncMock()
    monkeypatch.setattr("app.services._batch_runtime.asyncio.sleep", sleep)

    async def _mutate(_session, _run) -> None:
        return None

    with pytest.raises(OperationalError):
        await _retry_run_update(session, 23, _mutate)

    session.flush.assert_awaited_once()
    assert session.execute.await_count == 1
    assert session.rollback.await_count == 1
    assert session.commit.await_count == 0
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_run_update_retries_transient_connection_loss(
    monkeypatch: pytest.MonkeyPatch,
    batch_runtime_module,
) -> None:
    _retry_run_update = batch_runtime_module._retry_run_update
    run = SimpleNamespace(id=19, updated=False)
    session = SimpleNamespace(
        begin_nested=lambda: _FakeNestedTransaction(),
        commit=AsyncMock(),
        flush=AsyncMock(),
        rollback=AsyncMock(),
        execute=AsyncMock(
            side_effect=[
                OperationalError("SELECT", {}, _FakeConnectionDoesNotExistError()),
                _FakeResult(run),
            ]
        ),
    )
    sleep = AsyncMock()
    monkeypatch.setattr("app.services._batch_runtime.asyncio.sleep", sleep)

    async def _mutate(_session, retry_run) -> None:
        retry_run.updated = True

    await _retry_run_update(session, run.id, _mutate)

    assert run.updated is True
    session.flush.assert_awaited_once()
    assert session.execute.await_count == 2
    assert session.rollback.await_count == 1
    assert session.commit.await_count == 1
    sleep.assert_awaited_once_with(0.05)


@pytest.mark.asyncio
async def test_start_or_resume_run_uses_locked_status_for_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services._batch_run_store import BatchRunStore
    from app.services.crawl_state import CrawlStatus

    session = SimpleNamespace(refresh=AsyncMock())
    store = BatchRunStore(session)
    run = SimpleNamespace(id=31, status_value=CrawlStatus.PENDING)
    locked_run = SimpleNamespace(id=31, status_value=CrawlStatus.RUNNING)

    async def _apply(run_id, mutate):
        assert run_id == run.id
        await mutate(session, locked_run)
        run.status_value = locked_run.status_value

    async def _apply_method(self, run_id, mutate):
        await _apply(run_id, mutate)

    log_calls: list[tuple[int, str, str]] = []

    async def _log_method(self, run_id, level, message):
        log_calls.append((run_id, level, message))

    monkeypatch.setattr(BatchRunStore, "apply", _apply_method)
    monkeypatch.setattr(BatchRunStore, "_log", _log_method)

    update_calls: list[tuple[object, object]] = []

    def _update_run_status(target_run, status):
        update_calls.append((target_run, status))

    monkeypatch.setattr("app.services._batch_run_store.update_run_status", _update_run_status)

    await store.start_or_resume_run(run)

    assert update_calls == []
    assert log_calls == [(run.id, "info", "Pipeline resumed")]
    session.refresh.assert_awaited_once_with(run)


@pytest.mark.asyncio
async def test_start_or_resume_run_starts_when_locked_status_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services._batch_run_store import BatchRunStore
    from app.services.crawl_state import CrawlStatus

    session = SimpleNamespace(refresh=AsyncMock())
    store = BatchRunStore(session)
    run = SimpleNamespace(id=32, status_value=CrawlStatus.PENDING)
    locked_run = SimpleNamespace(id=32, status_value=CrawlStatus.PENDING)

    async def _apply(run_id, mutate):
        assert run_id == run.id
        await mutate(session, locked_run)
        run.status_value = locked_run.status_value

    async def _apply_method(self, run_id, mutate):
        await _apply(run_id, mutate)

    log_calls: list[tuple[int, str, str]] = []

    async def _log_method(self, run_id, level, message):
        log_calls.append((run_id, level, message))

    monkeypatch.setattr(BatchRunStore, "apply", _apply_method)
    monkeypatch.setattr(BatchRunStore, "_log", _log_method)

    def _update_run_status(target_run, status):
        target_run.status_value = status

    monkeypatch.setattr("app.services._batch_run_store.update_run_status", _update_run_status)

    await store.start_or_resume_run(run)

    assert locked_run.status_value == CrawlStatus.RUNNING
    assert log_calls == [(run.id, "info", "Pipeline started")]
    session.refresh.assert_awaited_once_with(run)
