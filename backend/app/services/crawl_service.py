from __future__ import annotations
from collections.abc import Awaitable, Callable
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.crawl import CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult, ProxyPoolExhausted
from app.services.shared_acquisition import acquire, run_adapter, try_blocked_adapter_recovery
from app.services._batch_runtime import (
    _build_acquisition_profile,
    _build_url_metrics,
    _count_run_records,
    _finalize_url_metrics,
    _handle_run_control_signal,
    _merge_run_acquisition_metrics,
    _run_control_checkpoint,
    _sleep_with_checkpoint,
    process_run as _batch_process_run,
)
from app.services.crawl_crud import (
    active_jobs,
    commit_llm_suggestions,
    commit_selected_fields,
    create_crawl_run,
    delete_run,
    get_run,
    get_run_logs,
    get_run_records,
    list_runs,
)
from app.services.crawl_utils import parse_csv_urls
from app.services.db_utils import with_retry
from app.services.crawl_state import (
    ACTIVE_STATUSES,
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    CrawlStatus,
    TERMINAL_STATUSES,
    normalize_status,
    set_control_request,
    update_run_status,
)
from app.services.llm_runtime import discover_xpath_candidates, review_field_candidates
from app.services.pipeline import (
    STAGE_ANALYZE,
    STAGE_FETCH,
    STAGE_SAVE,
    _aggregate_verdict,
    _apply_llm_suggestions_to_candidate_values,
    _build_acquisition_trace,
    _build_field_discovery_summary,
    _build_legible_listing_fallback_record,
    _build_llm_candidate_evidence,
    _build_llm_discovered_sources,
    _build_manifest_trace,
    _build_review_bucket,
    _clean_candidate_text,
    _clean_page_text,
    _collect_detail_llm_suggestions,
    _compact_dict,
    _compute_verdict,
    _elapsed_ms,
    _extract_detail,
    _extract_listing,
    _find_fallback_card_group,
    _first_non_empty_text,
    _listing_acquisition_blocked,
    _load_domain_requested_fields,
    _log,
    _looks_like_job_listing_page,
    _resolve_listing_surface,
    _looks_like_loading_listing_shell,
    _mark_run_failed,
    _merge_record_fields,
    _merge_review_bucket_entries,
    _normalize_committed_field_name,
    _normalize_detail_candidate_values,
    _normalize_llm_cleanup_review,
    _normalize_llm_review_bucket_item,
    _normalize_record_fields,
    _normalize_review_value,
    _normalize_target_url,
    _passes_core_verdict,
    _passes_detail_quality_gate,
    _persist_failure_state,
    _process_json_response,
    _process_single_url,
    _public_record_fields,
    _raw_record_payload,
    _reconcile_detail_candidate_values,
    _refresh_record_commit_metadata,
    _refresh_schema_from_record,
    _render_fallback_card_group,
    _render_fallback_node_markdown,
    _render_manifest_tables_markdown,
    _requested_field_coverage,
    _review_bucket_fingerprint,
    _review_bucket_source_for_field,
    _review_values_equal,
    _sanitize_listing_record_fields,
    _select_llm_review_candidates,
    _set_stage,
    _should_prefer_secondary_field,
    _should_skip_fallback_node,
    _should_surface_discovered_field,
    _snapshot_for_llm,
    _split_detail_output_fields,
    _split_llm_cleanup_payload,
    _summarize_job_listing_description,
    _supports_parallel_batch_sessions,
    _validate_extraction_contract,
)

# Compatibility exports for tests and existing import paths.
_COMPAT_EXPORTS = (
    active_jobs,
    commit_llm_suggestions,
    create_crawl_run,
    delete_run,
    get_run,
    get_run_logs,
    get_run_records,
    list_runs,
    _looks_like_job_listing_page,
    _resolve_listing_surface,
)
VERDICT_SUCCESS, VERDICT_PARTIAL, VERDICT_BLOCKED = "success", "partial", "blocked"
VERDICT_SCHEMA_MISS, VERDICT_LISTING_FAILED, VERDICT_EMPTY = "schema_miss", "listing_detection_failed", "empty"


async def _load_run_with_normalized_status(
    retry_session: AsyncSession, run_id: int
) -> tuple[CrawlRun, CrawlStatus]:
    retry_run = await retry_session.get(CrawlRun, run_id)
    if retry_run is None:
        raise ValueError("Run not found")
    return retry_run, normalize_status(retry_run.status)


async def _run_control_update(
    session: AsyncSession,
    run: CrawlRun,
    operation: Callable[[AsyncSession, CrawlRun, CrawlStatus], Awaitable[None]],
) -> CrawlRun:
    async def _wrapped(retry_session: AsyncSession) -> None:
        retry_run, current = await _load_run_with_normalized_status(retry_session, run.id)
        await operation(retry_session, retry_run, current)

    await with_retry(session, _wrapped)
    await session.refresh(run)
    return run


async def process_run(session: AsyncSession, run_id: int) -> None:
    """Compatibility wrapper so test patches on crawl_service symbols still apply."""
    await _batch_process_run(session, run_id)


async def pause_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current != CrawlStatus.RUNNING:
            raise ValueError(f"Cannot pause run in state: {retry_run.status}")
        set_control_request(retry_run, CONTROL_REQUEST_PAUSE)
        await _log(
            retry_session,
            retry_run.id,
            "warning",
            "Pause requested; crawl will stop at the next checkpoint",
        )

    return await _run_control_update(session, run, _operation)


async def resume_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current != CrawlStatus.PAUSED:
            raise ValueError(f"Cannot resume run in state: {retry_run.status}")
        update_run_status(retry_run, CrawlStatus.RUNNING)
        set_control_request(retry_run, None)
        await _log(retry_session, retry_run.id, "info", "Resume requested")

    return await _run_control_update(session, run, _operation)


async def kill_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current in TERMINAL_STATUSES:
            raise ValueError(f"Cannot kill run in terminal state: {retry_run.status}")
        if current == CrawlStatus.RUNNING:
            set_control_request(retry_run, CONTROL_REQUEST_KILL)
            await _log(
                retry_session,
                retry_run.id,
                "warning",
                "Hard kill requested; crawl will stop at the next checkpoint",
            )
        else:
            update_run_status(retry_run, CrawlStatus.KILLED)
            set_control_request(retry_run, None)
            await _log(
                retry_session,
                retry_run.id,
                "warning",
                "Run killed before execution resumed",
            )

    return await _run_control_update(session, run, _operation)


async def cancel_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    return await kill_run(session, run)
