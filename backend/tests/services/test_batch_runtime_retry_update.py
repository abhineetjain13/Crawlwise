from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

pipeline_core = types.ModuleType("app.services.pipeline.core")
pipeline_core.STAGE_FETCH = "FETCH"
pipeline_core.STAGE_SAVE = "SAVE"
pipeline_core._log = AsyncMock()
pipeline_core._mark_run_failed = AsyncMock()
pipeline_core._process_single_url = AsyncMock()
pipeline_core._set_stage = AsyncMock()
sys.modules.setdefault("app.services.pipeline.core", pipeline_core)

from app.services._batch_runtime import _retry_run_update


class _FakeLockError(Exception):
    sqlstate = "55P03"

    def __str__(self) -> str:
        return "could not obtain lock on row in relation crawl_runs"


class _FakeResult:
    def __init__(self, run) -> None:
        self._run = run

    def scalar_one_or_none(self):
        return self._run


@pytest.mark.asyncio
async def test_retry_run_update_retries_fast_on_lock_contention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SimpleNamespace(id=17, updated=False)
    session = SimpleNamespace(
        commit=AsyncMock(),
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
    assert session.execute.await_count == 2
    assert session.rollback.await_count == 1
    assert session.commit.await_count == 2
    sleep.assert_awaited_once_with(0.05)


@pytest.mark.asyncio
async def test_retry_run_update_does_not_retry_non_lock_operational_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(
        commit=AsyncMock(),
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

    assert session.execute.await_count == 1
    assert session.rollback.await_count == 1
    assert session.commit.await_count == 1
    sleep.assert_not_awaited()
