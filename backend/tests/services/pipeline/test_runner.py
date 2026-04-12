from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.pipeline.runner import PipelineRunner
from app.services.pipeline.types import PipelineContext, URLProcessingConfig
from app.services.pipeline.verdict import VERDICT_ERROR, _aggregate_verdict


class _ExplodingStage:
    async def execute(self, ctx: PipelineContext) -> None:
        raise KeyError("boom")


class _NoopStage:
    async def execute(self, ctx: PipelineContext) -> None:
        ctx.url_metrics["noop"] = True


@pytest.mark.asyncio
async def test_pipeline_runner_converts_unhandled_stage_error_into_url_error() -> None:
    ctx = PipelineContext(
        session=SimpleNamespace(),
        run=SimpleNamespace(id=123),
        url="https://example.com/item",
        config=URLProcessingConfig(persist_logs=False),
        acquisition_request=SimpleNamespace(),
        persist_logs=False,
    )
    runner = PipelineRunner([_ExplodingStage()])

    await runner.execute(ctx)

    assert ctx.verdict == VERDICT_ERROR
    assert ctx.records == []
    assert ctx.url_metrics["pipeline_error"]["stage"] == "_ExplodingStage"
    assert ctx.url_metrics["pipeline_error"]["type"] == "KeyError"


@pytest.mark.asyncio
async def test_pipeline_runner_converts_before_hook_error_into_url_error() -> None:
    async def _before_hook(_stage_name: str, _ctx: PipelineContext) -> None:
        raise KeyError("hook boom")

    ctx = PipelineContext(
        session=SimpleNamespace(),
        run=SimpleNamespace(id=123),
        url="https://example.com/item",
        config=URLProcessingConfig(persist_logs=False),
        acquisition_request=SimpleNamespace(),
        persist_logs=False,
    )
    runner = PipelineRunner([_NoopStage()], on_before_stage=_before_hook)

    await runner.execute(ctx)

    assert ctx.verdict == VERDICT_ERROR
    assert ctx.records == []
    assert ctx.url_metrics["pipeline_error"]["stage"] == "_NoopStage"
    assert ctx.url_metrics["pipeline_error"]["type"] == "KeyError"


@pytest.mark.asyncio
async def test_pipeline_runner_converts_after_hook_error_into_url_error() -> None:
    async def _after_hook(_stage_name: str, _ctx: PipelineContext) -> None:
        raise RuntimeError("after hook boom")

    ctx = PipelineContext(
        session=SimpleNamespace(),
        run=SimpleNamespace(id=123),
        url="https://example.com/item",
        config=URLProcessingConfig(persist_logs=False),
        acquisition_request=SimpleNamespace(),
        persist_logs=False,
    )
    runner = PipelineRunner([_NoopStage()], on_after_stage=_after_hook)

    await runner.execute(ctx)

    assert ctx.verdict == VERDICT_ERROR
    assert ctx.records == []
    assert ctx.url_metrics["pipeline_error"]["stage"] == "_NoopStage"
    assert ctx.url_metrics["pipeline_error"]["type"] == "RuntimeError"


def test_aggregate_verdict_preserves_error_when_no_successful_urls() -> None:
    assert _aggregate_verdict([VERDICT_ERROR]) == VERDICT_ERROR
    assert _aggregate_verdict([VERDICT_ERROR, "listing_detection_failed"]) == VERDICT_ERROR
