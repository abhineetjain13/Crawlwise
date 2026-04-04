from __future__ import annotations

import asyncio
import time
from collections import defaultdict


_LOCKS: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_NEXT_ALLOWED_AT: dict[str, float] = {}


async def wait_for_host_slot(host: str, minimum_interval_ms: int) -> float:
    normalized_host = str(host or "").strip().lower()
    if not normalized_host or minimum_interval_ms <= 0:
        return 0.0
    lock = _LOCKS[normalized_host]
    async with lock:
        now = time.monotonic()
        next_allowed = _NEXT_ALLOWED_AT.get(normalized_host, now)
        delay = max(0.0, next_allowed - now)
        if delay > 0:
            await asyncio.sleep(delay)
        _NEXT_ALLOWED_AT[normalized_host] = time.monotonic() + (minimum_interval_ms / 1000)
        return delay


def reset_pacing_state() -> None:
    """Clear all pacing state.

    WARNING: Not safe to call while pacing operations are in progress.
    Intended for test cleanup only.
    """
    _NEXT_ALLOWED_AT.clear()
    _LOCKS.clear()
