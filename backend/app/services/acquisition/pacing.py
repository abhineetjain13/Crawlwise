from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from math import ceil
from uuid import uuid4

from app.core.redis import get_redis, redis_fail_open, redis_failure_total, redis_is_enabled
from app.services.config.crawl_runtime import (
    INTERRUPTIBLE_WAIT_POLL_MS,
    PACING_HOST_CACHE_TTL_SECONDS,
)

_PACING_KEY_PREFIX = "crawl:pacing"
_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""
logger = logging.getLogger(__name__)


def _lock_key(normalized_host: str) -> str:
    return f"{_PACING_KEY_PREFIX}:lock:{normalized_host}"


def _next_allowed_key(normalized_host: str) -> str:
    return f"{_PACING_KEY_PREFIX}:next:{normalized_host}"


def _lock_ttl_seconds(minimum_interval_ms: int) -> int:
    minimum_interval_seconds = max(1, ceil(max(0, minimum_interval_ms) / 1000))
    return max(minimum_interval_seconds * 2 + 5, 10)


async def _release_lock(lock_key: str, token: str) -> None:
    redis = get_redis()
    try:
        await redis.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, token)
    except Exception:
        logger.warning("Failed to release pacing lock for %s", lock_key, exc_info=True)


async def _cooperative_delay(
    delay_seconds: float,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    remaining = max(0.0, float(delay_seconds or 0.0))
    poll_seconds = max(INTERRUPTIBLE_WAIT_POLL_MS, 50) / 1000.0
    while remaining > 0:
        if checkpoint is not None:
            await checkpoint()
        current_sleep = min(remaining, poll_seconds)
        await asyncio.sleep(current_sleep)
        remaining -= current_sleep
    if checkpoint is not None:
        await checkpoint()


async def wait_for_host_slot(
    host: str,
    minimum_interval_ms: int,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> float:
    normalized_host = str(host or "").strip().lower()
    if not normalized_host or minimum_interval_ms <= 0:
        return 0.0
    ttl_seconds = max(1, int(PACING_HOST_CACHE_TTL_SECONDS or 0))
    lock_key = _lock_key(normalized_host)
    next_key = _next_allowed_key(normalized_host)
    interval_seconds = minimum_interval_ms / 1000.0

    if not redis_is_enabled():
        await _cooperative_delay(interval_seconds, checkpoint=checkpoint)
        return interval_seconds

    async def _wait(redis) -> float:
        total_delay = 0.0
        while True:
            if checkpoint is not None:
                await checkpoint()
            token = uuid4().hex
            lock_ttl_seconds = _lock_ttl_seconds(minimum_interval_ms)
            acquired = await redis.set(
                lock_key,
                token,
                nx=True,
                ex=lock_ttl_seconds,
            )
            if not acquired:
                await _cooperative_delay(
                    max(INTERRUPTIBLE_WAIT_POLL_MS, 50) / 1000.0,
                    checkpoint=checkpoint,
                )
                continue
            try:
                now = time.time()
                raw_next_allowed = await redis.get(next_key)
                try:
                    next_allowed = float(raw_next_allowed) if raw_next_allowed is not None else now
                except (TypeError, ValueError):
                    next_allowed = now
                delay = max(0.0, next_allowed - now)
                if delay > 0:
                    max_delay = max(0.0, lock_ttl_seconds - 1.0)
                    sleep_delay = min(delay, max_delay)
                    await _cooperative_delay(sleep_delay, checkpoint=checkpoint)
                    total_delay += sleep_delay
                    if await redis.get(lock_key) != token:
                        continue
                    if delay > sleep_delay:
                        continue
                current_time = time.time()
                await redis.set(
                    next_key,
                    f"{current_time + interval_seconds:.6f}",
                    ex=ttl_seconds,
                )
                return total_delay
            finally:
                await _release_lock(lock_key, token)

    failure_count_before = redis_failure_total()
    result = await redis_fail_open(
        _wait,
        default=interval_seconds,
        operation_name=f"wait_for_host_slot:{normalized_host}",
    )
    if redis_failure_total() != failure_count_before:
        await _cooperative_delay(interval_seconds, checkpoint=checkpoint)
        return interval_seconds
    return result


async def reset_pacing_state() -> None:
    async def _reset(redis) -> None:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match=f"{_PACING_KEY_PREFIX}:*",
                count=200,
            )
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                return

    await redis_fail_open(
        _reset,
        default=None,
        operation_name="reset_pacing_state",
    )
