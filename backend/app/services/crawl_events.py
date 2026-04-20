from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis import redis_fail_open, schedule_fail_open
from app.models.crawl import CrawlLog, CrawlRun
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger("app.crawl.events")
_LEVEL_ORDER = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "error": 40,
    "critical": 50,
}
_URL_PROGRESS_PATTERN = re.compile(r"^Processing URL \d+/\d+: ")
_COUNTER_TTL_SECONDS = 86400
_REDIS_KEY_PREFIX = "crawl:events"
_DETACHED_LOG_WRITE_CONCURRENCY = 8
_DETACHED_LOG_WRITE_SEMAPHORE = asyncio.Semaphore(_DETACHED_LOG_WRITE_CONCURRENCY)


def clear_url_progress_counter(run_id: int) -> None:
    schedule_fail_open(
        lambda redis: redis.delete(
            _url_progress_counter_key(run_id),
            _db_log_counter_key(run_id),
        ),
        operation_name=f"clear_url_progress_counter:{run_id}",
    )


async def clear_url_progress_counter_async(run_id: int) -> None:
    await redis_fail_open(
        lambda redis: redis.delete(
            _url_progress_counter_key(run_id),
            _db_log_counter_key(run_id),
        ),
        default=0,
        operation_name=f"clear_url_progress_counter:{run_id}",
    )


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
        "result_summary": run.summary_dict(),
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


def _url_progress_counter_key(run_id: int) -> str:
    return f"{_REDIS_KEY_PREFIX}:progress:{int(run_id)}"


def _db_log_counter_key(run_id: int) -> str:
    return f"{_REDIS_KEY_PREFIX}:db:{int(run_id)}"


def _should_persist_log_without_redis(level: str) -> bool:
    return _LEVEL_ORDER[_normalize_level(level)] >= _LEVEL_ORDER["info"]


async def _should_persist_log(level: str, run_id: int, message: str) -> bool:
    min_level = _normalize_level(settings.crawl_log_db_min_level)
    log_level = _normalize_level(level)
    if _LEVEL_ORDER[log_level] < _LEVEL_ORDER[min_level]:
        return False

    async def _decide(redis) -> bool:
        sample_rate = max(1, int(settings.crawl_log_db_url_progress_sample_rate or 1))
        if (
            sample_rate > 1
            and log_level == "info"
            and _URL_PROGRESS_PATTERN.match(message)
        ):
            counter = int(await redis.incr(_url_progress_counter_key(run_id)))
            if counter == 1:
                await redis.expire(
                    _url_progress_counter_key(run_id), _COUNTER_TTL_SECONDS
                )
            return counter % sample_rate == 1

        max_rows = max(1, int(settings.crawl_log_db_max_rows_per_run or 1))
        db_count = int(await redis.incr(_db_log_counter_key(run_id)))
        if db_count == 1:
            await redis.expire(_db_log_counter_key(run_id), _COUNTER_TTL_SECONDS)
        return db_count <= max_rows

    return await redis_fail_open(
        _decide,
        default=_should_persist_log_without_redis(log_level),
        operation_name=f"should_persist_log:{run_id}",
    )


def _append_log_file_line(
    *,
    run_id: int,
    level: str,
    message: str,
    created_at: datetime,
) -> None:
    if not bool(settings.crawl_log_file_enabled):
        return
    logger.info(
        "crawl_log %s",
        json.dumps(
            {
                "run_id": int(run_id),
                "level": str(level or "info"),
                "message": str(message or ""),
                "created_at": created_at.isoformat(),
            },
            ensure_ascii=True,
        ),
    )


async def prepare_log_event(
    run_id: int, level: str, message: str
) -> tuple[str, str, bool]:
    normalized_level = _normalize_level(level)
    formatted_message = _format_message(message, None)
    logger.log(
        _LEVEL_ORDER.get(normalized_level, logging.INFO),
        "run_id=%s %s",
        run_id,
        formatted_message,
    )
    should_persist = await _should_persist_log(
        normalized_level, run_id, formatted_message
    )
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
            await _should_persist_log(level, run_id, str(message or "")),
        )
    else:
        normalized_level, formatted_message, should_persist = await prepare_log_event(
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

    row = CrawlLog(
        run_id=run_id,
        level=normalized_level,
        message=formatted_message,
    )

    if session is not None:
        session.add(row)
        await session.flush()
        return serialize_log_event(row)

    async with _DETACHED_LOG_WRITE_SEMAPHORE:
        async with SessionLocal() as new_session:
            try:
                new_session.add(row)
                await new_session.flush()
                await new_session.commit()
                await new_session.refresh(row)
                return serialize_log_event(row)
            except IntegrityError:
                await new_session.rollback()
                logger.debug(
                    "Skipping persisted crawl log because run_id=%s is not yet visible to the detached session",
                    run_id,
                    exc_info=True,
                )
                return {
                    "id": None,
                    "run_id": run_id,
                    "level": normalized_level,
                    "message": formatted_message,
                    "created_at": created_at.isoformat(),
                }
            except Exception:
                await new_session.rollback()
                logger.debug(
                    "Skipping detached crawl log persistence for run_id=%s after transient session failure",
                    run_id,
                    exc_info=True,
                )
                return {
                    "id": None,
                    "run_id": run_id,
                    "level": normalized_level,
                    "message": formatted_message,
                    "created_at": created_at.isoformat(),
                }


async def persist_run_summary_patch(
    *,
    run_id: int,
    summary_patch: dict[str, Any],
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    async def _do_patch(s: AsyncSession) -> CrawlRun | None:
        result = await s.execute(
            select(CrawlRun).where(CrawlRun.id == run_id).with_for_update()
        )
        run = result.scalar_one_or_none()
        if run is None:
            return None
        result_summary = run.summary_dict()
        if run.merge_summary_patch(summary_patch) == result_summary:
            return run
        await s.flush()
        return run

    if session is not None:
        run = await _do_patch(session)
        if run is None:
            return None
        return serialize_run_snapshot(run)

    async with SessionLocal() as new_session:
        run = await _do_patch(new_session)
        if run is None:
            return None
        await new_session.commit()
        await new_session.refresh(run)
        return serialize_run_snapshot(run)


async def load_run_for_events(
    session: AsyncSession,
    *,
    run_id: int,
) -> CrawlRun | None:
    return await session.get(CrawlRun, run_id)
