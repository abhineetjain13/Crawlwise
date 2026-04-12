from __future__ import annotations

import asyncio

import pytest

from app.services.url_concurrency import DistributedURLSlotGuard


@pytest.mark.asyncio
async def test_distributed_url_slot_guard_coordinates_across_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.url_concurrency._URL_SLOT_POLL_INTERVAL_SECONDS",
        0.001,
    )
    first = DistributedURLSlotGuard(limit=1)
    second = DistributedURLSlotGuard(limit=1)

    await first.acquire()
    acquire_task = asyncio.create_task(second.acquire())
    await asyncio.sleep(0.01)

    assert not acquire_task.done()

    await first.release()
    await asyncio.wait_for(acquire_task, timeout=0.1)
    await second.release()
