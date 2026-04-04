from __future__ import annotations

import asyncio
import time
from collections import OrderedDict

from app.services.pipeline_config import PACING_HOST_CACHE_MAX_ENTRIES, PACING_HOST_CACHE_TTL_SECONDS


_LOCKS: OrderedDict[str, asyncio.Lock] = OrderedDict()
_NEXT_ALLOWED_AT: dict[str, float] = {}
_LAST_TOUCHED_AT: dict[str, float] = {}


def _touch_host(normalized_host: str, now: float) -> None:
    _LAST_TOUCHED_AT[normalized_host] = now
    if normalized_host in _LOCKS:
        _LOCKS.move_to_end(normalized_host)


def _prune_state(now: float) -> None:
    ttl_seconds = max(0, PACING_HOST_CACHE_TTL_SECONDS)
    if ttl_seconds > 0:
        for host in list(_LOCKS.keys()):
            lock = _LOCKS.get(host)
            touched_at = _LAST_TOUCHED_AT.get(host, now)
            if lock is None or lock.locked() or now - touched_at <= ttl_seconds:
                continue
            _LOCKS.pop(host, None)
            _NEXT_ALLOWED_AT.pop(host, None)
            _LAST_TOUCHED_AT.pop(host, None)
    max_entries = max(1, PACING_HOST_CACHE_MAX_ENTRIES)
    while len(_LOCKS) > max_entries:
        evicted = False
        for host, lock in list(_LOCKS.items()):
            if lock.locked():
                continue
            _LOCKS.pop(host, None)
            _NEXT_ALLOWED_AT.pop(host, None)
            _LAST_TOUCHED_AT.pop(host, None)
            evicted = True
            break
        if not evicted:
            break


def _get_lock(normalized_host: str, now: float) -> asyncio.Lock:
    _prune_state(now)
    lock = _LOCKS.get(normalized_host)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[normalized_host] = lock
    _touch_host(normalized_host, now)
    return lock


def _get_next_allowed_at(normalized_host: str, now: float) -> float:
    _touch_host(normalized_host, now)
    return _NEXT_ALLOWED_AT.get(normalized_host, now)


def _set_next_allowed_at(normalized_host: str, value: float, now: float) -> None:
    _NEXT_ALLOWED_AT[normalized_host] = value
    _touch_host(normalized_host, now)


async def wait_for_host_slot(host: str, minimum_interval_ms: int) -> float:
    normalized_host = str(host or "").strip().lower()
    if not normalized_host or minimum_interval_ms <= 0:
        return 0.0
    while True:
        now = time.monotonic()
        lock = _get_lock(normalized_host, now)
        async with lock:
            current_lock = _get_lock(normalized_host, time.monotonic())
            if current_lock is not lock:
                continue
            now = time.monotonic()
            next_allowed = _get_next_allowed_at(normalized_host, now)
            delay = max(0.0, next_allowed - now)
            if delay > 0:
                await asyncio.sleep(delay)
            current_time = time.monotonic()
            _set_next_allowed_at(normalized_host, current_time + (minimum_interval_ms / 1000), current_time)
            return delay


def reset_pacing_state() -> None:
    """Clear all pacing state.

    WARNING: Not safe to call while pacing operations are in progress.
    Intended for test cleanup only.
    """
    _NEXT_ALLOWED_AT.clear()
    _LAST_TOUCHED_AT.clear()
    _LOCKS.clear()
