# Host memory for acquisition retry policy.
from __future__ import annotations

import time
from urllib.parse import urlparse

from app.core.redis import redis_fail_open
from app.services.config.crawl_runtime import (
    STEALTH_MIN_TTL_HOURS,
    STEALTH_PREFER_TTL_HOURS,
)

_HOST_MEMORY_KEY_PREFIX = "crawl:host-memory:stealth"


def host_key(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.netloc or parsed.path or "").lower().strip()


def _redis_key(url: str) -> str:
    return f"{_HOST_MEMORY_KEY_PREFIX}:{host_key(url)}"


async def host_prefers_stealth(url: str) -> bool:
    key = host_key(url)
    if not key:
        return False

    async def _lookup(redis) -> bool:
        return bool(await redis.exists(_redis_key(url)))

    return await redis_fail_open(
        _lookup,
        default=False,
        operation_name=f"host_prefers_stealth:{key}",
    )


async def remember_stealth_host(
    url: str, ttl_hours: int | None = None, reason: str = "blocked"
) -> None:
    key = host_key(url)
    if not key:
        return
    ttl = ttl_hours if ttl_hours is not None else STEALTH_PREFER_TTL_HOURS
    ttl = max(STEALTH_MIN_TTL_HOURS, int(ttl))
    expires_at = time.time() + ttl * 3600

    async def _remember(redis) -> None:
        await redis.hset(
            _redis_key(url),
            mapping={
                "reason": str(reason or "blocked").strip() or "blocked",
                "preferred_stealth_until": f"{expires_at:.6f}",
            },
        )
        await redis.expire(_redis_key(url), ttl * 3600)

    await redis_fail_open(
        _remember,
        default=None,
        operation_name=f"remember_stealth_host:{key}",
    )


async def clear_stealth_host(url: str) -> None:
    key = host_key(url)
    if not key:
        return

    await redis_fail_open(
        lambda redis: redis.delete(_redis_key(url)),
        default=0,
        operation_name=f"clear_stealth_host:{key}",
    )


async def reset_host_memory() -> None:
    async def _reset(redis) -> None:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match=f"{_HOST_MEMORY_KEY_PREFIX}:*",
                count=200,
            )
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                return

    await redis_fail_open(
        _reset,
        default=None,
        operation_name="reset_host_memory",
    )


async def snapshot_host_memory() -> dict[str, dict[str, object]]:
    async def _snapshot(redis) -> dict[str, dict[str, object]]:
        results: dict[str, dict[str, object]] = {}
        async for key in redis.scan_iter(match=f"{_HOST_MEMORY_KEY_PREFIX}:*"):
            payload = await redis.hgetall(key)
            host = str(key).removeprefix(f"{_HOST_MEMORY_KEY_PREFIX}:")
            expires_at = _as_float(payload.get("preferred_stealth_until"))
            if not host or expires_at <= time.time():
                continue
            results[host] = {
                "reason": str(payload.get("reason") or "blocked"),
                "preferred_stealth_until": expires_at,
            }
        return results

    return await redis_fail_open(
        _snapshot,
        default={},
        operation_name="snapshot_host_memory",
    )


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
