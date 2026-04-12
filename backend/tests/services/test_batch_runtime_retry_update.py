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
