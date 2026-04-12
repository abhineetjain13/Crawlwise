from __future__ import annotations

import asyncio

import pytest

from app.services.url_concurrency import (
    DistributedURLSlotGuard,
    SlotAcquisitionTimeout,
)


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
    acquire_task: asyncio.Task[None] | None = None

    try:
        await first.acquire()
        acquire_task = asyncio.create_task(second.acquire())
        await asyncio.sleep(0.01)

        assert not acquire_task.done()

        await first.release()
        await asyncio.wait_for(acquire_task, timeout=0.1)
    finally:
        await first.release()
        await second.release()
        if acquire_task is not None and not acquire_task.done():
            acquire_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await acquire_task


@pytest.mark.asyncio
async def test_distributed_url_slot_guard_times_out_when_slot_never_frees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.url_concurrency._URL_SLOT_POLL_INTERVAL_SECONDS",
        0.001,
    )
    first = DistributedURLSlotGuard(limit=1)
    second = DistributedURLSlotGuard(limit=1)

    try:
        await first.acquire()
        with pytest.raises(SlotAcquisitionTimeout):
            await second.acquire(acquire_timeout=0.02)
    finally:
        await first.release()
        await second.release()
