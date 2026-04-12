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
from app.services.acquisition import ProxyPoolExhausted
from app.services.crawl_state import (
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    TERMINAL_STATUSES,
    CrawlStatus,
    get_control_request,
    set_control_request,
    update_run_status,
)
from app.services.exceptions import RunControlError
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
    STAGE_SAVE,
    log_event,
    set_stage,
)
from app.services.pipeline.verdict import (
    VERDICT_BLOCKED,
    VERDICT_EMPTY,
    VERDICT_LISTING_FAILED,
    VERDICT_PARTIAL,
    VERDICT_SCHEMA_MISS,
    VERDICT_SUCCESS,
    _aggregate_verdict,
)
from app.services.llm_runtime import snapshot_active_configs
from app.services.pipeline.types import URLProcessingConfig, URLProcessingResult
from app.services.config.crawl_runtime import (
    MAX_URL_PROCESS_TIMEOUT_SECONDS,
    URL_PROCESS_TIMEOUT_SECONDS,
)
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.resource_monitor import MemoryAdaptiveSemaphore

logger = logging.getLogger(__name__)
_global_url_semaphore: MemoryAdaptiveSemaphore | None = None
_global_url_semaphore_limit: int | None = None
_RUN_UPDATE_LOCK_RETRY_DELAYS_SECONDS = (0.0, 0.05, 0.1, 0.2, 0.5)
_LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"
_LOCK_NOT_AVAILABLE_ERROR_CODES = {"1205", "1222", "3572"}
_LOCK_NOT_AVAILABLE_MESSAGE_FRAGMENTS = (
    "could not obtain lock",
    "lock not available",
    "could not acquire lock",
    "database is locked",
    "database table is locked",
    "lock wait timeout exceeded",
    "nowait is set",
)


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


def _build_batch_run_context(
    run: CrawlRun,
    settings_view: CrawlRunSettings,
    *,
    correlation_id: str,
) -> _BatchRunContext:
    return _BatchRunContext(
        run=run,
        correlation_id=correlation_id,
        url_list=_resolve_run_urls(run, settings_view),
        proxy_list=settings_view.proxy_list(),
        traversal_mode=settings_view.traversal_mode(),
        max_pages=settings_view.max_pages(),
        max_scrolls=settings_view.max_scrolls(),
        max_records=settings_view.max_records(),
        sleep_ms=settings_view.sleep_ms(),
        advanced_enabled=settings_view.advanced_enabled(),
        url_timeout_seconds=_coerce_url_timeout_seconds(settings_view),
    )


async def _retry_run_update(
    session: AsyncSession,
    run_id: int,
    mutate,
) -> None:
    """Persist pending changes and update the run row in one retried transaction."""
    await session.flush()
    for attempt, delay_seconds in enumerate(
        _RUN_UPDATE_LOCK_RETRY_DELAYS_SECONDS,
        start=1,
    ):
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        try:
            run_missing = False
            async with session.begin_nested():
                result = await session.execute(
                    select(CrawlRun).where(CrawlRun.id == run_id).with_for_update(nowait=True)
                )
                run = result.scalar_one_or_none()
                if run is None:
                    run_missing = True
                else:
                    await mutate(session, run)
            if run_missing:
                await session.commit()
                return
            await session.commit()
            return
        except OperationalError as exc:
            if _is_lock_not_available_error(exc) and attempt < len(
                _RUN_UPDATE_LOCK_RETRY_DELAYS_SECONDS
            ):
                logger.debug(
                    "Retrying crawl run update after lock contention for run_id=%s (attempt=%s)",
                    run_id,
                    attempt,
                )
                continue
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise


def _is_lock_not_available_error(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)
    for attr_name in ("sqlstate", "pgcode"):
        code = str(getattr(orig, attr_name, "") or "").strip()
        if code == _LOCK_NOT_AVAILABLE_SQLSTATE:
            return True
    args = getattr(orig, "args", ())
    if args:
        code = str(args[0] or "").strip()
        if code in _LOCK_NOT_AVAILABLE_ERROR_CODES:
            return True
    message = " ".join(
        part
        for part in (
            str(orig or "").strip(),
            str(exc or "").strip(),
        )
        if part
    ).lower()
    return any(fragment in message for fragment in _LOCK_NOT_AVAILABLE_MESSAGE_FRAGMENTS)


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
    current_status = run.status_value
    if current_status == CrawlStatus.PENDING:

        async def _start_mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            update_run_status(retry_run, CrawlStatus.RUNNING)

        await _retry_run_update(session, run.id, _start_mutation)
        await _log_with_retry(session, run.id, "info", "Pipeline started")
    else:

        async def _resume_mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            return None

        await _retry_run_update(session, run.id, _resume_mutation)
        await _log_with_retry(session, run.id, "info", "Pipeline resumed")
    await session.refresh(run)


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

    if str(persisted_summary.get("correlation_id") or "").strip() != correlation_id:

        async def _correlation_mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            retry_run.update_summary(correlation_id=correlation_id)

        await _retry_run_update(session, run.id, _correlation_mutation)
        await session.refresh(run)

    settings_view = run.settings_view
    if settings_view.llm_enabled() and not settings_view.has_llm_config_snapshot():
        try:
            llm_snapshot = await snapshot_active_configs(session)
            if llm_snapshot:

                async def _stamp_llm_snapshot(
                    retry_session: AsyncSession, retry_run: CrawlRun
                ) -> None:
                    retry_run.settings = retry_run.settings_view.with_updates(
                        llm_config_snapshot=llm_snapshot
                    ).as_dict()

                await _retry_run_update(session, run.id, _stamp_llm_snapshot)
                await session.refresh(run)
                settings_view = run.settings_view
        except Exception:
            logger.warning(
                "Failed to stamp LLM config snapshot for run %s", run.id, exc_info=True
            )

    return _build_batch_run_context(
        run,
        settings_view,
        correlation_id=correlation_id,
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

    async def _finalize_mutation(
        retry_session: AsyncSession, retry_run: CrawlRun
    ) -> None:
        current_status = retry_run.status_value
        if current_status == CrawlStatus.RUNNING:
            if aggregate_verdict == VERDICT_SUCCESS:
                update_run_status(retry_run, CrawlStatus.COMPLETED)
            elif aggregate_verdict in {
                VERDICT_PARTIAL,
                VERDICT_EMPTY,
                VERDICT_BLOCKED,
                VERDICT_SCHEMA_MISS,
                VERDICT_LISTING_FAILED,
            }:
                update_run_status(retry_run, CrawlStatus.FAILED)
        retry_run.merge_summary_patch(
            {
                **summary_patch,
                "current_stage": STAGE_SAVE,
            }
        )

    await _retry_run_update(session, run_id, _finalize_mutation)
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

        async def _proxy_exhausted_mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            update_run_status(retry_run, CrawlStatus.PROXY_EXHAUSTED)
            retry_run.merge_summary_patch(
                {
                    "error": error_message,
                    "extraction_verdict": "proxy_exhausted",
                }
            )
            await log_event(retry_session, retry_run.id, "error", error_message)

        await _retry_run_update(session, run.id, _proxy_exhausted_mutation)
        return

    if isinstance(exc, TimeoutError):
        await _mark_run_failed(session, run_id, "URL processing timed out")
        return

    if isinstance(exc, RunControlSignal):
        await _handle_run_control_signal(session, run_id, exc.request)
        return

    error_msg = f"{type(exc).__name__}: {exc}"
    await _mark_run_failed(session, run_id, error_msg)


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
        pending_items = list(
            enumerate(
                url_list[progress_state.completed_count :],
                start=progress_state.completed_count,
            )
        )
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

            async with _get_global_url_semaphore():
                url_config = URLProcessingConfig(
                    proxy_list=proxy_list,
                    traversal_mode=traversal_mode,
                    max_pages=max_pages,
                    max_scrolls=max_scrolls,
                    max_records=remaining_records,
                    sleep_ms=sleep_ms,
                )
                url_result = _ensure_url_processing_result(
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
            await progress_state.persist_url_result(
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
