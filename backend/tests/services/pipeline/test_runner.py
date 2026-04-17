from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.pipeline.runner import PipelineRunner
from app.services.pipeline.runner import build_default_stages
from app.services.pipeline.stages import ParseStage
from app.services.pipeline.types import PipelineContext, URLProcessingConfig
from app.services.publish import VERDICT_ERROR, _aggregate_verdict


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


def test_build_default_stages_excludes_blocked_detection_stage() -> None:
    stage_names = [type(stage).__name__ for stage in build_default_stages()]
    assert "BlockedDetectionStage" not in stage_names


@pytest.mark.asyncio
async def test_parse_stage_populates_shared_soup_and_page_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed_soup = object()
    parsed_sources = {"json_ld": [{"name": "Widget"}]}

    async def _fake_parse_html(html: str):
        assert html == "<html><body>ok</body></html>"
        return parsed_soup

    async def _fake_parse_page_sources_async(html: str, *, soup=None):
        assert html == "<html><body>ok</body></html>"
        assert soup is parsed_soup
        return parsed_sources

    monkeypatch.setattr("app.services.pipeline.stages.parse_html", _fake_parse_html)
    monkeypatch.setattr(
        "app.services.pipeline.stages.parse_page_sources_async",
        _fake_parse_page_sources_async,
    )

    ctx = PipelineContext(
        session=SimpleNamespace(),
        run=SimpleNamespace(id=123),
        url="https://example.com/item",
        config=URLProcessingConfig(persist_logs=False),
        acquisition_request=SimpleNamespace(),
        acquisition_result=SimpleNamespace(
            html="<html><body>ok</body></html>",
            content_type="html",
        ),
        persist_logs=False,
    )

    await ParseStage().execute(ctx)

    assert ctx.soup is parsed_soup
    assert ctx.page_sources == parsed_sources
