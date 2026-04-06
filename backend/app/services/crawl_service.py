# Crawl orchestration service.
#
# Implements the single pipeline: FETCH -> ANALYZE -> SAVE
# Handles crawl, batch (multi-URL), and listing (category) crawls.
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import time
from datetime import UTC, datetime
from html import unescape
from urllib.parse import urljoin, urlparse

import regex as regex_lib
from bs4 import BeautifulSoup, NavigableString, Tag
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult, ProxyPoolExhausted, acquire
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.adapters.registry import run_adapter, try_blocked_adapter_recovery
from app.services.crawl_state import (
    ACTIVE_STATUSES,
    CONTROL_REQUEST_PAUSE,
    CONTROL_REQUEST_KILL,
    CrawlStatus,
    TERMINAL_STATUSES,
    get_control_request,
    normalize_status,
    set_control_request,
    update_run_status,
)
from app.services.extract.json_extractor import extract_json_detail, extract_json_listing
from app.services.extract.listing_extractor import extract_listing_records
from app.services.extract.source_parsers import parse_page_sources
from app.services.extract.service import coerce_field_candidate_value, extract_candidates
from app.services.xpath_service import validate_xpath_syntax
from app.services.knowledge_base.store import get_canonical_fields, get_selector_defaults
from app.services.llm_runtime import discover_xpath_candidates, review_field_candidates, snapshot_active_configs
from app.services.normalizers import extract_currency_hint, normalize_value
from app.services.pipeline_config import (
    DEFAULT_MAX_SCROLLS,
    DISCOVERED_FIELD_NOISE_TOKENS,
    DISCOVERED_VALUE_NOISE_PHRASES,
    LLM_CLEAN_CANDIDATE_TEXT_LIMIT,
    MIN_REQUEST_DELAY_MS,
    VERDICT_CORE_FIELDS_DETAIL,
    VERDICT_CORE_FIELDS_LISTING,
)
from app.services.domain_utils import normalize_domain
from app.services.requested_field_policy import expand_requested_fields
from app.services.schema_service import (
    ResolvedSchema,
    learn_schema_from_record,
    load_resolved_schema,
    persist_resolved_schema,
    resolve_schema,
    schema_trace_payload,
)
from app.services.url_safety import ensure_public_crawl_targets
from app.services.xpath_service import build_deterministic_selector_suggestions
from app.services.xpath_service import validate_xpath_candidate


# Extraction quality verdicts persisted in result_summary.
VERDICT_SUCCESS = "success"
VERDICT_PARTIAL = "partial"
VERDICT_BLOCKED = "blocked"
VERDICT_SCHEMA_MISS = "schema_miss"
VERDICT_LISTING_FAILED = "listing_detection_failed"
VERDICT_EMPTY = "empty"

logger = logging.getLogger(__name__)
MAX_SELECTOR_ROWS_PER_FIELD = 100
_TRAVERSAL_MODES = {"auto", "scroll", "load_more", "paginate"}
STAGE_FETCH = "FETCH"
STAGE_ANALYZE = "ANALYZE"
STAGE_SAVE = "SAVE"


class RunControlSignal(RuntimeError):
    def __init__(self, request: str) -> None:
        super().__init__(request)
        self.request = request


# ---------------------------------------------------------------------------
# Run CRUD helpers
# ---------------------------------------------------------------------------

async def create_crawl_run(session: AsyncSession, user_id: int, payload: dict) -> CrawlRun:
    settings = dict(payload.get("settings", {}))
    urls = payload.get("urls") or []
    primary_url = payload.get("url") or (urls[0] if urls else "")
    normalized_surface = str(payload.get("surface") or "").strip()
    await ensure_public_crawl_targets(_collect_target_urls(payload, settings))
    _validate_extraction_contract(settings.get("extraction_contract") or [])
    settings["max_pages"] = max(1, int(settings.get("max_pages", 5) or 5))
    settings["max_records"] = max(1, int(settings.get("max_records", 100) or 100))
    settings["max_scrolls"] = max(1, int(settings.get("max_scrolls", DEFAULT_MAX_SCROLLS) or DEFAULT_MAX_SCROLLS))
    settings["sleep_ms"] = max(
        MIN_REQUEST_DELAY_MS,
        int(settings.get("sleep_ms", MIN_REQUEST_DELAY_MS) or MIN_REQUEST_DELAY_MS),
    )
    requested_advanced_mode = str(settings.get("advanced_mode") or "").strip().lower() or None
    settings["advanced_enabled"] = bool(settings.get("advanced_enabled"))
    settings["advanced_mode"] = requested_advanced_mode or None
    settings["traversal_mode"] = _resolve_traversal_mode(settings)
    domain_requested_fields = await _load_domain_requested_fields(session, url=primary_url, surface=normalized_surface)
    requested_fields = expand_requested_fields([
        *domain_requested_fields,
        *(payload.get("additional_fields") or []),
    ])
    if settings.get("llm_enabled"):
        settings["llm_config_snapshot"] = await snapshot_active_configs(session)
    if domain_requested_fields:
        settings["domain_requested_fields"] = domain_requested_fields
    run = CrawlRun(
        user_id=user_id,
        run_type=payload["run_type"],
        url=primary_url,
        surface=normalized_surface,
        status=CrawlStatus.PENDING.value,
        settings=settings,
        requested_fields=requested_fields,
        result_summary={"url_count": max(1, len(urls) or 1), "progress": 0, "current_stage": STAGE_FETCH},
    )
    session.add(run)
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
        pattern = f"%{url_search.lower()}%"
        query = query.where(func.lower(CrawlRun.url).like(pattern))
        count_query = count_query.where(func.lower(CrawlRun.url).like(pattern))
    total = int((await session.execute(count_query)).scalar() or 0)
    result = await session.execute(
        query.order_by(CrawlRun.created_at.desc()).offset((page - 1) * limit).limit(limit)
    )
    return list(result.scalars().all()), total


async def get_run(session: AsyncSession, run_id: int) -> CrawlRun | None:
    return await session.get(CrawlRun, run_id)


async def delete_run(session: AsyncSession, run: CrawlRun) -> None:
    if normalize_status(run.status) in ACTIVE_STATUSES:
        raise ValueError(f"Cannot delete run in state: {run.status}")
    await session.delete(run)
    await session.commit()


async def get_run_records(
    session: AsyncSession, run_id: int, page: int, limit: int
) -> tuple[list[CrawlRecord], int]:
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(CrawlRecord).where(CrawlRecord.run_id == run_id)
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


async def get_run_logs(session: AsyncSession, run_id: int) -> list[CrawlLog]:
    result = await session.execute(
        select(CrawlLog).where(CrawlLog.run_id == run_id).order_by(CrawlLog.created_at.asc())
    )
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
    result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id, CrawlRecord.id.in_(record_ids))
    )
    records = {record.id: record for record in result.scalars().all()}
    updated_records = 0
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
        field_name = _normalize_committed_field_name(item.get("field_name"))
        if not field_name:
            continue
        value = item.get("value")
        normalized_value = normalize_value(field_name, value)
        data = dict(record.data or {})
        data[field_name] = normalized_value
        record.data = data
        _refresh_record_commit_metadata(record, run=run, field_name=field_name, value=normalized_value)

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

    if updated_fields:
        updated_records = len(updated_record_ids)
        await _log(session, run.id, "info", f"[FIELDS] Committed {updated_fields} selected field value(s)")
        await session.commit()
    return updated_records, updated_fields


async def commit_llm_suggestions(
    session: AsyncSession,
    *,
    run: CrawlRun,
    items: list[dict],
) -> tuple[int, int]:
    return await commit_selected_fields(session=session, run=run, items=items)


async def pause_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    current = normalize_status(run.status)
    if current != CrawlStatus.RUNNING:
        raise ValueError(f"Cannot pause run in state: {run.status}")
    set_control_request(run, CONTROL_REQUEST_PAUSE)
    await _log(session, run.id, "warning", "Pause requested; worker will stop at the next checkpoint")
    await session.commit()
    await session.refresh(run)
    return run


async def resume_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    current = normalize_status(run.status)
    if current != CrawlStatus.PAUSED:
        raise ValueError(f"Cannot resume run in state: {run.status}")
    update_run_status(run, CrawlStatus.RUNNING)
    set_control_request(run, None)
    await _log(session, run.id, "info", "Resume requested")
    await session.commit()
    await session.refresh(run)
    return run


async def kill_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    current = normalize_status(run.status)
    if current in TERMINAL_STATUSES:
        raise ValueError(f"Cannot kill run in terminal state: {run.status}")
    if current == CrawlStatus.RUNNING:
        set_control_request(run, CONTROL_REQUEST_KILL)
        await _log(session, run.id, "warning", "Hard kill requested; worker will stop at the next checkpoint")
    else:
        update_run_status(run, CrawlStatus.KILLED)
        set_control_request(run, None)
        await _log(session, run.id, "warning", "Run killed before execution resumed")
    await session.commit()
    await session.refresh(run)
    return run


async def cancel_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    return await kill_run(session, run)


async def active_jobs(session: AsyncSession, *, user_id: int | None = None) -> list[dict]:
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
        rows.append({
            "run_id": run.id,
            "status": run.status,
            "progress": run.result_summary.get("progress", 0),
            "started_at": run.created_at,
            "url": run.url,
            "type": run.run_type,
            "user_id": run.user_id,
        })
    return rows


# ---------------------------------------------------------------------------
# CSV parsing helper
# ---------------------------------------------------------------------------

def parse_csv_urls(csv_content: str) -> list[str]:
    """Parse URLs from CSV content (first column, skip header if present)."""
    urls: list[str] = []
    reader = csv.reader(io.StringIO(csv_content))
    for i, row in enumerate(reader):
        if not row:
            continue
        cell = row[0].strip()
        if i == 0 and not cell.startswith(("http://", "https://")):
            continue  # skip header
        if cell.startswith(("http://", "https://")):
            urls.append(cell)
    return urls


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def process_run(session: AsyncSession, run_id: int) -> None:
    """Execute the crawl pipeline for a run.

    Handles single-URL crawl, batch (multi-URL), and listing/category crawls.
    All errors are caught and the run is marked as failed with a message.
    """
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    current_status = normalize_status(run.status)
    if current_status in TERMINAL_STATUSES or current_status == CrawlStatus.PAUSED:
        return

    # If the job was PENDING or just CLAIMED by a worker, we treat it as a fresh start.
    # RUNNING implies it was already in progress and we are resuming (e.g. after a worker restart).
    if current_status in (CrawlStatus.PENDING, CrawlStatus.CLAIMED):
        update_run_status(run, CrawlStatus.RUNNING)
        await _log(session, run.id, "info", "Pipeline started")
        await session.commit()
    else:
        await _log(session, run.id, "info", "Pipeline resumed")
        await session.commit()

    async def _run_control_checkpoint() -> None:
        await session.refresh(run)
        current_status = normalize_status(run.status)
        control_request = get_control_request(run)
        if current_status == CrawlStatus.PAUSED or control_request == CONTROL_REQUEST_PAUSE:
            raise RunControlSignal(CONTROL_REQUEST_PAUSE)
        if current_status == CrawlStatus.KILLED or control_request == CONTROL_REQUEST_KILL:
            raise RunControlSignal(CONTROL_REQUEST_KILL)

    try:
        settings = run.settings or {}
        urls = settings.get("urls", [])
        run_type = run.run_type

        # Determine URL list
        if run_type == "batch" and urls:
            url_list = urls
        elif run_type == "csv" and settings.get("csv_content"):
            url_list = parse_csv_urls(settings["csv_content"])
        elif run.url:
            url_list = [run.url]
        else:
            raise ValueError("No URL provided")

        # Extract crawl settings
        proxy_list = settings.get("proxy_list", [])
        traversal_mode = settings.get("traversal_mode")
        max_pages = settings.get("max_pages", 5)
        max_scrolls = settings.get("max_scrolls", DEFAULT_MAX_SCROLLS)
        max_records = settings.get("max_records", 100)
        sleep_ms = settings.get("sleep_ms", 0)

        total_urls = len(url_list)
        persisted_summary = dict(run.result_summary or {})
        start_index = min(int(persisted_summary.get("completed_urls", 0) or 0), total_urls)
        persisted_record_count = await _count_run_records(session, run.id)
        url_verdicts: list[str] = list(persisted_summary.get("url_verdicts") or [])[:start_index]
        verdict_counts: dict[str, int] = dict(persisted_summary.get("verdict_counts") or {})
        for idx in range(start_index, total_urls):
            url = url_list[idx]
            await session.refresh(run)
            current_status = normalize_status(run.status)
            control_request = get_control_request(run)
            if current_status == CrawlStatus.PAUSED or control_request == CONTROL_REQUEST_PAUSE:
                update_run_status(run, CrawlStatus.PAUSED)
                set_control_request(run, None)
                await _log(session, run.id, "warning", "Run paused by user")
                await session.commit()
                return
            if current_status == CrawlStatus.KILLED or control_request == CONTROL_REQUEST_KILL:
                update_run_status(run, CrawlStatus.KILLED)
                set_control_request(run, None)
                await _log(session, run.id, "warning", "Run killed by user")
                await session.commit()
                return
            remaining_records = max(max_records - persisted_record_count, 0)
            if remaining_records <= 0:
                await _log(session, run.id, "info", f"Reached max_records ceiling ({max_records})")
                break

            await _log(session, run.id, "info", f"Processing URL {idx + 1}/{total_urls}: {url}")
            await _set_stage(
                session,
                run,
                STAGE_FETCH,
                current_url=url,
                current_url_index=idx + 1,
                total_urls=total_urls,
            )

            records, verdict, url_metrics = await _process_single_url(
                session=session,
                run=run,
                url=url,
                proxy_list=proxy_list,
                traversal_mode=traversal_mode,
                max_pages=max_pages,
                max_scrolls=max_scrolls,
                max_records=remaining_records,
                sleep_ms=sleep_ms,
                checkpoint=_run_control_checkpoint,
            )
            persisted_record_count += len(records)
            if idx < len(url_verdicts):
                url_verdicts[idx] = verdict
            else:
                url_verdicts.append(verdict)
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            acquisition_summary = _merge_run_acquisition_metrics(
                run.result_summary.get("acquisition_summary") if isinstance(run.result_summary, dict) else {},
                url_metrics,
            )

            # Update progress
            progress = int(((idx + 1) / total_urls) * 100)
            run.result_summary = {
                **(run.result_summary or {}),
                "url_count": total_urls,
                "record_count": persisted_record_count,
                "domain": _domain(url),
                "progress": progress,
                "processed_urls": idx + 1,
                "completed_urls": idx + 1,
                "remaining_urls": max(total_urls - (idx + 1), 0),
                "url_verdicts": url_verdicts,
                "verdict_counts": verdict_counts,
                "acquisition_summary": acquisition_summary,
            }
            await session.commit()
            await session.refresh(run)
            current_status = normalize_status(run.status)
            control_request = get_control_request(run)
            if current_status == CrawlStatus.PAUSED or control_request == CONTROL_REQUEST_PAUSE:
                update_run_status(run, CrawlStatus.PAUSED)
                set_control_request(run, None)
                await _log(session, run.id, "warning", "Run paused after checkpoint; partial output preserved")
                await session.commit()
                return
            if current_status == CrawlStatus.KILLED or control_request == CONTROL_REQUEST_KILL:
                update_run_status(run, CrawlStatus.KILLED)
                set_control_request(run, None)
                await _log(session, run.id, "warning", "Run killed after checkpoint; partial output preserved")
                await session.commit()
                return
            if persisted_record_count >= max_records:
                await _log(session, run.id, "info", f"Stopped after reaching max_records={max_records}")
                break

            # Sleep between URLs if configured (for rate limiting)
            if sleep_ms > 0 and idx < total_urls - 1:
                await _sleep_with_checkpoint(sleep_ms, _run_control_checkpoint)

        # Compute aggregate extraction verdict
        aggregate_verdict = _aggregate_verdict(url_verdicts)

        if normalize_status(run.status) == CrawlStatus.RUNNING:
            if aggregate_verdict in {VERDICT_SUCCESS, VERDICT_PARTIAL}:
                update_run_status(run, CrawlStatus.COMPLETED)
            elif aggregate_verdict in {VERDICT_EMPTY, VERDICT_BLOCKED, VERDICT_SCHEMA_MISS, VERDICT_LISTING_FAILED}:
                update_run_status(run, CrawlStatus.FAILED)
        run.result_summary = {
            **(run.result_summary or {}),
            "url_count": total_urls,
            "record_count": persisted_record_count,
            "domain": _domain(url_list[0]) if url_list else "",
            "progress": 100,
            "extraction_verdict": aggregate_verdict,
            "url_verdicts": url_verdicts,
            "processed_urls": total_urls,
            "completed_urls": total_urls,
            "remaining_urls": 0,
            "verdict_counts": verdict_counts,
        }
        await _log(session, run.id, "info",
                    f"Pipeline finished. {persisted_record_count} records. verdict={aggregate_verdict}")
        await session.commit()

    except ProxyPoolExhausted as exc:
        await session.rollback()
        run = await session.get(CrawlRun, run_id)
        if run is None:
            return
        update_run_status(run, CrawlStatus.PROXY_EXHAUSTED)
        summary = dict(run.result_summary or {})
        summary["error"] = str(exc)
        summary["extraction_verdict"] = "proxy_exhausted"
        run.result_summary = summary
        await _log(session, run.id, "error", str(exc))
        await session.commit()
    except RunControlSignal as signal:
        await _handle_run_control_signal(session, run, signal.request)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        await _mark_run_failed(session, run_id, error_msg)


async def _process_single_url(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    proxy_list: list[str],
    traversal_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    max_records: int,
    sleep_ms: int,
    checkpoint=None,
    update_run_state: bool = True,
    persist_logs: bool = True,
) -> tuple[list[dict], str, dict]:
    """Run the single-URL pipeline.

    Returns (saved_records, extraction_verdict).
    """
    surface = run.surface
    additional_fields = expand_requested_fields(run.requested_fields or [])
    extraction_contract = (run.settings or {}).get("extraction_contract", [])
    is_listing = surface in ("ecommerce_listing", "job_listing")
    requested_field_selectors = {
        field_name: get_selector_defaults(normalize_domain(url), field_name)
        for field_name in additional_fields
        if field_name
    }
    acquisition_profile = _build_acquisition_profile(run.settings or {})

    # ── STAGE 1: FETCH ──
    if update_run_state:
        await _set_stage(session, run, STAGE_FETCH)
    if persist_logs:
        await _log(session, run.id, "info", f"[FETCH] Fetching {url}")
    acquisition_started_at = time.perf_counter()
    acq = await acquire(
        run_id=run.id,
        url=url,
        surface=surface,
        proxy_list=proxy_list or None,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        sleep_ms=sleep_ms,
        requested_fields=additional_fields,
        requested_field_selectors=requested_field_selectors,
        acquisition_profile=acquisition_profile,
        checkpoint=checkpoint,
    )
    acquisition_ms = _elapsed_ms(acquisition_started_at)
    url_metrics = _build_url_metrics(acq, requested_fields=additional_fields)
    url_metrics["acquisition_ms"] = acquisition_ms

    # ── STAGE 1.5: BLOCKED PAGE DETECTION ──
    # For JSON responses, skip blocked detection (APIs don't serve challenge pages)
    if acq.content_type != "json":
        blocked = detect_blocked_page(acq.html)
        if blocked.is_blocked:
            recovered = None if proxy_list else await try_blocked_adapter_recovery(url, surface)
            if recovered and recovered.records:
                if persist_logs:
                    await _log(
                        session,
                        run.id,
                        "info",
                        f"[BLOCKED] {url} matched blocked-page signals, recovered {len(recovered.records)} Shopify records from public endpoint",
                    )
                if is_listing:
                    return await _extract_listing(
                        session, run, url, "", acq, recovered,
                        recovered.records, additional_fields,
                        surface, max_records, url_metrics,
                        update_run_state=update_run_state,
                        persist_logs=persist_logs,
                    )
                return await _extract_detail(
                    session, run, url, "", acq, recovered,
                    recovered.records, additional_fields, extraction_contract,
                    surface, url_metrics,
                    update_run_state=update_run_state,
                    persist_logs=persist_logs,
                )
            if persist_logs:
                await _log(session, run.id, "warning", f"[BLOCKED] {url} — {blocked.reason}")
            record = CrawlRecord(
                run_id=run.id,
                source_url=url,
                data={"_status": "blocked", "_message": blocked.reason,
                      "_provider": blocked.provider},
                raw_data={},
                discovered_data=blocked.as_dict(),
                source_trace={**_build_acquisition_trace(acq), "blocked": True},
                raw_html_path=acq.artifact_path,
            )
            session.add(record)
            await session.flush()
            return [], VERDICT_BLOCKED, url_metrics

    # ── STAGE 2: ANALYZE ──
    if acq.content_type == "json" and acq.json_data is not None:
        if persist_logs:
            await _log(session, run.id, "info", "[ANALYZE] JSON-first path — API response detected")
        extraction_started_at = time.perf_counter()
        records, verdict, url_metrics = await _process_json_response(
            session, run, url, acq, is_listing, max_records, additional_fields, url_metrics,
            update_run_state=update_run_state,
            persist_logs=persist_logs,
        )
        url_metrics["extraction_ms"] = _elapsed_ms(extraction_started_at)
        return records, verdict, url_metrics

    html = acq.html
    # ── STAGE 2: ANALYZE ──
    if update_run_state:
        await _set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await _log(session, run.id, "info", f"[ANALYZE] Enumerating sources (method={acq.method})")

    # Run platform adapter (rank 1 source)
    adapter_result = await run_adapter(url, html, surface)
    adapter_records = adapter_result.records if adapter_result else []

    # ── STAGE 2: ANALYZE ──
    if update_run_state:
        await _set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await _log(session, run.id, "info", "[ANALYZE] Extracting candidates")

    if is_listing:
        extraction_started_at = time.perf_counter()
        records, verdict, url_metrics = await _extract_listing(
            session, run, url, html, acq, adapter_result,
            adapter_records, additional_fields,
            surface, max_records, url_metrics,
            update_run_state=update_run_state,
            persist_logs=persist_logs,
        )
        url_metrics["extraction_ms"] = _elapsed_ms(extraction_started_at)
        if verdict == VERDICT_LISTING_FAILED and acq.method == "curl_cffi":
            if persist_logs:
                await _log(
                    session,
                    run.id,
                    "info",
                    "[ANALYZE] Listing extraction was weak/empty on curl_cffi — retrying with browser rendering",
                )
            browser_retry_started_at = time.perf_counter()
            browser_profile = dict(acquisition_profile or {})
            browser_profile["prefer_browser"] = True
            browser_acq = await acquire(
                run_id=run.id,
                url=url,
                surface=surface,
                proxy_list=proxy_list or None,
                traversal_mode=traversal_mode,
                max_pages=max_pages,
                max_scrolls=max_scrolls,
                sleep_ms=sleep_ms,
                requested_fields=additional_fields,
                requested_field_selectors=requested_field_selectors,
                acquisition_profile=browser_profile,
                checkpoint=checkpoint,
            )
            browser_retry_ms = _elapsed_ms(browser_retry_started_at)
            browser_html = browser_acq.html
            browser_adapter_result = await run_adapter(url, browser_html, surface)
            browser_adapter_records = browser_adapter_result.records if browser_adapter_result else []
            extraction_started_at = time.perf_counter()
            records, verdict, url_metrics = await _extract_listing(
                session, run, url, browser_html, browser_acq, browser_adapter_result,
                browser_adapter_records, additional_fields,
                surface, max_records, url_metrics,
                update_run_state=update_run_state,
                persist_logs=persist_logs,
            )
            url_metrics["listing_browser_retry"] = True
            url_metrics["listing_browser_retry_method"] = browser_acq.method
            url_metrics["listing_browser_retry_acquisition_ms"] = browser_retry_ms
            url_metrics["extraction_ms"] = _elapsed_ms(extraction_started_at)
        return records, verdict, url_metrics
    else:
        extraction_started_at = time.perf_counter()
        records, verdict, url_metrics = await _extract_detail(
            session, run, url, html, acq, adapter_result,
            adapter_records, additional_fields, extraction_contract,
            surface, url_metrics,
            update_run_state=update_run_state,
            persist_logs=persist_logs,
        )
        url_metrics["extraction_ms"] = _elapsed_ms(extraction_started_at)
        return records, verdict, url_metrics


async def _process_json_response(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    acq: AcquisitionResult,
    is_listing: bool,
    max_records: int,
    requested_fields: list[str],
    url_metrics: dict,
    update_run_state: bool = True,
    persist_logs: bool = True,
) -> tuple[list[dict], str, dict]:
    """Handle a JSON API response — extract directly without HTML parsing."""
    if is_listing:
        extracted = extract_json_listing(acq.json_data, url, max_records)
    else:
        extracted = extract_json_detail(acq.json_data, url)

    if not extracted:
        if persist_logs:
            await _log(session, run.id, "warning", "[ANALYZE] JSON response parsed but no records found")
        return [], VERDICT_SCHEMA_MISS, url_metrics

    if update_run_state:
        await _set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await _log(session, run.id, "info", "[ANALYZE] Normalizing JSON records")
    saved = []
    resolved_schema = await resolve_schema(
        session,
        run.surface,
        url,
        run_id=run.id,
        explicit_fields=requested_fields,
        sample_record=extracted[0] if extracted and isinstance(extracted[0], dict) else None,
        llm_enabled=bool((run.settings or {}).get("llm_enabled")),
    )
    current_schema = resolved_schema
    for raw_record in extracted:
        if len(saved) >= max_records:
            break
        learned_schema = await _refresh_schema_from_record(
            session,
            surface=run.surface,
            url=url,
            base_schema=current_schema,
            sample_record=raw_record,
        )
        current_schema = learned_schema or current_schema
        allowed_fields = set(current_schema.fields)
        public_fields = _public_record_fields(raw_record)
        normalized, discovered_fields = _split_detail_output_fields(public_fields, allowed_fields=allowed_fields)
        raw_data = _raw_record_payload(raw_record)
        requested_coverage = _requested_field_coverage(normalized, requested_fields)
        review_bucket = _build_review_bucket(
            discovered_fields,
            fallback_source=str(raw_record.get("_source") or "json_api"),
        )
        db_record = CrawlRecord(
            run_id=run.id,
            source_url=raw_record.get("url", url),
            data=normalized,
            raw_data=raw_data,
            discovered_data=_compact_dict({
                "review_bucket": review_bucket or None,
                "requested_field_coverage": requested_coverage or None,
            }),
            source_trace=_compact_dict({
                "type": "json_api",
                "method": acq.method,
                "schema_resolution": schema_trace_payload(current_schema),
                "acquisition": _build_acquisition_trace(acq).get("acquisition"),
                "requested_fields": requested_fields or None,
                "requested_field_coverage": requested_coverage or None,
                "manifest_trace": _build_manifest_trace(
                    html="",
                    xhr_payloads=[],
                    adapter_records=[],
                    extra={
                        "content_type": "json",
                        "source": raw_record.get("_source", "json_api"),
                        "json_record_keys": sorted(raw_data.keys()) if isinstance(raw_data, dict) else None,
                        "full_json_response": acq.json_data if not is_listing else None,
                    },
                ) or None,
            }),
            raw_html_path=acq.artifact_path,
        )
        session.add(db_record)
        saved.append(normalized)

    if update_run_state:
        await _set_stage(session, run, STAGE_SAVE)
    verdict = _compute_verdict(saved, is_listing)
    if persist_logs:
        await _log(session, run.id, "info", f"[SAVE] Saved {len(saved)} JSON records (verdict={verdict})")
    await session.flush()
    _finalize_url_metrics(url_metrics, records=saved, requested_fields=requested_fields)
    return saved, verdict, url_metrics


async def _extract_listing(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    html: str,
    acq: AcquisitionResult,
    adapter_result,
    adapter_records: list[dict],
    additional_fields: list[str],
    surface: str,
    max_records: int,
    url_metrics: dict,
    update_run_state: bool = True,
    persist_logs: bool = True,
) -> tuple[list[dict], str, dict]:
    """Listing extraction — adapter > structured data > DOM cards.

    Never falls back to a single detail-style record. If no listing items
    are found, returns an explicit listing_detection_failed verdict.
    """
    adapter_name = adapter_result.adapter_name if adapter_result else None
    effective_surface = _resolve_listing_surface(surface=surface, url=url, html=html, acq=acq)
    url_metrics["listing_surface_used"] = effective_surface
    if effective_surface != surface:
        url_metrics["listing_surface_corrected"] = True

    extracted_records = extract_listing_records(
        html=html,
        surface=effective_surface,
        target_fields=set(additional_fields),
        page_url=url,
        max_records=max_records,
        xhr_payloads=acq.network_payloads,
        adapter_records=adapter_records,
    )
    source_label = "listing_extractor"
    if not extracted_records and adapter_records:
        extracted_records = adapter_records
        source_label = "adapter"

    # ── LISTING FALLBACK GUARD ──
    # If listing extraction found zero records, distinguish actual extraction
    # misses from anti-bot/interstitial failures before marking the run failed.
    if not extracted_records:
        if _listing_acquisition_blocked(acq, html):
            if persist_logs:
                await _log(
                    session,
                    run.id,
                    "warning",
                    "[ANALYZE] Listing extraction found 0 records because the acquired page was blocked",
                )
            return [], VERDICT_BLOCKED, url_metrics
        if _looks_like_loading_listing_shell(html, surface=effective_surface):
            if persist_logs:
                await _log(
                    session,
                    run.id,
                    "warning",
                    "[ANALYZE] Listing extraction found 0 records on a loading shell; skipping page fallback so browser retry/failure is explicit",
                )
            return [], VERDICT_LISTING_FAILED, url_metrics
        if effective_surface == "job_listing":
            if persist_logs:
                await _log(
                    session,
                    run.id,
                    "warning",
                    "[ANALYZE] Job listing extraction found 0 records; skipping page fallback so browser retry/failure is explicit",
                )
            return [], VERDICT_LISTING_FAILED, url_metrics
        fallback_record = _build_legible_listing_fallback_record(
            url=url,
            html=html,
            xhr_payloads=acq.network_payloads,
            adapter_records=adapter_records,
        )
        if fallback_record is not None:
            if update_run_state:
                await _set_stage(session, run, STAGE_ANALYZE)
            if persist_logs:
                await _log(
                    session,
                    run.id,
                    "warning",
                    "[ANALYZE] Listing extraction found 0 item records but preserved legible page fallback",
                )
            db_record = CrawlRecord(
                run_id=run.id,
                source_url=url,
                data=fallback_record["data"],
                raw_data=fallback_record["raw_data"],
                discovered_data=_compact_dict({
                    "requested_field_coverage": _requested_field_coverage(
                        fallback_record["data"], additional_fields
                    ) or None,
                    "fallback_reason": "listing_no_item_records",
                }),
                source_trace=_compact_dict({
                    "type": "listing_fallback",
                    "source": "legible_page_fallback",
                    "adapter": adapter_name,
                    "fallback_kind": "page_markdown",
                    "fallback_summary": fallback_record["summary"],
                    "manifest_trace": fallback_record.get("manifest_trace"),
                    **_build_acquisition_trace(acq),
                }),
                raw_html_path=acq.artifact_path,
            )
            session.add(db_record)
            await session.flush()
            saved = [dict(fallback_record["data"])]
            _finalize_url_metrics(url_metrics, records=saved, requested_fields=additional_fields)
            return saved, VERDICT_PARTIAL, url_metrics
        if persist_logs:
            await _log(session, run.id, "warning",
                        "[ANALYZE] Listing extraction found 0 records — marking as listing_detection_failed")
        return [], VERDICT_LISTING_FAILED, url_metrics

    # Save each listing record
    if update_run_state:
        await _set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await _log(session, run.id, "info", "[ANALYZE] Normalizing listing records")
    saved: list[dict] = []
    resolved_schema = await resolve_schema(
        session,
        surface,
        url,
        run_id=run.id,
        explicit_fields=additional_fields,
        sample_record=extracted_records[0] if extracted_records and isinstance(extracted_records[0], dict) else None,
        llm_enabled=bool((run.settings or {}).get("llm_enabled")),
    )
    current_schema = resolved_schema
    for raw_record in extracted_records:
        if len(saved) >= max_records:
            break
        learned_schema = await _refresh_schema_from_record(
            session,
            surface=surface,
            url=url,
            base_schema=current_schema,
            sample_record=raw_record,
        )
        current_schema = learned_schema or current_schema
        allowed_fields = set(current_schema.fields)
        record_source_label = str(raw_record.get("_source") or source_label).strip() or source_label
        public_record = _sanitize_listing_record_fields(
            _public_record_fields(raw_record),
            surface=effective_surface,
        )
        normalized, discovered_fields = _split_detail_output_fields(
            public_record,
            allowed_fields=allowed_fields,
        )
        raw_data = _raw_record_payload(raw_record)
        requested_coverage = _requested_field_coverage(normalized, additional_fields)
        review_bucket = _build_review_bucket(
            discovered_fields,
            fallback_source=adapter_name or record_source_label,
        )
        db_record = CrawlRecord(
            run_id=run.id,
            source_url=raw_record.get("url", url),
            data=normalized,
            raw_data=raw_data,
            discovered_data=_compact_dict({
                "review_bucket": review_bucket or None,
                "requested_field_coverage": requested_coverage or None,
            }),
            source_trace=_compact_dict({
                "type": "listing",
                "schema_resolution": schema_trace_payload(current_schema),
                **_build_acquisition_trace(acq),
                "adapter": adapter_name,
                "source": record_source_label,
                "surface_used": effective_surface,
                "surface_requested": surface if effective_surface != surface else None,
                "requested_fields": additional_fields or None,
                "requested_field_coverage": requested_coverage or None,
                "manifest_trace": _build_manifest_trace(
                    html=html,
                    xhr_payloads=acq.network_payloads,
                    adapter_records=adapter_records,
                ) or None,
            }),
            raw_html_path=acq.artifact_path,
        )
        session.add(db_record)
        saved.append(normalized)

    if update_run_state:
        await _set_stage(session, run, STAGE_SAVE)
    verdict = _compute_verdict(saved, is_listing=True)
    if persist_logs:
        await _log(session, run.id, "info", f"[SAVE] Saved {len(saved)} listing records (verdict={verdict})")
    await session.flush()
    _finalize_url_metrics(url_metrics, records=saved, requested_fields=additional_fields)
    return saved, verdict, url_metrics


def _listing_acquisition_blocked(acq: AcquisitionResult, html: str) -> bool:
    if html and detect_blocked_page(html).is_blocked:
        return True
    diagnostics = acq.diagnostics if isinstance(acq.diagnostics, dict) else {}
    if bool(diagnostics.get("browser_blocked")):
        return True
    browser_diagnostics = diagnostics.get("browser_diagnostics")
    if isinstance(browser_diagnostics, dict) and bool(browser_diagnostics.get("blocked")):
        return True
    return False


def _looks_like_loading_listing_shell(html: str, *, surface: str) -> bool:
    if not html or "listing" not in str(surface or "").lower():
        return False
    lowered = html.lower()
    if "job" in str(surface or "").lower():
        return False
    if lowered.count("product-card-skeleton") >= 4:
        return True
    if "data-test-id=\"content-grid\"" in lowered and lowered.count("animate-pulse") >= 8:
        return True
    return False


def _sanitize_listing_record_fields(record: dict, *, surface: str) -> dict:
    sanitized = dict(record or {})
    if not sanitized:
        return sanitized

    title = str(sanitized.get("title") or "").strip()
    if title:
        normalized_title = re.sub(r"\s+([,;:/|])", r"\1", " ".join(title.split())).strip()
        normalized_title = re.sub(r"\s*[,;/|:-]+\s*$", "", normalized_title).strip()
        if normalized_title:
            sanitized["title"] = normalized_title

    if "job" not in str(surface or "").lower():
        return sanitized

    sanitized.pop("image_url", None)
    sanitized.pop("additional_images", None)

    description = _summarize_job_listing_description(sanitized.get("description"))
    if description:
        sanitized["description"] = description
    else:
        sanitized.pop("description", None)
    return sanitized


def _summarize_job_listing_description(value: object) -> str:
    text = _clean_candidate_text(value, limit=None)
    if not text:
        return ""
    text = " ".join(str(text).split()).strip()
    if not text:
        return ""
    if len(text) <= 180:
        return text

    parts = [
        segment.strip(" -|,:;/")
        for segment in re.split(r"(?<=[.!?])\s+", text)
        if segment and segment.strip(" -|,:;/")
    ]
    if not parts:
        return text[:180].rstrip(" ,;:-") + "..."

    summary_parts: list[str] = []
    summary_len = 0
    for part in parts:
        projected = summary_len + len(part) + (1 if summary_parts else 0)
        if projected > 180:
            break
        summary_parts.append(part)
        summary_len = projected
        if summary_len >= 80 or len(summary_parts) >= 4:
            break

    summary = " ".join(summary_parts).strip()
    if len(summary) >= 35:
        return summary
    return text[:180].rstrip(" ,;:-") + "..."


async def _extract_detail(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    html: str,
    acq: AcquisitionResult,
    adapter_result,
    adapter_records: list[dict],
    additional_fields: list[str],
    extraction_contract: list[dict],
    surface: str,
    url_metrics: dict,
    update_run_state: bool = True,
    persist_logs: bool = True,
) -> tuple[list[dict], str, dict]:
    """Detail page extraction — adapter > candidates."""
    adapter_name = adapter_result.adapter_name if adapter_result else None
    resolved_schema = await resolve_schema(
        session,
        surface,
        url,
        run_id=run.id,
        explicit_fields=additional_fields,
        html=html,
        sample_record=adapter_records[0] if adapter_records and isinstance(adapter_records[0], dict) else None,
        llm_enabled=bool((run.settings or {}).get("llm_enabled")),
    )

    candidates, source_trace = extract_candidates(
        url,
        surface,
        html,
        acq.network_payloads,
        additional_fields,
        extraction_contract,
        resolved_fields=resolved_schema.fields,
        adapter_records=adapter_records,
    )
    persisted_field_names = set(resolved_schema.fields)
    candidate_values, reconciliation = _reconcile_detail_candidate_values(
        candidates,
        allowed_fields=persisted_field_names,
        url=url,
    )
    semantic = source_trace.get("semantic") if isinstance(source_trace.get("semantic"), dict) else {}
    source_trace = {
        **_build_acquisition_trace(acq),
        **source_trace,
    }

    # Build deterministic field discovery summary for all detail fields before any
    # optional LLM suggestion pass. Canonical output still comes strictly from the
    # first candidate row in source order.
    source_trace = _build_field_discovery_summary(
        source_trace, candidates, candidate_values, additional_fields, surface,
    )

    if adapter_records:
        extracted_records = adapter_records
    else:
        extracted_records = []

    llm_review_bucket: list[dict[str, object]] = []
    if html and (run.settings or {}).get("llm_enabled"):
        source_trace, llm_review_bucket = await _collect_detail_llm_suggestions(
            session=session,
            run=run,
            url=url,
            surface=surface,
            html=html,
            xhr_payloads=acq.network_payloads,
            additional_fields=additional_fields,
            adapter_records=extracted_records,
            candidate_values=candidate_values,
            source_trace=source_trace,
            resolved_schema=resolved_schema,
        )
        candidate_values, llm_promoted_fields = _apply_llm_suggestions_to_candidate_values(
            candidate_values,
            allowed_fields=persisted_field_names,
            source_trace=source_trace,
            url=url,
        )
        if llm_promoted_fields:
            llm_status = dict(source_trace.get("llm_cleanup_status") or {})
            llm_status["auto_promoted_fields"] = sorted(llm_promoted_fields.keys())
            source_trace["llm_cleanup_status"] = llm_status
        source_trace = _build_field_discovery_summary(
            source_trace, source_trace.get("candidates") or candidates, candidate_values, additional_fields, surface,
        )

    saved: list[dict] = []

    if update_run_state:
        await _set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await _log(session, run.id, "info", "[ANALYZE] Normalizing detail record")
    if extracted_records:
        # Detail page with adapter records — take first only
        for raw_record in extracted_records[:1]:
            merged_record = _merge_record_fields(raw_record, candidate_values)
            public_fields = _public_record_fields(merged_record)
            normalized, discovered_fields = _split_detail_output_fields(public_fields, allowed_fields=persisted_field_names)
            raw_data = _raw_record_payload(merged_record)
            requested_coverage = _requested_field_coverage(normalized, additional_fields)
            review_bucket = _merge_review_bucket_entries(
                _build_review_bucket(
                    discovered_fields,
                    source_trace=source_trace,
                    fallback_source=adapter_name or "adapter",
                ),
                llm_review_bucket,
            )
            db_record = CrawlRecord(
                run_id=run.id,
                source_url=url,
                data=normalized,
                raw_data=raw_data,
                discovered_data=_compact_dict({
                    "review_bucket": review_bucket or None,
                    "requested_field_coverage": requested_coverage or None,
                }),
                source_trace=_compact_dict({
                    **source_trace,
                    "type": "detail",
                    "adapter": adapter_name,
                    "schema_resolution": schema_trace_payload(resolved_schema),
                    "reconciliation": reconciliation or None,
                    "requested_fields": additional_fields or None,
                    "requested_field_coverage": requested_coverage or None,
                    "manifest_trace": _build_manifest_trace(
                        html=html,
                        xhr_payloads=acq.network_payloads,
                        adapter_records=adapter_records,
                        semantic=semantic,
                    ) or None,
                }),
                raw_html_path=acq.artifact_path,
            )
            session.add(db_record)
            saved.append(normalized)
    elif candidate_values or source_trace.get("llm_cleanup_suggestions"):
        # Build record from candidates (detail page, no adapter)
        normalized, discovered_fields = _split_detail_output_fields(candidate_values, allowed_fields=persisted_field_names)
        raw_data = candidate_values
        requested_coverage = _requested_field_coverage(normalized, additional_fields)
        review_bucket = _merge_review_bucket_entries(
            _build_review_bucket(
                discovered_fields,
                source_trace=source_trace,
                fallback_source="detail_candidates",
            ),
            llm_review_bucket,
        )
        discovered_data = _compact_dict({
            "review_bucket": review_bucket or None,
            "requested_field_coverage": requested_coverage or None,
        })
        db_record = CrawlRecord(
            run_id=run.id,
            source_url=url,
            data=normalized,
            raw_data=raw_data,
            discovered_data=discovered_data,
            source_trace=_compact_dict({
                **source_trace,
                "type": "detail",
                "schema_resolution": schema_trace_payload(resolved_schema),
                "reconciliation": reconciliation or None,
                "requested_fields": additional_fields or None,
                "requested_field_coverage": requested_coverage or None,
                "manifest_trace": _build_manifest_trace(
                    html=html,
                    xhr_payloads=acq.network_payloads,
                    adapter_records=adapter_records,
                    semantic=semantic,
                ) or None,
            }),
            raw_html_path=acq.artifact_path,
        )
        session.add(db_record)
        saved.append(normalized)

    if update_run_state:
        await _set_stage(session, run, STAGE_SAVE)
    verdict = _compute_verdict(saved, is_listing=False)
    if persist_logs:
        await _log(session, run.id, "info", f"[SAVE] Saved {len(saved)} detail records (verdict={verdict})")
    await session.flush()
    _finalize_url_metrics(url_metrics, records=saved, requested_fields=additional_fields)
    return saved, verdict, url_metrics


# ---------------------------------------------------------------------------
# Verdict helpers
# ---------------------------------------------------------------------------

def _compute_verdict(
    records: list[dict],
    is_listing: bool,
) -> str:
    """Compute extraction quality verdict for a single URL.

    Verdict is based on core field presence, not requested fields.
    Requested field coverage is tracked separately in ``_requested_field_coverage``
    and stored in ``discovered_data`` — it does NOT downgrade the verdict.
    """
    if not records:
        return VERDICT_LISTING_FAILED if is_listing else VERDICT_EMPTY

    core_fields = VERDICT_CORE_FIELDS_LISTING if is_listing else VERDICT_CORE_FIELDS_DETAIL
    for record in records:
        record_keys = {k for k in record if not k.startswith("_")}
        if core_fields & record_keys:
            return VERDICT_SUCCESS

    return VERDICT_PARTIAL


def _aggregate_verdict(verdicts: list[str]) -> str:
    """Aggregate per-URL verdicts into a single run verdict."""
    if not verdicts:
        return VERDICT_EMPTY

    if all(v == VERDICT_BLOCKED for v in verdicts):
        return VERDICT_BLOCKED
    if all(v == VERDICT_SUCCESS for v in verdicts):
        return VERDICT_SUCCESS
    if any(v in {VERDICT_SUCCESS, VERDICT_PARTIAL} for v in verdicts):
        return VERDICT_PARTIAL

    # Return the most common non-success verdict
    for v in [VERDICT_LISTING_FAILED, VERDICT_SCHEMA_MISS, VERDICT_BLOCKED, VERDICT_EMPTY]:
        if v in verdicts:
            return v
    return VERDICT_PARTIAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _log(session: AsyncSession, run_id: int, level: str, message: str) -> None:
    session.add(CrawlLog(run_id=run_id, level=level, message=message))
    await session.flush()


async def _set_stage(
    session: AsyncSession,
    run: CrawlRun,
    stage: str,
    *,
    current_url: str | None = None,
    current_url_index: int | None = None,
    total_urls: int | None = None,
) -> None:
    result_summary = dict(run.result_summary or {})
    result_summary["current_stage"] = stage
    if current_url is not None:
        result_summary["current_url"] = current_url
    if current_url_index is not None:
        result_summary["current_url_index"] = current_url_index
    if total_urls is not None:
        result_summary["total_urls"] = total_urls
    run.result_summary = result_summary
    await session.commit()


async def _mark_run_failed(session: AsyncSession, run_id: int, error_msg: str) -> None:
    """Mark a run as failed.

    First attempts recovery using the existing session (after a rollback).
    If that fails, creates an isolated session via ``SessionLocal`` so a
    poisoned transaction cannot block failure recording.
    """
    try:
        await session.rollback()
    except Exception:
        pass  # Original session may already be invalidated — that's fine.

    # Try the original session first — works in tests and when the session is still usable.
    try:
        await _persist_failure_state(session, run_id, error_msg)
        return
    except Exception:
        logger.debug("Original session unusable for failure recovery; falling back to SessionLocal", exc_info=True)

    from app.core.database import SessionLocal

    async with SessionLocal() as recovery:
        run = await recovery.get(CrawlRun, run_id)
        if run is None:
            return
        result_summary = dict(run.result_summary or {})
        result_summary["error"] = error_msg
        result_summary["progress"] = result_summary.get("progress", 0)
        result_summary["extraction_verdict"] = "error"
        if normalize_status(run.status) not in TERMINAL_STATUSES:
            update_run_status(run, CrawlStatus.FAILED)
        run.result_summary = result_summary
        recovery.add(CrawlLog(run_id=run.id, level="error", message=f"Pipeline failed: {error_msg}"))
        await recovery.commit()


async def _persist_failure_state(session: AsyncSession, run_id: int, error_msg: str) -> None:
    """Write failure state into the given session and commit."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    result_summary = dict(run.result_summary or {})
    result_summary["error"] = error_msg
    result_summary["progress"] = result_summary.get("progress", 0)
    result_summary["extraction_verdict"] = "error"
    if normalize_status(run.status) not in TERMINAL_STATUSES:
        update_run_status(run, CrawlStatus.FAILED)
    run.result_summary = result_summary
    session.add(CrawlLog(run_id=run.id, level="error", message=f"Pipeline failed: {error_msg}"))
    await session.commit()


def _collect_target_urls(payload: dict, settings: dict) -> list[str]:
    candidates: list[str] = []
    direct_url = str(payload.get("url") or "").strip()
    if direct_url:
        candidates.append(direct_url)
    for value in payload.get("urls") or []:
        candidate = str(value or "").strip()
        if candidate:
            candidates.append(candidate)
    for value in settings.get("urls") or []:
        candidate = str(value or "").strip()
        if candidate:
            candidates.append(candidate)
    csv_content = str(settings.get("csv_content") or "")
    if csv_content:
        candidates.extend(parse_csv_urls(csv_content))
    return list(dict.fromkeys(candidates))


async def _count_run_records(session: AsyncSession, run_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(CrawlRecord).where(CrawlRecord.run_id == run_id)
            )
        ).scalar()
        or 0
    )


def _public_record_fields(record: dict) -> dict:
    return {
        key: value
        for key, value in record.items()
        if not str(key).startswith("_")
    }


def _build_legible_listing_fallback_record(
    *,
    url: str,
    html: str,
    xhr_payloads: list[dict],
    adapter_records: list[dict],
) -> dict[str, dict[str, object] | dict[str, int | bool | str]] | None:
    page_sources = parse_page_sources(html)
    tables = list(page_sources.get("tables") or [])
    soup = BeautifulSoup(html or "", "html.parser")
    for selector in ("script", "style", "noscript", "svg", "iframe", "header", "footer", "nav", "aside"):
        for node in soup.select(selector):
            node.decompose()

    title = _first_non_empty_text(
        soup.select_one("main h1"),
        soup.select_one("article h1"),
        soup.select_one("h1"),
    )
    if not title:
        title = _clean_page_text((soup.title.string if soup.title and soup.title.string else ""))
    description_meta = soup.select_one("meta[name='description']")
    description = _clean_page_text(description_meta.get("content", "") if description_meta else "")

    content_root = soup.select_one("main") or soup.select_one("article") or soup.body or soup
    markdown_lines: list[str] = []
    fallback_table_rows: list[dict[str, object]] = []
    total_chars = 0
    card_lines, card_chars, fallback_table_rows = _render_fallback_card_group(content_root, page_url=url)
    if card_lines:
        markdown_lines.extend(card_lines)
        total_chars += card_chars
    else:
        seen_text: set[str] = set()
        for node in content_root.select("h2, h3, h4, p, li"):
            if _should_skip_fallback_node(node, page_url=url):
                continue
            text = _render_fallback_node_markdown(node, page_url=url)
            if not text or text in seen_text:
                continue
            seen_text.add(text)
            plain_text = _clean_page_text(node.get_text(" ", strip=True))
            if node.name in {"h2", "h3", "h4"} and len(plain_text) <= 140:
                line = f"## {text}"
            elif node.name == "li":
                line = f"- {text}"
            else:
                line = text
            markdown_lines.append(line)
            total_chars += len(plain_text)
            if total_chars >= 2400 or len(markdown_lines) >= 24:
                break

    table_markdown = _render_manifest_tables_markdown(tables)
    if table_markdown:
        if markdown_lines:
            markdown_lines.extend(["## Tables", table_markdown])
        else:
            markdown_lines.extend(["## Tables", table_markdown])

    enough_text = total_chars >= 180 and len(markdown_lines) >= 3
    has_tables = bool(table_markdown)
    if not enough_text and not has_tables:
        return None

    page_markdown_lines: list[str] = []
    if title:
        page_markdown_lines.append(f"# {title}")
    if description:
        page_markdown_lines.extend(["", description])
    if markdown_lines:
        page_markdown_lines.extend(["", *markdown_lines] if page_markdown_lines else markdown_lines)
    page_markdown = "\n".join(line for line in page_markdown_lines if line is not None).strip()
    if len(page_markdown) < 120 and not has_tables:
        return None

    data = _compact_dict({
        "title": title or None,
        "description": description or None,
        "page_markdown": page_markdown or None,
        "table_markdown": table_markdown or None,
        "record_type": "page_fallback",
    })
    raw_data = _compact_dict({
        "page_text_excerpt": page_markdown or None,
        "tables": tables[:3] if tables else None,
        "typed_table_rows": fallback_table_rows or None,
    })
    summary: dict[str, int | bool | str] = _compact_dict({
        "title": title or None,
        "has_description": bool(description),
        "content_chars": total_chars,
        "table_count": len(tables),
        "has_tables": has_tables,
        "typed_row_count": len(fallback_table_rows),
    })
    manifest_tables = list(tables)
    if fallback_table_rows:
        manifest_tables.append({
            "table_index": len(manifest_tables) + 1,
            "section_title": "Fallback cards",
            "caption": "Fallback listing rows",
            "headers": [
                {"text": "title", "href": None},
                {"text": "url", "href": None},
                {"text": "description", "href": None},
            ],
            "rows": [
                {
                    "row_index": index,
                    "cells": [
                        {"text": str(item.get("title") or ""), "href": None},
                        {"text": str(item.get("url") or ""), "href": None},
                        {"text": str(item.get("description") or ""), "href": None},
                    ],
                }
                for index, item in enumerate(fallback_table_rows, start=1)
            ],
        })
    return {
        "data": data,
        "raw_data": raw_data,
        "summary": summary,
        "manifest_trace": _compact_dict({
            "adapter_data": adapter_records or None,
            "network_payloads": [{"url": row.get("url"), "status": row.get("status")} for row in xhr_payloads if isinstance(row, dict)] or None,
            "next_data": page_sources.get("next_data") or None,
            "_hydrated_states": page_sources.get("hydrated_states") or None,
            "embedded_json": page_sources.get("embedded_json") or None,
            "open_graph": page_sources.get("open_graph") or None,
            "json_ld": page_sources.get("json_ld") or None,
            "microdata": page_sources.get("microdata") or None,
            "tables": manifest_tables or None,
            "fallback_table_rows": fallback_table_rows or None,
        }),
    }


def _first_non_empty_text(*nodes: object) -> str:
    for node in nodes:
        text = ""
        if node is not None and hasattr(node, "get_text"):
            text = _clean_page_text(node.get_text(" ", strip=True))
        if text:
            return text
    return ""


def _clean_page_text(value: object) -> str:
    text = unescape(str(value or "")).replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _render_fallback_node_markdown(node: Tag, *, page_url: str) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = _clean_page_text(str(child))
            if text:
                parts.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        if child.name == "a":
            text = _clean_page_text(child.get_text(" ", strip=True))
            href = _clean_page_text(child.get("href", ""))
            resolved_href = urljoin(page_url, href) if href else ""
            if text and resolved_href:
                parts.append(f"[{text}]({resolved_href})")
            elif text:
                parts.append(text)
            continue
        nested = _render_fallback_node_markdown(child, page_url=page_url)
        if nested:
            parts.append(nested)
    return _clean_page_text(" ".join(parts)) if parts else _clean_page_text(node.get_text(" ", strip=True))


def _render_fallback_card_group(root: Tag, *, page_url: str) -> tuple[list[str], int, list[dict[str, object]]]:
    cards = _find_fallback_card_group(root)
    if not cards:
        return [], 0, []

    lines: list[str] = []
    typed_rows: list[dict[str, object]] = []
    total_chars = 0
    seen_titles: set[str] = set()
    for card in cards[:12]:
        title_node = card.select_one("h1 a, h2 a, h3 a, h4 a, h5 a, h1, h2, h3, h4, h5")
        title_text = _clean_page_text(title_node.get_text(" ", strip=True)) if title_node else ""
        if not title_text or title_text.lower() in seen_titles:
            continue
        seen_titles.add(title_text.lower())
        link_node = title_node if isinstance(title_node, Tag) and title_node.name == "a" else card.select_one("a[href]")
        href = _clean_page_text(link_node.get("href", "")) if isinstance(link_node, Tag) else ""
        resolved_href = urljoin(page_url, href) if href else ""
        title_line = f"## [{title_text}]({resolved_href})" if resolved_href else f"## {title_text}"
        lines.append(title_line)
        total_chars += len(title_text)
        typed_row: dict[str, object] = {
            "title": title_text,
            "url": resolved_href or None,
        }

        description_node = card.select_one("p, [class*='description' i], [class*='summary' i], [class*='excerpt' i]")
        if description_node:
            description_text = _clean_page_text(description_node.get_text(" ", strip=True))
            if description_text and description_text.lower() != title_text.lower():
                lines.append(description_text)
                total_chars += len(description_text)
                typed_row["description"] = description_text
        typed_rows.append(_compact_dict(typed_row))
        if len(lines) >= 24 or total_chars >= 2400:
            break

    return lines, total_chars, typed_rows


def _find_fallback_card_group(root: Tag) -> list[Tag]:
    best_group: list[Tag] = []
    best_score: tuple[int, int] = (0, 0)
    for container in root.select("main, section, div, ul, ol"):
        children = [child for child in container.children if isinstance(child, Tag)]
        if len(children) < 2:
            continue
        grouped: dict[tuple[str, tuple[str, ...]], list[Tag]] = {}
        for child in children:
            key = (child.name, tuple(sorted(child.get("class", []))))
            grouped.setdefault(key, []).append(child)
        for _key, group in grouped.items():
            if len(group) < 2:
                continue
            linked_titles = 0
            descriptive_cards = 0
            for card in group[:12]:
                if card.select_one("h1 a, h2 a, h3 a, h4 a, h5 a, h1, h2, h3, h4, h5") and card.select_one("a[href]"):
                    linked_titles += 1
                desc_node = card.select_one("p, [class*='description' i], [class*='summary' i], [class*='excerpt' i]")
                if desc_node and len(_clean_page_text(desc_node.get_text(" ", strip=True))) >= 40:
                    descriptive_cards += 1
            score = (linked_titles, descriptive_cards)
            if linked_titles >= 2 and score > best_score:
                best_group = group
                best_score = score
    return best_group


def _should_skip_fallback_node(node: Tag, *, page_url: str) -> bool:
    text = _clean_page_text(node.get_text(" ", strip=True))
    if not text:
        return True
    lowered = text.lower()
    if node.name == "li":
        if len(text) <= 30:
            anchor = node.select_one("a[href]")
            href = _clean_page_text(anchor.get("href", "")) if isinstance(anchor, Tag) else ""
            resolved_href = urljoin(page_url, href) if href else ""
            if resolved_href:
                parsed = urlparse(resolved_href)
                segments = [segment for segment in parsed.path.split("/") if segment]
                if len(segments) <= 1:
                    return True
            if lowered in {"home", "products", "services", "contact us", "blogs", "news", "grinding advice"}:
                return True
    if lowered in {"read more", "learn more", "view more"}:
        return True
    return False


def _render_manifest_tables_markdown(tables: list[dict] | None) -> str:
    rendered_tables: list[str] = []
    for table in list(tables or [])[:3]:
        rows = table.get("rows") if isinstance(table, dict) else None
        if not isinstance(rows, list) or not rows:
            continue
        table_lines: list[str] = []
        for row in rows[:8]:
            cells = row.get("cells") if isinstance(row, dict) else None
            if not isinstance(cells, list):
                continue
            values = [
                _clean_page_text(cell.get("text", "")) for cell in cells
                if isinstance(cell, dict) and _clean_page_text(cell.get("text", ""))
            ]
            if values:
                table_lines.append("| " + " | ".join(values) + " |")
        if table_lines:
            rendered_tables.append("\n".join(table_lines))
    return "\n\n".join(rendered_tables).strip()


def _normalize_record_fields(record: dict[str, object]) -> dict[str, object]:
    normalized = _compact_dict({
        _normalize_committed_field_name(key): normalize_value(_normalize_committed_field_name(key), value)
        for key, value in record.items()
        if _normalize_committed_field_name(key)
    })
    if not str(normalized.get("currency") or "").strip():
        for field_name in ("price", "sale_price", "original_price", "salary"):
            currency_hint = extract_currency_hint(normalized.get(field_name))
            if currency_hint:
                normalized["currency"] = currency_hint
                break
    return normalized


def _reconcile_detail_candidate_values(
    candidates: dict[str, list[dict]],
    *,
    allowed_fields: set[str],
    url: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    reconciled: dict[str, object] = {}
    reconciliation: dict[str, dict[str, object]] = {}

    for field_name in sorted(allowed_fields):
        rows = list(candidates.get(field_name) or [])
        if not rows:
            continue

        accepted_row: dict | None = None
        rejected_rows: list[dict[str, object]] = []
        for row in rows:
            value = row.get("value")
            normalized_value = coerce_field_candidate_value(field_name, value, base_url=url)
            if normalized_value in (None, "", [], {}):
                rejected_rows.append({
                    "value": value,
                    "reason": "empty_after_normalization",
                    "source": row.get("source"),
                })
                continue
            if not _passes_detail_quality_gate(field_name, normalized_value):
                rejected_rows.append({
                    "value": normalized_value,
                    "reason": "quality_gate_rejected",
                    "source": row.get("source"),
                })
                continue
            accepted_row = {**row, "value": normalized_value}
            break

        if accepted_row is None:
            if rejected_rows:
                reconciliation[field_name] = {"status": "rejected", "rejected": rejected_rows[:6]}
            continue

        reconciled[field_name] = accepted_row["value"]
        if rejected_rows:
            reconciliation[field_name] = _compact_dict({
                "status": "accepted_with_rejections",
                "accepted_source": accepted_row.get("source"),
                "rejected": rejected_rows[:6],
            })

    return reconciled, reconciliation


def _passes_detail_quality_gate(field_name: str, value: object) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        if not text or text.lower() in {"-", "—", "--", "n/a", "na", "none", "null", "undefined"}:
            return False
        if field_name in {"title", "brand", "category"}:
            return len(text) >= 2
        if field_name in {"price", "sale_price", "original_price", "salary", "review_count", "rating"}:
            return bool(re.search(r"\d", text))
        if field_name == "currency":
            return bool(re.fullmatch(r"[A-Z]{3}", text.upper()) or re.search(r"[€£$¥₹]", text))
        if field_name in {"sku", "availability"}:
            return len(text) >= 2
        return len(text) >= 1
    return True


def _apply_llm_suggestions_to_candidate_values(
    candidate_values: dict[str, object],
    *,
    allowed_fields: set[str],
    source_trace: dict,
    url: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    suggestions = source_trace.get("llm_cleanup_suggestions")
    if not isinstance(suggestions, dict):
        return candidate_values, {}

    trace_candidates = source_trace.setdefault("candidates", {})
    promoted: dict[str, dict[str, object]] = {}
    for field_name, raw_suggestion in suggestions.items():
        normalized_field = str(field_name or "").strip()
        if not normalized_field or normalized_field not in allowed_fields:
            continue
        if candidate_values.get(normalized_field) not in (None, "", [], {}):
            continue
        if not isinstance(raw_suggestion, dict):
            continue

        suggested_value = raw_suggestion.get("suggested_value")
        normalized_value = coerce_field_candidate_value(normalized_field, suggested_value, base_url=url)
        if normalized_value in (None, "", [], {}):
            continue
        if not _passes_detail_quality_gate(normalized_field, normalized_value):
            continue

        source = str(raw_suggestion.get("source") or "llm_cleanup").strip() or "llm_cleanup"
        note = _clean_candidate_text(raw_suggestion.get("note") or raw_suggestion.get("reason"), limit=280)
        candidate_values[normalized_field] = normalized_value
        promoted[normalized_field] = _compact_dict({
            "value": normalized_value,
            "source": source,
            "note": note or None,
        })

        existing_rows = trace_candidates.setdefault(normalized_field, [])
        normalized_fingerprint = _review_bucket_fingerprint(normalized_value)
        if not any(
            isinstance(row, dict)
            and str(row.get("source") or "").strip() == source
            and _review_bucket_fingerprint(row.get("value")) == normalized_fingerprint
            for row in existing_rows
        ):
            existing_rows.insert(0, _compact_dict({
                "value": normalized_value,
                "source": source,
                "status": "auto_promoted",
                "note": note or None,
            }))

        updated_suggestion = dict(raw_suggestion)
        updated_suggestion["status"] = "auto_promoted"
        updated_suggestion["accepted_value"] = normalized_value
        updated_suggestion["score"] = score
        suggestions[normalized_field] = _compact_dict(updated_suggestion)

    if promoted:
        source_trace["llm_cleanup_suggestions"] = suggestions
        source_trace["llm_promoted_fields"] = promoted
    return candidate_values, promoted


def _split_detail_output_fields(
    record: dict[str, object],
    *,
    allowed_fields: set[str],
) -> tuple[dict[str, object], dict[str, object]]:
    normalized = _normalize_record_fields(record)
    canonical: dict[str, object] = {}
    discovered: dict[str, object] = {}
    for key, value in normalized.items():
        if key in allowed_fields:
            canonical[key] = value
        else:
            discovered[key] = value
    return canonical, discovered


def _build_review_bucket(
    discovered_fields: dict[str, object],
    *,
    source_trace: dict | None = None,
    fallback_source: str = "deterministic_extraction",
) -> list[dict[str, object]]:
    candidate_map = source_trace.get("candidates") if isinstance(source_trace, dict) else {}
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for field_name, value in discovered_fields.items():
        normalized_value = _normalize_review_value(value)
        if normalized_value is None:
            continue
        source = _review_bucket_source_for_field(field_name, candidate_map, fallback_source)
        if not _should_surface_discovered_field(field_name, normalized_value, source=source):
            continue
        entry = _compact_dict({
            "key": str(field_name).strip(),
            "value": normalized_value,
            "confidence_score": _review_bucket_confidence(field_name, normalized_value, source),
            "source": source,
        })
        fingerprint = (str(entry["key"]), _review_bucket_fingerprint(entry["value"]))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        rows.append(entry)
    return rows


def _merge_review_bucket_entries(*groups: list[dict[str, object]]) -> list[dict[str, object]]:
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for group in groups:
        for row in group:
            key = str(row.get("key") or "").strip()
            if not key:
                continue
            normalized_value = _normalize_review_value(row.get("value"))
            if normalized_value is None:
                continue
            source = str(row.get("source") or "review_bucket").strip() or "review_bucket"
            if not _should_surface_discovered_field(key, normalized_value, source=source):
                continue
            fingerprint = (key, _review_bucket_fingerprint(normalized_value))
            existing = merged.get(fingerprint)
            candidate = _compact_dict({
                "key": key,
                "value": normalized_value,
                "confidence_score": _clamp_review_confidence(row.get("confidence_score", row.get("confidence", 5))),
                "source": source,
            })
            if existing is None or int(candidate["confidence_score"]) > int(existing.get("confidence_score", 0)):
                merged[fingerprint] = candidate
    return sorted(
        merged.values(),
        key=lambda item: (
            -int(item.get("confidence_score", 0)),
            str(item.get("key") or ""),
            str(item.get("source") or ""),
        ),
    )


def _build_manifest_trace(
    *,
    html: str,
    xhr_payloads: list[dict],
    adapter_records: list[dict],
    semantic: dict | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    page_sources = parse_page_sources(html)
    payload = _compact_dict({
        "adapter_data": adapter_records or None,
        "network_payloads": [
            _compact_dict({
                "url": row.get("url"),
                "status": row.get("status"),
                "body": row.get("body"),
            })
            for row in xhr_payloads
            if isinstance(row, dict)
        ] or None,
        "next_data": page_sources.get("next_data") or None,
        "_hydrated_states": page_sources.get("hydrated_states") or None,
        "embedded_json": page_sources.get("embedded_json") or None,
        "open_graph": page_sources.get("open_graph") or None,
        "json_ld": page_sources.get("json_ld") or None,
        "microdata": page_sources.get("microdata") or None,
        "tables": page_sources.get("tables") or None,
        "semantic": semantic or None,
        **(extra or {}),
    })
    return payload


def _resolve_listing_surface(
    *,
    surface: str,
    url: str,
    html: str,
    acq: AcquisitionResult,
) -> str:
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface != "ecommerce_listing":
        return surface
    if _looks_like_job_listing_page(url=url, html=html, acq=acq):
        return "job_listing"
    return surface


def _looks_like_job_listing_page(*, url: str, html: str, acq: AcquisitionResult) -> bool:
    lowered_url = str(url or "").lower()
    if any(token in lowered_url for token in ("/jobs", "/job-", "/job/", "/careers", "/career", "job-search", "search-jobs")):
        return True

    diagnostics = acq.diagnostics if isinstance(acq.diagnostics, dict) else {}
    platform_family = str((diagnostics.get("curl_platform_family") or "")).strip().lower()
    if platform_family in {"workday", "icims", "adp", "generic_jobs", "rippling_ats"}:
        return True

    lowered_html = str(html or "").lower()
    job_markers = (
        "search jobs",
        "current openings",
        "open positions",
        "job openings",
        "career opportunities",
        "apply now",
        "job search",
        "employment opportunities",
        "data-automation-id=\"jobtitle\"",
        "data-testid=\"careers",
        "careers.js",
        "job-location-autocomplete",
        "job-title",
    )
    signals = sum(1 for marker in job_markers if marker in lowered_html)
    return signals >= 2




def _review_bucket_source_for_field(field_name: str, candidate_map: object, fallback_source: str) -> str:
    if isinstance(candidate_map, dict):
        rows = candidate_map.get(field_name)
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                source = str(row.get("source") or "").strip()
                if source:
                    return source
    return fallback_source


def _review_bucket_confidence(field_name: str, value: object, source: str) -> int:
    normalized_source = str(source or "").strip().lower()
    base = 6
    if normalized_source.startswith("adapter") or normalized_source in {"json_api", "network_payload"}:
        base = 8
    elif normalized_source.startswith("semantic_spec") or "table" in normalized_source:
        base = 9
    elif normalized_source.startswith("json_ld") or normalized_source.startswith("microdata"):
        base = 8
    elif normalized_source.startswith("llm_xpath"):
        base = 7
    elif normalized_source.startswith("llm_cleanup"):
        base = 6
    elif normalized_source.startswith("dom"):
        base = 5
    if _passes_detail_quality_gate(field_name, value):
        base += 1
    else:
        base -= 1
    return max(1, min(10, base))


def _clamp_review_confidence(value: object) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = 5
    return max(1, min(10, numeric))


def _review_bucket_fingerprint(value: object) -> str:
    normalized_value = _normalize_review_value(value)
    try:
        return json.dumps(normalized_value, sort_keys=True, default=str)
    except TypeError:
        return str(normalized_value)


def _normalize_committed_field_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    normalized = re.sub(r"\s+", "_", text.lower())
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _raw_record_payload(record: dict) -> dict:
    raw_item = record.get("_raw_item")
    if isinstance(raw_item, dict):
        return raw_item
    return _public_record_fields(record)


def _merge_record_fields(primary: dict, secondary: dict) -> dict:
    merged = dict(primary)
    for key, value in secondary.items():
        if key.startswith("_"):
            continue
        if _should_prefer_secondary_field(key, merged.get(key), value):
            merged[key] = value
    return merged


def _should_prefer_secondary_field(field_name: str, existing: object, candidate: object) -> bool:
    if candidate in (None, "", [], {}):
        return False
    if existing in (None, "", [], {}):
        return True
    if field_name in {"description", "specifications"}:
        return len(_clean_candidate_text(candidate, limit=None)) > len(_clean_candidate_text(existing, limit=None))
    if field_name == "additional_images":
        existing_count = len([part for part in str(existing or "").split(",") if part.strip()])
        candidate_count = len([part for part in str(candidate or "").split(",") if part.strip()])
        return candidate_count > existing_count
    return False


def _requested_field_coverage(record: dict, requested_fields: list[str]) -> dict:
    if not requested_fields:
        return {}
    normalized_requested = [field for field in requested_fields if field]
    found = [
        field
        for field in normalized_requested
        if record.get(field) not in (None, "", [], {})
    ]
    return {
        "requested": len(normalized_requested),
        "found": len(found),
        "missing": [field for field in normalized_requested if field not in found],
    }


def _build_acquisition_profile(run_settings: dict | None) -> dict[str, object]:
    profile: dict[str, object] = {}
    settings = run_settings if isinstance(run_settings, dict) else {}
    if "anti_bot_enabled" in settings:
        profile["anti_bot_enabled"] = bool(settings.get("anti_bot_enabled"))
    return profile


def _resolve_traversal_mode(settings: dict | None) -> str | None:
    if not isinstance(settings, dict):
        return None
    if not bool(settings.get("advanced_enabled")):
        return None
    mode = str(settings.get("advanced_mode") or "").strip().lower()
    if mode in _TRAVERSAL_MODES:
        return mode
    return None


def _build_url_metrics(acq: AcquisitionResult, *, requested_fields: list[str]) -> dict[str, object]:
    diagnostics = acq.diagnostics if isinstance(acq.diagnostics, dict) else {}
    timing_map = diagnostics.get("timings_ms") if isinstance(diagnostics.get("timings_ms"), dict) else {}
    return _compact_dict({
        "method": acq.method,
        "content_type": acq.content_type,
        "platform_family": str(diagnostics.get("curl_platform_family") or "").strip() or None,
        "browser_attempted": bool(diagnostics.get("browser_attempted")),
        "browser_used": acq.method == "playwright",
        "memory_browser_first": bool(diagnostics.get("memory_browser_first")),
        "proxy_used": bool(diagnostics.get("proxy_used")),
        "network_payloads": len(acq.network_payloads or []),
        "host_wait_seconds": float(diagnostics.get("host_wait_seconds", 0.0) or 0.0),
        "requested_fields": len(requested_fields or []),
        "curl_fetch_ms": int(timing_map.get("curl_fetch_ms", 0) or 0),
        "browser_decision_ms": int(timing_map.get("browser_decision_ms", 0) or 0),
        "browser_launch_ms": int(timing_map.get("browser_launch_ms", 0) or 0),
        "browser_origin_warm_ms": int(timing_map.get("browser_origin_warm_ms", 0) or 0),
        "browser_navigation_ms": int(timing_map.get("browser_navigation_ms", 0) or 0),
        "browser_challenge_wait_ms": int(timing_map.get("browser_challenge_wait_ms", 0) or 0),
        "browser_listing_readiness_wait_ms": int(timing_map.get("browser_listing_readiness_wait_ms", 0) or 0),
        "browser_traversal_ms": int(timing_map.get("browser_traversal_ms", 0) or 0),
    })


def _finalize_url_metrics(url_metrics: dict[str, object], *, records: list[dict], requested_fields: list[str]) -> dict[str, object]:
    found_counts = [
        int((_requested_field_coverage(record, requested_fields) or {}).get("found", 0) or 0)
        for record in records
    ]
    requested_total = len([field for field in requested_fields if field])
    url_metrics["record_count"] = len(records)
    if requested_total > 0:
        url_metrics["requested_fields_total"] = requested_total
        url_metrics["requested_fields_found_best"] = max(found_counts or [0])
    return url_metrics


def _merge_run_acquisition_metrics(existing: object, url_metrics: dict[str, object]) -> dict[str, object]:
    current = dict(existing) if isinstance(existing, dict) else {}
    methods = dict(current.get("methods") or {})
    method = str(url_metrics.get("method") or "").strip()
    if method:
        methods[method] = int(methods.get(method, 0) or 0) + 1
    platform_families = dict(current.get("platform_families") or {})
    platform_family = str(url_metrics.get("platform_family") or "").strip()
    if platform_family:
        platform_families[platform_family] = int(platform_families.get(platform_family, 0) or 0) + 1

    summary = {
        "methods": methods,
        "platform_families": platform_families,
        "browser_attempted_urls": int(current.get("browser_attempted_urls", 0) or 0) + int(bool(url_metrics.get("browser_attempted"))),
        "browser_used_urls": int(current.get("browser_used_urls", 0) or 0) + int(bool(url_metrics.get("browser_used"))),
        "memory_browser_first_urls": int(current.get("memory_browser_first_urls", 0) or 0) + int(bool(url_metrics.get("memory_browser_first"))),
        "proxy_used_urls": int(current.get("proxy_used_urls", 0) or 0) + int(bool(url_metrics.get("proxy_used"))),
        "network_payloads_total": int(current.get("network_payloads_total", 0) or 0) + int(url_metrics.get("network_payloads", 0) or 0),
        "host_wait_seconds_total": round(float(current.get("host_wait_seconds_total", 0.0) or 0.0) + float(url_metrics.get("host_wait_seconds", 0.0) or 0.0), 3),
        "records_total": int(current.get("records_total", 0) or 0) + int(url_metrics.get("record_count", 0) or 0),
        "acquisition_ms_total": int(current.get("acquisition_ms_total", 0) or 0) + int(url_metrics.get("acquisition_ms", 0) or 0),
        "extraction_ms_total": int(current.get("extraction_ms_total", 0) or 0) + int(url_metrics.get("extraction_ms", 0) or 0),
        "curl_fetch_ms_total": int(current.get("curl_fetch_ms_total", 0) or 0) + int(url_metrics.get("curl_fetch_ms", 0) or 0),
        "browser_decision_ms_total": int(current.get("browser_decision_ms_total", 0) or 0) + int(url_metrics.get("browser_decision_ms", 0) or 0),
        "browser_launch_ms_total": int(current.get("browser_launch_ms_total", 0) or 0) + int(url_metrics.get("browser_launch_ms", 0) or 0),
        "browser_origin_warm_ms_total": int(current.get("browser_origin_warm_ms_total", 0) or 0) + int(url_metrics.get("browser_origin_warm_ms", 0) or 0),
        "browser_navigation_ms_total": int(current.get("browser_navigation_ms_total", 0) or 0) + int(url_metrics.get("browser_navigation_ms", 0) or 0),
        "browser_challenge_wait_ms_total": int(current.get("browser_challenge_wait_ms_total", 0) or 0) + int(url_metrics.get("browser_challenge_wait_ms", 0) or 0),
        "browser_listing_readiness_wait_ms_total": int(current.get("browser_listing_readiness_wait_ms_total", 0) or 0) + int(url_metrics.get("browser_listing_readiness_wait_ms", 0) or 0),
        "browser_traversal_ms_total": int(current.get("browser_traversal_ms_total", 0) or 0) + int(url_metrics.get("browser_traversal_ms", 0) or 0),
    }
    if "requested_fields_total" in url_metrics:
        summary["requested_fields_total"] = int(current.get("requested_fields_total", 0) or 0) + int(url_metrics.get("requested_fields_total", 0) or 0)
        summary["requested_fields_found_best_total"] = int(current.get("requested_fields_found_best_total", 0) or 0) + int(url_metrics.get("requested_fields_found_best", 0) or 0)
    return summary


def _compact_dict(payload: dict) -> dict:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }
def _build_acquisition_trace(acq: AcquisitionResult) -> dict[str, object]:
    diagnostics = acq.diagnostics if isinstance(acq.diagnostics, dict) else {}
    browser_diagnostics = diagnostics.get("browser_diagnostics") if isinstance(diagnostics.get("browser_diagnostics"), dict) else {}
    timing_map = diagnostics.get("timings_ms") if isinstance(diagnostics.get("timings_ms"), dict) else {}
    return _compact_dict({
        "method": acq.method,
        "browser_attempted": bool(diagnostics.get("browser_attempted")),
        "acquisition": _compact_dict({
            "final_url": diagnostics.get("curl_final_url") or browser_diagnostics.get("final_url"),
            "platform_family": str(diagnostics.get("curl_platform_family") or "").strip() or None,
            "browser_attempted": bool(diagnostics.get("browser_attempted")),
            "browser_used": acq.method == "playwright",
            "challenge_state": diagnostics.get("browser_challenge_state"),
            "origin_warmed": diagnostics.get("browser_origin_warmed"),
            "invalid_surface_page": diagnostics.get("invalid_surface_page"),
            "page_classification": diagnostics.get("page_classification") if isinstance(diagnostics.get("page_classification"), dict) else None,
            "timings_ms": timing_map or None,
        }) or None,
    })


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((time.perf_counter() - started_at) * 1000)))


def _validate_extraction_contract(contract_rows: list[dict]) -> None:
    errors: list[str] = []
    for index, row in enumerate(contract_rows, start=1):
        field_name = str(row.get("field_name") or "").strip()
        xpath = str(row.get("xpath") or "").strip()
        regex = str(row.get("regex") or "").strip()
        if not field_name:
            errors.append(f"Row {index}: field_name is required")
        if xpath:
            valid_xpath, xpath_error = validate_xpath_syntax(xpath)
            if not valid_xpath:
                errors.append(
                    f"Row {index} ({field_name or 'unnamed'}): invalid XPath ({xpath_error})"
                )
        if regex:
            try:
                regex_lib.compile(regex)
            except re.error as exc:
                errors.append(f"Row {index} ({field_name or 'unnamed'}): invalid regex ({exc})")
    if errors:
        raise ValueError("; ".join(errors))


async def _collect_detail_llm_suggestions(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    surface: str,
    html: str,
    xhr_payloads: list[dict],
    additional_fields: list[str],
    adapter_records: list[dict],
    candidate_values: dict,
    source_trace: dict,
    resolved_schema: ResolvedSchema,
) -> tuple[dict, list[dict[str, object]]]:
    trace_candidates = source_trace.setdefault("candidates", {})
    llm_cleanup_suggestions: dict[str, dict] = source_trace.get("llm_cleanup_suggestions", {})
    llm_cleanup_status: dict[str, object] = dict(source_trace.get("llm_cleanup_status") or {})
    llm_review_bucket: list[dict[str, object]] = []
    preview_record = (
        _merge_record_fields(adapter_records[0], candidate_values)
        if adapter_records else dict(candidate_values)
    )
    canonical_fields = sorted(set(resolved_schema.fields) | set(additional_fields))
    target_fields = list(canonical_fields)
    missing_fields = [
        field_name
        for field_name in target_fields
        if preview_record.get(field_name) in (None, "", [], {})
    ]

    domain = _domain(url)
    if missing_fields:
        await _log(session, run.id, "info", f"[ANALYZE] LLM XPath discovery for {len(missing_fields)} missing detail fields")
        xpath_rows, xpath_error = await discover_xpath_candidates(
            session,
            run_id=run.id,
            domain=domain,
            url=url,
            html_text=html,
            missing_fields=missing_fields,
            existing_values=preview_record,
        )
        if xpath_error:
            await _log(session, run.id, "warning", f"[LLM] XPath discovery failed: {xpath_error}")
            llm_cleanup_status = {
                **llm_cleanup_status,
                "status": "xpath_error",
                "message": xpath_error,
                "xpath_error": xpath_error,
            }
        elif not xpath_rows:
            await _log(session, run.id, "warning", "[ANALYZE] LLM XPath discovery returned no usable suggestions")
    else:
        xpath_rows = []
    selector_suggestions: dict[str, list[dict]] = source_trace.get("selector_suggestions", {})
    for row in xpath_rows:
        if not isinstance(row, dict):
            continue
        field_name = str(row.get("field_name") or "").strip()
        xpath = str(row.get("xpath") or "").strip()
        if not field_name or field_name not in missing_fields or not xpath:
            continue
        expected_value = str(row.get("expected_value") or "").strip() or None
        validation = validate_xpath_candidate(html, xpath, expected_value=expected_value)
        if not validation.get("valid"):
            continue
        matched_value = validation.get("matched_value")
        matched_value = coerce_field_candidate_value(field_name, matched_value, base_url=url)
        if matched_value in (None, "", [], {}):
            continue
        suggestion = _compact_dict({
            "field_name": field_name,
            "xpath": xpath,
            "css_selector": str(row.get("css_selector") or "").strip() or None,
            "regex": None,
            "status": "validated",
            "sample_value": matched_value or expected_value,
            "source": "llm_xpath",
        })
        selector_suggestions.setdefault(field_name, []).append(suggestion)
        trace_candidates.setdefault(field_name, []).append(_compact_dict({
            "value": matched_value,
            "source": "llm_xpath",
            "xpath": xpath,
            "css_selector": suggestion.get("css_selector"),
            "sample_value": matched_value or expected_value,
            "status": "validated",
        }))
        if matched_value not in (None, "", [], {}):
            llm_cleanup_suggestions[field_name] = _compact_dict({
                "field_name": field_name,
                "suggested_value": matched_value,
                "source": "llm_xpath",
                "xpath": xpath,
                "css_selector": suggestion.get("css_selector"),
                "status": "pending_review",
            })

    source_trace["selector_suggestions"] = selector_suggestions
    source_trace["llm_cleanup_suggestions"] = llm_cleanup_suggestions

    candidate_evidence = _build_llm_candidate_evidence(trace_candidates, preview_record)
    review_candidate_evidence = _select_llm_review_candidates(candidate_evidence, preview_record, target_fields)
    deterministic_fields = sorted(
        field_name
        for field_name in target_fields
        if field_name not in missing_fields and field_name not in review_candidate_evidence
    )
    discovered_sources = _build_llm_discovered_sources(
        source_trace,
        html=html,
        xhr_payloads=xhr_payloads,
        target_fields=list(review_candidate_evidence.keys()),
    )
    if not candidate_evidence and not discovered_sources and not preview_record:
        source_trace["llm_cleanup_status"] = {
            "status": "no_evidence",
            "message": "No candidate evidence was available for cleanup review.",
            "deterministic_fields": deterministic_fields,
            "missing_fields": missing_fields,
            "review_fields": [],
            "llm_assisted_fields": [],
        }
        return source_trace, llm_review_bucket
    if not review_candidate_evidence:
        source_trace["llm_cleanup_status"] = {
            "status": "skipped",
            "message": "Deterministic extraction already resolved the available field groups. LLM cleanup runs only for ambiguous or missing values.",
            "deterministic_fields": deterministic_fields,
            "missing_fields": missing_fields,
            "review_fields": [],
            "llm_assisted_fields": sorted(llm_cleanup_suggestions.keys()),
        }
        return source_trace, llm_review_bucket

    await _log(session, run.id, "info", f"[ANALYZE] LLM cleanup review for {len(review_candidate_evidence)} candidate field groups")
    llm_reviews, llm_error = await review_field_candidates(
        session,
        run_id=run.id,
        domain=domain,
        url=url,
        html_text=html,
        canonical_fields=canonical_fields,
        target_fields=sorted(review_candidate_evidence.keys()),
        existing_values=preview_record,
        candidate_evidence=review_candidate_evidence,
        discovered_sources=discovered_sources,
    )
    if llm_error:
        await _log(session, run.id, "warning", f"[LLM] Cleanup review failed: {llm_error}")
        source_trace["llm_cleanup_status"] = {
            "status": "error",
            "message": llm_error,
            "deterministic_fields": deterministic_fields,
            "missing_fields": missing_fields,
            "review_fields": sorted(review_candidate_evidence.keys()),
            "llm_assisted_fields": sorted(llm_cleanup_suggestions.keys()),
        }
        return source_trace, llm_review_bucket
    if not llm_reviews:
        await _log(session, run.id, "warning", "[ANALYZE] LLM cleanup review returned no suggestions")
        source_trace["llm_cleanup_status"] = {
            "status": "empty",
            "message": "LLM cleanup review returned no suggestions.",
            "deterministic_fields": deterministic_fields,
            "missing_fields": missing_fields,
            "review_fields": sorted(review_candidate_evidence.keys()),
            "llm_assisted_fields": sorted(llm_cleanup_suggestions.keys()),
        }
        return source_trace, llm_review_bucket

    canonical_reviews, llm_review_bucket = _split_llm_cleanup_payload(llm_reviews)
    for field_name, raw_review in canonical_reviews.items():
        normalized = _normalize_llm_cleanup_review(
            field_name,
            raw_review,
            current_value=preview_record.get(str(field_name or "").strip()),
        )
        if normalized is None:
            continue
        llm_cleanup_suggestions[normalized["field_name"]] = normalized
    source_trace["llm_cleanup_suggestions"] = llm_cleanup_suggestions
    source_trace["llm_cleanup_status"] = {
        **llm_cleanup_status,
        "status": "ready",
        "canonical_count": len(llm_cleanup_suggestions),
        "review_bucket_count": len(llm_review_bucket),
        "count": len(llm_cleanup_suggestions) + len(llm_review_bucket),
        "deterministic_fields": deterministic_fields,
        "missing_fields": missing_fields,
        "review_fields": sorted(review_candidate_evidence.keys()),
        "llm_assisted_fields": sorted(llm_cleanup_suggestions.keys()),
    }
    return source_trace, llm_review_bucket


def _build_llm_candidate_evidence(trace_candidates: dict, preview_record: dict) -> dict[str, list[dict]]:
    evidence: dict[str, list[dict]] = {}
    field_names = sorted({
        str(field_name or "").strip()
        for field_name in [*trace_candidates.keys(), *preview_record.keys()]
        if str(field_name or "").strip() and not str(field_name).startswith("_")
    })
    for field_name in field_names:
        rows: list[dict] = []
        seen: set[tuple[str, str]] = set()
        current_value = _clean_candidate_text(preview_record.get(field_name))
        if current_value:
            rows.append({
                "value": current_value,
                "source": "current_output",
            })
            seen.add(("current_output", current_value))
        for row in trace_candidates.get(field_name, []):
            if not isinstance(row, dict):
                continue
            value = _clean_candidate_text(row.get("value") if row.get("value") not in (None, "", [], {}) else row.get("sample_value"))
            if not value:
                continue
            source = str(row.get("source") or "candidate").strip() or "candidate"
            key = (source, value)
            if key in seen:
                continue
            seen.add(key)
            rows.append(_compact_dict({
                "value": value,
                "source": source,
                "xpath": str(row.get("xpath") or "").strip() or None,
                "css_selector": str(row.get("css_selector") or "").strip() or None,
                "regex": str(row.get("regex") or "").strip() or None,
                "selector_used": str(row.get("selector_used") or "").strip() or None,
            }))
            if len(rows) >= 8:
                break
        if rows:
            evidence[field_name] = rows
    return evidence


def _build_llm_discovered_sources(
    source_trace: dict,
    *,
    html: str,
    xhr_payloads: list[dict],
    target_fields: list[str] | None = None,
) -> dict[str, object]:
    page_sources = parse_page_sources(html)
    semantic = source_trace.get("semantic") if isinstance(source_trace.get("semantic"), dict) else {}
    relevant_fields = {field for field in (target_fields or []) if field}
    semantic_sections = semantic.get("sections") if isinstance(semantic.get("sections"), dict) else {}
    semantic_specs = semantic.get("specifications") if isinstance(semantic.get("specifications"), dict) else {}
    semantic_promoted = semantic.get("promoted_fields") if isinstance(semantic.get("promoted_fields"), dict) else {}
    manifest_snapshot = _compact_dict({
        "next_data": _snapshot_for_llm(page_sources.get("next_data"), max_items=150, text_limit=2000),
        "hydrated_states": _snapshot_for_llm(page_sources.get("hydrated_states"), max_items=150, text_limit=2000),
        "embedded_json": _snapshot_for_llm(page_sources.get("embedded_json"), max_items=150, text_limit=2000),
        "json_ld": _snapshot_for_llm(page_sources.get("json_ld"), max_items=150, text_limit=2000),
        "microdata": _snapshot_for_llm(page_sources.get("microdata"), max_items=150, text_limit=2000),
        "network_payloads": _snapshot_for_llm([
            _compact_dict({
                "url": payload.get("url"),
                "status": payload.get("status"),
                "body": payload.get("body"),
            })
            for payload in xhr_payloads[:2]
            if isinstance(payload, dict)
        ], max_items=150, text_limit=2000),
        "tables": _snapshot_for_llm(page_sources.get("tables"), max_items=150, text_limit=2000),
    })
    semantic_snapshot = _compact_dict({
        "sections": _snapshot_for_llm(
            {key: value for key, value in semantic_sections.items() if not relevant_fields or key in relevant_fields},
            text_limit=2000,
        ),
        "specifications": _snapshot_for_llm(
            {key: value for key, value in semantic_specs.items() if not relevant_fields or key in relevant_fields},
            text_limit=2000,
        ),
        "promoted_fields": _snapshot_for_llm(
            {key: value for key, value in semantic_promoted.items() if not relevant_fields or key in relevant_fields},
            text_limit=2000,
        ),
    })
    return _compact_dict({
        "semantic": semantic_snapshot,
        "manifest": manifest_snapshot,
    })


def _snapshot_for_llm(
    value: object,
    *,
    depth: int = 0,
    max_depth: int = 8,
    max_items: int = 150,
    text_limit: int = 2000,
) -> object:
    if value in (None, "", [], {}):
        return None
    if depth >= max_depth:
        return _clean_candidate_text(value, limit=text_limit)
    if isinstance(value, dict):
        snapshot: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                break
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            nested = _snapshot_for_llm(item, depth=depth + 1, max_depth=max_depth, max_items=max_items, text_limit=text_limit)
            if nested not in (None, "", [], {}):
                snapshot[normalized_key] = nested
        return snapshot or None
    if isinstance(value, list):
        rows: list[object] = []
        for item in value[:max_items]:
            nested = _snapshot_for_llm(item, depth=depth + 1, max_depth=max_depth, max_items=max_items, text_limit=text_limit)
            if nested not in (None, "", [], {}):
                rows.append(nested)
        return rows or None
    return _clean_candidate_text(value, limit=text_limit)


def _clean_candidate_text(value: object, *, limit: int | None = LLM_CLEAN_CANDIDATE_TEXT_LIMIT) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, list):
        joined = " | ".join(part for part in (_clean_candidate_text(item, limit=None) for item in value[:6]) if part)
        return joined[:limit] if limit and len(joined) > limit else joined
    if isinstance(value, dict):
        parts = []
        for index, (key, item) in enumerate(value.items()):
            if index >= 8:
                break
            cleaned = _clean_candidate_text(item, limit=None)
            if cleaned:
                parts.append(f"{key}: {cleaned}")
        joined = " | ".join(parts)
        return joined[:limit] if limit and len(joined) > limit else joined
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\u200b-\u200d\ufeff]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        return f"{text[:limit].rstrip()}..."
    return text


def _should_surface_discovered_field(field_name: object, value: object, *, source: str = "") -> bool:
    normalized_field = _normalize_committed_field_name(field_name)
    if not normalized_field or normalized_field.startswith("_"):
        return False
    tokens = {token for token in normalized_field.split("_") if token}
    if tokens & DISCOVERED_FIELD_NOISE_TOKENS:
        return False

    normalized_value = _normalize_review_value(value)
    if normalized_value is None:
        return False
    cleaned_text = _clean_candidate_text(normalized_value, limit=None)
    if isinstance(normalized_value, str):
        lowered_text = cleaned_text.lower()
        if len(cleaned_text) < 3:
            return False
        if any(phrase in lowered_text for phrase in DISCOVERED_VALUE_NOISE_PHRASES):
            return False

    lowered_source = str(source or "").strip().lower()
    if any(token in lowered_source for token in ("review", "reviews", "bazaarvoice", "rating_distribution")):
        return False

    return _passes_detail_quality_gate(normalized_field, normalized_value)


def _normalize_detail_candidate_values(candidate_values: dict[str, object], *, url: str) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for field_name, value in candidate_values.items():
        coerced = coerce_field_candidate_value(field_name, value, base_url=url)
        if coerced in (None, "", [], {}):
            continue
        normalized[field_name] = coerced

    primary_image = str(normalized.get("image_url") or "").strip()
    additional_images = str(normalized.get("additional_images") or "").strip()
    if additional_images:
        image_parts = [
            part.strip()
            for part in additional_images.split(",")
            if part.strip()
        ]
        deduped_parts: list[str] = []
        seen: set[str] = set()
        for part in image_parts:
            if part == primary_image or part in seen:
                continue
            seen.add(part)
            deduped_parts.append(part)
        if deduped_parts:
            normalized["additional_images"] = ", ".join(deduped_parts)
        else:
            normalized.pop("additional_images", None)

    return normalized


def _normalize_review_value(value: object) -> object | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        cleaned = _clean_candidate_text(value, limit=None)
        return cleaned or None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        rows = []
        for item in value:
            normalized = _normalize_review_value(item)
            if normalized is not None:
                rows.append(normalized)
        return rows or None
    if isinstance(value, dict):
        normalized_dict: dict[str, object] = {}
        for key, item in value.items():
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            normalized_item = _normalize_review_value(item)
            if normalized_item is not None:
                normalized_dict[normalized_key] = normalized_item
        return normalized_dict or None
    cleaned = _clean_candidate_text(value, limit=None)
    return cleaned or None


def _review_values_equal(left: object, right: object) -> bool:
    normalized_left = _normalize_review_value(left)
    normalized_right = _normalize_review_value(right)
    if normalized_left is None or normalized_right is None:
        return normalized_left == normalized_right
    if isinstance(normalized_left, str) or isinstance(normalized_right, str):
        return _clean_candidate_text(normalized_left, limit=None) == _clean_candidate_text(normalized_right, limit=None)
    try:
        return json.dumps(normalized_left, sort_keys=True, default=str) == json.dumps(normalized_right, sort_keys=True, default=str)
    except TypeError:
        return normalized_left == normalized_right


def _normalize_llm_cleanup_review(field_name: object, raw_review: object, *, current_value: object) -> dict | None:
    normalized_field = str(field_name or "").strip()
    if not normalized_field or normalized_field.startswith("_"):
        return None
    if isinstance(raw_review, dict):
        suggested_value = _normalize_review_value(
            raw_review.get("suggested_value")
            if raw_review.get("suggested_value") not in (None, "", [], {})
            else raw_review.get("value"),
        )
        source = str(raw_review.get("source") or "llm_cleanup").strip() or "llm_cleanup"
        note = _clean_candidate_text(raw_review.get("note") or raw_review.get("reason"), limit=280)
        supporting_sources = [
            str(item).strip()
            for item in (raw_review.get("supporting_sources") or [])
            if str(item).strip()
        ]
    else:
        suggested_value = _normalize_review_value(raw_review)
        source = "llm_cleanup"
        note = ""
        supporting_sources = []
    if not suggested_value:
        return None
    if _review_values_equal(current_value, suggested_value):
        return None
    return _compact_dict({
        "field_name": normalized_field,
        "suggested_value": suggested_value,
        "source": source,
        "supporting_sources": supporting_sources or None,
        "note": note or None,
        "status": "pending_review",
    })


def _split_llm_cleanup_payload(payload: object) -> tuple[dict[str, object], list[dict[str, object]]]:
    if not isinstance(payload, dict):
        return {}, []
    if "canonical" not in payload and "review_bucket" not in payload:
        canonical = {
            str(key).strip(): value
            for key, value in payload.items()
            if str(key).strip()
        }
        return canonical, []
    raw_canonical = payload.get("canonical")
    canonical = raw_canonical if isinstance(raw_canonical, dict) else {}
    raw_review_bucket = payload.get("review_bucket")
    review_bucket: list[dict[str, object]] = []
    if isinstance(raw_review_bucket, list):
        for row in raw_review_bucket:
            normalized = _normalize_llm_review_bucket_item(row)
            if normalized is not None:
                review_bucket.append(normalized)
    return canonical, _merge_review_bucket_entries(review_bucket)


def _normalize_llm_review_bucket_item(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    key = str(value.get("key") or "").strip()
    if not key or key.startswith("_"):
        return None
    normalized_value = _normalize_review_value(value.get("value"))
    if normalized_value is None:
        return None
    return _compact_dict({
        "key": key,
        "value": normalized_value,
        "confidence_score": _clamp_review_confidence(value.get("confidence_score", value.get("confidence", 5))),
        "source": str(value.get("source") or "llm_cleanup").strip() or "llm_cleanup",
    })


async def _load_domain_requested_fields(session: AsyncSession, *, url: str, surface: str) -> list[str]:
    resolved = await load_resolved_schema(session, surface, url)
    return expand_requested_fields(list(resolved.new_fields))


async def _refresh_schema_from_record(
    session: AsyncSession,
    *,
    surface: str,
    url: str,
    base_schema: ResolvedSchema,
    sample_record: dict | None,
) -> ResolvedSchema | None:
    if not isinstance(sample_record, dict) or not sample_record:
        return None
    learned = learn_schema_from_record(
        surface=surface,
        domain=base_schema.domain or normalize_domain(url),
        baseline_fields=base_schema.baseline_fields,
        explicit_fields=[field for field in base_schema.fields if field not in set(base_schema.baseline_fields)],
        sample_record=sample_record,
    )
    if (
        learned.fields == base_schema.fields
        and learned.new_fields == base_schema.new_fields
        and learned.deprecated_fields == base_schema.deprecated_fields
        and not base_schema.stale
        and base_schema.saved_at
    ):
        return None
    return await persist_resolved_schema(session, learned)


def _select_llm_review_candidates(
    candidate_evidence: dict[str, list[dict]],
    preview_record: dict,
    target_fields: list[str],
) -> dict[str, list[dict]]:
    selected: dict[str, list[dict]] = {}
    for field_name in target_fields:
        rows = candidate_evidence.get(field_name) or []
        if not rows:
            continue
        current_value = _clean_candidate_text(preview_record.get(field_name))
        distinct_values = {
            _clean_candidate_text(row.get("value"))
            for row in rows
            if _clean_candidate_text(row.get("value"))
        }
        source_labels = {str(row.get("source") or "").strip() for row in rows}
        if not current_value and len(distinct_values) <= 1 and "llm_xpath" not in source_labels:
            continue
        if not current_value or len(distinct_values) > 1 or "llm_xpath" in source_labels:
            selected[field_name] = rows[:6]
    return selected


def _build_field_discovery_summary(
    source_trace: dict,
    candidates: dict[str, list[dict]],
    candidate_values: dict,
    additional_fields: list[str],
    surface: str,
) -> dict:
    """Build a deterministic field discovery summary for additional_fields.

    Populates ``field_discovery`` in source_trace with per-field info:
    which sources contributed, what value was chosen, and which fields
    were not found. This powers markdown-oriented record inspection
    regardless of whether LLM is enabled.
    """
    canonical = set(get_canonical_fields(surface))
    requested = {field for field in additional_fields if field}
    target_fields = canonical | requested
    discovery: dict[str, dict] = {}
    missing: list[str] = []

    for field_name in sorted(set(candidates.keys()) | set(candidate_values.keys()) | target_fields):
        rows = candidates.get(field_name, [])
        winning_row = rows[0] if rows and isinstance(rows[0], dict) else {}
        first_row_value = rows[0].get("value") if rows and isinstance(rows[0], dict) else None
        chosen = candidate_values.get(field_name, first_row_value)
        if not rows and field_name in target_fields and chosen in (None, "", [], {}):
            missing.append(field_name)
            discovery[field_name] = _compact_dict({
                "status": "not_found",
                "sources": None,
                "is_canonical": field_name in canonical or None,
            })
            continue
        sources = sorted({str(row.get("source") or "").strip() for row in rows if row.get("source")})
        if field_name not in target_fields and not _should_surface_discovered_field(
            field_name,
            chosen if chosen not in (None, "", [], {}) else first_row_value,
            source=", ".join(sources),
        ):
            continue
        discovery[field_name] = _compact_dict({
            "status": "found",
            "value": _clean_candidate_text(chosen) if chosen not in (None, "", [], {}) else None,
            "sources": sources or None,
            "xpath": winning_row.get("xpath") or winning_row.get("_xpath") or None,
            "css_selector": winning_row.get("css_selector") or winning_row.get("_selector") or None,
            "is_canonical": field_name in canonical or None,
        })

    source_trace["field_discovery"] = discovery
    source_trace["field_discovery_missing"] = missing
    return source_trace


def _refresh_record_commit_metadata(
    record: CrawlRecord,
    *,
    run: CrawlRun,
    field_name: str,
    value: object,
    source_label: str = "user_commit",
) -> None:
    source_trace = dict(record.source_trace or {})
    field_discovery = dict(source_trace.get("field_discovery") or {})
    existing_entry = dict(field_discovery.get(field_name) or {})
    existing_sources = existing_entry.get("sources") or []
    sources = {
        str(source).strip()
        for source in existing_sources
        if str(source).strip()
    }
    sources.add(source_label)
    canonical_fields = set(get_canonical_fields(run.surface))
    field_discovery[field_name] = _compact_dict({
        **existing_entry,
        "status": "found",
        "value": _clean_candidate_text(value) if value not in (None, "", [], {}) else None,
        "sources": sorted(sources),
        "is_canonical": existing_entry.get("is_canonical", field_name in canonical_fields) or None,
    })
    missing_fields = [
        str(item).strip()
        for item in (source_trace.get("field_discovery_missing") or [])
        if str(item).strip() and str(item).strip() != field_name
    ]
    source_trace["field_discovery"] = field_discovery
    source_trace["field_discovery_missing"] = missing_fields

    committed_fields = dict(source_trace.get("committed_fields") or {})
    committed_fields[field_name] = {"value": value, "source": source_label}
    source_trace["committed_fields"] = committed_fields
    record.source_trace = source_trace

    discovered_data = dict(record.discovered_data or {})
    review_bucket = discovered_data.get("review_bucket") if isinstance(discovered_data.get("review_bucket"), list) else []
    if review_bucket:
        discovered_data["review_bucket"] = [
            row
            for row in review_bucket
            if not (
                isinstance(row, dict)
                and str(row.get("key") or "").strip() == field_name
            )
        ]
    requested_fields = list(run.requested_fields or [])
    if requested_fields:
        discovered_data["requested_field_coverage"] = _requested_field_coverage(record.data or {}, requested_fields)
    record.discovered_data = _compact_dict(discovered_data)


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
    run: CrawlRun,
    request: str,
) -> None:
    await session.refresh(run)
    if request == CONTROL_REQUEST_PAUSE:
        if normalize_status(run.status) != CrawlStatus.PAUSED:
            update_run_status(run, CrawlStatus.PAUSED)
        set_control_request(run, None)
        await _log(session, run.id, "warning", "Run paused during in-flight acquisition wait")
        await session.commit()
        return
    if normalize_status(run.status) != CrawlStatus.KILLED:
        update_run_status(run, CrawlStatus.KILLED)
    set_control_request(run, None)
    await _log(session, run.id, "warning", "Run killed during in-flight acquisition wait")
    await session.commit()


# Domain normalisation delegated to app.services.domain_utils.normalize_domain
_domain = normalize_domain
