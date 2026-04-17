from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.services.config.crawl_runtime import INTERRUPTIBLE_WAIT_POLL_MS


def _poll_ms() -> int:
    return max(INTERRUPTIBLE_WAIT_POLL_MS, 50)


async def cooperative_sleep_ms(
    delay_ms: int,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    remaining_ms = max(0, int(delay_ms or 0))
    poll_ms = _poll_ms()
    while remaining_ms > 0:
        if checkpoint is not None:
            await checkpoint()
        current_ms = min(remaining_ms, poll_ms)
        await asyncio.sleep(current_ms / 1000.0)
        remaining_ms -= current_ms
    if checkpoint is not None:
        await checkpoint()


async def cooperative_sleep_seconds(
    delay_seconds: float,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    await cooperative_sleep_ms(
        int(round(max(0.0, float(delay_seconds or 0.0)) * 1000.0)),
        checkpoint=checkpoint,
    )
