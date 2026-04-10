from __future__ import annotations

import csv
import io
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.telemetry import generate_correlation_id, get_correlation_id
from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun
from app.services.crawl_events import append_log_event
from app.services.db_utils import with_retry
from app.services.crawl_metadata import (
    load_domain_requested_fields,
    refresh_record_commit_metadata,
)
from app.services.crawl_state import ACTIVE_STATUSES, CrawlStatus, normalize_status
from app.services.crawl_utils import (
    collect_target_urls,
    normalize_committed_field_name,
    normalize_target_url,
    parse_csv_urls,
    resolve_traversal_mode,
    validate_extraction_contract,
)
from app.services.normalizers import normalize_value
from app.services.pipeline_config import DEFAULT_MAX_SCROLLS, MIN_REQUEST_DELAY_MS
from app.services.requested_field_policy import expand_requested_fields
from app.services.url_safety import ensure_public_crawl_targets

STAGE_FETCH = "FETCH"


def _escape_like_pattern(value: str) -> str:
    text = str(value or "")
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _safe_int(value, default: int, minimum: int, maximum: int | None = None) -> int:
    try:
        result = max(minimum, int(value))
        if maximum is not None:
            result = min(result, maximum)
        return result
    except (ValueError, TypeError):
        return default


async def create_crawl_run(
    session: AsyncSession, user_id: int, payload: dict
) -> CrawlRun:
    payload = dict(payload or {})
    settings = dict(payload.get("settings", {}))
    payload["url"] = normalize_target_url(payload.get("url"))
    payload["urls"] = [
        normalize_target_url(value) for value in (payload.get("urls") or [])
    ]
    settings["urls"] = [
        normalize_target_url(value) for value in (settings.get("urls") or [])
    ]
    urls = [value for value in (payload.get("urls") or []) if value]
    primary_url = payload.get("url") or (urls[0] if urls else "")
    normalized_surface = str(payload.get("surface") or "").strip()
    await ensure_public_crawl_targets(collect_target_urls(payload, settings))
    validate_extraction_contract(settings.get("extraction_contract") or [])
    settings["max_pages"] = _safe_int(settings.get("max_pages", 5), 5, 1, 20)  # Cap at 20 to prevent OOM
    settings["max_records"] = _safe_int(settings.get("max_records", 100), 100, 1)
    settings["max_scrolls"] = _safe_int(
        settings.get("max_scrolls", DEFAULT_MAX_SCROLLS), DEFAULT_MAX_SCROLLS, 1
    )
    settings["sleep_ms"] = _safe_int(
        settings.get("sleep_ms", MIN_REQUEST_DELAY_MS),
        MIN_REQUEST_DELAY_MS,
        MIN_REQUEST_DELAY_MS,
    )
    requested_traversal_mode = str(
        settings.get("traversal_mode") or settings.get("advanced_mode") or ""
    ).strip().lower()
    settings["traversal_mode"] = resolve_traversal_mode({
        **settings,
        "traversal_mode": requested_traversal_mode or None,
    })
    # Keep user-owned controls explicit in persisted settings.
    if settings.get("advanced_enabled"):
        settings["advanced_mode"] = settings["traversal_mode"]
    else:
        settings["advanced_mode"] = None
    
    domain_requested_fields = await load_domain_requested_fields(
        session, url=primary_url, surface=normalized_surface
    )
    requested_fields = expand_requested_fields(
        [
            *domain_requested_fields,
            *(payload.get("additional_fields") or []),
        ]
    )
    if domain_requested_fields:
        settings["domain_requested_fields"] = domain_requested_fields
    run_type = payload.get("run_type")
    if not run_type:
        raise ValueError("run_type is required")
    created_run_id: int | None = None

    async def _operation(retry_session: AsyncSession) -> None:
        nonlocal created_run_id
        run = CrawlRun(
            user_id=user_id,
            run_type=run_type,
            url=primary_url,
            surface=normalized_surface,
            status=CrawlStatus.PENDING.value,
            settings=settings,
            requested_fields=requested_fields,
            result_summary={
                "url_count": max(1, len(urls) or 1),
                "progress": 0,
                "current_stage": STAGE_FETCH,
                "correlation_id": get_correlation_id() or generate_correlation_id(),
            },
        )
        retry_session.add(run)
        await retry_session.flush()
        created_run_id = run.id

    await with_retry(session, _operation)
    if created_run_id is None:
        raise RuntimeError("Failed to create crawl run")
    run = await session.get(CrawlRun, created_run_id)
    if run is None:
        raise RuntimeError("Created crawl run not found")
    await session.refresh(run)
    return run


async def list_runs(
    session: AsyncSession,
    page: int,
    limit: int,
    status: str = "",
    run_type: str = "",
    url_search: str = "",
    user_id: int | None = None,
) -> tuple[list[CrawlRun], int]:
    page = max(1, page)
    query = select(CrawlRun)
    count_query = select(func.count()).select_from(CrawlRun)
    if user_id is not None:
        query = query.where(CrawlRun.user_id == user_id)
        count_query = count_query.where(CrawlRun.user_id == user_id)
    if status:
        query = query.where(CrawlRun.status == status)
        count_query = count_query.where(CrawlRun.status == status)
    if run_type:
        query = query.where(CrawlRun.run_type == run_type)
        count_query = count_query.where(CrawlRun.run_type == run_type)
    if url_search:
        escaped = _escape_like_pattern(url_search.lower())
        pattern = f"%{escaped}%"
        query = query.where(func.lower(CrawlRun.url).like(pattern, escape="\\"))
        count_query = count_query.where(
            func.lower(CrawlRun.url).like(pattern, escape="\\")
        )
    total = int((await session.execute(count_query)).scalar() or 0)
    result = await session.execute(
        query.order_by(CrawlRun.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def get_run(session: AsyncSession, run_id: int) -> CrawlRun | None:
    return await session.get(CrawlRun, run_id)


async def delete_run(session: AsyncSession, run: CrawlRun) -> None:
    async def _operation(retry_session: AsyncSession) -> None:
        retry_run = await retry_session.get(CrawlRun, run.id)
        if retry_run is None:
            return
        if normalize_status(retry_run.status) in ACTIVE_STATUSES:
            raise ValueError(f"Cannot delete run in state: {retry_run.status}")
        await retry_session.delete(retry_run)

    await with_retry(session, _operation)


async def get_run_records(
    session: AsyncSession, run_id: int, page: int, limit: int
) -> tuple[list[CrawlRecord], int]:
    page = max(1, page)
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(CrawlRecord)
                .where(CrawlRecord.run_id == run_id)
            )
        ).scalar()
        or 0
    )
    result = await session.execute(
        select(CrawlRecord)
        .where(CrawlRecord.run_id == run_id)
        .order_by(CrawlRecord.created_at.asc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def get_run_logs(
    session: AsyncSession,
    run_id: int,
    *,
    after_id: int | None = None,
    limit: int | None = None,
) -> list[CrawlLog]:
    query = (
        select(CrawlLog)
        .where(CrawlLog.run_id == run_id)
        .order_by(CrawlLog.created_at.asc())
    )
    if after_id is not None:
        query = query.where(CrawlLog.id > after_id)
    if limit is not None:
        query = query.limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def commit_selected_fields(
    session: AsyncSession,
    *,
    run: CrawlRun,
    items: list[dict],
) -> tuple[int, int]:
    if not items:
        return 0, 0
    valid_record_ids: list[int] = []
    for item in items:
        raw_record_id = item.get("record_id")
        if raw_record_id is None:
            continue
        try:
            valid_record_ids.append(int(raw_record_id))
        except (TypeError, ValueError):
            continue
    record_ids = sorted(set(valid_record_ids))
    async def _operation(retry_session: AsyncSession) -> tuple[int, int]:
        retry_run = await retry_session.get(CrawlRun, run.id)
        if retry_run is None:
            return (0, 0)
        result = await retry_session.execute(
            select(CrawlRecord).where(
                CrawlRecord.run_id == retry_run.id, CrawlRecord.id.in_(record_ids)
            )
        )
        records = {record.id: record for record in result.scalars().all()}
        updated_fields = 0
        updated_record_ids: set[int] = set()

        for item in items:
            raw_record_id = item.get("record_id")
            if raw_record_id is None:
                continue
            try:
                record_id = int(raw_record_id)
            except (TypeError, ValueError):
                continue
            record = records.get(record_id)
            if record is None:
                continue
            field_name = normalize_committed_field_name(item.get("field_name"))
            if not field_name:
                continue
            value = item.get("value")
            normalized_value = normalize_value(field_name, value)
            data = dict(record.data or {})
            data[field_name] = normalized_value
            record.data = data

            refresh_record_commit_metadata(
                record, run=retry_run, field_name=field_name, value=normalized_value
            )

            source_trace = dict(record.source_trace or {})
            llm_suggestions = dict(source_trace.get("llm_cleanup_suggestions") or {})
            if field_name in llm_suggestions:
                suggestion = dict(llm_suggestions[field_name])
                suggestion["status"] = "accepted"
                suggestion["accepted_value"] = normalized_value
                llm_suggestions[field_name] = suggestion
                source_trace["llm_cleanup_suggestions"] = llm_suggestions
                record.source_trace = source_trace

            updated_fields += 1
            updated_record_ids.add(record_id)
        return (len(updated_record_ids), updated_fields)

    updated_records, updated_fields = await with_retry(session, _operation)

    if updated_fields:
        await append_log_event(
            run_id=run.id,
            level="info",
            message=f"[FIELDS] Committed {updated_fields} selected field value(s)",
            session=session,
        )
    return updated_records, updated_fields


async def commit_llm_suggestions(
    session: AsyncSession,
    *,
    run: CrawlRun,
    items: list[dict],
) -> tuple[int, int]:
    return await commit_selected_fields(session=session, run=run, items=items)


async def active_jobs(
    session: AsyncSession, *, user_id: int | None = None
) -> list[dict]:
    query = (
        select(CrawlRun)
        .where(CrawlRun.status.in_([status.value for status in ACTIVE_STATUSES]))
        .order_by(CrawlRun.created_at.asc())
    )
    if user_id is not None:
        query = query.where(CrawlRun.user_id == user_id)
    result = await session.execute(query)
    rows = []
    for run in result.scalars().all():
        result_summary = run.result_summary if isinstance(run.result_summary, dict) else {}
        rows.append(
            {
                "run_id": run.id,
                "status": run.status,
                "progress": result_summary.get("progress", 0),
                "started_at": run.created_at,
                "url": run.url,
                "type": run.run_type,
                "user_id": run.user_id,
            }
        )
    return rows
