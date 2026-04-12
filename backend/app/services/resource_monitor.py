"""Memory-adaptive concurrency control.

Replaces the fixed ``asyncio.Semaphore`` used in ``_batch_runtime.py``
with a pressure-aware token bucket. When cgroup-backed memory pressure
exceeds configurable thresholds the semaphore blocks new URL acquisitions
until pressure drops.

Exposes ``MemoryPressureLevel`` so downstream components (e.g. browser
acquisition) can cheaply query current pressure and degrade gracefully
before the semaphore hard-blocks new work.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

# Defaults — should eventually move to pipeline_tuning.json / crawl_runtime.py
_DEFAULT_MEMORY_PRESSURE_THRESHOLD_PCT = 90
_DEFAULT_MEMORY_CRITICAL_THRESHOLD_PCT = 95
_PRESSURE_POLL_INTERVAL_SECONDS = 1.0
_CGROUP_V2_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V2_MEMORY_CURRENT = Path("/sys/fs/cgroup/memory.current")
_CGROUP_V1_MEMORY_LIMIT = Path("/sys/fs/cgroup/memory.limit_in_bytes")
_CGROUP_V1_MEMORY_USAGE = Path("/sys/fs/cgroup/memory.usage_in_bytes")
_CGROUP_V1_UNLIMITED_MIN = 1 << 60


class MemoryPressureLevel(enum.Enum):
    """Discrete pressure bands for downstream consumers.

    * ``NORMAL``   — below pressure threshold; full-fidelity operations.
    * ``ELEVATED`` — between pressure and critical thresholds; expensive
      operations (browser rendering) should degrade to lighter settings.
    * ``CRITICAL`` — above critical threshold; the semaphore will hard-block
      new work; anything already in-flight should shed load aggressively.
    """

    NORMAL = "normal"
    ELEVATED = "elevated"
    CRITICAL = "critical"


class MemoryPressureSource(enum.Enum):
    """Origin of the memory pressure reading used by adaptive throttling."""

    CGROUP = "cgroup"
    HOST_FALLBACK = "host_fallback"


@dataclass(frozen=True)
class MemoryPressureSample:
    percent: float
    source: MemoryPressureSource
    available_mb: int | None = None


def _read_cgroup_value(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _cgroup_memory_percent() -> float | None:
    for limit_path, usage_path in (
        (_CGROUP_V2_MEMORY_MAX, _CGROUP_V2_MEMORY_CURRENT),
        (_CGROUP_V1_MEMORY_LIMIT, _CGROUP_V1_MEMORY_USAGE),
    ):
        limit_raw = _read_cgroup_value(limit_path)
        if limit_raw is None:
            continue
        if limit_raw == "max":
            return None
        try:
            limit_bytes = int(limit_raw)
        except ValueError:
            continue
        if limit_path == _CGROUP_V1_MEMORY_LIMIT and limit_bytes >= _CGROUP_V1_UNLIMITED_MIN:
            continue
        if limit_bytes <= 0:
            continue
        usage_raw = _read_cgroup_value(usage_path)
        if usage_raw is None:
            continue
        try:
            usage_bytes = int(usage_raw)
        except ValueError:
            continue
        usage_bytes = max(0, usage_bytes)
        return min(100.0, max(0.0, (usage_bytes / limit_bytes) * 100.0))
    return None


def _memory_pressure_sample() -> MemoryPressureSample:
    cgroup_percent = _cgroup_memory_percent()
    if cgroup_percent is not None:
        return MemoryPressureSample(
            percent=cgroup_percent,
            source=MemoryPressureSource.CGROUP,
        )

    mem = psutil.virtual_memory()
    return MemoryPressureSample(
        percent=float(mem.percent),
        source=MemoryPressureSource.HOST_FALLBACK,
        available_mb=round(mem.available / (1024 * 1024)),
    )


def get_memory_pressure_level(
    *,
    pressure_threshold_pct: float = _DEFAULT_MEMORY_PRESSURE_THRESHOLD_PCT,
    critical_threshold_pct: float = _DEFAULT_MEMORY_CRITICAL_THRESHOLD_PCT,
) -> MemoryPressureLevel:
    """Return the current memory pressure level.

    This is a cheap, non-blocking call suitable for hot-path decisions
    like choosing browser fidelity settings.
    """
    pct = _memory_pressure_sample().percent
    if pct >= critical_threshold_pct:
        return MemoryPressureLevel.CRITICAL
    if pct >= pressure_threshold_pct:
        return MemoryPressureLevel.ELEVATED
    return MemoryPressureLevel.NORMAL


def get_memory_pressure_percent() -> float:
    """Return current memory pressure percent using the same source as pressure levels."""
    return _memory_pressure_sample().percent


class MemoryAdaptiveSemaphore:
    """An ``asyncio.Semaphore`` wrapper that refuses tokens under memory pressure.

    Under normal conditions it behaves as a standard bounded semaphore.
    When cgroup-backed memory pressure exceeds *pressure_threshold_pct*
    it blocks callers until memory drops below the threshold.

    If memory exceeds *critical_threshold_pct*, active tokens are **not**
    released back (the semaphore count stays reduced) until pressure
    stabilises, effectively reducing concurrency dynamically.

    When cgroup limits are unavailable, host-wide memory pressure remains
    visible for degraded-mode callers, but the semaphore does not hard-block
    based on that fallback signal.
    """

    def __init__(
        self,
        limit: int,
        *,
        pressure_threshold_pct: float = _DEFAULT_MEMORY_PRESSURE_THRESHOLD_PCT,
        critical_threshold_pct: float = _DEFAULT_MEMORY_CRITICAL_THRESHOLD_PCT,
    ) -> None:
        self._inner = asyncio.Semaphore(max(1, limit))
        self._limit = max(1, limit)
        self._pressure_threshold = pressure_threshold_pct
        self._critical_threshold = critical_threshold_pct
        self._active_tokens = 0
        self._throttled_since: float | None = None
        self._host_fallback_warning_logged = False

    # -- Semaphore interface --

    async def acquire(self) -> None:
        """Acquire a concurrency token, blocking if under memory pressure."""
        await self._wait_for_memory()
        await self._inner.acquire()
        self._active_tokens += 1

    def release(self) -> None:
        self._active_tokens = max(0, self._active_tokens - 1)
        self._inner.release()

    async def __aenter__(self) -> "MemoryAdaptiveSemaphore":
        await self.acquire()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.release()

    # -- Pressure logic --

    async def _wait_for_memory(self) -> None:
        """Block until memory pressure is below threshold."""
        sample = _memory_pressure_sample()
        memory_percent = sample.percent
        if sample.source is not MemoryPressureSource.CGROUP:
            if memory_percent >= self._pressure_threshold and not self._host_fallback_warning_logged:
                logger.warning(
                    "MemoryAdaptiveSemaphore observed %.1f%% host memory usage without a cgroup limit; "
                    "skipping hard throttling because container memory limits are unknown",
                    memory_percent,
                )
                self._host_fallback_warning_logged = True
            if memory_percent < self._pressure_threshold:
                self._host_fallback_warning_logged = False
            self._throttled_since = None
            return

        if memory_percent < self._pressure_threshold:
            if self._throttled_since is not None:
                elapsed = time.monotonic() - self._throttled_since
                logger.info(
                    "Memory pressure resolved after %.1fs (%.1f%% used)",
                    elapsed,
                    memory_percent,
                )
                self._throttled_since = None
            return

        # Memory pressure detected — wait
        if self._throttled_since is None:
            self._throttled_since = time.monotonic()
            logger.warning(
                "Memory pressure detected: %.1f%% used (threshold=%.0f%%), "
                "throttling new URL acquisition; active_tokens=%d",
                memory_percent,
                self._pressure_threshold,
                self._active_tokens,
            )

        while True:
            await asyncio.sleep(_PRESSURE_POLL_INTERVAL_SECONDS)
            memory_percent = get_memory_pressure_percent()
            if memory_percent < self._pressure_threshold:
                elapsed = time.monotonic() - (self._throttled_since or time.monotonic())
                logger.info(
                    "Memory pressure resolved after %.1fs (%.1f%% used)",
                    elapsed,
                    memory_percent,
                )
                self._throttled_since = None
                return

    # -- Pressure query --

    @property
    def pressure_level(self) -> MemoryPressureLevel:
        """Current pressure level using this semaphore's thresholds."""
        return get_memory_pressure_level(
            pressure_threshold_pct=self._pressure_threshold,
            critical_threshold_pct=self._critical_threshold,
        )

    # -- Observability --

    def snapshot(self) -> dict[str, object]:
        sample = _memory_pressure_sample()
        level = get_memory_pressure_level(
            pressure_threshold_pct=self._pressure_threshold,
            critical_threshold_pct=self._critical_threshold,
        )
        return {
            "limit": self._limit,
            "active_tokens": self._active_tokens,
            "memory_percent": round(sample.percent, 1),
            "memory_available_mb": sample.available_mb,
            "memory_source": sample.source.value,
            "memory_cgroup_limited": sample.source is MemoryPressureSource.CGROUP,
            "pressure_threshold_pct": self._pressure_threshold,
            "critical_threshold_pct": self._critical_threshold,
            "pressure_level": level.value,
            "throttled": self._throttled_since is not None,
            "throttled_duration_s": (
                round(time.monotonic() - self._throttled_since, 1)
                if self._throttled_since is not None
                else 0
            ),
        }
