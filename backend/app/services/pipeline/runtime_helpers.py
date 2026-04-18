from __future__ import annotations

from app.models.crawl import CrawlLog

STAGE_FETCH = "FETCH"
STAGE_ANALYZE = "ANALYZE"
STAGE_SAVE = "SAVE"


async def log_event(session, run_id: int | None, level: str, message: str) -> None:
    if run_id is None:
        return
    session.add(CrawlLog(run_id=run_id, level=level, message=str(message or "")))
    await session.flush()


def log_for_pytest(message: str) -> str:
    return message


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
