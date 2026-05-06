from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from app.core.database import SessionLocal
from app.models.crawl import CrawlRun
from app.services.crawl_state import (
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    TERMINAL_STATUSES,
    CrawlStatus,
    get_control_request,
    set_control_request,
    update_run_status,
)
from app.services.crawl_utils import normalize_target_url, parse_csv_urls_async
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_utils import normalize_domain
from app.services.pipeline.core import process_single_url
from app.services.pipeline.runtime_helpers import (
    STAGE_ACQUIRE,
    log_event,
    mark_run_failed,
    set_stage,
)
from app.services.pipeline.types import URLProcessingConfig, URLProcessingResult
from app.services.publish import VERDICT_ERROR, _aggregate_verdict
from app.services.run_summary import as_int
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _require_url_processing_result(url_result: object) -> URLProcessingResult:
    if isinstance(url_result, URLProcessingResult):
        return url_result
    raise TypeError(f"Unexpected URL result type: {type(url_result)!r}")


async def _resolve_run_urls(run: CrawlRun, settings_view) -> list[str]:
    urls = settings_view.urls()
    if run.run_type == "batch" and urls:
        url_list = urls
    elif run.run_type == "csv" and settings_view.get("csv_content"):
        url_list = await parse_csv_urls_async(settings_view.get("csv_content"))
    elif run.url:
        url_list = [run.url]
    else:
        raise ValueError("No URL provided")
    return [
        value for value in (normalize_target_url(item) for item in url_list) if value
    ]


def _current_duration_ms(run: CrawlRun) -> int:
    if not isinstance(run.created_at, datetime):
        return 0
    return max(0, int((datetime.now(UTC) - run.created_at).total_seconds() * 1000))


def _touch_run_heartbeat(run: CrawlRun) -> None:
    run.last_heartbeat_at = datetime.now(UTC)


def _url_timeout_seconds(settings_view) -> float:
    configured_timeout = settings_view.get("url_timeout_seconds")
    if configured_timeout not in (None, ""):
        return settings_view.url_timeout_seconds()
    return crawler_runtime_settings.default_url_process_timeout_seconds()


def _url_failure_metrics(exc: BaseException) -> dict[str, object]:
    metrics: dict[str, object] = {"error": f"{type(exc).__name__}: {exc}"}
    browser_diagnostics = getattr(exc, "browser_diagnostics", None)
    if not isinstance(browser_diagnostics, dict):
        return metrics
    diagnostics = dict(browser_diagnostics)
    metrics["browser_diagnostics"] = diagnostics
    failure_reason = str(diagnostics.get("failure_reason") or "").strip()
    if failure_reason:
        metrics["failure_reason"] = failure_reason
    browser_outcome = str(diagnostics.get("browser_outcome") or "").strip()
    if browser_outcome:
        metrics["browser_outcome"] = browser_outcome
    if diagnostics.get("browser_attempted") is not None:
        metrics["browser_attempted"] = bool(diagnostics.get("browser_attempted"))
    return metrics


async def _rollback_url_session(session: AsyncSession, *, context: str) -> bool:
    try:
        await session.rollback()
        session.expire_all()
        return True
    except Exception:
        logger.debug("Session rollback failed during %s", context, exc_info=True)
        return False


async def _recover_url_failure(
    session: AsyncSession,
    *,
    run: CrawlRun | None = None,
    run_id: int,
    url: str,
    exc: BaseException,
    log_message: str,
) -> tuple[CrawlRun, URLProcessingResult]:
    await _rollback_url_session(session, context="URL failure recovery")
    if run is not None:
        with suppress(Exception):
            session.expire(run)
        with suppress(Exception):
            await session.refresh(run)
    recovery_error: Exception | None = None
    try:
        run = await _persist_url_failure_log(
            session,
            run_id=run_id,
            url=url,
            exc=exc,
            log_message=log_message,
        )
    except Exception as original_session_error:
        recovery_error = original_session_error
        logger.debug(
            "Original session unusable for URL failure recovery; falling back to SessionLocal",
            exc_info=True,
        )
        await _rollback_url_session(session, context="before URL recovery fallback")
        try:
            async with SessionLocal() as recovery:
                await _persist_url_failure_log(
                    recovery,
                    run_id=run_id,
                    url=url,
                    exc=exc,
                    log_message=log_message,
                )
        except Exception as fallback_error:
            recovery_error = fallback_error
            logger.exception(
                "Failed to persist URL failure log for run=%s url=%s",
                run_id,
                url,
            )
        await _rollback_url_session(session, context="after URL recovery fallback")
        try:
            reloaded_run = await session.get(CrawlRun, run_id, populate_existing=True)
        except Exception as reload_error:
            logger.debug(
                "Failed to reload run after URL failure recovery; keeping current instance",
                exc_info=True,
            )
            if run is None:
                raise RuntimeError(
                    f"Original session unusable after URL failure recovery for run {run_id}"
                ) from reload_error
        else:
            if reloaded_run is not None:
                run = reloaded_run
    if run is None:
        raise RuntimeError(f"Run {run_id} disappeared after URL failure") from exc
    metrics = _url_failure_metrics(exc)
    if recovery_error is not None:
        metrics["failure_log_persistence_error"] = (
            f"{type(recovery_error).__name__}: {recovery_error}"
        )
        metrics["failure_log_persisted"] = False
    return run, URLProcessingResult(
        records=[],
        verdict=VERDICT_ERROR,
        url_metrics=metrics,
    )


async def _persist_url_failure_log(
    session: AsyncSession,
    *,
    run_id: int,
    url: str,
    exc: BaseException,
    log_message: str,
) -> CrawlRun:
    run = await session.get(CrawlRun, run_id, populate_existing=True)
    if run is None:
        raise RuntimeError(f"Run {run_id} disappeared after URL failure") from exc
    logger.warning("URL processing failed for run=%s url=%s", run_id, url, exc_info=True)
    await log_event(session, run.id, "warning", log_message)
    await session.commit()
    return run


async def process_run(session: AsyncSession, run_id: int) -> None:
    try:
        run = await session.get(CrawlRun, run_id, populate_existing=True)
        if run is None or run.status_value in TERMINAL_STATUSES:
            return
        await session.refresh(run)
        if run.status_value == CrawlStatus.PAUSED:
            return
        if run.status_value == CrawlStatus.PENDING:
            update_run_status(run, CrawlStatus.RUNNING)

        _touch_run_heartbeat(run)
        settings_view = run.settings_view
        url_list = await _resolve_run_urls(run, settings_view)
        total_urls = len(url_list)
        if total_urls == 0:
            raise ValueError("No URL provided")

        max_records = settings_view.max_records()
        sleep_ms = settings_view.sleep_ms()
        url_timeout_seconds = _url_timeout_seconds(settings_view)

        progress_state = run.build_batch_progress_state(
            total_urls=total_urls,
            url_domain=normalize_domain(url_list[0]) if url_list else "",
            persisted_record_count=as_int(run.get_summary("record_count", 0)),
        )
        run.update_summary(
            **progress_state.build_progress_patch(
                current_url=url_list[0] if url_list else "",
                current_url_index=0,
            ),
            current_stage=STAGE_ACQUIRE,
            resolved_url_list=url_list,
        )
        await session.commit()

        verdicts: list[str] = []
        record_count = as_int(run.get_summary("record_count", 0))

        for idx, url in enumerate(url_list, start=1):
            await session.refresh(run)
            _touch_run_heartbeat(run)
            control_request = get_control_request(run)
            if control_request == CONTROL_REQUEST_PAUSE:
                update_run_status(run, CrawlStatus.PAUSED)
                set_control_request(run, None)
                await log_event(session, run.id, "warning", "Run paused at checkpoint")
                await session.commit()
                return
            if control_request == CONTROL_REQUEST_KILL:
                update_run_status(run, CrawlStatus.KILLED)
                set_control_request(run, None)
                await log_event(session, run.id, "warning", "Run killed at checkpoint")
                await session.commit()
                return

            if idx == 1:
                await log_event(session, run.id, "info", f"Starting crawl run for {url}")
                await log_event(session, run.id, "info", f"Resolved {total_urls} seed URL(s), domain policy: standard")
            else:
                await log_event(session, run.id, "info", f"Starting crawl run for {url} ({idx}/{total_urls})")
            await set_stage(
                session,
                run,
                STAGE_ACQUIRE,
                current_url=url,
                current_url_index=idx,
                total_urls=total_urls,
            )
            await session.commit()
            remaining_records = max(max_records - record_count, 1)
            url_config = URLProcessingConfig.from_acquisition_plan(
                run.settings_view.acquisition_plan(
                    surface=run.surface,
                    max_records=remaining_records,
                ),
                update_run_state=True,
                persist_logs=True,
            )
            try:
                url_result = _require_url_processing_result(
                    await asyncio.wait_for(
                        process_single_url(
                            session=session,
                            run=run,
                            url=url,
                            config=url_config,
                        ),
                        timeout=url_timeout_seconds,
                    )
                )
            except TimeoutError as exc:
                logger.warning("URL processing timed out for run=%s url=%s", run.id, url)
                run, url_result = await _recover_url_failure(
                    session,
                    run=run,
                    run_id=run.id,
                    url=url,
                    exc=exc,
                    log_message=(
                        f"URL processing timed out for {url} "
                        f"(timeout_seconds={url_timeout_seconds})"
                    ),
                )
                url_result.url_metrics["error"] = (
                    f"TimeoutError: url exceeded timeout_seconds={url_timeout_seconds}"
                )
            except SQLAlchemyError as exc:
                run, url_result = await _recover_url_failure(
                    session,
                    run=run,
                    run_id=run.id,
                    url=url,
                    exc=exc,
                    log_message=(
                        f"URL processing failed for {url}: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            except Exception as exc:
                run, url_result = await _recover_url_failure(
                    session,
                    run=run,
                    run_id=run.id,
                    url=url,
                    exc=exc,
                    log_message=(
                        f"URL processing failed for {url}: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )

            verdicts.append(str(url_result.verdict or VERDICT_ERROR))
            records_count = as_int(
                url_result.url_metrics.get("record_count", len(url_result.records))
            )
            record_count += records_count
            progress_state.record_url_result(
                idx=idx - 1,
                records_count=records_count,
                verdict=str(url_result.verdict or VERDICT_ERROR),
                url_metrics=url_result.url_metrics,
            )
            _touch_run_heartbeat(run)
            run.update_summary(
                **progress_state.build_progress_patch(
                    current_url=url,
                    current_url_index=idx,
                ),
                duration_ms=_current_duration_ms(run),
            )
            await session.commit()

            if record_count >= max_records:
                await log_event(
                    session,
                    run.id,
                    "info",
                    f"Stopped after reaching max_records={max_records}",
                )
                await session.commit()
                break
            if sleep_ms > 0 and idx < total_urls:
                await asyncio.sleep(sleep_ms / 1000)

        await session.refresh(run)
        if run.status_value in TERMINAL_STATUSES:
            return
        aggregate_verdict = _aggregate_verdict(verdicts)
        update_run_status(run, CrawlStatus.COMPLETED)
        _touch_run_heartbeat(run)
        run.update_summary(
            **progress_state.build_final_patch(aggregate_verdict),
            duration_ms=_current_duration_ms(run),
        )
        await log_event(
            session,
            run.id,
            "info",
            f"Pipeline finished. {record_count} records. verdict={aggregate_verdict}",
        )
        await session.commit()
    except (RuntimeError, ValueError, TypeError, SQLAlchemyError) as exc:
        logger.exception("Run-level failure for run=%s", run_id)
        await _rollback_url_session(session, context="run failure marking")
        await mark_run_failed(session, run_id, f"{type(exc).__name__}: {exc}")
