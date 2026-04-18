from __future__ import annotations

import asyncio

from app.services.crawl_engine import (
    browser_runtime_snapshot,
    shutdown_browser_runtime,
)


def browser_pool_snapshot() -> dict[str, object]:
    return browser_runtime_snapshot()


async def shutdown_browser_pool() -> None:
    await shutdown_browser_runtime()


def shutdown_browser_pool_sync() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(shutdown_browser_runtime())
        return
    loop.create_task(shutdown_browser_runtime())


def prepare_browser_pool_for_worker_process() -> None:
    return None


class BrowserPool:
    pass
