from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from app.services.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)


def annotate_browser_failure(
    exc: Exception,
    *,
    phase_timings_ms: dict[str, int],
    stage: str,
) -> None:
    setattr(exc, "browser_failure_stage", stage)
    merged_timings = dict(getattr(exc, "browser_phase_timings_ms", {}) or {})
    merged_timings.update(dict(phase_timings_ms or {}))
    setattr(exc, "browser_phase_timings_ms", merged_timings)


async def run_browser_stage(
    *,
    stage: str,
    page: Any,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
    operation,
):
    stage_task = asyncio.create_task(operation())
    bounded_timeout_seconds = max(0.1, float(timeout_seconds))
    try:
        done, _pending = await asyncio.wait(
            {stage_task},
            timeout=bounded_timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
    except asyncio.CancelledError:
        await abort_browser_stage(
            stage_task,
            page=page,
            stage=stage,
            reason="cancelled",
        )
        raise
    if stage_task not in done:
        await abort_browser_stage(
            stage_task,
            page=page,
            stage=stage,
            reason="timeout",
        )
        timeout_exc = TimeoutError(
            f"Browser {stage} stage exceeded timeout_seconds={bounded_timeout_seconds:.2f}"
        )
        annotate_browser_failure(
            timeout_exc,
            phase_timings_ms=phase_timings_ms,
            stage=stage,
        )
        raise timeout_exc
    try:
        return stage_task.result()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        annotate_browser_failure(
            exc,
            phase_timings_ms=phase_timings_ms,
            stage=stage,
        )
        raise


async def abort_browser_stage(
    stage_task: asyncio.Task[Any],
    *,
    page: Any,
    stage: str,
    reason: str,
) -> None:
    if not stage_task.done():
        stage_task.cancel()
    await force_close_browser_handles(page, stage=stage, reason=reason)
    try:
        await asyncio.wait_for(
            asyncio.shield(stage_task),
            timeout=browser_stage_cleanup_timeout_seconds(),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Browser %s stage did not exit within %.1fs after %s; continuing teardown",
            stage,
            browser_stage_cleanup_timeout_seconds(),
            reason,
        )
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.debug(
            "Browser %s stage raised while unwinding after %s",
            stage,
            reason,
            exc_info=True,
        )


def browser_stage_cleanup_timeout_seconds() -> float:
    return max(
        0.1,
        float(crawler_runtime_settings.browser_close_timeout_ms) / 1000,
    )


async def force_close_browser_handles(
    page: Any,
    *,
    stage: str,
    reason: str,
) -> None:
    close_timeout_seconds = browser_stage_cleanup_timeout_seconds()
    page_close = getattr(page, "close", None)
    if callable(page_close):
        try:
            await asyncio.wait_for(page_close(), timeout=close_timeout_seconds)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug(
                "Browser page close failed during %s %s teardown",
                stage,
                reason,
                exc_info=True,
            )
    context = getattr(page, "context", None)
    if callable(context):
        with suppress(TypeError):
            context = context()
    context_close = getattr(context, "close", None)
    if not callable(context_close):
        return
    try:
        await asyncio.wait_for(context_close(), timeout=close_timeout_seconds)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.debug(
            "Browser context close failed during %s %s teardown",
            stage,
            reason,
            exc_info=True,
        )


__all__ = ["run_browser_stage"]
