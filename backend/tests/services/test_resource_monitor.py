from __future__ import annotations
from unittest.mock import patch

import pytest

from app.services.resource_monitor import (
    MemoryAdaptiveSemaphore,
    MemoryPressureSample,
    MemoryPressureSource,
    _cgroup_memory_percent,
)


def test_cgroup_v1_unlimited_memory_limit_falls_back_to_none() -> None:
    values = {
        "/sys/fs/cgroup/memory.max": None,
        "/sys/fs/cgroup/memory.limit_in_bytes": str(0x7FFFFFFFFFFFF000),
        "/sys/fs/cgroup/memory.usage_in_bytes": "1024",
    }

    with patch(
        "app.services.resource_monitor._read_cgroup_value",
        side_effect=lambda path: values.get(str(path)),
    ):
        assert _cgroup_memory_percent() is None


@pytest.mark.asyncio
async def test_memory_adaptive_semaphore_does_not_throttle_on_host_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semaphore = MemoryAdaptiveSemaphore(limit=1, pressure_threshold_pct=80)
    sleep_mock = patch("app.services.resource_monitor.asyncio.sleep")
    with sleep_mock as mocked_sleep:
        monkeypatch.setattr(
            "app.services.resource_monitor._memory_pressure_sample",
            lambda: MemoryPressureSample(
                percent=92.0,
                source=MemoryPressureSource.HOST_FALLBACK,
                available_mb=256,
            ),
        )
        await semaphore.acquire()
        semaphore.release()

    mocked_sleep.assert_not_called()


def test_memory_adaptive_semaphore_snapshot_exposes_memory_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semaphore = MemoryAdaptiveSemaphore(limit=2, pressure_threshold_pct=80)
    monkeypatch.setattr(
        "app.services.resource_monitor._memory_pressure_sample",
        lambda: MemoryPressureSample(
            percent=67.5,
            source=MemoryPressureSource.HOST_FALLBACK,
            available_mb=512,
        ),
    )

    snapshot = semaphore.snapshot()

    assert snapshot["memory_percent"] == 67.5
    assert snapshot["memory_available_mb"] == 512
    assert snapshot["memory_source"] == "host_fallback"
    assert snapshot["memory_cgroup_limited"] is False
