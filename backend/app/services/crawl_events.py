from __future__ import annotations

import logging
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.crawl import CrawlLog, CrawlRun
from app.services.db_utils import sqlite_write_lock, with_retry

logger = logging.getLogger("app.crawl.events")
_LEVEL_ORDER = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "error": 40,
    "critical": 50,
}
_URL_PROGRESS_PATTERN = re.compile(r"^Processing URL \d+/\d+: ")
_url_progress_counters: dict[int, int] = {}
_db_log_counters: dict[int, int] = {}


def clear_url_progress_counter(run_id: int) -> None:
    _url_progress_counters.pop(run_id, None)
    _db_log_counters.pop(run_id, None)


def _isoformat(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def serialize_log_event(log: CrawlLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "run_id": log.run_id,
        "level": log.level,
        "message": log.message,
        "created_at": _isoformat(log.created_at),
    }


def serialize_run_snapshot(run: CrawlRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "result_summary": dict(run.result_summary or {}),
        "updated_at": _isoformat(run.updated_at),
        "completed_at": _isoformat(run.completed_at),
    }


def _normalize_level(level: str) -> str:
    normalized = str(level or "").strip().lower()
    return normalized if normalized in _LEVEL_ORDER else "info"


def _format_message(message: str, correlation_id: str | None) -> str:
    text = str(message or "")
    if text.startswith("[corr:"):
        text = text.split("]", 1)[1] if "]" in text else text
    return text


def _should_persist_log(level: str, run_id: int, message: str) -> bool:
    min_level = _normalize_level(settings.crawl_log_db_min_level)
    log_level = _normalize_level(level)
    if _LEVEL_ORDER[log_level] < _LEVEL_ORDER[min_level]:
        return False
    sample_rate = max(1, int(settings.crawl_log_db_url_progress_sample_rate or 1))
    if sample_rate > 1 and log_level == "info" and _URL_PROGRESS_PATTERN.match(message):
        counter = _url_progress_counters.get(run_id, 0) + 1
        _url_progress_counters[run_id] = counter
        return counter % sample_rate == 1
    max_rows = max(1, int(settings.crawl_log_db_max_rows_per_run or 1))
    db_count = _db_log_counters.get(run_id, 0)
    if db_count >= max_rows:
        return False
    _db_log_counters[run_id] = db_count + 1
    return True


def _run_log_path(run_id: int) -> Path:
    return settings.crawl_log_file_dir / f"run_{int(run_id)}.jsonl"


def _append_log_file_line(
    *,
    run_id: int,
    level: str,
    message: str,
    created_at: datetime,
) -> None:
    if not bool(settings.crawl_log_file_enabled):
        return
    path = _run_log_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "run_id": int(run_id),
            "level": str(level or "info"),
            "message": str(message or ""),
            "created_at": created_at.isoformat(),
        },
        ensure_ascii=True,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def prepare_log_event(run_id: int, level: str, message: str) -> tuple[str, str, bool]:
    normalized_level = _normalize_level(level)
    formatted_message = _format_message(message, None)
    logger.log(
        _LEVEL_ORDER.get(normalized_level, logging.INFO),
        "run_id=%s %s",
        run_id,
        formatted_message,
    )
    should_persist = _should_persist_log(normalized_level, run_id, formatted_message)
    return normalized_level, formatted_message, should_persist


async def append_log_event(
    run_id: int,
    level: str,
    message: str,
    *,
    preformatted: bool = False,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    if preformatted:
        normalized_level, formatted_message, should_persist = (
            _normalize_level(level),
            str(message or ""),
            _should_persist_log(level, run_id, str(message or "")),
        )
    else:
        normalized_level, formatted_message, should_persist = prepare_log_event(
            run_id, level, message
        )
    created_at = datetime.now()
    try:
        _append_log_file_line(
            run_id=run_id,
            level=normalized_level,
            message=formatted_message,
            created_at=created_at,
        )
    except OSError:
        logger.debug(
            "Unable to append crawl log file line for run_id=%s",
            run_id,
            exc_info=True,
        )
    if not should_persist:
        return {
            "id": None,
            "run_id": run_id,
            "level": normalized_level,
            "message": formatted_message,
            "created_at": created_at.isoformat(),
        }

    async def _operation(retry_session: AsyncSession) -> CrawlLog:
        row = CrawlLog(
            run_id=run_id,
            level=normalized_level,
            message=formatted_message,
        )
        retry_session.add(row)
        await retry_session.flush()
        return row

    if session is not None:
        row = await _operation(session)
        # We don't commit here because it's the caller's session.
        # But we do need to return serialized log.
        return serialize_log_event(row)

    async with SessionLocal() as new_session:
        row = await with_retry(new_session, _operation)
        await new_session.refresh(row)
        return serialize_log_event(row)


async def persist_run_summary_patch(
    *,
    run_id: int,
    summary_patch: dict[str, Any],
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    async def _operation(retry_session: AsyncSession) -> CrawlRun | None:
        bind = retry_session.bind
        is_sqlite = bind is not None and bind.dialect.name == "sqlite"
        if not is_sqlite:
            result = await retry_session.execute(
                select(CrawlRun).where(CrawlRun.id == run_id).with_for_update()
            )
            run = result.scalar_one_or_none()
        else:
            run = await retry_session.get(CrawlRun, run_id)
        if run is None:
            return None
        result_summary = dict(run.result_summary or {})
        merged_summary = _merge_run_summary_patch(result_summary, summary_patch)
        if merged_summary == result_summary:
            return run
        run.result_summary = merged_summary
        await retry_session.flush()
        return run

    if session is not None:
        bind = session.bind
        if bind is not None and bind.dialect.name == "sqlite":
            async with sqlite_write_lock:
                run = await _operation(session)
        else:
            run = await _operation(session)
        if run is None:
            return None
        return serialize_run_snapshot(run)

    async with SessionLocal() as new_session:
        bind = new_session.bind
        if bind is not None and bind.dialect.name == "sqlite":
            async with sqlite_write_lock:
                run = await with_retry(new_session, _operation)
        else:
            run = await with_retry(new_session, _operation)
        if run is None:
            return None
        await new_session.refresh(run)
        return serialize_run_snapshot(run)


def _merge_run_summary_patch(current: object, patch: dict[str, Any]) -> dict[str, Any]:
    summary = dict(current) if isinstance(current, dict) else {}
    merged = {**summary, **patch}

    # Preserve monotonic counters/progress when late/stale writes race in.
    for key in ("url_count", "record_count", "progress", "processed_urls", "completed_urls"):
        if key in summary or key in patch:
            merged[key] = max(_as_int(summary.get(key)), _as_int(patch.get(key)))

    if "remaining_urls" in patch:
        prev_remaining = summary.get("remaining_urls")
        if prev_remaining is None:
            merged["remaining_urls"] = _as_int(patch.get("remaining_urls"))
        else:
            merged["remaining_urls"] = min(
                _as_int(prev_remaining),
                _as_int(patch.get("remaining_urls")),
            )

    if "url_verdicts" in patch or "url_verdicts" in summary:
        merged["url_verdicts"] = _merge_url_verdicts(
            summary.get("url_verdicts"),
            patch.get("url_verdicts"),
        )

    if "verdict_counts" in patch or "verdict_counts" in summary:
        merged["verdict_counts"] = _merge_verdict_counts(
            summary.get("verdict_counts"),
            patch.get("verdict_counts"),
        )

    return merged


def _merge_url_verdicts(current: object, patch: object) -> list[str]:
    current_list = list(current) if isinstance(current, list) else []
    patch_list = list(patch) if isinstance(patch, list) else []
    max_len = max(len(current_list), len(patch_list))
    merged: list[str] = []
    for idx in range(max_len):
        patch_value = str(patch_list[idx] or "").strip() if idx < len(patch_list) else ""
        current_value = str(current_list[idx] or "").strip() if idx < len(current_list) else ""
        merged.append(patch_value or current_value)
    return merged


def _merge_verdict_counts(current: object, patch: object) -> dict[str, int]:
    current_map = dict(current) if isinstance(current, dict) else {}
    patch_map = dict(patch) if isinstance(patch, dict) else {}
    keys = set(current_map) | set(patch_map)
    merged: dict[str, int] = {}
    for key in keys:
        merged[str(key)] = max(_as_int(current_map.get(key)), _as_int(patch_map.get(key)))
    return merged


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def load_run_for_events(
    session: AsyncSession,
    *,
    run_id: int,
) -> CrawlRun | None:
    return await session.get(CrawlRun, run_id)
