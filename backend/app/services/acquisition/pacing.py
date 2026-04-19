from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

from app.services.config.runtime_settings import crawler_runtime_settings

_HOST_NEXT_ALLOWED_AT: dict[str, float] = {}
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
    min_interval_ms = max(
        0,
        int(crawler_runtime_settings.acquire_host_min_interval_ms),
    )
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


def _enforce_host_cache_limit() -> None:
    max_entries = max(
        1,
        int(crawler_runtime_settings.pacing_host_cache_max_entries),
    )
    overflow = len(_HOST_NEXT_ALLOWED_AT) - max_entries
    if overflow <= 0:
        return
    for host, _ in sorted(_HOST_NEXT_ALLOWED_AT.items(), key=lambda item: item[1])[
        :overflow
    ]:
        _HOST_NEXT_ALLOWED_AT.pop(host, None)
