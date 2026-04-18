from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass

from app.core.celery_app import celery_app, worker_process_init, worker_process_shutdown
from app.core.database import SessionLocal
from app.services.acquisition import (
    prepare_browser_pool_for_worker_process,
    shutdown_browser_pool_sync,
)
from app.services._batch_runtime import process_run as process_run_async

logger = logging.getLogger(__name__)
_SignalHandler = Callable[[int, object | None], object]


@dataclass
class _WorkerTaskState:
    active_task_loop: asyncio.AbstractEventLoop | None = None
    active_run_task: asyncio.Task[None] | None = None
    termination_requested: bool = False


_WORKER_TASK_STATE = _WorkerTaskState()


@worker_process_init.connect
def _worker_process_init(**_kwargs) -> None:
    prepare_browser_pool_for_worker_process()


@worker_process_shutdown.connect
def _worker_process_shutdown(**_kwargs) -> None:
    shutdown_browser_pool_sync()


async def _run_with_session(run_id: int) -> None:
    async with SessionLocal() as session:
        await process_run_async(session, run_id)


def _task_termination_handler(signum: int, _frame: object | None) -> None:
    _WORKER_TASK_STATE.termination_requested = True
    logger.warning(
        "Received signal %s while processing crawl task; cancelling async run", signum
    )
    loop = _WORKER_TASK_STATE.active_task_loop
    task = _WORKER_TASK_STATE.active_run_task
    if loop is None or task is None or loop.is_closed() or task.done():
        return
    loop.call_soon_threadsafe(task.cancel)


@contextmanager
def _install_task_signal_handlers() -> dict[int, _SignalHandler | int | None]:
    previous_handlers: dict[int, _SignalHandler | int | None] = {}
    for signame in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, signame, None)
        if signum is None:
            continue
        previous_handlers[int(signum)] = signal.getsignal(signum)
        signal.signal(signum, _task_termination_handler)
    try:
        yield previous_handlers
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def _run_task_in_worker_loop(run_id: int) -> None:
    _WORKER_TASK_STATE.termination_requested = False
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = loop.create_task(_run_with_session(run_id), name=f"crawl-run-{run_id}")
    _WORKER_TASK_STATE.active_task_loop = loop
    _WORKER_TASK_STATE.active_run_task = task
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        if _WORKER_TASK_STATE.termination_requested:
            shutdown_browser_pool_sync()
            raise SystemExit(0) from None
        raise
    finally:
        _WORKER_TASK_STATE.active_run_task = None
        _WORKER_TASK_STATE.active_task_loop = None
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            try:
                loop.run_until_complete(loop.shutdown_default_executor())
            except RuntimeError:
                logger.warning("Failed to shutdown default executor", exc_info=True)
            finally:
                asyncio.set_event_loop(None)
                loop.close()


@celery_app.task(name="crawl.process_run")
def process_run_task(run_id: int) -> None:
    with _install_task_signal_handlers():
        _run_task_in_worker_loop(run_id)
