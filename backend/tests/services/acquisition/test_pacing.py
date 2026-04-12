from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.acquisition import pacing


@pytest.mark.asyncio
async def test_wait_for_host_slot_enforces_delay_when_redis_already_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delay = AsyncMock()
    monkeypatch.setattr(pacing, "redis_is_enabled", lambda: False)
    monkeypatch.setattr(pacing, "_cooperative_delay", delay)

    waited = await pacing.wait_for_host_slot("example.com", 250)

    assert waited == 0.25
    delay.assert_awaited_once_with(0.25, checkpoint=None)


@pytest.mark.asyncio
async def test_wait_for_host_slot_enforces_delay_only_when_current_call_failed_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delay = AsyncMock()
    failure_counts = iter([3, 4])

    monkeypatch.setattr(pacing, "redis_is_enabled", lambda: True)
    monkeypatch.setattr(pacing, "redis_failure_total", lambda: next(failure_counts))
    monkeypatch.setattr(pacing, "_cooperative_delay", delay)

    async def _fake_redis_fail_open(operation, *, default, operation_name):
        return default

    monkeypatch.setattr(pacing, "redis_fail_open", _fake_redis_fail_open)

    waited = await pacing.wait_for_host_slot("example.com", 400)

    assert waited == 0.4
    delay.assert_awaited_once_with(0.4, checkpoint=None)


@pytest.mark.asyncio
async def test_wait_for_host_slot_does_not_double_sleep_when_delay_matches_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delay = AsyncMock()
    failure_counts = iter([7, 7])

    monkeypatch.setattr(pacing, "redis_is_enabled", lambda: True)
    monkeypatch.setattr(pacing, "redis_failure_total", lambda: next(failure_counts))
    monkeypatch.setattr(pacing, "_cooperative_delay", delay)

    async def _fake_redis_fail_open(operation, *, default, operation_name):
        return default

    monkeypatch.setattr(pacing, "redis_fail_open", _fake_redis_fail_open)

    waited = await pacing.wait_for_host_slot("example.com", 400)

    assert waited == 0.4
    delay.assert_not_awaited()
