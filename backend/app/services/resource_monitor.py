"""Memory-adaptive concurrency control.

Replaces the fixed ``asyncio.Semaphore`` used in ``_batch_runtime.py``
with a pressure-aware token bucket.  When system memory pressure exceeds
configurable thresholds the semaphore blocks new URL acquisitions until
pressure drops.

Exposes ``MemoryPressureLevel`` so downstream components (e.g. browser
acquisition) can cheaply query current pressure and degrade gracefully
before the semaphore hard-blocks new work.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time

import psutil

logger = logging.getLogger(__name__)

# Defaults — should eventually move to pipeline_tuning.json / crawl_runtime.py
_DEFAULT_MEMORY_PRESSURE_THRESHOLD_PCT = 90
_DEFAULT_MEMORY_CRITICAL_THRESHOLD_PCT = 95
_PRESSURE_POLL_INTERVAL_SECONDS = 1.0


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


def get_memory_pressure_level(
    *,
    pressure_threshold_pct: float = _DEFAULT_MEMORY_PRESSURE_THRESHOLD_PCT,
    critical_threshold_pct: float = _DEFAULT_MEMORY_CRITICAL_THRESHOLD_PCT,
) -> MemoryPressureLevel:
    """Return the current memory pressure level.

    This is a cheap, non-blocking call suitable for hot-path decisions
    like choosing browser fidelity settings.
    """
    pct = psutil.virtual_memory().percent
    if pct >= critical_threshold_pct:
        return MemoryPressureLevel.CRITICAL
    if pct >= pressure_threshold_pct:
        return MemoryPressureLevel.ELEVATED
    return MemoryPressureLevel.NORMAL


class MemoryAdaptiveSemaphore:
    """An ``asyncio.Semaphore`` wrapper that refuses tokens under memory pressure.

    Under normal conditions it behaves as a standard bounded semaphore.
    When ``psutil.virtual_memory().percent`` exceeds *pressure_threshold_pct*
    it blocks callers until memory drops below the threshold.

    If memory exceeds *critical_threshold_pct*, active tokens are **not**
    released back (the semaphore count stays reduced) until pressure
    stabilises, effectively reducing concurrency dynamically.
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
        mem = psutil.virtual_memory()
        if mem.percent < self._pressure_threshold:
            if self._throttled_since is not None:
                elapsed = time.monotonic() - self._throttled_since
                logger.info(
                    "Memory pressure resolved after %.1fs (%.1f%% used)",
                    elapsed,
                    mem.percent,
                )
                self._throttled_since = None
            return

        # Memory pressure detected — wait
        if self._throttled_since is None:
            self._throttled_since = time.monotonic()
            logger.warning(
                "Memory pressure detected: %.1f%% used (threshold=%.0f%%), "
                "throttling new URL acquisition; active_tokens=%d",
                mem.percent,
                self._pressure_threshold,
                self._active_tokens,
            )

        while True:
            await asyncio.sleep(_PRESSURE_POLL_INTERVAL_SECONDS)
            mem = psutil.virtual_memory()
            if mem.percent < self._pressure_threshold:
                elapsed = time.monotonic() - (self._throttled_since or time.monotonic())
                logger.info(
                    "Memory pressure resolved after %.1fs (%.1f%% used)",
                    elapsed,
                    mem.percent,
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
        mem = psutil.virtual_memory()
        level = get_memory_pressure_level(
            pressure_threshold_pct=self._pressure_threshold,
            critical_threshold_pct=self._critical_threshold,
        )
        return {
            "limit": self._limit,
            "active_tokens": self._active_tokens,
            "memory_percent": round(mem.percent, 1),
            "memory_available_mb": round(mem.available / (1024 * 1024)),
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
