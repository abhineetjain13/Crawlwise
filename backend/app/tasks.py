from __future__ import annotations

import asyncio

from app.core.celery_app import celery_app, worker_process_init, worker_process_shutdown
from app.core.database import SessionLocal
from app.services.acquisition.browser_client import (
    prepare_browser_pool_for_worker_process,
    shutdown_browser_pool_sync,
)
from app.services._batch_runtime import process_run as process_run_async


@worker_process_init.connect
def _worker_process_init(**_kwargs) -> None:
    prepare_browser_pool_for_worker_process()


@worker_process_shutdown.connect
def _worker_process_shutdown(**_kwargs) -> None:
    shutdown_browser_pool_sync()


async def _run_with_session(run_id: int) -> None:
    async with SessionLocal() as session:
        await process_run_async(session, run_id)


@celery_app.task(name="crawl.process_run")
def process_run_task(run_id: int) -> None:
    asyncio.run(_run_with_session(run_id))
