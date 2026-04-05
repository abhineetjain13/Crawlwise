# Crawl orchestration service.
#
# Implements the single pipeline: ACQUIRE -> DISCOVER -> EXTRACT -> UNIFY -> PUBLISH
# Handles crawl, batch (multi-URL), and listing (category) crawls.
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
from datetime import UTC, datetime
from html import unescape

import regex as regex_lib
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from lxml import etree

from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun, ReviewPromotion
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
from app.services.discover.service import DiscoveryManifest, discover_sources
from app.services.extract.json_extractor import extract_json_detail, extract_json_listing
from app.services.extract.listing_extractor import extract_listing_records
from app.services.extract.service import _field_quality_score, coerce_field_candidate_value, extract_candidates
from app.services.extract.spa_pruner import prune_spa_state
from app.services.knowledge_base.store import get_canonical_fields, get_selector_defaults, save_selector_defaults
from app.services.llm_runtime import discover_xpath_candidates, review_field_candidates, snapshot_active_configs
from app.services.normalizers.field_normalizers import extract_currency_hint, normalize_value
from app.services.pipeline_config import (
    DEFAULT_MAX_SCROLLS,
    INTELLIGENCE_FIELD_NOISE_TOKENS,
    INTELLIGENCE_VALUE_NOISE_PHRASES,
    LLM_CLEAN_CANDIDATE_TEXT_LIMIT,
    MIN_REQUEST_DELAY_MS,
    VERDICT_CORE_FIELDS_DETAIL,
    VERDICT_CORE_FIELDS_LISTING,
)
from app.services.domain_utils import normalize_domain
from app.services.requested_field_policy import expand_requested_fields
from app.services.site_memory_service import get_memory as get_site_memory, merge_memory
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


# ---------------------------------------------------------------------------
# Run CRUD helpers
# ---------------------------------------------------------------------------

async def create_crawl_run(session: AsyncSession, user_id: int, payload: dict) -> CrawlRun:
    settings = dict(payload.get("settings", {}))
    urls = payload.get("urls") or []
    primary_url = payload.get("url") or (urls[0] if urls else "")
    await ensure_public_crawl_targets(_collect_target_urls(payload, settings))
    _validate_extraction_contract(settings.get("extraction_contract") or [])
    settings["max_pages"] = max(1, int(settings.get("max_pages", 5) or 5))
    settings["max_records"] = max(1, int(settings.get("max_records", 100) or 100))
    settings["max_scrolls"] = max(1, int(settings.get("max_scrolls", DEFAULT_MAX_SCROLLS) or DEFAULT_MAX_SCROLLS))
    settings["sleep_ms"] = max(
        MIN_REQUEST_DELAY_MS,
        int(settings.get("sleep_ms", MIN_REQUEST_DELAY_MS) or MIN_REQUEST_DELAY_MS),
    )
    advanced_enabled = bool(settings.get("advanced_enabled"))
    advanced_mode = str(settings.get("advanced_mode") or "").strip() or None
    if advanced_enabled and not advanced_mode:
        settings["advanced_mode"] = "auto"
    elif advanced_mode:
        settings["advanced_mode"] = advanced_mode
    else:
        settings["advanced_mode"] = None
    domain_requested_fields = await _load_domain_requested_fields(session, url=primary_url, surface=payload["surface"])
    site_memory_fields = await _load_site_memory_fields(session, url=primary_url)
    requested_fields = expand_requested_fields([
        *domain_requested_fields,
        *site_memory_fields,
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
        surface=payload["surface"],
        status=CrawlStatus.PENDING.value,
        settings=settings,
        requested_fields=requested_fields,
        result_summary={"url_count": max(1, len(urls) or 1), "progress": 0, "current_stage": "ACQUIRE"},
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
        advanced_mode = settings.get("advanced_mode")
        if settings.get("advanced_enabled") and not advanced_mode:
            advanced_mode = "auto"
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
                "ACQUIRE",
                current_url=url,
                current_url_index=idx + 1,
                total_urls=total_urls,
            )

            records, verdict = await _process_single_url(
                session=session,
                run=run,
                url=url,
                proxy_list=proxy_list,
                advanced_mode=advanced_mode,
                max_pages=max_pages,
                max_scrolls=max_scrolls,
                max_records=remaining_records,
                sleep_ms=sleep_ms,
            )
            persisted_record_count += len(records)
            if idx < len(url_verdicts):
                url_verdicts[idx] = verdict
            else:
                url_verdicts.append(verdict)
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

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
                await asyncio.sleep(sleep_ms / 1000)

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
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        await _mark_run_failed(session, run_id, error_msg)


async def _process_single_url(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    proxy_list: list[str],
    advanced_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    max_records: int,
    sleep_ms: int,
) -> tuple[list[dict], str]:
    """Run the full 5-stage pipeline on a single URL.

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

    # ── STAGE 1: ACQUIRE ──
    await _set_stage(session, run, "ACQUIRE")
    await _log(session, run.id, "info", f"[ACQUIRE] Fetching {url}")
    acq = await acquire(
        run_id=run.id,
        url=url,
        proxy_list=proxy_list or None,
        advanced_mode=advanced_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        sleep_ms=sleep_ms,
        requested_fields=additional_fields,
        requested_field_selectors=requested_field_selectors,
    )

    # ── STAGE 1.5: BLOCKED PAGE DETECTION ──
    # For JSON responses, skip blocked detection (APIs don't serve challenge pages)
    if acq.content_type != "json":
        blocked = detect_blocked_page(acq.html)
        if blocked.is_blocked:
            recovered = None if proxy_list else await try_blocked_adapter_recovery(url, surface)
            if recovered and recovered.records:
                await _log(
                    session,
                    run.id,
                    "info",
                    f"[BLOCKED] {url} matched blocked-page signals, recovered {len(recovered.records)} Shopify records from public endpoint",
                )
                manifest = discover_sources(
                    html="",
                    network_payloads=acq.network_payloads,
                    adapter_records=recovered.records,
                )
                if is_listing:
                    return await _extract_listing(
                        session, run, url, "", acq, manifest, recovered,
                        recovered.records, additional_fields,
                        surface, max_records,
                    )
                return await _extract_detail(
                    session, run, url, "", acq, manifest, recovered,
                    recovered.records, additional_fields, extraction_contract,
                    surface,
                )
            await _log(session, run.id, "warning", f"[BLOCKED] {url} — {blocked.reason}")
            record = CrawlRecord(
                run_id=run.id,
                source_url=url,
                data={"_status": "blocked", "_message": blocked.reason,
                      "_provider": blocked.provider},
                raw_data={},
                discovered_data=blocked.as_dict(),
                source_trace={"method": acq.method, "blocked": True},
                raw_html_path=acq.artifact_path,
            )
            session.add(record)
            await session.flush()
            return [], VERDICT_BLOCKED

    # ── STAGE 2: JSON-FIRST EXTRACTION PATH ──
    if acq.content_type == "json" and acq.json_data is not None:
        await _log(session, run.id, "info", "[EXTRACT] JSON-first path — API response detected")
        return await _process_json_response(
            session, run, url, acq, is_listing, max_records, additional_fields,
        )

    html = acq.html

    # ── STAGE 3: DISCOVER ──
    await _set_stage(session, run, "DISCOVER")
    await _log(session, run.id, "info", f"[DISCOVER] Enumerating sources (method={acq.method})")

    # Run platform adapter (rank 1 source)
    adapter_result = await run_adapter(url, html, surface)
    adapter_records = adapter_result.records if adapter_result else []

    manifest = discover_sources(
        html=html,
        network_payloads=acq.network_payloads,
        adapter_records=adapter_records,
    )

    # ── STAGE 4: EXTRACT ──
    await _set_stage(session, run, "EXTRACT")
    await _log(session, run.id, "info", "[EXTRACT] Extracting candidates")

    if is_listing:
        return await _extract_listing(
            session, run, url, html, acq, manifest, adapter_result,
            adapter_records, additional_fields,
            surface, max_records,
        )
    else:
        return await _extract_detail(
            session, run, url, html, acq, manifest, adapter_result,
            adapter_records, additional_fields, extraction_contract,
            surface,
        )


async def _process_json_response(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    acq: AcquisitionResult,
    is_listing: bool,
    max_records: int,
    requested_fields: list[str],
) -> tuple[list[dict], str]:
    """Handle a JSON API response — extract directly without HTML parsing."""
    if is_listing:
        extracted = extract_json_listing(acq.json_data, url, max_records)
    else:
        extracted = extract_json_detail(acq.json_data, url)

    if not extracted:
        await _log(session, run.id, "warning", "[EXTRACT] JSON response parsed but no records found")
        return [], VERDICT_SCHEMA_MISS

    await _set_stage(session, run, "UNIFY")
    await _log(session, run.id, "info", "[UNIFY] Normalizing JSON records")
    saved = []
    allowed_fields = set(get_canonical_fields(run.surface)) | set(requested_fields)
    for raw_record in extracted:
        if len(saved) >= max_records:
            break
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
                "requested_fields": requested_fields or None,
                "requested_field_coverage": requested_coverage or None,
                "manifest_trace": _build_manifest_trace(
                    None,
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

    await _set_stage(session, run, "PUBLISH")
    verdict = _compute_verdict(saved, is_listing)
    await _log(session, run.id, "info", f"[PUBLISH] Saved {len(saved)} JSON records (verdict={verdict})")
    await session.flush()
    return saved, verdict


async def _extract_listing(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    html: str,
    acq: AcquisitionResult,
    manifest: DiscoveryManifest,
    adapter_result,
    adapter_records: list[dict],
    additional_fields: list[str],
    surface: str,
    max_records: int,
) -> tuple[list[dict], str]:
    """Listing extraction — adapter > structured data > DOM cards.

    Never falls back to a single detail-style record. If no listing items
    are found, returns an explicit listing_detection_failed verdict.
    """
    adapter_name = adapter_result.adapter_name if adapter_result else None

    if adapter_records:
        extracted_records = adapter_records
        source_label = "adapter"
    else:
        # Use the enhanced listing extractor (structured-data-first, then DOM cards)
        extracted_records = extract_listing_records(
            html=html,
            surface=surface,
            target_fields=set(additional_fields),
            page_url=url,
            max_records=max_records,
            manifest=manifest,
        )
        source_label = "listing_extractor"

    # ── LISTING FALLBACK GUARD ──
    # If listing extraction found zero or one record, do NOT fall through to
    # a detail-style single-record path. Mark the run as failed.
    if not extracted_records:
        await _log(session, run.id, "warning",
                    "[EXTRACT] Listing extraction found 0 records — marking as listing_detection_failed")
        return [], VERDICT_LISTING_FAILED

    # Save each listing record
    await _set_stage(session, run, "UNIFY")
    await _log(session, run.id, "info", "[UNIFY] Normalizing listing records")
    saved: list[dict] = []
    allowed_fields = set(get_canonical_fields(surface)) | set(additional_fields)
    for raw_record in extracted_records:
        if len(saved) >= max_records:
            break
        normalized, discovered_fields = _split_detail_output_fields(
            _public_record_fields(raw_record),
            allowed_fields=allowed_fields,
        )
        raw_data = _raw_record_payload(raw_record)
        requested_coverage = _requested_field_coverage(normalized, additional_fields)
        review_bucket = _build_review_bucket(
            discovered_fields,
            fallback_source=adapter_name or source_label,
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
                "adapter": adapter_name,
                "source": source_label,
                "requested_fields": additional_fields or None,
                "requested_field_coverage": requested_coverage or None,
                "manifest_trace": _build_manifest_trace(manifest) or None,
            }),
            raw_html_path=acq.artifact_path,
        )
        session.add(db_record)
        saved.append(normalized)

    await _set_stage(session, run, "PUBLISH")
    verdict = _compute_verdict(saved, is_listing=True)
    await _log(session, run.id, "info", f"[PUBLISH] Saved {len(saved)} listing records (verdict={verdict})")
    if saved:
        await _save_site_memory_observations(
            session,
            url=url,
            requested_fields=additional_fields,
            extraction_contract=[],
            source_trace={
                "llm_cleanup_status": {},
            },
            html_text=html,
            browser_diagnostics=acq.diagnostics.get("browser_diagnostics") if isinstance(acq.diagnostics, dict) else {},
        )
    await session.flush()
    return saved, verdict


async def _extract_detail(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    html: str,
    acq: AcquisitionResult,
    manifest: DiscoveryManifest,
    adapter_result,
    adapter_records: list[dict],
    additional_fields: list[str],
    extraction_contract: list[dict],
    surface: str,
) -> tuple[list[dict], str]:
    """Detail page extraction — adapter > candidates."""
    adapter_name = adapter_result.adapter_name if adapter_result else None

    candidates, source_trace = extract_candidates(
        url, surface, html, manifest, additional_fields, extraction_contract,
    )
    persisted_field_names = set(get_canonical_fields(surface)) | set(additional_fields)
    candidate_values, reconciliation = _reconcile_detail_candidate_values(
        candidates,
        allowed_fields=persisted_field_names,
        url=url,
    )
    semantic = source_trace.get("semantic") if isinstance(source_trace.get("semantic"), dict) else {}

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
            manifest=manifest,
            additional_fields=additional_fields,
            adapter_records=extracted_records,
            candidate_values=candidate_values,
            source_trace=source_trace,
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

    await _set_stage(session, run, "UNIFY")
    await _log(session, run.id, "info", "[UNIFY] Normalizing detail record")
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
                    "reconciliation": reconciliation or None,
                    "requested_fields": additional_fields or None,
                    "requested_field_coverage": requested_coverage or None,
                    "manifest_trace": _build_manifest_trace(manifest, semantic=semantic) or None,
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
                "reconciliation": reconciliation or None,
                "requested_fields": additional_fields or None,
                "requested_field_coverage": requested_coverage or None,
                "manifest_trace": _build_manifest_trace(manifest, semantic=semantic) or None,
            }),
            raw_html_path=acq.artifact_path,
        )
        session.add(db_record)
        saved.append(normalized)

    await _set_stage(session, run, "PUBLISH")
    verdict = _compute_verdict(saved, is_listing=False)
    await _log(session, run.id, "info", f"[PUBLISH] Saved {len(saved)} detail records (verdict={verdict})")
    if saved:
        await _save_site_memory_observations(
            session,
            url=url,
            requested_fields=additional_fields,
            extraction_contract=extraction_contract,
            source_trace=source_trace,
            html_text=html,
            browser_diagnostics=acq.diagnostics.get("browser_diagnostics") if isinstance(acq.diagnostics, dict) else {},
        )
    await session.flush()
    return saved, verdict


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


def _normalize_record_fields(record: dict[str, object]) -> dict[str, object]:
    normalized = _compact_dict({
        key: normalize_value(key, value)
        for key, value in record.items()
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
            score = _field_quality_score(field_name, normalized_value)
            if not _passes_detail_quality_gate(field_name, normalized_value, score):
                rejected_rows.append({
                    "value": normalized_value,
                    "reason": "quality_gate_rejected",
                    "score": score,
                    "source": row.get("source"),
                })
                continue
            accepted_row = {**row, "value": normalized_value, "_score": score}
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
                "accepted_score": accepted_row.get("_score"),
                "rejected": rejected_rows[:6],
            })

    return reconciled, reconciliation


def _passes_detail_quality_gate(field_name: str, value: object, score: int) -> bool:
    if value in (None, "", [], {}):
        return False
    if field_name in {"title", "brand", "category"}:
        return score >= 10
    if field_name in {"price", "sale_price", "original_price", "currency", "sku", "availability"}:
        return score > 0
    return score >= 1


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
        score = _field_quality_score(normalized_field, normalized_value)
        if not _passes_detail_quality_gate(normalized_field, normalized_value, score):
            continue

        source = str(raw_suggestion.get("source") or "llm_cleanup").strip() or "llm_cleanup"
        note = _clean_candidate_text(raw_suggestion.get("note") or raw_suggestion.get("reason"), limit=280)
        candidate_values[normalized_field] = normalized_value
        promoted[normalized_field] = _compact_dict({
            "value": normalized_value,
            "source": source,
            "score": score,
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
        if not _should_surface_intelligence_field(field_name, normalized_value, source=source):
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
            if not _should_surface_intelligence_field(key, normalized_value, source=source):
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
    manifest: DiscoveryManifest | None,
    *,
    semantic: dict | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    manifest = manifest or DiscoveryManifest()
    payload = _compact_dict({
        "adapter_data": manifest.adapter_data or None,
        "network_payloads": [
            _compact_dict({
                "url": row.get("url"),
                "status": row.get("status"),
                "body": prune_spa_state(row.get("body")),
            })
            for row in manifest.network_payloads
            if isinstance(row, dict)
        ] or None,
        "next_data": prune_spa_state(manifest.next_data),
        "_hydrated_states": prune_spa_state(manifest._hydrated_states),
        "embedded_json": prune_spa_state(manifest.embedded_json),
        "open_graph": manifest.open_graph or None,
        "json_ld": manifest.json_ld or None,
        "microdata": manifest.microdata or None,
        "hidden_dom": manifest.hidden_dom or None,
        "tables": manifest.tables or None,
        "semantic": semantic or None,
        **(extra or {}),
    })
    return payload


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
    score = _field_quality_score(field_name, value)
    if score >= 10:
        base += 1
    elif score <= 1:
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
    text = str(value or "").strip().lower()
    if not text:
        return ""
    normalized = re.sub(r"\s+", "_", text)
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
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
        if merged.get(key) in (None, "", [], {}):
            merged[key] = value
    return merged


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


def _compact_dict(payload: dict) -> dict:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }


def _validate_extraction_contract(contract_rows: list[dict]) -> None:
    errors: list[str] = []
    for index, row in enumerate(contract_rows, start=1):
        field_name = str(row.get("field_name") or "").strip()
        xpath = str(row.get("xpath") or "").strip()
        regex = str(row.get("regex") or "").strip()
        if not field_name:
            errors.append(f"Row {index}: field_name is required")
        if xpath:
            try:
                etree.XPath(xpath)
            except etree.XPathError as exc:
                errors.append(f"Row {index} ({field_name or 'unnamed'}): invalid XPath ({exc})")
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
    manifest: DiscoveryManifest,
    additional_fields: list[str],
    adapter_records: list[dict],
    candidate_values: dict,
    source_trace: dict,
) -> tuple[dict, list[dict[str, object]]]:
    trace_candidates = source_trace.setdefault("candidates", {})
    llm_cleanup_suggestions: dict[str, dict] = source_trace.get("llm_cleanup_suggestions", {})
    llm_cleanup_status: dict[str, object] = dict(source_trace.get("llm_cleanup_status") or {})
    llm_review_bucket: list[dict[str, object]] = []
    preview_record = (
        _merge_record_fields(adapter_records[0], candidate_values)
        if adapter_records else dict(candidate_values)
    )
    canonical_fields = sorted(set(get_canonical_fields(surface)) | set(additional_fields))
    target_fields = list(canonical_fields)
    missing_fields = [
        field_name
        for field_name in target_fields
        if preview_record.get(field_name) in (None, "", [], {})
    ]

    domain = _domain(url)
    if missing_fields:
        await _log(session, run.id, "info", f"[EXTRACT] LLM XPath discovery for {len(missing_fields)} missing detail fields")
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
            await _log(session, run.id, "warning", "[EXTRACT] LLM XPath discovery returned no usable suggestions")
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
    discovered_sources = _build_llm_discovered_sources(source_trace, manifest, target_fields=list(review_candidate_evidence.keys()))
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

    await _log(session, run.id, "info", f"[EXTRACT] LLM cleanup review for {len(review_candidate_evidence)} candidate field groups")
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
        await _log(session, run.id, "warning", "[EXTRACT] LLM cleanup review returned no suggestions")
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
    manifest: DiscoveryManifest,
    *,
    target_fields: list[str] | None = None,
) -> dict[str, object]:
    semantic = source_trace.get("semantic") if isinstance(source_trace.get("semantic"), dict) else {}
    relevant_fields = {field for field in (target_fields or []) if field}
    semantic_sections = semantic.get("sections") if isinstance(semantic.get("sections"), dict) else {}
    semantic_specs = semantic.get("specifications") if isinstance(semantic.get("specifications"), dict) else {}
    semantic_promoted = semantic.get("promoted_fields") if isinstance(semantic.get("promoted_fields"), dict) else {}
    manifest_snapshot = _compact_dict({
        "next_data": _snapshot_for_llm(prune_spa_state(manifest.next_data), max_items=150, text_limit=2000),
        "hydrated_states": _snapshot_for_llm(prune_spa_state(manifest._hydrated_states), max_items=150, text_limit=2000),
        "embedded_json": _snapshot_for_llm(prune_spa_state(manifest.embedded_json), max_items=150, text_limit=2000),
        "json_ld": _snapshot_for_llm(manifest.json_ld, max_items=150, text_limit=2000),
        "microdata": _snapshot_for_llm(manifest.microdata, max_items=150, text_limit=2000),
        "network_payloads": _snapshot_for_llm([
            _compact_dict({
                "url": payload.get("url"),
                "status": payload.get("status"),
                "body": prune_spa_state(payload.get("body")),
            })
            for payload in manifest.network_payloads[:2]
            if isinstance(payload, dict)
        ], max_items=150, text_limit=2000),
        "tables": _snapshot_for_llm(manifest.tables, max_items=150, text_limit=2000),
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


def _should_surface_intelligence_field(field_name: object, value: object, *, source: str = "") -> bool:
    normalized_field = _normalize_committed_field_name(field_name)
    if not normalized_field or normalized_field.startswith("_"):
        return False
    tokens = {token for token in normalized_field.split("_") if token}
    if tokens & INTELLIGENCE_FIELD_NOISE_TOKENS:
        return False

    normalized_value = _normalize_review_value(value)
    if normalized_value is None:
        return False
    cleaned_text = _clean_candidate_text(normalized_value, limit=None)
    if isinstance(normalized_value, str):
        lowered_text = cleaned_text.lower()
        if len(cleaned_text) < 3:
            return False
        if any(phrase in lowered_text for phrase in INTELLIGENCE_VALUE_NOISE_PHRASES):
            return False

    lowered_source = str(source or "").strip().lower()
    if any(token in lowered_source for token in ("review", "reviews", "bazaarvoice", "rating_distribution")):
        return False

    return _field_quality_score(normalized_field, normalized_value) > 0


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
    domain = normalize_domain(url)
    if not domain:
        return []
    result = await session.execute(
        select(ReviewPromotion)
        .where(ReviewPromotion.domain == domain, ReviewPromotion.surface == surface)
        .order_by(ReviewPromotion.updated_at.desc(), ReviewPromotion.created_at.desc())
        .limit(1)
    )
    promotion = result.scalar_one_or_none()
    if promotion is None or not isinstance(promotion.approved_schema, dict):
        return []
    fields = promotion.approved_schema.get("fields")
    if not isinstance(fields, list):
        return []
    return expand_requested_fields([str(field or "") for field in fields])


async def _load_site_memory_fields(session: AsyncSession, *, url: str) -> list[str]:
    memory = await get_site_memory(session, url)
    if memory is None or not isinstance(memory.payload, dict):
        return []
    fields = memory.payload.get("fields")
    if not isinstance(fields, list):
        return []
    return expand_requested_fields([str(field or "") for field in fields])


async def _save_site_memory_observations(
    session: AsyncSession,
    *,
    url: str,
    requested_fields: list[str],
    extraction_contract: list[dict],
    source_trace: dict,
    html_text: str,
    browser_diagnostics: dict | None = None,
) -> None:
    selectors: dict[str, list[dict]] = {}
    for row in extraction_contract:
        field_name = str(row.get("field_name") or "").strip().lower()
        xpath = str(row.get("xpath") or "").strip()
        regex = str(row.get("regex") or "").strip()
        if not field_name or not any([xpath, regex]):
            continue
        selectors.setdefault(field_name, []).append({
            "xpath": xpath or None,
            "css_selector": None,
            "regex": regex or None,
            "status": "validated",
            "source": "crawl_contract",
        })

    domain = normalize_domain(url)
    if html_text and domain:
        target_fields = [field for field in requested_fields if field]
        candidate_map = source_trace.get("candidates") if isinstance(source_trace, dict) else {}
        selector_defaults = {
            field_name: get_selector_defaults(domain, field_name)
            for field_name in target_fields
        }
        deterministic = build_deterministic_selector_suggestions(
            html_text,
            target_fields,
            existing_candidates=candidate_map if isinstance(candidate_map, dict) else {},
            selector_defaults=selector_defaults,
        )
        for field_name, rows in deterministic.items():
            if field_name not in target_fields:
                continue
            selectors.setdefault(field_name, [])
            selectors[field_name].extend(rows)

    suggestion_rows = source_trace.get("selector_suggestions") if isinstance(source_trace, dict) else {}
    if isinstance(suggestion_rows, dict):
        for field_name, rows in suggestion_rows.items():
            normalized_field = str(field_name or "").strip().lower()
            if not normalized_field or not isinstance(rows, list):
                continue
            selectors.setdefault(normalized_field, [])
            selectors[normalized_field].extend([row for row in rows if isinstance(row, dict)])

    trigger_rows = browser_diagnostics.get("field_trigger_selectors") if isinstance(browser_diagnostics, dict) else {}
    if isinstance(trigger_rows, dict):
        for field_name, rows in trigger_rows.items():
            normalized_field = str(field_name or "").strip().lower()
            if not normalized_field or not isinstance(rows, list):
                continue
            selectors.setdefault(normalized_field, [])
            selectors[normalized_field].extend([row for row in rows if isinstance(row, dict)])

    field_discovery = source_trace.get("field_discovery") if isinstance(source_trace, dict) else {}
    source_mappings = {
        str(field_name or "").strip().lower(): str(row.get("source") or "").strip()
        for field_name, row in (field_discovery.items() if isinstance(field_discovery, dict) else [])
        if isinstance(row, dict) and str(field_name or "").strip() and str(row.get("source") or "").strip()
    }
    llm_status = source_trace.get("llm_cleanup_status") if isinstance(source_trace, dict) else {}
    llm_columns = {}
    if isinstance(llm_status, dict):
        llm_columns = {
            "llm_assisted_fields": list(llm_status.get("llm_assisted_fields") or []),
            "deterministic_fields": list(llm_status.get("deterministic_fields") or []),
        }

    await merge_memory(
        session,
        url,
        fields=requested_fields,
        selectors=selectors,
        source_mappings=source_mappings,
        llm_columns=llm_columns,
        last_crawl_at=datetime.now(UTC),
    )
    if domain:
        for field_name, rows in selectors.items():
            normalized_field = str(field_name or "").strip().lower()
            if not normalized_field or not isinstance(rows, list):
                continue
            existing_rows = get_selector_defaults(domain, normalized_field)
            merged_rows = existing_rows + [row for row in rows if isinstance(row, dict)]
            deduped_and_capped_rows: list[dict] = []
            seen_selector_rows: set[tuple[object, object, object]] = set()
            for row in merged_rows:
                if not isinstance(row, dict):
                    continue
                row_key = (row.get("xpath"), row.get("css_selector"), row.get("regex"))
                if row_key in seen_selector_rows:
                    continue
                seen_selector_rows.add(row_key)
                deduped_and_capped_rows.append(row)
                if len(deduped_and_capped_rows) >= MAX_SELECTOR_ROWS_PER_FIELD:
                    break
            await save_selector_defaults(domain, normalized_field, deduped_and_capped_rows)


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
    were not found.  This powers the intelligence tab regardless of
    whether LLM is enabled.
    """
    canonical = set(get_canonical_fields(surface))
    requested = {field for field in additional_fields if field}
    target_fields = canonical | requested
    discovery: dict[str, dict] = {}
    missing: list[str] = []

    for field_name in sorted(set(candidates.keys()) | set(candidate_values.keys()) | target_fields):
        rows = candidates.get(field_name, [])
        first_row_value = rows[0].get("value") if rows and isinstance(rows[0], dict) else None
        chosen = candidate_values.get(field_name, first_row_value)
        tier = "canonical" if field_name in target_fields else "intelligence"
        if not rows and field_name in target_fields and chosen in (None, "", [], {}):
            missing.append(field_name)
            discovery[field_name] = _compact_dict({
                "status": "not_found",
                "tier": tier,
                "sources": None,
                "candidate_count": 0,
                "is_canonical": field_name in canonical or None,
            })
            continue
        sources = sorted({str(row.get("source") or "").strip() for row in rows if row.get("source")})
        if tier == "intelligence" and not _should_surface_intelligence_field(
            field_name,
            chosen if chosen not in (None, "", [], {}) else first_row_value,
            source=", ".join(sources),
        ):
            continue
        discovery[field_name] = _compact_dict({
            "status": "found",
            "value": _clean_candidate_text(chosen) if chosen not in (None, "", [], {}) else None,
            "tier": tier,
            "sources": sources or None,
            "candidate_count": len(rows),
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
        "candidate_count": existing_entry.get("candidate_count"),
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


# Domain normalisation delegated to app.services.domain_utils.normalize_domain
_domain = normalize_domain
