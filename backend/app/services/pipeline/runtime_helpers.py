from __future__ import annotations

import logging
import re

from app.models.crawl import CrawlRecord, CrawlRun
from app.services.crawl_events import append_log_event, prepare_log_event
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

STAGE_FETCH = "FETCH"
STAGE_ANALYZE = "ANALYZE"
STAGE_SAVE = "SAVE"

_ERROR_PAGE_TITLE_TOKENS = frozenset(
    {
        "account is locked",
        "already applied",
        "access denied",
        "session expired",
        "sign in to continue",
        "you must be logged in",
        "page not found",
        "404",
        "403",
    }
)


def log_for_pytest(level: int, message: str, *args: object) -> None:
    logger.log(level, message, *args)
    root_logger = logging.getLogger()
    if any(type(handler).__name__ == "LogCaptureHandler" for handler in root_logger.handlers):
        root_logger.log(level, message, *args)


def is_error_page_record(record: dict) -> bool:
    title = str(record.get("title") or "").lower()
    description = str(record.get("description") or "").lower()
    combined = title + " " + description
    for token in _ERROR_PAGE_TITLE_TOKENS:
        if token.isdigit():
            if re.search(rf"\b{re.escape(token)}\b", combined):
                return True
            continue
        if token in combined:
            return True
    return False


async def count_run_records(session: AsyncSession, run_id: int) -> int:
    if not hasattr(session, "execute"):
        raise TypeError(
            "count_run_records expected AsyncSession-like object with execute, "
            f"got {type(session)}"
        )
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


async def effective_max_records(
    session: AsyncSession,
    run: CrawlRun,
    requested_max_records: int,
) -> int:
    settings_view = getattr(run, "settings_view", None)
    if settings_view is not None and hasattr(settings_view, "max_records"):
        attr = getattr(settings_view, "max_records", None)
        try:
            configured_max = attr() if callable(attr) else attr
            configured_max = int(configured_max or 0)
        except (TypeError, ValueError):
            configured_max = 0
    else:
        configured_max = int(requested_max_records or 0)
    budget_limit = max(0, min(int(requested_max_records or 0), configured_max))
    run_id = int(getattr(run, "id", 0) or 0)
    existing_records = await count_run_records(session, run_id) if run_id else 0
    return max(0, budget_limit - existing_records)


async def log_event(
    session: AsyncSession,
    run_id: int,
    level: str,
    message: str,
) -> None:
    normalized_level, formatted_message, should_persist = await prepare_log_event(
        run_id, level, message
    )
    if not should_persist:
        return
    persisted = await append_log_event(
        run_id,
        normalized_level,
        formatted_message,
        preformatted=True,
    )
    if persisted.get("id") is None:
        await append_log_event(
            run_id,
            normalized_level,
            formatted_message,
            preformatted=True,
            session=session,
        )


async def set_stage(
    session: AsyncSession,
    run: CrawlRun,
    stage: str,
    *,
    current_url: str | None = None,
    current_url_index: int | None = None,
    total_urls: int | None = None,
) -> None:
    summary_patch = {
        "current_stage": stage,
        **({"current_url": current_url} if current_url is not None else {}),
        **(
            {"current_url_index": current_url_index}
            if current_url_index is not None
            else {}
        ),
        **({"total_urls": total_urls} if total_urls is not None else {}),
    }
    run.update_summary(**summary_patch)
    await session.flush()
