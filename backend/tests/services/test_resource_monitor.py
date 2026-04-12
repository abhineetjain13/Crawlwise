from __future__ import annotations

from unittest.mock import patch

from app.services.resource_monitor import _cgroup_memory_percent


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
