from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.core.config import settings
from app.core.telemetry import (
    generate_correlation_id,
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.models.crawl import CrawlRecord, CrawlRun
from app.models.crawl_settings import CrawlRunSettings
from app.services._batch_run_store import BatchRunStore, retry_run_update
from app.services._batch_progress import persist_batch_url_result
from app.services.crawl_state import (
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    TERMINAL_STATUSES,
    CrawlStatus,
    get_control_request,
    set_control_request,
    update_run_status,
)
from app.services.exceptions import ProxyPoolExhaustedError, RunControlError
from app.services.crawl_utils import (
    normalize_target_url,
    parse_csv_urls,
)
from app.services.domain_utils import normalize_domain
from app.services.pipeline.core import (
    _mark_run_failed,
    _process_single_url,
)
from app.services.pipeline.runtime_helpers import (
    STAGE_FETCH,
    log_event,
    set_stage,
)
from app.services.pipeline.verdict import (
    VERDICT_ERROR,
    _aggregate_verdict,
)
from app.services.llm_runtime import snapshot_active_configs
from app.services.pipeline.types import URLProcessingConfig, URLProcessingResult
from app.services.config.crawl_runtime import (
    MAX_URL_PROCESS_TIMEOUT_SECONDS,
    URL_PROCESS_TIMEOUT_SECONDS,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.resource_monitor import MemoryAdaptiveSemaphore
from app.services.url_concurrency import DistributedURLSlotGuard

logger = logging.getLogger(__name__)
_global_url_semaphore: MemoryAdaptiveSemaphore | None = None
_global_url_semaphore_limit: int | None = None
ProxyPoolExhausted = ProxyPoolExhaustedError


@dataclass(slots=True)
class _BatchRunContext:
    run: CrawlRun
    correlation_id: str
    url_list: list[str]
    proxy_list: list[str]
    traversal_mode: str | None
    max_pages: int
    max_scrolls: int
    max_records: int
    sleep_ms: int
    advanced_enabled: bool
    url_timeout_seconds: float

    @property
    def total_urls(self) -> int:
        return len(self.url_list)


def _get_global_url_semaphore() -> MemoryAdaptiveSemaphore:
    """Return the global memory-adaptive URL concurrency semaphore.

    Replaces the former fixed ``asyncio.Semaphore`` — new URL acquisitions
    are now blocked automatically when system memory pressure is high.
    """
    global _global_url_semaphore, _global_url_semaphore_limit
    limit = max(1, int(settings.system_max_concurrent_urls or 1))
    if _global_url_semaphore is None or _global_url_semaphore_limit != limit:
        _global_url_semaphore = MemoryAdaptiveSemaphore(limit)
        _global_url_semaphore_limit = limit
    return _global_url_semaphore


async def _log_with_retry(
    session: AsyncSession,
    run_id: int,
    level: str,
    message: str,
) -> None:
    tagged_message = _with_correlation_tag(message)
    await log_event(session, run_id, level, tagged_message)
    await session.commit()


def _with_correlation_tag(message: str) -> str:
    correlation_id = str(get_correlation_id() or "").strip()
    text = str(message or "")
    if not correlation_id:
        return text
    if text.startswith("[corr="):
        return text
    return f"[corr={correlation_id}] {text}"


def _coerce_url_timeout_seconds(settings_view: CrawlRunSettings) -> float:
    raw_value = settings_view.get("url_timeout_seconds", URL_PROCESS_TIMEOUT_SECONDS)
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return URL_PROCESS_TIMEOUT_SECONDS
    if value <= 0:
        return URL_PROCESS_TIMEOUT_SECONDS
    return min(value, MAX_URL_PROCESS_TIMEOUT_SECONDS)


def _ensure_url_processing_result(
    url_result: URLProcessingResult | tuple[object, object, object],
) -> URLProcessingResult:
    if isinstance(url_result, URLProcessingResult):
        return url_result
    if isinstance(url_result, tuple) and len(url_result) == 3:
        records, verdict, metrics = url_result
        return URLProcessingResult(
            records=list(records or []),
            verdict=str(verdict or ""),
            url_metrics=dict(metrics or {}),
        )
    raise TypeError(f"Unexpected URL result type: {type(url_result)!r}")


async def _count_run_records(session: AsyncSession, run_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(CrawlRecord)
                .where(CrawlRecord.run_id == run_id)
            )
        ).scalar()
        or 0
    )


def _resolve_run_urls(run: CrawlRun, settings_view: CrawlRunSettings) -> list[str]:
    urls = settings_view.urls()
    if run.run_type == "batch" and urls:
        url_list = urls
    elif run.run_type == "csv" and settings_view.get("csv_content"):
        url_list = parse_csv_urls(settings_view.get("csv_content"))
    elif run.url:
        url_list = [run.url]
    else:
        raise ValueError("No URL provided")
    return [
        value for value in (normalize_target_url(item) for item in url_list) if value
    ]


def _coerce_persisted_url_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    persisted_urls: list[str] = []
    for item in value:
        normalized = normalize_target_url(item)
        if normalized:
            persisted_urls.append(normalized)
    return persisted_urls


def _build_batch_run_context(
    run: CrawlRun,
    settings_view: CrawlRunSettings,
    *,
    correlation_id: str,
    url_list: list[str] | None = None,
) -> _BatchRunContext:
    return _BatchRunContext(
        run=run,
        correlation_id=correlation_id,
        url_list=list(url_list) if url_list is not None else _resolve_run_urls(run, settings_view),
        proxy_list=settings_view.proxy_list(),
        traversal_mode=settings_view.traversal_mode(),
        max_pages=settings_view.max_pages(),
        max_scrolls=settings_view.max_scrolls(),
        max_records=settings_view.max_records(),
        sleep_ms=settings_view.sleep_ms(),
        advanced_enabled=settings_view.advanced_enabled(),
        url_timeout_seconds=_coerce_url_timeout_seconds(settings_view),
    )


_retry_run_update = retry_run_update


class RunControlSignal(RunControlError):
    def __init__(self, request: str) -> None:
        super().__init__(request)
        self.request = request


async def _run_control_checkpoint(session: AsyncSession, run: CrawlRun) -> None:
    refreshed_run = run
    try:
        await session.refresh(run)
    except Exception:
        fetched = await session.get(CrawlRun, int(getattr(run, "id", 0) or 0))
        if fetched is not None:
            refreshed_run = fetched
    current_status = refreshed_run.status_value
    control_request = get_control_request(refreshed_run)
    if current_status == CrawlStatus.PAUSED or control_request == CONTROL_REQUEST_PAUSE:
        raise RunControlSignal(CONTROL_REQUEST_PAUSE)
    if current_status == CrawlStatus.KILLED or control_request == CONTROL_REQUEST_KILL:
        raise RunControlSignal(CONTROL_REQUEST_KILL)


async def _start_or_resume_run(session: AsyncSession, run: CrawlRun) -> None:
    await BatchRunStore(session).start_or_resume_run(run)


async def _load_batch_run_context(
    session: AsyncSession,
    run_id: int,
) -> _BatchRunContext | None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    current_status = run.status_value
    if current_status in TERMINAL_STATUSES or current_status == CrawlStatus.PAUSED:
        return None

    await _start_or_resume_run(session, run)

    persisted_summary = run.summary_dict()
    correlation_id = str(
        persisted_summary.get("correlation_id") or generate_correlation_id()
    ).strip()
    persisted_url_list = _coerce_persisted_url_list(
        persisted_summary.get("resolved_url_list")
    )

    store = BatchRunStore(session)
    if str(persisted_summary.get("correlation_id") or "").strip() != correlation_id:
        await store.ensure_correlation_id(run, correlation_id)

    settings_view = run.settings_view
    if settings_view.llm_enabled() and not settings_view.has_llm_config_snapshot():
        try:
            llm_snapshot = await snapshot_active_configs(session)
            if llm_snapshot:
                await store.stamp_llm_snapshot(run, llm_snapshot)
                settings_view = run.settings_view
        except Exception:
            logger.warning(
                "Failed to stamp LLM config snapshot for run %s", run.id, exc_info=True
            )

    resolved_url_list = _resolve_run_urls(run, settings_view)
    if persisted_url_list:
        run_url_list = persisted_url_list
    else:
        run_url_list = resolved_url_list
        await store.persist_resolved_url_list(run, run_url_list)

    return _build_batch_run_context(
        run,
        settings_view,
        correlation_id=correlation_id,
        url_list=run_url_list,
    )


async def _finalize_batch_run(
    session: AsyncSession,
    run_id: int,
    *,
    summary_patch: dict[str, object],
    aggregate_verdict: str,
    acquisition_summary: object,
) -> None:
    acquisition_summary_map = (
        dict(acquisition_summary) if isinstance(acquisition_summary, dict) else {}
    )

    await BatchRunStore(session).finalize_run(
        run_id,
        summary_patch=summary_patch,
        aggregate_verdict=aggregate_verdict,
    )
    traversal_attempted = int(
        acquisition_summary_map.get("traversal_attempted", 0) or 0
    )
    traversal_succeeded = int(
        acquisition_summary_map.get("traversal_succeeded", 0) or 0
    )
    traversal_fell_back = int(
        acquisition_summary_map.get("traversal_fell_back", 0) or 0
    )
    traversal_modes_used = dict(
        acquisition_summary_map.get("traversal_modes_used") or {}
    )
    await _log_with_retry(
        session,
        run_id,
        "info",
        "[traversal-summary] attempted="
        f"{traversal_attempted}, succeeded={traversal_succeeded}, "
        f"fell_back={traversal_fell_back}, modes={traversal_modes_used}",
    )
    await _log_with_retry(
        session,
        run_id,
        "info",
        f"[SAVE] Finalized run summary (record_count={int(summary_patch.get('record_count', 0) or 0)}, verdict={aggregate_verdict})",
    )
    await _log_with_retry(
        session,
        run_id,
        "info",
        f"Pipeline finished. {int(summary_patch.get('record_count', 0) or 0)} records. verdict={aggregate_verdict}",
    )


async def _handle_batch_run_exception(
    session: AsyncSession,
    run_id: int,
    exc: Exception,
) -> None:
    if isinstance(exc, ProxyPoolExhausted):
        await session.rollback()
        run = await session.get(CrawlRun, run_id)
        if run is None:
            return
        error_message = str(exc)
        await BatchRunStore(session).mark_proxy_exhausted(run.id, error_message)
        return

    if isinstance(exc, TimeoutError):
        await _mark_run_failed(session, run_id, "URL processing timed out")
        return

    if isinstance(exc, RunControlSignal):
        await _handle_run_control_signal(session, run_id, exc.request)
        return

    error_msg = f"{type(exc).__name__}: {exc}"
    await _mark_run_failed(session, run_id, error_msg)


async def _build_batch_url_error_result(
    session: AsyncSession,
    run_id: int,
    url: str,
    exc: Exception,
) -> URLProcessingResult:
    try:
        await session.rollback()
    except Exception:
        logger.debug(
            "Failed to rollback session after URL-level batch error for run_id=%s url=%s",
            run_id,
            url,
            exc_info=True,
        )
    error_message = str(exc).strip()
    logger.warning(
        "Continuing batch run after URL-level failure for run_id=%s url=%s: %s: %s",
        run_id,
        url,
        type(exc).__name__,
        error_message,
        exc_info=True,
    )
    return URLProcessingResult(
        records=[],
        verdict=VERDICT_ERROR,
        url_metrics={
            "pipeline_error": {
                "type": type(exc).__name__,
                "message": error_message,
            }
        },
    )


async def _process_batch_url(
    session: AsyncSession,
    run: CrawlRun,
    *,
    url: str,
    url_config: URLProcessingConfig,
    url_timeout_seconds: float,
) -> URLProcessingResult:
    try:
        async with DistributedURLSlotGuard(settings.system_max_concurrent_urls):
            async with _get_global_url_semaphore():
                return _ensure_url_processing_result(
                    await asyncio.wait_for(
                        _process_single_url(
                            session=session,
                            run=run,
                            url=url,
                            config=url_config,
                            checkpoint=lambda: _run_control_checkpoint(session, run),
                        ),
                        timeout=url_timeout_seconds,
                    )
                )
    except (ProxyPoolExhausted, RunControlSignal):
        raise
    except (TimeoutError, RuntimeError, ValueError, TypeError, OSError) as exc:
        return await _build_batch_url_error_result(session, run.id, url, exc)


async def process_run(session: AsyncSession, run_id: int) -> None:
    correlation_token: str | None = None
    try:
        context = await _load_batch_run_context(session, run_id)
        if context is None:
            return
        run = context.run
        correlation_token = set_correlation_id(context.correlation_id)
        url_list = context.url_list
        proxy_list = context.proxy_list
        traversal_mode = context.traversal_mode
        max_pages = context.max_pages
        max_scrolls = context.max_scrolls
        max_records = context.max_records
        sleep_ms = context.sleep_ms
        url_timeout_seconds = context.url_timeout_seconds
        await _log_with_retry(
            session,
            run.id,
            "info",
            f"[traversal] mode={traversal_mode}, advanced={context.advanced_enabled}, url={url_list[0] if url_list else ''}",
        )

        total_urls = context.total_urls
        persisted_record_count = await _count_run_records(session, run.id)
        progress_state = run.build_batch_progress_state(
            total_urls=total_urls,
            url_domain=_domain(url_list[0]) if url_list else "",
            persisted_record_count=persisted_record_count,
        )
        pending_items = [
            (idx, url)
            for idx, url in enumerate(url_list)
            if idx >= progress_state.completed_count
            and not str(
                progress_state.url_verdicts[idx]
                if idx < len(progress_state.url_verdicts)
                else ""
            ).strip()
        ]
        persisted_record_count = progress_state.persisted_record_count
        url_verdicts = progress_state.url_verdicts
        acquisition_summary = progress_state.acquisition_summary

        for idx, url in pending_items:
            remaining_records = max(max_records - persisted_record_count, 0)
            if remaining_records <= 0:
                await log_event(
                    session,
                    run.id,
                    "info",
                    f"Reached max_records ceiling ({max_records})",
                )
                break

            await log_event(
                session,
                run.id,
                "info",
                f"Processing URL {idx + 1}/{total_urls}: {url}",
            )
            await set_stage(
                session,
                run,
                STAGE_FETCH,
                current_url=url,
                current_url_index=idx + 1,
                total_urls=total_urls,
            )

            url_config = URLProcessingConfig(
                proxy_list=proxy_list,
                traversal_mode=traversal_mode,
                max_pages=max_pages,
                max_scrolls=max_scrolls,
                max_records=remaining_records,
                sleep_ms=sleep_ms,
            )
            url_result = await _process_batch_url(
                session,
                run,
                url=url,
                url_config=url_config,
                url_timeout_seconds=url_timeout_seconds,
            )
            pipeline_error = (
                url_result.url_metrics.get("pipeline_error")
                if isinstance(url_result.url_metrics, dict)
                else None
            )
            combined_error: str | None = None
            if isinstance(pipeline_error, dict):
                error_type = str(pipeline_error.get("type") or "").strip()
                error_message = str(pipeline_error.get("message") or "").strip()
                combined_error = ": ".join(
                    part for part in (error_type, error_message) if part
                ) or None
            await persist_batch_url_result(
                state=progress_state,
                session=session,
                run_id=run.id,
                retry_run_update=_retry_run_update,
                idx=idx,
                url=url,
                records_count=len(url_result.records),
                verdict=url_result.verdict,
                url_metrics=url_result.url_metrics,
                error_message=combined_error,
            )
            persisted_record_count = progress_state.persisted_record_count
            url_verdicts = progress_state.url_verdicts
            acquisition_summary = progress_state.acquisition_summary
            if persisted_record_count >= max_records:
                await log_event(
                    session,
                    run.id,
                    "info",
                    f"Stopped after reaching max_records={max_records}",
                )
                break

            if sleep_ms > 0 and idx < total_urls - 1:
                await _sleep_with_checkpoint(
                    sleep_ms, lambda: _run_control_checkpoint(session, run)
                )

        aggregate_verdict = _aggregate_verdict(url_verdicts)
        await _finalize_batch_run(
            session,
            run.id,
            summary_patch=progress_state.build_final_patch(aggregate_verdict),
            aggregate_verdict=aggregate_verdict,
            acquisition_summary=acquisition_summary,
        )

    except (
        ProxyPoolExhausted,
        TimeoutError,
        RunControlSignal,
        RuntimeError,
        ValueError,
        TypeError,
        OSError,
    ) as exc:
        await _handle_batch_run_exception(session, run_id, exc)
    finally:
        if correlation_token is not None:
            reset_correlation_id(correlation_token)


async def _sleep_with_checkpoint(sleep_ms: int, checkpoint) -> None:
    remaining_ms = max(0, int(sleep_ms or 0))
    while remaining_ms > 0:
        await checkpoint()
        current_ms = min(remaining_ms, 250)
        await asyncio.sleep(current_ms / 1000)
        remaining_ms -= current_ms
    await checkpoint()


async def _handle_run_control_signal(
    session: AsyncSession,
    run_id: int,
    request: str,
) -> None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    if request == CONTROL_REQUEST_PAUSE:
        if run.status_value != CrawlStatus.PAUSED:
            update_run_status(run, CrawlStatus.PAUSED)
        set_control_request(run, None)
        await log_event(session, run.id, "warning", "Run paused at checkpoint")
        await session.commit()
        return
    if run.status_value != CrawlStatus.KILLED:
        update_run_status(run, CrawlStatus.KILLED)
    set_control_request(run, None)
    await log_event(session, run.id, "warning", "Run killed at checkpoint")
    await session.commit()


_domain = normalize_domain
