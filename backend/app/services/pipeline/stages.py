"""Concrete pipeline stage implementations.

Each stage is a lightweight class with a single ``async execute(ctx)`` method
that reads from and writes to the shared :class:`PipelineContext`.

Stages are composed by :class:`PipelineRunner` (see ``runner.py``) and
replace the monolithic inline logic that previously lived in
``_process_single_url``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.crawl_metrics import (
    build_url_metrics as _build_url_metrics,
)
from app.services.config.crawl_runtime import AUTO_DETECT_SURFACE

from .types import PipelineContext
from .utils import _elapsed_ms, parse_html
from .verdict import VERDICT_BLOCKED, VERDICT_LISTING_FAILED

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage 1: Acquisition
# ---------------------------------------------------------------------------


class AcquireStage:
    """Fetch the target URL via the acquisition waterfall (curl → Playwright)."""

    async def execute(self, ctx: PipelineContext) -> None:
        from .core import STAGE_FETCH, _log, _set_stage, acquire

        if ctx.update_run_state:
            await _set_stage(ctx.session, ctx.run, STAGE_FETCH)
        if ctx.persist_logs:
            await _log(ctx.session, ctx.run.id, "info", f"[FETCH] Fetching {ctx.url}")

        if ctx.acquisition_result is None:
            started_at = time.perf_counter()
            ctx.acquisition_result = await acquire(request=ctx.acquisition_request)
            ctx.acquisition_ms = _elapsed_ms(started_at)
        ctx.url_metrics = _build_url_metrics(
            ctx.acquisition_result, requested_fields=ctx.additional_fields
        )
        ctx.url_metrics["acquisition_ms"] = ctx.acquisition_ms

        # Log traversal progress
        if ctx.persist_logs and ctx.url_metrics.get("traversal_attempted"):
            _t_mode = (
                ctx.url_metrics.get("traversal_mode_used")
                or ctx.config.traversal_mode
                or "?"
            )
            _t_pages = ctx.url_metrics.get("traversal_pages_collected", 0)
            _t_stop = ctx.url_metrics.get("traversal_stop_reason") or "unknown"
            _t_fallback = ctx.url_metrics.get("traversal_fallback_used", False)
            _t_ms = ctx.url_metrics.get("browser_traversal_ms", 0)
            _t_msg = (
                f"[TRAVERSAL] mode={_t_mode}, pages_collected={_t_pages}, "
                f"stop_reason={_t_stop}, time={_t_ms}ms"
            )
            if _t_fallback:
                _t_msg += " (fallback to single-page)"
            await _log(ctx.session, ctx.run.id, "info", _t_msg)


# ---------------------------------------------------------------------------
# Stage 1.2: Surface Validation
# ---------------------------------------------------------------------------


class SurfaceValidationStage:
    """Optional auto-detection of the effective listing surface."""

    async def execute(self, ctx: PipelineContext) -> None:
        from .core import _resolve_listing_surface

        acq = ctx.acquisition_result
        assert acq is not None
        requested_surface = ctx.surface
        ctx.url_metrics["requested_surface"] = requested_surface
        if AUTO_DETECT_SURFACE:
            ctx.surface = _resolve_listing_surface(surface=ctx.surface, acq=acq)
            if ctx.surface != requested_surface:
                ctx.url_metrics["effective_surface"] = ctx.surface
                ctx.url_metrics["surface_remapped"] = True


# ---------------------------------------------------------------------------
# Stage 1.5: Blocked Page Detection
# ---------------------------------------------------------------------------


class BlockedDetectionStage:
    """Detect anti-bot challenge pages and attempt recovery."""

    async def execute(self, ctx: PipelineContext) -> None:
        from app.models.crawl import CrawlRecord

        from .core import _log, acquire, try_blocked_adapter_recovery
        from .trace_builders import _build_acquisition_trace

        acq = ctx.acquisition_result
        assert acq is not None
        if acq.content_type == "json":
            return  # APIs don't serve challenge pages

        blocked = detect_blocked_page(acq.html)

        # Listing + curl blocked → one browser-first retry
        if blocked.is_blocked and ctx.is_listing and acq.method != "playwright":
            if ctx.persist_logs:
                await _log(
                    ctx.session,
                    ctx.run.id,
                    "info",
                    "[BLOCKED] Listing page matched blocked signals on initial acquire; retrying once with browser-first recovery",
                )
            browser_retry_started = time.perf_counter()
            browser_acq = await acquire(
                request=ctx.acquisition_request.with_profile_updates(
                    prefer_browser=True,
                    anti_bot_enabled=True,
                ),
            )
            browser_retry_ms = _elapsed_ms(browser_retry_started)
            browser_blocked = (
                detect_blocked_page(browser_acq.html)
                if browser_acq.content_type != "json"
                else None
            )
            if not (browser_blocked and browser_blocked.is_blocked):
                ctx.acquisition_result = browser_acq
                acq = browser_acq
                ctx.acquisition_ms += browser_retry_ms
                ctx.url_metrics = _build_url_metrics(
                    acq, requested_fields=ctx.additional_fields
                )
                ctx.url_metrics["acquisition_ms"] = ctx.acquisition_ms
                if ctx.persist_logs:
                    await _log(
                        ctx.session,
                        ctx.run.id,
                        "info",
                        "[BLOCKED] Browser-first recovery succeeded; continuing listing extraction",
                    )
                blocked = (
                    detect_blocked_page(acq.html)
                    if acq.content_type != "json"
                    else blocked
                )

        if not blocked.is_blocked:
            return

        # Adapter recovery attempt
        recovered = (
            None
            if ctx.config.proxy_list or not ctx.is_listing
            else await try_blocked_adapter_recovery(ctx.url, ctx.surface)
        )
        if recovered and recovered.records:
            if ctx.persist_logs:
                await _log(
                    ctx.session,
                    ctx.run.id,
                    "info",
                    f"[BLOCKED] {ctx.url} matched blocked-page signals, recovered {len(recovered.records)} "
                    f"{recovered.adapter_name or 'adapter'} records from public endpoint",
                )
            ctx.adapter_result = recovered
            ctx.adapter_records = recovered.records
            # Let extraction stages handle the recovered records
            return

        # Irrecoverably blocked
        if ctx.persist_logs:
            await _log(
                ctx.session,
                ctx.run.id,
                "warning",
                f"[BLOCKED] {ctx.url} — {blocked.reason}",
            )
        record = CrawlRecord(
            run_id=ctx.run.id,
            source_url=ctx.url,
            data={
                "_status": "blocked",
                "_message": blocked.reason,
                "_provider": blocked.provider,
            },
            raw_data={},
            discovered_data=blocked.as_dict(),
            source_trace={**_build_acquisition_trace(acq), "blocked": True},
            raw_html_path=acq.artifact_path,
        )
        ctx.session.add(record)
        await ctx.session.flush()
        ctx.verdict = VERDICT_BLOCKED
        ctx.records = []


# ---------------------------------------------------------------------------
# Stage 2a: HTML Parse (single parse, shared soup)
# ---------------------------------------------------------------------------


class ParseStage:
    """Parse HTML into BeautifulSoup once, offloaded to thread pool."""

    async def execute(self, ctx: PipelineContext) -> None:
        acq = ctx.acquisition_result
        assert acq is not None
        html = acq.html
        if html and acq.content_type != "json":
            ctx.soup = await parse_html(html)


# ---------------------------------------------------------------------------
# Stage 2b: Adapter Execution
# ---------------------------------------------------------------------------


class AdapterStage:
    """Run domain-matched platform adapters against the acquired HTML."""

    async def execute(self, ctx: PipelineContext) -> None:
        from .core import STAGE_ANALYZE, _log, _set_stage, run_adapter

        acq = ctx.acquisition_result
        assert acq is not None
        if acq.content_type == "json":
            return
        if ctx.adapter_result is not None or ctx.adapter_records:
            return
        html = acq.html
        ctx.adapter_result = await run_adapter(ctx.url, html, ctx.surface)
        ctx.adapter_records = ctx.adapter_result.records if ctx.adapter_result else []

        if ctx.update_run_state:
            await _set_stage(ctx.session, ctx.run, STAGE_ANALYZE)
        if ctx.persist_logs:
            await _log(
                ctx.session, ctx.run.id, "info", "[ANALYZE] Extracting candidates"
            )


# ---------------------------------------------------------------------------
# Stage 3: Extraction (delegates to existing _extract_listing / _extract_detail)
# ---------------------------------------------------------------------------


class ExtractStage:
    """Delegates to the appropriate extraction path based on surface/content type."""

    async def execute(self, ctx: PipelineContext) -> None:
        from .core import (
            STAGE_ANALYZE,
            _extract_detail,
            _extract_listing,
            _log,
            _process_json_response,
            _set_stage,
        )

        acq = ctx.acquisition_result
        assert acq is not None

        # JSON path
        if acq.content_type == "json" and acq.json_data is not None:
            if ctx.persist_logs:
                await _log(
                    ctx.session,
                    ctx.run.id,
                    "info",
                    "[ANALYZE] JSON-first path — API response detected",
                )
            extraction_started = time.perf_counter()
            result = await _process_json_response(
                ctx.session,
                ctx.run,
                ctx.url,
                acq,
                ctx.is_listing,
                ctx.config.max_records,
                ctx.additional_fields,
                ctx.url_metrics,
                update_run_state=ctx.update_run_state,
                persist_logs=ctx.persist_logs,
            )
            result.url_metrics["extraction_ms"] = _elapsed_ms(extraction_started)
            ctx.records = result.records
            ctx.verdict = result.verdict
            ctx.url_metrics = result.url_metrics
            return

        html = acq.html
        if ctx.update_run_state:
            await _set_stage(ctx.session, ctx.run, STAGE_ANALYZE)
        if ctx.persist_logs:
            await _log(
                ctx.session,
                ctx.run.id,
                "info",
                f"[ANALYZE] Enumerating sources (method={acq.method})",
            )

        if ctx.is_listing:
            extraction_started = time.perf_counter()
            result = await _extract_listing(
                ctx.session,
                ctx.run,
                ctx.url,
                html,
                acq,
                ctx.adapter_result,
                ctx.adapter_records,
                ctx.additional_fields,
                ctx.surface,
                ctx.config.max_records,
                ctx.url_metrics,
                update_run_state=ctx.update_run_state,
                persist_logs=ctx.persist_logs,
            )
            result.url_metrics["extraction_ms"] = _elapsed_ms(extraction_started)
            ctx.records = result.records
            ctx.verdict = result.verdict
            ctx.url_metrics = result.url_metrics
        else:
            extraction_started = time.perf_counter()
            result = await _extract_detail(
                ctx.session,
                ctx.run,
                ctx.url,
                html,
                acq,
                ctx.adapter_result,
                ctx.adapter_records,
                ctx.additional_fields,
                ctx.extraction_contract,
                ctx.surface,
                ctx.url_metrics,
                update_run_state=ctx.update_run_state,
                persist_logs=ctx.persist_logs,
            )
            result.url_metrics["extraction_ms"] = _elapsed_ms(extraction_started)
            ctx.records = result.records
            ctx.verdict = result.verdict
            ctx.url_metrics = result.url_metrics


# ---------------------------------------------------------------------------
# Stage 3.5: Listing Browser Retry
# ---------------------------------------------------------------------------


class ListingBrowserRetryStage:
    """If listing extraction failed on curl, retry with browser rendering."""

    async def execute(self, ctx: PipelineContext) -> None:
        from .core import _extract_listing, _log, acquire, run_adapter

        acq = ctx.acquisition_result
        assert acq is not None

        if not ctx.is_listing:
            return
        if ctx.verdict != VERDICT_LISTING_FAILED:
            return
        if acq.method != "curl_cffi":
            return

        if ctx.persist_logs:
            await _log(
                ctx.session,
                ctx.run.id,
                "info",
                "[ANALYZE] Listing extraction was weak/empty on curl_cffi — retrying with browser rendering",
            )

        browser_retry_started = time.perf_counter()
        browser_acq = await acquire(
            request=ctx.acquisition_request.with_profile_updates(prefer_browser=True),
        )
        browser_retry_ms = _elapsed_ms(browser_retry_started)
        browser_html = browser_acq.html
        browser_adapter_result = await run_adapter(ctx.url, browser_html, ctx.surface)
        browser_adapter_records = (
            browser_adapter_result.records if browser_adapter_result else []
        )

        extraction_started = time.perf_counter()
        result = await _extract_listing(
            ctx.session,
            ctx.run,
            ctx.url,
            browser_html,
            browser_acq,
            browser_adapter_result,
            browser_adapter_records,
            ctx.additional_fields,
            ctx.surface,
            ctx.config.max_records,
            ctx.url_metrics,
            update_run_state=ctx.update_run_state,
            persist_logs=ctx.persist_logs,
        )
        result.url_metrics["listing_browser_retry"] = True
        result.url_metrics["listing_browser_retry_method"] = browser_acq.method
        result.url_metrics["listing_browser_retry_acquisition_ms"] = browser_retry_ms
        result.url_metrics["extraction_ms"] = _elapsed_ms(extraction_started)
        ctx.records = result.records
        ctx.verdict = result.verdict
        ctx.url_metrics = result.url_metrics
