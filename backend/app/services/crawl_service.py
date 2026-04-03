# Crawl orchestration service.
#
# Implements the single pipeline: ACQUIRE -> DISCOVER -> EXTRACT -> UNIFY -> PUBLISH
# Handles crawl, batch (multi-URL), and listing (category) crawls.
from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import traceback
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from lxml import etree

from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult, ProxyPoolExhausted, acquire
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.adapters.registry import run_adapter, try_blocked_adapter_recovery
from app.services.crawl_state import (
    ACTIVE_STATUSES,
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
from app.services.extract.service import extract_candidates
from app.services.knowledge_base.store import get_canonical_fields
from app.services.llm_runtime import discover_xpath_candidates, extract_missing_fields, snapshot_active_configs
from app.services.normalizers.field_normalizers import normalize_value
from app.services.pipeline_config import VERDICT_CORE_FIELDS_DETAIL, VERDICT_CORE_FIELDS_LISTING
from app.services.domain_utils import normalize_domain
from app.services.requested_field_policy import expand_requested_fields
from app.services.xpath_service import validate_xpath_candidate


# Extraction quality verdicts persisted in result_summary.
VERDICT_SUCCESS = "success"
VERDICT_PARTIAL = "partial"
VERDICT_BLOCKED = "blocked"
VERDICT_SCHEMA_MISS = "schema_miss"
VERDICT_LISTING_FAILED = "listing_detection_failed"
VERDICT_EMPTY = "empty"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run CRUD helpers
# ---------------------------------------------------------------------------

async def create_crawl_run(session: AsyncSession, user_id: int, payload: dict) -> CrawlRun:
    urls = payload.get("urls") or []
    settings = dict(payload.get("settings", {}))
    _validate_extraction_contract(settings.get("extraction_contract") or [])
    settings["max_records"] = max(1, int(settings.get("max_records", 100) or 100))
    settings["sleep_ms"] = max(0, int(settings.get("sleep_ms", 0) or 0))
    if settings.get("llm_enabled"):
        settings["llm_config_snapshot"] = await snapshot_active_configs(session)
    run = CrawlRun(
        user_id=user_id,
        run_type=payload["run_type"],
        url=payload.get("url") or (urls[0] if urls else ""),
        surface=payload["surface"],
        status=CrawlStatus.PENDING.value,
        settings=settings,
        requested_fields=payload.get("additional_fields", []),
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


async def commit_llm_suggestions(
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
        field_name = str(item.get("field_name") or "").strip()
        if not field_name:
            continue
        value = item.get("value")
        normalized_value = normalize_value(field_name, value)
        data = dict(record.data or {})
        data[field_name] = normalized_value
        record.data = data

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
        await _log(session, run.id, "info", f"[LLM] Committed {updated_fields} accepted suggestion(s)")
        await session.commit()
    return updated_records, updated_fields


async def pause_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    current = normalize_status(run.status)
    if current != CrawlStatus.RUNNING:
        raise ValueError(f"Cannot pause run in state: {run.status}")
    update_run_status(run, CrawlStatus.PAUSED)
    set_control_request(run, None)
    await _log(session, run.id, "warning", "Pause requested")
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
    if current_status == CrawlStatus.PENDING:
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
        advanced_mode = settings.get("advanced_mode")  # None, "scroll", "paginate", "load_more", "auto"
        max_records = settings.get("max_records", 100)
        max_pages = settings.get("max_pages", 10)
        sleep_ms = settings.get("sleep_ms", 0)

        total_urls = len(url_list)
        start_index = min(int((run.result_summary or {}).get("processed_urls", 0) or 0), total_urls)
        persisted_record_count = await _count_run_records(session, run.id)
        url_verdicts: list[str] = []
        verdict_counts: dict[str, int] = dict((run.result_summary or {}).get("verdict_counts") or {})

        for idx in range(start_index, total_urls):
            url = url_list[idx]
            await session.refresh(run)
            current_status = normalize_status(run.status)
            if current_status == CrawlStatus.PAUSED:
                await _log(session, run.id, "warning", "Run paused by user")
                return
            if current_status == CrawlStatus.KILLED or get_control_request(run) == CONTROL_REQUEST_KILL:
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
                max_records=remaining_records,
                max_pages=max_pages,
                sleep_ms=sleep_ms,
            )
            persisted_record_count += len(records)
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
                "verdict_counts": verdict_counts,
            }
            await session.commit()
            await session.refresh(run)
            current_status = normalize_status(run.status)
            if current_status == CrawlStatus.PAUSED:
                await _log(session, run.id, "warning", "Run paused after checkpoint; partial output preserved")
                return
            if current_status == CrawlStatus.KILLED or get_control_request(run) == CONTROL_REQUEST_KILL:
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
            if aggregate_verdict == VERDICT_SUCCESS:
                update_run_status(run, CrawlStatus.COMPLETED)
            else:
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
    max_records: int,
    max_pages: int,
    sleep_ms: int,
) -> tuple[list[dict], str]:
    """Run the full 5-stage pipeline on a single URL.

    Returns (saved_records, extraction_verdict).
    """
    surface = run.surface
    additional_fields = expand_requested_fields(run.requested_fields or [])
    extraction_contract = (run.settings or {}).get("extraction_contract", [])
    is_listing = surface in ("ecommerce_listing", "job_listing")

    # ── STAGE 1: ACQUIRE ──
    await _set_stage(session, run, "ACQUIRE")
    await _log(session, run.id, "info", f"[ACQUIRE] Fetching {url}")
    acq = await acquire(
        run_id=run.id,
        url=url,
        proxy_list=proxy_list or None,
        advanced_mode=advanced_mode,
        max_pages=max_pages,
        sleep_ms=sleep_ms,
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
                        recovered.records, additional_fields, extraction_contract,
                        surface, max_records,
                    )
                return await _extract_detail(
                    session, run, url, "", acq, manifest, recovered,
                    recovered.records, additional_fields, extraction_contract,
                    surface,
                )
            await _log(session, run.id, "warning",
                       f"[BLOCKED] {url} — {blocked.reason} (confidence={blocked.confidence:.2f})")
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
            session, run, url, acq, is_listing, surface, max_records, additional_fields,
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
            adapter_records, additional_fields, extraction_contract,
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
    surface: str,
    max_records: int,
    requested_fields: list[str],
) -> tuple[list[dict], str]:
    """Handle a JSON API response — extract directly without HTML parsing."""
    if is_listing:
        extracted = extract_json_listing(acq.json_data, surface, url, max_records)
    else:
        extracted = extract_json_detail(acq.json_data, surface, url)

    if not extracted:
        await _log(session, run.id, "warning", "[EXTRACT] JSON response parsed but no records found")
        return [], VERDICT_SCHEMA_MISS

    await _set_stage(session, run, "UNIFY")
    await _log(session, run.id, "info", "[UNIFY] Normalizing JSON records")
    saved = []
    for raw_record in extracted:
        if len(saved) >= max_records:
            break
        public_fields = _public_record_fields(raw_record)
        normalized = {k: normalize_value(k, v) for k, v in public_fields.items()}
        raw_data = _raw_record_payload(raw_record)
        requested_coverage = _requested_field_coverage(public_fields, requested_fields)
        db_record = CrawlRecord(
            run_id=run.id,
            source_url=raw_record.get("url", url),
            data=normalized,
            raw_data=raw_data,
            discovered_data=_compact_dict({
                "content_type": "json",
                "source": raw_record.get("_source", "json_api"),
                "json_record_keys": sorted(raw_data.keys()) if isinstance(raw_data, dict) else None,
                "full_json_response": acq.json_data if not is_listing else None,
            }),
            source_trace=_compact_dict({
                "type": "json_api",
                "method": acq.method,
                "requested_fields": requested_fields or None,
                "requested_field_coverage": requested_coverage or None,
            }),
            raw_html_path=acq.artifact_path,
        )
        session.add(db_record)
        saved.append(normalized)

    await _set_stage(session, run, "PUBLISH")
    verdict = _compute_verdict(saved, is_listing, requested_fields=requested_fields)
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
    extraction_contract: list[dict],
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
    for raw_record in extracted_records:
        if len(saved) >= max_records:
            break
        normalized = {
            k: normalize_value(k, v)
            for k, v in _public_record_fields(raw_record).items()
        }
        raw_data = _raw_record_payload(raw_record)
        db_record = CrawlRecord(
            run_id=run.id,
            source_url=raw_record.get("url", url),
            data=normalized,
            raw_data=raw_data,
            discovered_data=_compact_dict({
                **manifest.as_dict(),
                "requested_fields": additional_fields or None,
            }),
            source_trace=_compact_dict({
                "type": "listing",
                "adapter": adapter_name,
                "source": source_label,
            }),
            raw_html_path=acq.artifact_path,
        )
        session.add(db_record)
        saved.append(normalized)

    await _set_stage(session, run, "PUBLISH")
    verdict = _compute_verdict(saved, is_listing=True)
    await _log(session, run.id, "info", f"[PUBLISH] Saved {len(saved)} listing records (verdict={verdict})")
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
    candidate_values = {
        field: rows[0]["value"]
        for field, rows in candidates.items()
        if rows
    }
    semantic = source_trace.get("semantic") if isinstance(source_trace.get("semantic"), dict) else {}

    if adapter_records:
        extracted_records = adapter_records
    else:
        extracted_records = []

    if html and (run.settings or {}).get("llm_enabled"):
        source_trace = await _collect_detail_llm_suggestions(
            session=session,
            run=run,
            url=url,
            surface=surface,
            html=html,
            additional_fields=additional_fields,
            adapter_records=extracted_records,
            candidate_values=candidate_values,
            source_trace=source_trace,
        )

    saved: list[dict] = []

    await _set_stage(session, run, "UNIFY")
    await _log(session, run.id, "info", "[UNIFY] Normalizing detail record")
    if extracted_records:
        # Detail page with adapter records — take first only
        for raw_record in extracted_records[:1]:
            merged_record = _merge_record_fields(raw_record, candidate_values)
            public_fields = _public_record_fields(merged_record)
            normalized = {k: normalize_value(k, v) for k, v in public_fields.items()}
            raw_data = _raw_record_payload(merged_record)
            requested_coverage = _requested_field_coverage(public_fields, additional_fields)
            db_record = CrawlRecord(
                run_id=run.id,
                source_url=url,
                data=normalized,
                raw_data=raw_data,
                discovered_data=_compact_dict({
                    **manifest.as_dict(),
                    "semantic": semantic or None,
                    "requested_field_coverage": requested_coverage or None,
                }),
                source_trace=_compact_dict({
                    **source_trace,
                    "type": "detail",
                    "adapter": adapter_name,
                    "requested_fields": additional_fields or None,
                    "requested_field_coverage": requested_coverage or None,
                }),
                raw_html_path=acq.artifact_path,
            )
            session.add(db_record)
            saved.append(normalized)
    elif candidate_values or source_trace.get("llm_cleanup_suggestions"):
        # Build record from candidates (detail page, no adapter)
        normalized = {
            field: normalize_value(field, value)
            for field, value in candidate_values.items()
        }
        raw_data = candidate_values
        requested_coverage = _requested_field_coverage(candidate_values, additional_fields)
        discovered_data = _compact_dict({
            "json_ld": manifest.json_ld or None,
            "next_data": manifest.next_data,
            "_hydrated_states": manifest._hydrated_states or None,
            "microdata": manifest.microdata or None,
            "tables": manifest.tables or None,
            "semantic": semantic or None,
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
                "requested_fields": additional_fields or None,
                "requested_field_coverage": requested_coverage or None,
            }),
            raw_html_path=acq.artifact_path,
        )
        session.add(db_record)
        saved.append(normalized)

    await _set_stage(session, run, "PUBLISH")
    verdict = _compute_verdict(saved, is_listing=False, requested_fields=additional_fields)
    await _log(session, run.id, "info", f"[PUBLISH] Saved {len(saved)} detail records (verdict={verdict})")
    await session.flush()
    return saved, verdict


# ---------------------------------------------------------------------------
# Verdict helpers
# ---------------------------------------------------------------------------

def _compute_verdict(
    records: list[dict],
    is_listing: bool,
    requested_fields: list[str] | None = None,
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
    await session.rollback()
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

    try:
        await _log(session, run.id, "error", f"Pipeline failed: {error_msg}")
        await session.commit()
    except Exception:
        await session.rollback()
        run = await session.get(CrawlRun, run_id)
        if run is None:
            return
        retry_summary = dict(run.result_summary or {})
        retry_summary["error"] = error_msg
        retry_summary["progress"] = retry_summary.get("progress", 0)
        retry_summary["extraction_verdict"] = "error"
        if normalize_status(run.status) not in TERMINAL_STATUSES:
            update_run_status(run, CrawlStatus.FAILED)
        run.result_summary = retry_summary
        try:
            await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                logger.exception(
                    "Rollback failed after double commit failure while marking crawl run failed",
                    extra={"run_id": run_id},
                )
            logger.error(
                "Double commit failure while marking crawl run failed",
                extra={
                    "run_id": run.id,
                    "run_status": run.status,
                    "traceback": traceback.format_exc(),
                },
            )
            raise


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
                re.compile(regex)
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
    additional_fields: list[str],
    adapter_records: list[dict],
    candidate_values: dict,
    source_trace: dict,
) -> dict:
    trace_candidates = source_trace.setdefault("candidates", {})
    llm_cleanup_suggestions: dict[str, dict] = source_trace.get("llm_cleanup_suggestions", {})
    preview_record = (
        _merge_record_fields(adapter_records[0], candidate_values)
        if adapter_records else dict(candidate_values)
    )
    target_fields = sorted(set(get_canonical_fields(surface)) | set(additional_fields))
    missing_fields = [
        field_name
        for field_name in target_fields
        if preview_record.get(field_name) in (None, "", [], {})
    ]
    if not missing_fields:
        return source_trace

    domain = _domain(url)
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
    elif not xpath_rows:
        await _log(session, run.id, "warning", "[EXTRACT] LLM XPath discovery returned no usable suggestions")
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
        suggestion = _compact_dict({
            "field_name": field_name,
            "xpath": xpath,
            "css_selector": str(row.get("css_selector") or "").strip() or None,
            "regex": None,
            "status": "validated",
            "confidence": row.get("confidence") or 0.78,
            "sample_value": matched_value or expected_value,
            "source": "llm_xpath",
        })
        selector_suggestions.setdefault(field_name, []).append(suggestion)
        trace_candidates.setdefault(field_name, []).append(_compact_dict({
            "value": matched_value,
            "source": "llm_xpath",
            "confidence": row.get("confidence") or 0.78,
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
    preview_record = (
        _merge_record_fields(adapter_records[0], candidate_values)
        if adapter_records else dict(candidate_values)
    )
    remaining_missing = [
        field_name
        for field_name in target_fields
        if preview_record.get(field_name) in (None, "", [], {})
    ]
    if not remaining_missing:
        return source_trace

    await _log(session, run.id, "info", f"[EXTRACT] LLM value extraction for {len(remaining_missing)} unresolved detail fields")
    llm_values, llm_error = await extract_missing_fields(
        session,
        run_id=run.id,
        domain=domain,
        url=url,
        html_text=html,
        missing_fields=remaining_missing,
        existing_values=preview_record,
    )
    if llm_error:
        await _log(session, run.id, "warning", f"[LLM] Value extraction failed: {llm_error}")
    elif not llm_values:
        await _log(session, run.id, "warning", "[EXTRACT] LLM value extraction failed or returned no suggestions")
    for field_name, value in llm_values.items():
        if field_name not in remaining_missing or value in (None, "", [], {}):
            continue
        trace_candidates.setdefault(field_name, []).append(_compact_dict({
            "value": value,
            "source": "llm_value",
            "confidence": 0.7,
            "sample_value": value,
        }))
        llm_cleanup_suggestions[field_name] = _compact_dict({
            "field_name": field_name,
            "suggested_value": value,
            "source": "llm_value",
            "status": "pending_review",
        })
    source_trace["llm_cleanup_suggestions"] = llm_cleanup_suggestions
    return source_trace


# Domain normalisation delegated to app.services.domain_utils.normalize_domain
_domain = normalize_domain
