from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.models.crawl import CrawlLog, CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult, PageEvidence
from app.services.crawl_state import TERMINAL_STATUSES, CrawlStatus, update_run_status
from app.services.db_utils import mapping_or_empty
from app.services.publish import VERDICT_ERROR, is_effectively_blocked
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError


STAGE_ACQUIRE = "ACQUIRE"
STAGE_EXTRACT = "EXTRACT"
STAGE_NORMALIZE = "NORMALIZE"
STAGE_PERSIST = "PERSIST"


async def log_event(session, run_id: int | None, level: str, message: str) -> None:
    if run_id is None:
        return
    session.add(CrawlLog(run_id=run_id, level=level, message=str(message or "")))
    await session.flush()


async def set_stage(
    session,
    run,
    stage: str,
    *,
    current_url: str | None = None,
    current_url_index: int | None = None,
    total_urls: int | None = None,
) -> None:
    summary = run.summary_dict()
    summary["current_stage"] = stage
    if current_url is not None:
        summary["current_url"] = current_url
    if current_url_index is not None:
        summary["current_url_index"] = current_url_index
    if total_urls is not None:
        summary["url_count"] = total_urls
    run.result_summary = summary
    await session.flush()


logger = logging.getLogger(__name__)

def browser_attempted(acquisition_result: AcquisitionResult) -> bool:
    return PageEvidence.from_acquisition_result(acquisition_result).browser_attempted

def browser_outcome(acquisition_result: AcquisitionResult) -> str:
    return PageEvidence.from_acquisition_result(acquisition_result).browser_outcome


def browser_launch_log_message(acquisition_result: AcquisitionResult) -> str:
    diagnostics = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    engine = str(diagnostics.get("browser_engine") or "chromium").strip().lower() or "chromium"
    launch_mode = str(diagnostics.get("browser_launch_mode") or "").strip().lower()
    if not launch_mode:
        launch_mode = "headless"
    proxy_label = str(diagnostics.get("proxy_url_redacted") or "direct").strip() or "direct"
    profile = str(diagnostics.get("browser_profile") or "").strip()
    details = [engine, f"proxy: {proxy_label}"]
    if profile:
        details.append(f"profile: {profile}")
    return f"Launched {launch_mode} browser ({', '.join(details)})"


def effective_blocked(acquisition_result: AcquisitionResult) -> bool:
    return is_effectively_blocked(acquisition_result)


def suppress_empty_downstream_record_logs(
    acquisition_result: AcquisitionResult,
    records: list[dict[str, object]],
) -> bool:
    return not records and effective_blocked(acquisition_result)

def screenshot_required(browser_outcome: str) -> bool:
    return browser_outcome in {
        "challenge_page",
        "location_required",
        "low_content_shell",
        "navigation_failed",
        "traversal_failed",
        "render_timeout",
    }

def browser_result_is_extractable(acquisition_result: AcquisitionResult) -> bool:
    if getattr(acquisition_result, "method", "") != "browser":
        return True
    return browser_outcome(acquisition_result) in {"", "usable_content"}

def merge_browser_diagnostics(
    acquisition_result: AcquisitionResult,
    diagnostics: dict[str, object],
) -> None:
    merged = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    merged.update(dict(diagnostics or {}))
    acquisition_result.browser_diagnostics = merged



async def mark_run_failed(session: AsyncSession, run_id: int, error_msg: str) -> None:
    try:
        await session.rollback()
    except SQLAlchemyError:
        logger.debug("Session rollback failed before failure persistence", exc_info=True)
    try:
        await persist_failure_state(session, run_id, error_msg)
        return
    except SQLAlchemyError:
        logger.debug(
            "Original session unusable for failure recovery; falling back to SessionLocal",
            exc_info=True,
        )
    try:
        async with SessionLocal() as recovery:
            await persist_failure_state(recovery, run_id, error_msg)
    except SQLAlchemyError:
        logger.critical(
            "Failure recovery via SessionLocal failed for run_id=%s — "
            "run may be stuck in RUNNING state (zombie run). "
            "Original error: %s",
            run_id,
            error_msg,
            exc_info=True,
        )
        return

async def persist_failure_state(
    session: AsyncSession,
    run_id: int,
    error_msg: str,
) -> None:
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
