from __future__ import annotations

import asyncio
import time

from app.services.config.crawl_runtime import (
    PROXY_FAILURE_BACKOFF_MAX_EXPONENT,
    PROXY_FAILURE_COOLDOWN_BASE_MS,
    PROXY_FAILURE_COOLDOWN_MAX_MS,
    PROXY_FAILURE_STATE_MAX_ENTRIES,
    PROXY_FAILURE_STATE_TTL_SECONDS,
)

_PROXY_FAILURE_STATE: dict[str, tuple[int, float, float]] = {}
_PROXY_FAILURE_STATE_LOCK = asyncio.Lock()


class ProxyRotator:
    """Round-robin proxy rotator."""

    def __init__(self, proxies: list[str] | None = None):
        self._proxies = [
            proxy.strip() for proxy in (proxies or []) if proxy and proxy.strip()
        ]
        self._index = 0

    def next(self) -> str | None:
        if not self._proxies:
            return None
        proxy = self._proxies[self._index % len(self._proxies)]
        self._index += 1
        return proxy

    async def cycle_once(self, *, use_cooldown: bool = True) -> list[str]:
        if not self._proxies:
            return []
        candidates = list(self._proxies)
        if not use_cooldown:
            return [proxy for proxy in candidates if proxy]
        available: list[str] = []
        for proxy in candidates:
            if proxy and await is_proxy_available(proxy):
                available.append(proxy)
        return available


def proxy_backoff_seconds(failure_count: int) -> float:
    if failure_count <= 0:
        return 0.0
    exponent = min(failure_count - 1, PROXY_FAILURE_BACKOFF_MAX_EXPONENT)
    delay_ms = PROXY_FAILURE_COOLDOWN_BASE_MS * (2**exponent)
    bounded_ms = min(delay_ms, PROXY_FAILURE_COOLDOWN_MAX_MS)
    return max(0.0, bounded_ms / 1000)


def evict_stale_proxy_entries(now: float) -> None:
    stale_cutoff = now - PROXY_FAILURE_STATE_TTL_SECONDS
    stale_keys = [
        key
        for key, (
            _failures,
            last_failure_time,
            _cooldown_until,
        ) in _PROXY_FAILURE_STATE.items()
        if last_failure_time <= stale_cutoff
    ]
    for key in stale_keys:
        _PROXY_FAILURE_STATE.pop(key, None)

    if len(_PROXY_FAILURE_STATE) <= PROXY_FAILURE_STATE_MAX_ENTRIES:
        return
    overflow = len(_PROXY_FAILURE_STATE) - PROXY_FAILURE_STATE_MAX_ENTRIES
    for key, _state in sorted(
        _PROXY_FAILURE_STATE.items(), key=lambda item: item[1][1]
    )[:overflow]:
        _PROXY_FAILURE_STATE.pop(key, None)


async def is_proxy_available(proxy: str) -> bool:
    key = str(proxy or "").strip()
    if not key:
        return True
    async with _PROXY_FAILURE_STATE_LOCK:
        now = time.monotonic()
        evict_stale_proxy_entries(now)
        state = _PROXY_FAILURE_STATE.get(key)
        if state is None:
            return True
        _, _, cooldown_until = state
        return now >= cooldown_until


async def mark_proxy_failed(proxy: str) -> None:
    key = str(proxy or "").strip()
    if not key:
        return
    async with _PROXY_FAILURE_STATE_LOCK:
        now = time.monotonic()
        evict_stale_proxy_entries(now)
        previous_failures = int((_PROXY_FAILURE_STATE.get(key) or (0, 0.0, 0.0))[0])
        failures = max(1, previous_failures + 1)
        cooldown_until = now + proxy_backoff_seconds(failures)
        _PROXY_FAILURE_STATE[key] = (failures, now, cooldown_until)
        evict_stale_proxy_entries(now)


async def mark_proxy_succeeded(proxy: str) -> None:
    key = str(proxy or "").strip()
    if not key:
        return
    async with _PROXY_FAILURE_STATE_LOCK:
        now = time.monotonic()
        _PROXY_FAILURE_STATE.pop(key, None)
        evict_stale_proxy_entries(now)
