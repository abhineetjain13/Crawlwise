from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_client: Redis | None = None
_redis_disabled_until: float = 0.0
_last_disable_log_at: float = 0.0
_T = TypeVar("_T")
_DISABLE_COOLDOWN_SECONDS = 30.0


def redis_is_enabled() -> bool:
    if not settings.redis_state_enabled:
        return False
    return time.monotonic() >= _redis_disabled_until


def _temporarily_disable_redis(exc: Exception) -> None:
    global _redis_disabled_until, _last_disable_log_at
    now = time.monotonic()
    _redis_disabled_until = now + _DISABLE_COOLDOWN_SECONDS
    if now - _last_disable_log_at >= _DISABLE_COOLDOWN_SECONDS:
        logger.warning(
            "Redis unavailable; disabling shared state for %.0fs: %s",
            _DISABLE_COOLDOWN_SECONDS,
            exc,
        )
        _last_disable_log_at = now


def get_redis_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            health_check_interval=30,
        )
    return _pool


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis(connection_pool=get_redis_pool())
    return _client


async def close_redis() -> None:
    global _client, _pool
    client = _client
    pool = _pool
    _client = None
    _pool = None
    if client is not None:
        await client.aclose()
    if pool is not None:
        await pool.aclose()


async def redis_fail_open(
    operation: Callable[[Redis], Awaitable[_T]],
    *,
    default: _T,
    operation_name: str,
) -> _T:
    if not redis_is_enabled():
        return default
    try:
        return await operation(get_redis())
    except Exception as exc:
        _temporarily_disable_redis(exc)
        logger.warning(
            "Redis operation failed; continuing without shared state: %s",
            operation_name,
            exc_info=False,
        )
        return default


def schedule_fail_open(
    operation: Callable[[Redis], Awaitable[object]],
    *,
    operation_name: str,
) -> None:
    if not redis_is_enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _runner() -> None:
        await redis_fail_open(
            operation,
            default=None,
            operation_name=operation_name,
        )

    loop.create_task(_runner())
