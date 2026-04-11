from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.models.crawl import CrawlRun
from app.services.acquisition import AcquisitionRequest, AcquisitionResult
from app.services.acquisition.acquirer import acquire as _acquire
from app.services.adapters.registry import (
    run_adapter as _run_adapter,
    try_blocked_adapter_recovery as _try_blocked_adapter_recovery,
)
from app.services.config.field_mappings import CANONICAL_SCHEMAS
from app.services.crawl_metrics import (
    build_acquisition_profile as _build_acquisition_profile,
)
from app.services.crawl_state import (
    TERMINAL_STATUSES,
    CrawlStatus,
    update_run_status,
)
from app.services.domain_utils import normalize_domain
from app.services.llm_runtime import (
    discover_xpath_candidates as _discover_xpath_candidates,
    review_field_candidates as _review_field_candidates,
)
from app.services.requested_field_policy import expand_requested_fields
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from .runtime_helpers import (
    STAGE_ANALYZE,
    STAGE_FETCH,
    STAGE_SAVE,
    effective_max_records,
    is_error_page_record,
    log_event,
    log_for_pytest,
    set_stage,
)
from .runner import PipelineRunner, build_default_stages

# Import from sibling modules in pipeline package
from .types import PipelineContext, URLProcessingConfig, URLProcessingResult
from .verdict import (
    VERDICT_EMPTY,
    VERDICT_ERROR,
    VERDICT_SUCCESS,
)

logger = logging.getLogger(__name__)
HTTP_URL_PREFIXES = ("http://", "https://")
_TRAVERSAL_MODES = {"auto", "scroll", "load_more", "paginate"}
# Batch runtime helpers now live directly in _batch_runtime.

__all__ = [
    "STAGE_FETCH",
    "STAGE_ANALYZE",
    "STAGE_SAVE",
]

acquire = _acquire
run_adapter = _run_adapter
try_blocked_adapter_recovery = _try_blocked_adapter_recovery
discover_xpath_candidates = _discover_xpath_candidates
review_field_candidates = _review_field_candidates
_effective_max_records = effective_max_records
_is_error_page_record = is_error_page_record
_log = log_event
_log_for_pytest = log_for_pytest
_set_stage = set_stage


def get_selector_defaults(_domain: str, _field_name: str) -> list[dict]:
    return []


def get_canonical_fields(surface: str) -> list[str]:
    return list(CANONICAL_SCHEMAS.get(str(surface or "").strip(), []))


def _resolved_url_processing_config(
    *,
    config: URLProcessingConfig | None,
    proxy_list: list[str] | None,
    traversal_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    max_records: int,
    sleep_ms: int,
    update_run_state: bool,
    persist_logs: bool,
) -> URLProcessingConfig:
    if config is not None:
        return config
    return URLProcessingConfig(
        proxy_list=list(proxy_list or []),
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        max_records=max_records,
        sleep_ms=sleep_ms,
        update_run_state=update_run_state,
        persist_logs=persist_logs,
        prefetch_only=False,
        record_writer=None,
    )


async def _pipeline_stage_checkpoint(_stage_name: str, ctx: PipelineContext) -> None:
    if ctx.checkpoint is not None:
        await ctx.checkpoint()


async def _process_single_url(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    config: URLProcessingConfig | None = None,
    *,
    # Legacy keyword arguments — prefer passing a URLProcessingConfig instead.
    proxy_list: list[str] | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = 3,
    max_records: int = 100,
    sleep_ms: int = 0,
    checkpoint=None,
    update_run_state: bool = True,
    persist_logs: bool = True,
    prefetched_acquisition: AcquisitionResult | None = None,
) -> URLProcessingResult:
    """Run the single-URL pipeline.

    Returns a ``URLProcessingResult`` with records, verdict, and metrics.
    """
    resolved_config = _resolved_url_processing_config(
        config=config,
        proxy_list=proxy_list,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        max_records=max_records,
        sleep_ms=sleep_ms,
        update_run_state=update_run_state,
        persist_logs=persist_logs,
    )
    surface = run.surface
    settings_view = run.settings_view
    additional_fields = expand_requested_fields(run.requested_fields or [])
    extraction_contract = settings_view.extraction_contract()
    is_listing = surface in ("ecommerce_listing", "job_listing")
    requested_field_selectors = {
        field_name: get_selector_defaults(normalize_domain(url), field_name)
        for field_name in additional_fields
        if field_name
    }
    acquisition_profile = _build_acquisition_profile(settings_view)
    base_acquisition_request = AcquisitionRequest(
        run_id=run.id,
        url=url,
        surface=surface,
        proxy_list=list(resolved_config.proxy_list or []),
        traversal_mode=resolved_config.traversal_mode,
        max_pages=resolved_config.max_pages,
        max_scrolls=resolved_config.max_scrolls,
        sleep_ms=resolved_config.sleep_ms,
        requested_fields=list(additional_fields),
        requested_field_selectors=dict(requested_field_selectors),
        acquisition_profile=dict(acquisition_profile or {}),
        checkpoint=checkpoint,
    )
    resolved_max_records = await effective_max_records(
        session,
        run,
        resolved_config.max_records,
    )
    resolved_config = URLProcessingConfig(
        proxy_list=list(resolved_config.proxy_list or []),
        traversal_mode=resolved_config.traversal_mode,
        max_pages=resolved_config.max_pages,
        max_scrolls=resolved_config.max_scrolls,
        max_records=resolved_max_records,
        sleep_ms=resolved_config.sleep_ms,
        update_run_state=resolved_config.update_run_state,
        persist_logs=resolved_config.persist_logs,
        prefetch_only=resolved_config.prefetch_only,
        record_writer=resolved_config.record_writer,
    )
    ctx = PipelineContext(
        session=session,
        run=run,
        url=url,
        config=resolved_config,
        acquisition_request=base_acquisition_request,
        additional_fields=additional_fields,
        extraction_contract=extraction_contract,
        is_listing=is_listing,
        surface=surface,
        update_run_state=resolved_config.update_run_state,
        persist_logs=resolved_config.persist_logs,
        checkpoint=checkpoint,
        record_writer=resolved_config.record_writer,
        acquisition_result=prefetched_acquisition,
        acquisition_ms=0,
    )
    runner = PipelineRunner(
        build_default_stages(prefetch_only=resolved_config.prefetch_only),
        on_before_stage=_pipeline_stage_checkpoint,
    )
    await runner.execute(ctx)
    if resolved_config.prefetch_only:
        ctx.url_metrics["prefetch_only"] = True
        if not ctx.verdict:
            acq = ctx.acquisition_result
            if acq is None:
                ctx.verdict = VERDICT_ERROR
            elif acq.content_type == "json" and acq.json_data is not None:
                ctx.verdict = VERDICT_SUCCESS
            elif acq.html:
                ctx.verdict = VERDICT_SUCCESS
            else:
                ctx.verdict = VERDICT_EMPTY
    return ctx.to_result()


def _supports_parallel_batch_sessions(session: AsyncSession) -> bool:
    return session.bind is not None


async def _mark_run_failed(session: AsyncSession, run_id: int, error_msg: str) -> None:
    """Mark a run as failed.

    First attempts recovery using the existing session (after a rollback).
    If that fails, creates an isolated session via ``SessionLocal`` so a
    poisoned transaction cannot block failure recording.
    """
    try:
        await session.rollback()
    except SQLAlchemyError:
        pass  # Original session may already be invalidated — that's fine.

    # Try the original session first — works in tests and when the session is still usable.
    try:
        await _persist_failure_state(session, run_id, error_msg)
        return
    except SQLAlchemyError:
        logger.debug(
            "Original session unusable for failure recovery; falling back to SessionLocal",
            exc_info=True,
        )

        try:
            async with SessionLocal() as recovery:
                await _persist_failure_state(recovery, run_id, error_msg)
        except SQLAlchemyError:
            logger.exception("Failure recovery via SessionLocal failed")


async def _persist_failure_state(
    session: AsyncSession, run_id: int, error_msg: str
) -> None:
    """Write failure state."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    result_summary = run.summary_dict()
    run.update_summary(
        error=error_msg,
        progress=result_summary.get("progress", 0),
        extraction_verdict=VERDICT_ERROR,
    )
    if run.status_value not in TERMINAL_STATUSES:
        update_run_status(run, CrawlStatus.FAILED)
    await session.commit()


# Domain normalisation delegated to app.services.domain_utils.normalize_domain
_domain = normalize_domain
