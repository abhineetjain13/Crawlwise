from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

from app.services.config.runtime_settings import crawler_runtime_settings

_HOST_NEXT_ALLOWED_AT: dict[str, float] = {}
_HOST_BROWSER_FIRST_UNTIL: dict[str, float] = {}
_HOST_PACING_LOCK = asyncio.Lock()


def _normalized_host(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        split = urlsplit(text)
        return str(split.netloc or split.hostname or "").strip().lower()
    return text


async def wait_for_host_slot(_url: str) -> None:
    host = _normalized_host(_url)
    if not host:
        return
    min_interval_ms = _host_interval_ms(protected=False)
    ttl_seconds = max(
        1,
        int(crawler_runtime_settings.pacing_host_cache_ttl_seconds),
    )
    now = time.monotonic()
    async with _HOST_PACING_LOCK:
        _prune_expired_hosts(now=now, ttl_seconds=ttl_seconds)
        next_allowed_at = _HOST_NEXT_ALLOWED_AT.get(host, now)
        wait_seconds = max(0.0, next_allowed_at - now)
        _HOST_NEXT_ALLOWED_AT[host] = max(now, next_allowed_at) + (
            min_interval_ms / 1000.0
        )
        _enforce_host_cache_limit()
    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)


async def reset_pacing_state() -> None:
    async with _HOST_PACING_LOCK:
        _HOST_NEXT_ALLOWED_AT.clear()
        _HOST_BROWSER_FIRST_UNTIL.clear()


async def mark_browser_first_host(_url: str) -> None:
    host = _normalized_host(_url)
    if not host:
        return
    ttl_seconds = max(
        1,
        int(crawler_runtime_settings.pacing_host_cache_ttl_seconds),
    )
    now = time.monotonic()
    async with _HOST_PACING_LOCK:
        _prune_expired_hosts(now=now, ttl_seconds=ttl_seconds)
        _HOST_BROWSER_FIRST_UNTIL[host] = now + ttl_seconds
        _enforce_host_cache_limit()


async def should_prefer_browser_for_host(_url: str) -> bool:
    host = _normalized_host(_url)
    if not host:
        return False
    ttl_seconds = max(
        1,
        int(crawler_runtime_settings.pacing_host_cache_ttl_seconds),
    )
    now = time.monotonic()
    async with _HOST_PACING_LOCK:
        _prune_expired_hosts(now=now, ttl_seconds=ttl_seconds)
        return _HOST_BROWSER_FIRST_UNTIL.get(host, 0.0) > now


async def apply_protected_host_backoff(_url: str) -> None:
    host = _normalized_host(_url)
    if not host:
        return
    ttl_seconds = max(
        1,
        int(crawler_runtime_settings.pacing_host_cache_ttl_seconds),
    )
    now = time.monotonic()
    protected_interval_seconds = _host_interval_ms(protected=True) / 1000.0
    async with _HOST_PACING_LOCK:
        _prune_expired_hosts(now=now, ttl_seconds=ttl_seconds)
        next_allowed_at = _HOST_NEXT_ALLOWED_AT.get(host, now)
        _HOST_NEXT_ALLOWED_AT[host] = max(next_allowed_at, now + protected_interval_seconds)
        _enforce_host_cache_limit()


def _host_interval_ms(*, protected: bool) -> int:
    base_interval_ms = max(
        0,
        int(crawler_runtime_settings.acquire_host_min_interval_ms),
    )
    if not protected:
        return base_interval_ms
    return max(
        base_interval_ms,
        int(crawler_runtime_settings.protected_host_additional_interval_ms),
    )


def _prune_expired_hosts(*, now: float, ttl_seconds: int) -> None:
    # allowed_at is a future timestamp; an entry is stale when the scheduled
    # window *plus* the TTL has elapsed (i.e., the host hasn't been paced for
    # longer than ttl_seconds since its last allowed_at).
    expired_hosts = [
        host
        for host, allowed_at in _HOST_NEXT_ALLOWED_AT.items()
        if now > allowed_at + ttl_seconds
    ]
    for host in expired_hosts:
        _HOST_NEXT_ALLOWED_AT.pop(host, None)
    expired_browser_hosts = [
        host
        for host, browser_first_until in _HOST_BROWSER_FIRST_UNTIL.items()
        if now > browser_first_until
    ]
    for host in expired_browser_hosts:
        _HOST_BROWSER_FIRST_UNTIL.pop(host, None)


def _enforce_host_cache_limit() -> None:
    max_entries = max(
        1,
        int(crawler_runtime_settings.pacing_host_cache_max_entries),
    )
    _trim_host_cache(_HOST_NEXT_ALLOWED_AT, max_entries=max_entries)
    _trim_host_cache(_HOST_BROWSER_FIRST_UNTIL, max_entries=max_entries)


def _trim_host_cache(cache: dict[str, float], *, max_entries: int) -> None:
    overflow = len(cache) - max_entries
    if overflow <= 0:
        return
    for host, _ in sorted(cache.items(), key=lambda item: item[1])[:overflow]:
        cache.pop(host, None)
