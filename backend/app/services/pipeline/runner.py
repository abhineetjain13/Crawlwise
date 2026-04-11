"""Pipeline runner — composes and executes stage chains.

The runner is a thin orchestrator that replaces the deeply nested control
flow previously embedded in ``_process_single_url``.  Hook points
(``on_before_stage`` / ``on_after_stage``) allow injection of cross-cutting
concerns (timing, logging, checkpointing) without modifying stage code.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from .types import PipelineContext, PipelineStage
from .utils import _elapsed_ms

logger = logging.getLogger(__name__)

# Type alias for hook callables
StageHook = Callable[[str, PipelineContext], Awaitable[None]] | None


class PipelineRunner:
    """Execute an ordered list of pipeline stages against a shared context.

    Usage::

        runner = PipelineRunner(
            stages=[AcquireStage(), SurfaceValidationStage(), ...],
            on_after_stage=my_timing_hook,
        )
        ctx = PipelineContext(...)
        await runner.execute(ctx)
        result = ctx.to_result()
    """

    def __init__(
        self,
        stages: list[PipelineStage],
        *,
        on_before_stage: StageHook = None,
        on_after_stage: StageHook = None,
    ) -> None:
        self._stages = list(stages)
        self._on_before_stage = on_before_stage
        self._on_after_stage = on_after_stage

    async def execute(self, ctx: PipelineContext) -> None:
        """Run all stages in order.  Stops early if *ctx.verdict* is set."""
        for stage in self._stages:
            stage_name = type(stage).__name__

            if self._on_before_stage is not None:
                await self._on_before_stage(stage_name, ctx)

            started = time.perf_counter()
            await stage.execute(ctx)
            elapsed = _elapsed_ms(started)

            # Record per-stage timing in metrics
            ctx.url_metrics.setdefault("stage_timings_ms", {})[stage_name] = elapsed

            if self._on_after_stage is not None:
                await self._on_after_stage(stage_name, ctx)

            # Early pipeline stages may set terminal verdicts such as
            # "blocked". ExtractStage also sets provisional verdicts that the
            # final browser-retry stage may refine, so don't stop on those.
            if ctx.verdict and stage_name != "ExtractStage":
                logger.debug(
                    "Pipeline short-circuited at %s with verdict=%s",
                    stage_name,
                    ctx.verdict,
                )
                break


def build_default_stages(*, prefetch_only: bool = False) -> list[PipelineStage]:
    """Build the default stage chain matching the legacy ``_process_single_url`` behaviour.

    Order: Acquire → SurfaceValidation → BlockedDetection → Adapter → Parse → Extract → ListingBrowserRetry
    """
    from .stages import (
        AcquireStage,
        AdapterStage,
        BlockedDetectionStage,
        ExtractStage,
        ListingBrowserRetryStage,
        ParseStage,
        SurfaceValidationStage,
    )

    stages: list[PipelineStage] = [
        AcquireStage(),
        SurfaceValidationStage(),
        BlockedDetectionStage(),
        ParseStage(),
    ]
    if prefetch_only:
        return stages
    stages.extend(
        [
            AdapterStage(),
            ExtractStage(),
            ListingBrowserRetryStage(),
        ]
    )
    return stages
