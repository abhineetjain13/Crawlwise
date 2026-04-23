from __future__ import annotations

import asyncio

import pytest

from app.core import redis as redis_module


@pytest.mark.asyncio
async def test_schedule_fail_open_tracks_background_tasks_until_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    finished = asyncio.Event()
    release = asyncio.Event()

    async def _fake_redis_fail_open(operation, *, default, operation_name):
        del operation, default, operation_name
        started.set()
        await release.wait()
        finished.set()
        return None

    redis_module._BACKGROUND_TASKS.clear()
    monkeypatch.setattr(redis_module, "redis_is_enabled", lambda: True)
    monkeypatch.setattr(redis_module, "redis_fail_open", _fake_redis_fail_open)

    redis_module.schedule_fail_open(lambda _: asyncio.sleep(0), operation_name="test")

    await asyncio.wait_for(started.wait(), timeout=1)
    assert len(redis_module._BACKGROUND_TASKS) == 1

    release.set()
    await asyncio.wait_for(finished.wait(), timeout=1)
    await asyncio.sleep(0)

    assert redis_module._BACKGROUND_TASKS == set()
