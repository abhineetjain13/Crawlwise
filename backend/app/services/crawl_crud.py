from __future__ import annotations

from app.core.telemetry import generate_correlation_id, get_correlation_id
from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun
from app.models.crawl_settings import CrawlRunSettings
from app.services.crawl_events import append_log_event
from app.services.crawl_metadata import (
    load_domain_requested_fields,
    refresh_record_commit_metadata,
)
from app.services.crawl_state import ACTIVE_STATUSES, CrawlStatus
from app.models.crawl_settings import normalize_crawl_settings
from app.services.crawl_utils import (
    collect_target_urls,
    infer_surface_from_url,
    normalize_committed_field_name,
    normalize_target_url,
    validate_extraction_contract,
)
from app.services.db_utils import escape_like_pattern
from app.services.normalizers import normalize_value
from app.services.requested_field_policy import expand_requested_fields
from app.services.url_safety import ensure_public_crawl_targets
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

STAGE_FETCH = "FETCH"


async def create_crawl_run(
    session: AsyncSession, user_id: int, payload: dict
) -> CrawlRun:
    payload = dict(payload or {})
    settings = normalize_crawl_settings(payload.get("settings"))
    settings_view = CrawlRunSettings.from_value(settings)
    payload["url"] = normalize_target_url(payload.get("url"))
    payload["urls"] = [
        normalize_target_url(value) for value in (payload.get("urls") or [])
    ]
    urls = [value for value in (payload.get("urls") or []) if value]
    primary_url = payload.get("url") or (urls[0] if urls else "")
    requested_surface = str(payload.get("surface") or "").strip()
    normalized_surface = (
        requested_surface
        if requested_surface
        else infer_surface_from_url(primary_url, requested_surface)
    )
    await ensure_public_crawl_targets(collect_target_urls(payload, settings_view))
    validate_extraction_contract(settings_view.extraction_contract())
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
        settings = settings_view.with_updates(
            domain_requested_fields=domain_requested_fields
        ).as_dict()
    run_type = payload.get("run_type")
    if not run_type:
        raise ValueError("run_type is required")
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
    session.add(run)
    await session.flush()
    await session.commit()
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
        escaped = escape_like_pattern(url_search.lower())
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
    db_run = await session.get(CrawlRun, run.id)
    if db_run is None:
        return
    if db_run.is_active():
        raise ValueError(f"Cannot delete run in state: {db_run.status}")
    await session.delete(db_run)
    await session.commit()


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
    db_run = await session.get(CrawlRun, run.id)
    if db_run is None:
        return 0, 0
    result = await session.execute(
        select(CrawlRecord).where(
            CrawlRecord.run_id == db_run.id, CrawlRecord.id.in_(record_ids)
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
            record, run=db_run, field_name=field_name, value=normalized_value
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
    updated_records = len(updated_record_ids)
    await session.commit()

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
        result_summary = run.summary_dict()
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
