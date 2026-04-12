from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from app.core.redis import get_redis, redis_is_enabled
from app.services.config.crawl_runtime import MAX_URL_PROCESS_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

_URL_SLOT_KEY_PREFIX = "crawl:url-slot"
_URL_SLOT_POLL_INTERVAL_SECONDS = 0.1
_URL_SLOT_TTL_SECONDS = max(30, int(MAX_URL_PROCESS_TIMEOUT_SECONDS) + 30)
_URL_SLOT_ACQUIRE_TIMEOUT_SECONDS = float(_URL_SLOT_TTL_SECONDS)
_RELEASE_SLOT_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""
_redis_disabled_warning_logged = False


def _slot_key(limit: int, slot_index: int) -> str:
    return f"{_URL_SLOT_KEY_PREFIX}:{limit}:{slot_index}"


class DistributedURLSlotGuard:
    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._slot_key: str | None = None
        self._token: str | None = None

    async def acquire(self, *, acquire_timeout: float = _URL_SLOT_ACQUIRE_TIMEOUT_SECONDS) -> None:
        global _redis_disabled_warning_logged
        if not redis_is_enabled():
            if not _redis_disabled_warning_logged:
                logger.warning(
                    "Redis shared state is disabled; URL concurrency remains process-local"
                )
                _redis_disabled_warning_logged = True
            return
        _redis_disabled_warning_logged = False
        redis = get_redis()
        deadline = asyncio.get_running_loop().time() + max(0.0, float(acquire_timeout))
        while True:
            for slot_index in range(self._limit):
                token = uuid4().hex
                slot_key = _slot_key(self._limit, slot_index)
                acquired = await redis.set(
                    slot_key,
                    token,
                    nx=True,
                    ex=_URL_SLOT_TTL_SECONDS,
                )
                if acquired:
                    self._slot_key = slot_key
                    self._token = token
                    return
            if asyncio.get_running_loop().time() >= deadline:
                raise SlotAcquisitionTimeout(
                    f"Timed out acquiring distributed URL slot for limit={self._limit} after {acquire_timeout:.2f}s"
                )
            await asyncio.sleep(_URL_SLOT_POLL_INTERVAL_SECONDS)

    async def release(self) -> None:
        if not self._slot_key or not self._token or not redis_is_enabled():
            self._slot_key = None
            self._token = None
            return
        try:
            await get_redis().eval(
                _RELEASE_SLOT_SCRIPT,
                1,
                self._slot_key,
                self._token,
            )
        except Exception:
            logger.warning(
                "Failed to release distributed URL slot %s",
                self._slot_key,
                exc_info=True,
            )
        finally:
            self._slot_key = None
            self._token = None

    async def __aenter__(self) -> "DistributedURLSlotGuard":
        await self.acquire()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.release()


class SlotAcquisitionTimeout(TimeoutError):
    """Raised when a distributed URL slot cannot be acquired in time."""
