from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from html import unescape
from urllib.parse import urljoin, urlparse
import regex as regex_lib
from bs4 import BeautifulSoup, NavigableString, Tag
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.db_utils import with_retry
from app.services.shared_acquisition import (
    acquire,
    run_adapter,
    try_blocked_adapter_recovery,
)
from app.services.crawl_state import (
    CrawlStatus,
    TERMINAL_STATUSES,
    normalize_status,
    update_run_status,
)
from app.services.domain_utils import normalize_domain
from app.services.crawl_events import (
    append_log_event,
    persist_run_summary_patch,
    prepare_log_event,
)
from app.services.crawl_metrics import (
    build_acquisition_profile as _build_acquisition_profile,
    build_url_metrics as _build_url_metrics,
    finalize_url_metrics as _finalize_url_metrics,
)
from app.services.extract.json_extractor import (
    extract_json_detail,
    extract_json_listing,
)
from app.services.extract.listing_extractor import extract_listing_records
from app.services.extract.listing_quality import assess_listing_record_quality
from app.services.extract.service import (
    coerce_field_candidate_value,
    extract_candidates,
)
from app.services.extract.source_parsers import parse_page_sources
from app.services.knowledge_base.store import (
    get_canonical_fields,
    get_selector_defaults,
)
from app.services.llm_runtime import discover_xpath_candidates, review_field_candidates
from app.services.normalizers import (
    extract_currency_hint,
    normalize_value,
    validate_value,
)
from app.services.pipeline_config import (
    SOURCE_RANKING,
)
from app.services.requested_field_policy import expand_requested_fields
from app.services.schema_service import (
    ResolvedSchema,
    _supports_record_learning,
    learn_schema_from_record,
    load_resolved_schema,
    persist_resolved_schema,
    resolve_schema,
    schema_trace_payload,
)
from app.services.xpath_service import validate_xpath_candidate, validate_xpath_syntax

# Import from sibling modules in pipeline package
from .utils import (
    _elapsed_ms,
    _compact_dict,
    _clean_page_text,
    _first_non_empty_text,
    _clean_candidate_text,
)
from .field_normalization import (
    _normalize_review_value,
    _review_values_equal,
    _normalize_record_fields,
    _passes_detail_quality_gate,
    _raw_record_payload,
    _public_record_fields,
    _merge_record_fields,
    _should_prefer_secondary_field,
    _requested_field_coverage,
)
from .verdict import (
    VERDICT_SUCCESS,
    VERDICT_BLOCKED,
    VERDICT_SCHEMA_MISS,
    VERDICT_LISTING_FAILED,
    VERDICT_EMPTY,
    _compute_verdict,
    _passes_core_verdict,
    _aggregate_verdict,
    _review_bucket_fingerprint,
)
from .listing_helpers import (
    _listing_acquisition_blocked,
    _looks_like_loading_listing_shell,
    _sanitize_listing_record_fields,
    _summarize_job_listing_description,
)
from .rendering import (
    _render_fallback_node_markdown,
    _render_fallback_card_group,
    _find_fallback_card_group,
    _should_skip_fallback_node,
    _normalize_target_url,
    _render_manifest_tables_markdown,
)
from .llm_integration import (
    _apply_llm_suggestions_to_candidate_values,
    _build_llm_candidate_evidence,
    _build_llm_discovered_sources,
    _snapshot_for_llm,
    _normalize_llm_cleanup_review,
    _split_llm_cleanup_payload,
    _normalize_llm_review_bucket_item,
    _select_llm_review_candidates,
)
from .trace_builders import (
    _build_acquisition_trace,
    _build_manifest_trace,
    _build_review_bucket,
    _review_bucket_source_for_field,
    _build_field_discovery_summary,
)
from .review_helpers import (
    _merge_review_bucket_entries,
    _should_surface_discovered_field,
)


logger = logging.getLogger(__name__)
MAX_SELECTOR_ROWS_PER_FIELD = 100
HTTP_URL_PREFIXES = ("http://", "https://")
TITLE_SELECTOR = "h1 a, h2 a, h3 a, h4 a, h5 a, h1, h2, h3, h4, h5"
ANCHOR_SELECTOR = "a[href]"
_TRAVERSAL_MODES = {"auto", "scroll", "load_more", "paginate"}
_ECOMMERCE_ONLY_JOB_LISTING_FIELDS = frozenset(
    {
        "price",
        "sale_price",
        "original_price",
        "currency",
        "sku",
        "part_number",
        "availability",
        "rating",
        "review_count",
        "image_url",
        "additional_images",
    }
)
STAGE_FETCH = "FETCH"
STAGE_ANALYZE = "ANALYZE"
STAGE_SAVE = "SAVE"
# Batch runtime helpers now live directly in _batch_runtime.


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
    prefetched_acquisition: AcquisitionResult | None = None,
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
    await _sqlite_live_checkpoint(session, run)
    if prefetched_acquisition is None:
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
    else:
        acq = prefetched_acquisition
        acquisition_ms = 0
    url_metrics = _build_url_metrics(acq, requested_fields=additional_fields)
    url_metrics["acquisition_ms"] = acquisition_ms

    # ── STAGE 1.5: BLOCKED PAGE DETECTION ──
    # For JSON responses, skip blocked detection (APIs don't serve challenge pages)
    if acq.content_type != "json":
        blocked = detect_blocked_page(acq.html)
        if blocked.is_blocked and is_listing and acq.method != "playwright":
            if persist_logs:
                await _log(
                    session,
                    run.id,
                    "info",
                    "[BLOCKED] Listing page matched blocked signals on initial acquire; retrying once with browser-first recovery",
                )
            browser_retry_started_at = time.perf_counter()
            browser_profile = dict(acquisition_profile or {})
            browser_profile["prefer_browser"] = True
            browser_profile["anti_bot_enabled"] = True
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
            browser_blocked = (
                detect_blocked_page(browser_acq.html)
                if browser_acq.content_type != "json"
                else None
            )
            if not (browser_blocked and browser_blocked.is_blocked):
                acq = browser_acq
                acquisition_ms += browser_retry_ms
                url_metrics = _build_url_metrics(acq, requested_fields=additional_fields)
                url_metrics["acquisition_ms"] = acquisition_ms
                if persist_logs:
                    await _log(
                        session,
                        run.id,
                        "info",
                        "[BLOCKED] Browser-first recovery succeeded; continuing listing extraction",
                    )
                blocked = detect_blocked_page(acq.html) if acq.content_type != "json" else blocked
        if blocked.is_blocked:
            recovered = (
                None if proxy_list else await try_blocked_adapter_recovery(url, surface)
            )
            if recovered and recovered.records:
                if persist_logs:
                    await _log(
                        session,
                        run.id,
                        "info",
                        f"[BLOCKED] {url} matched blocked-page signals, recovered {len(recovered.records)} {recovered.adapter_name or 'adapter'} records from public endpoint",
                    )
                if is_listing:
                    return await _extract_listing(
                        session,
                        run,
                        url,
                        "",
                        acq,
                        recovered,
                        recovered.records,
                        additional_fields,
                        surface,
                        max_records,
                        url_metrics,
                        update_run_state=update_run_state,
                        persist_logs=persist_logs,
                    )
                return await _extract_detail(
                    session,
                    run,
                    url,
                    "",
                    acq,
                    recovered,
                    recovered.records,
                    additional_fields,
                    extraction_contract,
                    surface,
                    url_metrics,
                    update_run_state=update_run_state,
                    persist_logs=persist_logs,
                )
            if persist_logs:
                await _log(
                    session, run.id, "warning", f"[BLOCKED] {url} — {blocked.reason}"
                )
            record = CrawlRecord(
                run_id=run.id,
                source_url=url,
                data={
                    "_status": "blocked",
                    "_message": blocked.reason,
                    "_provider": blocked.provider,
                },
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
            await _log(
                session,
                run.id,
                "info",
                "[ANALYZE] JSON-first path — API response detected",
            )
        extraction_started_at = time.perf_counter()
        records, verdict, url_metrics = await _process_json_response(
            session,
            run,
            url,
            acq,
            is_listing,
            max_records,
            additional_fields,
            url_metrics,
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
        await _log(
            session,
            run.id,
            "info",
            f"[ANALYZE] Enumerating sources (method={acq.method})",
        )
    await _sqlite_live_checkpoint(session, run)

    # Run platform adapter (rank 1 source)
    adapter_result = await run_adapter(url, html, surface)
    adapter_records = adapter_result.records if adapter_result else []

    # ── STAGE 2: ANALYZE ──
    if update_run_state:
        await _set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await _log(session, run.id, "info", "[ANALYZE] Extracting candidates")
    await _sqlite_live_checkpoint(session, run)

    if is_listing:
        extraction_started_at = time.perf_counter()
        records, verdict, url_metrics = await _extract_listing(
            session,
            run,
            url,
            html,
            acq,
            adapter_result,
            adapter_records,
            additional_fields,
            surface,
            max_records,
            url_metrics,
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
            await _sqlite_live_checkpoint(session, run)
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
            browser_adapter_records = (
                browser_adapter_result.records if browser_adapter_result else []
            )
            extraction_started_at = time.perf_counter()
            records, verdict, url_metrics = await _extract_listing(
                session,
                run,
                url,
                browser_html,
                browser_acq,
                browser_adapter_result,
                browser_adapter_records,
                additional_fields,
                surface,
                max_records,
                url_metrics,
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
            session,
            run,
            url,
            html,
            acq,
            adapter_result,
            adapter_records,
            additional_fields,
            extraction_contract,
            surface,
            url_metrics,
            update_run_state=update_run_state,
            persist_logs=persist_logs,
        )
        url_metrics["extraction_ms"] = _elapsed_ms(extraction_started_at)
        return records, verdict, url_metrics


def _supports_parallel_batch_sessions(session: AsyncSession) -> bool:
    bind = session.bind
    if bind is None:
        return False
    if bind.dialect.name == "sqlite":
        return False
    return True


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
        extracted = await asyncio.to_thread(
            extract_json_listing,
            acq.json_data,
            url,
            max_records,
        )
    else:
        extracted = await asyncio.to_thread(
            extract_json_detail,
            acq.json_data,
            url,
        )

    if not extracted:
        if persist_logs:
            await _log(
                session,
                run.id,
                "warning",
                "[ANALYZE] JSON response parsed but no records found",
            )
        return [], VERDICT_SCHEMA_MISS, url_metrics

    if update_run_state:
        await _set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await _log(session, run.id, "info", "[ANALYZE] Normalizing JSON records")
    if is_listing:
        saved = await _save_listing_records(
            session=session,
            run=run,
            records=extracted,
            source_type="json_api",
            source_label="json_api",
            url=url,
            surface=run.surface,
            max_records=max_records,
            raw_html_path=acq.artifact_path,
            acquisition_trace=_build_acquisition_trace(acq),
            manifest_trace=_build_manifest_trace(
                html="",
                xhr_payloads=[],
                adapter_records=[],
                extra={"content_type": "json"},
            ),
        )
    else:
        saved = []
        resolved_schema = await resolve_schema(
            session,
            run.surface,
            url,
            run_id=run.id,
            explicit_fields=requested_fields,
            sample_record=extracted[0]
            if extracted and isinstance(extracted[0], dict)
            else None,
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
            normalized, discovered_fields = _split_detail_output_fields(
                public_fields,
                allowed_fields=allowed_fields,
                surface=run.surface,
            )
            raw_data = _raw_record_payload(raw_record)
            requested_coverage = _requested_field_coverage(normalized, requested_fields)
            review_bucket = _build_review_bucket(
                discovered_fields,
                fallback_source=str(raw_record.get("_source") or "json_api"),
            )
            db_record = CrawlRecord(
                run_id=run.id,
                source_url=raw_record.get("source_url") or raw_record.get("url", url),
                data=normalized,
                raw_data=raw_data,
                discovered_data=_compact_dict(
                    {
                        "review_bucket": review_bucket or None,
                        "requested_field_coverage": requested_coverage or None,
                    }
                ),
                source_trace=_compact_dict(
                    {
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
                                "json_record_keys": sorted(raw_data.keys())
                                if isinstance(raw_data, dict)
                                else None,
                                "full_json_hash": hashlib.sha256(
                                    str(acq.json_data).encode()
                                ).hexdigest()[:16]
                                if not is_listing and acq.json_data is not None
                                else None,
                            },
                        )
                        or None,
                    }
                ),
                raw_html_path=acq.artifact_path,
            )
            session.add(db_record)
            saved.append(normalized)

    if update_run_state:
        await _set_stage(session, run, STAGE_SAVE)
    verdict = _compute_verdict(saved, run.surface)
    if persist_logs:
        await _log(
            session,
            run.id,
            "info",
            f"[SAVE] Saved {len(saved)} JSON records (verdict={verdict})",
        )
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
    effective_surface = surface
    url_metrics["listing_surface_used"] = effective_surface

    extracted_records = await asyncio.to_thread(
        extract_listing_records,
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
        if persist_logs:
            await _log(
                session,
                run.id,
                "warning",
                "[ANALYZE] Listing extraction found 0 records — marking as listing_detection_failed",
            )
        return [], VERDICT_LISTING_FAILED, url_metrics

    # Save each listing record
    if update_run_state:
        await _set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await _log(session, run.id, "info", "[ANALYZE] Normalizing listing records")
    manifest_trace = await asyncio.to_thread(
        _build_manifest_trace,
        html=html,
        xhr_payloads=acq.network_payloads,
        adapter_records=adapter_records,
    )
    saved = await _save_listing_records(
        session=session,
        run=run,
        records=extracted_records,
        source_type="listing",
        source_label=source_label,
        url=url,
        surface=effective_surface,
        max_records=max_records,
        raw_html_path=acq.artifact_path,
        acquisition_trace=_build_acquisition_trace(acq),
        manifest_trace=manifest_trace,
        adapter_name=adapter_name,
        surface_requested=surface if effective_surface != surface else None,
    )

    if update_run_state:
        await _set_stage(session, run, STAGE_SAVE)
    verdict = _compute_verdict(saved, effective_surface)
    if persist_logs:
        await _log(
            session,
            run.id,
            "info",
            f"[SAVE] Saved {len(saved)} listing records (verdict={verdict})",
        )
    await session.flush()
    _finalize_url_metrics(
        url_metrics, records=saved, requested_fields=additional_fields
    )
    return saved, verdict, url_metrics


async def _save_listing_records(
    *,
    session: AsyncSession,
    run: CrawlRun,
    records: list[dict],
    source_type: str,
    source_label: str,
    url: str,
    surface: str,
    max_records: int,
    raw_html_path: str | None,
    acquisition_trace: dict,
    manifest_trace: dict | None,
    adapter_name: str | None = None,
    surface_requested: str | None = None,
) -> list[dict]:
    saved: list[dict] = []
    for raw_record in records:
        if len(saved) >= max_records:
            break
        record_source_label = (
            str(raw_record.get("_source") or source_label).strip() or source_label
        )
        public_record = _sanitize_listing_record_fields(
            _public_record_fields(raw_record),
            surface=surface,
            page_base_url=url,
        )
        normalized = _normalize_record_fields(public_record, surface=surface)
        if not normalized:
            continue
        db_record = CrawlRecord(
            run_id=run.id,
            source_url=raw_record.get("source_url") or raw_record.get("url", url),
            data=normalized,
            raw_data=_raw_record_payload(raw_record),
            discovered_data={},
            source_trace=_compact_dict(
                {
                    "type": source_type,
                    **acquisition_trace,
                    "adapter": adapter_name,
                    "source": record_source_label,
                    "surface_used": surface,
                    "surface_requested": surface_requested,
                    "manifest_trace": manifest_trace or None,
                }
            ),
            raw_html_path=raw_html_path,
        )
        session.add(db_record)
        saved.append(normalized)
    return saved


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
        sample_record=adapter_records[0]
        if adapter_records and isinstance(adapter_records[0], dict)
        else None,
        llm_enabled=bool((run.settings or {}).get("llm_enabled")),
    )

    candidates, source_trace = await asyncio.to_thread(
        extract_candidates,
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
    semantic = (
        source_trace.get("semantic")
        if isinstance(source_trace.get("semantic"), dict)
        else {}
    )
    source_trace = {
        **_build_acquisition_trace(acq),
        **source_trace,
    }
    detail_manifest_trace = await asyncio.to_thread(
        _build_manifest_trace,
        html=html,
        xhr_payloads=acq.network_payloads,
        adapter_records=adapter_records,
        semantic=semantic,
    )

    # Build deterministic field discovery summary for all detail fields before any
    # optional LLM suggestion pass. Canonical output still comes strictly from the
    # first candidate row in source order.
    source_trace = _build_field_discovery_summary(
        source_trace,
        candidates,
        candidate_values,
        additional_fields,
        surface,
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
        candidate_values, llm_promoted_fields = (
            _apply_llm_suggestions_to_candidate_values(
                candidate_values,
                allowed_fields=persisted_field_names,
                source_trace=source_trace,
                url=url,
            )
        )
        if llm_promoted_fields:
            llm_status = dict(source_trace.get("llm_cleanup_status") or {})
            llm_status["auto_promoted_fields"] = sorted(llm_promoted_fields.keys())
            source_trace["llm_cleanup_status"] = llm_status
        source_trace = _build_field_discovery_summary(
            source_trace,
            source_trace.get("candidates") or candidates,
            candidate_values,
            additional_fields,
            surface,
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
            normalized, discovered_fields = _split_detail_output_fields(
                public_fields,
                allowed_fields=persisted_field_names,
                surface=surface,
            )
            raw_data = _raw_record_payload(merged_record)
            requested_coverage = _requested_field_coverage(
                normalized, additional_fields
            )
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
                discovered_data=_compact_dict(
                    {
                        "review_bucket": review_bucket or None,
                        "requested_field_coverage": requested_coverage or None,
                    }
                ),
                source_trace=_compact_dict(
                    {
                        **source_trace,
                        "type": "detail",
                        "adapter": adapter_name,
                        "schema_resolution": schema_trace_payload(resolved_schema),
                        "reconciliation": reconciliation or None,
                        "requested_fields": additional_fields or None,
                        "requested_field_coverage": requested_coverage or None,
                        "manifest_trace": detail_manifest_trace or None,
                    }
                ),
                raw_html_path=acq.artifact_path,
            )
            session.add(db_record)
            saved.append(normalized)
    elif candidate_values or source_trace.get("llm_cleanup_suggestions"):
        # Build record from candidates (detail page, no adapter)
        normalized, discovered_fields = _split_detail_output_fields(
            candidate_values,
            allowed_fields=persisted_field_names,
            surface=surface,
        )
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
        discovered_data = _compact_dict(
            {
                "review_bucket": review_bucket or None,
                "requested_field_coverage": requested_coverage or None,
            }
        )
        db_record = CrawlRecord(
            run_id=run.id,
            source_url=url,
            data=normalized,
            raw_data=raw_data,
            discovered_data=discovered_data,
            source_trace=_compact_dict(
                {
                    **source_trace,
                    "type": "detail",
                    "schema_resolution": schema_trace_payload(resolved_schema),
                    "reconciliation": reconciliation or None,
                    "requested_fields": additional_fields or None,
                    "requested_field_coverage": requested_coverage or None,
                    "manifest_trace": detail_manifest_trace or None,
                }
            ),
            raw_html_path=acq.artifact_path,
        )
        session.add(db_record)
        saved.append(normalized)

    if update_run_state:
        await _set_stage(session, run, STAGE_SAVE)
    verdict = _compute_verdict(saved, surface)
    if persist_logs:
        await _log(
            session,
            run.id,
            "info",
            f"[SAVE] Saved {len(saved)} detail records (verdict={verdict})",
        )
    await session.flush()
    _finalize_url_metrics(
        url_metrics, records=saved, requested_fields=additional_fields
    )
    return saved, verdict, url_metrics


# ---------------------------------------------------------------------------
# Verdict helpers
# ---------------------------------------------------------------------------
# Note: These are imported from .verdict module at the top of the file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _log(session: AsyncSession, run_id: int, level: str, message: str) -> None:
    normalized_level, formatted_message, should_persist = prepare_log_event(
        run_id, level, message
    )
    if not should_persist:
        return
    if _use_isolated_event_writes(session):
        await append_log_event(
            run_id, normalized_level, formatted_message, preformatted=True
        )
    else:
        session.add(
            CrawlLog(run_id=run_id, level=normalized_level, message=formatted_message)
        )


async def _set_stage(
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
    if _use_isolated_event_writes(session):
        await persist_run_summary_patch(run_id=run.id, summary_patch=summary_patch)
        return

    async def _operation(retry_session: AsyncSession) -> None:
        retry_run = await retry_session.get(CrawlRun, run.id)
        if retry_run is None:
            return
        result_summary = dict(retry_run.result_summary or {})
        if all(result_summary.get(key) == value for key, value in summary_patch.items()):
            return
        result_summary.update(summary_patch)
        retry_run.result_summary = result_summary

    await with_retry(session, _operation)


def _use_isolated_event_writes(session: AsyncSession) -> bool:
    bind = session.bind
    if bind is None:
        return False
    # SQLite must keep run/log writes in the same session transaction.
    # Separate writer sessions can block against an in-flight stage flush
    # and make FETCH appear stuck at "Processing URL ...".
    return bind.dialect.name != "sqlite"


async def _sqlite_live_checkpoint(session: AsyncSession, run: CrawlRun) -> None:
    bind = session.bind
    if bind is None or bind.dialect.name != "sqlite":
        return
    # Persist stage/log snapshots so polling UI can render live progress.
    # Use unit-of-work retry semantics to avoid commit-only retry footguns.
    async def _commit_only_operation(retry_session: AsyncSession) -> None:
        return None

    await with_retry(session, _commit_only_operation)
    await session.refresh(run)


async def _mark_run_failed(session: AsyncSession, run_id: int, error_msg: str) -> None:
    """Mark a run as failed.

    First attempts recovery using the existing session (after a rollback).
    If that fails, creates an isolated session via ``SessionLocal`` so a
    poisoned transaction cannot block failure recording.
    """
    try:
        await session.rollback()
    except SQLAlchemyError:
        pass  # Original session may already be invalidated — that's fine.

    # Try the original session first — works in tests and when the session is still usable.
    try:
        await _persist_failure_state(session, run_id, error_msg)
        return
    except SQLAlchemyError:
        logger.debug(
            "Original session unusable for failure recovery; falling back to SessionLocal",
            exc_info=True,
        )

        try:
            async with SessionLocal() as recovery:
                await _persist_failure_state(recovery, run_id, error_msg)
        except SQLAlchemyError:
            logger.exception("Failure recovery via SessionLocal failed")


async def _persist_failure_state(
    session: AsyncSession, run_id: int, error_msg: str
) -> None:
    """Write failure state with retry-safe full mutation retries."""

    async def _mutation(retry_session: AsyncSession) -> None:
        run = await retry_session.get(CrawlRun, run_id)
        if run is None:
            return
        result_summary = dict(run.result_summary or {})
        result_summary["error"] = error_msg
        result_summary["progress"] = result_summary.get("progress", 0)
        result_summary["extraction_verdict"] = "error"
        if normalize_status(run.status) not in TERMINAL_STATUSES:
            update_run_status(run, CrawlStatus.FAILED)
        run.result_summary = result_summary
    await with_retry(session, _mutation)


def _reconcile_detail_candidate_values(
    candidates: dict[str, list[dict]],
    *,
    allowed_fields: set[str],
    url: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    def _row_rank(row: dict) -> int:
        source = str(row.get("source") or "").strip()
        if not source:
            return 0
        source_parts = [part.strip() for part in source.split(",") if part.strip()]
        if not source_parts:
            return 0
        return max(int(SOURCE_RANKING.get(part, 0)) for part in source_parts)

    reconciled: dict[str, object] = {}
    reconciliation: dict[str, dict[str, object]] = {}

    for field_name in sorted(allowed_fields):
        rows = list(candidates.get(field_name) or [])
        if not rows:
            continue

        accepted_rows: list[dict] = []
        rejected_rows: list[dict[str, object]] = []
        for row in rows:
            value = row.get("value")
            normalized_value = coerce_field_candidate_value(
                field_name, value, base_url=url
            )
            if normalized_value in (None, "", [], {}):
                rejected_rows.append(
                    {
                        "value": value,
                        "reason": "empty_after_normalization",
                        "source": row.get("source"),
                    }
                )
                continue
            if not _passes_detail_quality_gate(field_name, normalized_value):
                rejected_rows.append(
                    {
                        "value": normalized_value,
                        "reason": "quality_gate_rejected",
                        "source": row.get("source"),
                    }
                )
                continue
            accepted_rows.append({**row, "value": normalized_value})

        if not accepted_rows:
            if rejected_rows:
                reconciliation[field_name] = {
                    "status": "rejected",
                    "rejected": rejected_rows[:6],
                }
            continue

        accepted_row = accepted_rows[0]
        accepted_rank = _row_rank(accepted_row)
        for candidate_row in accepted_rows[1:]:
            candidate_rank = _row_rank(candidate_row)
            if candidate_rank > accepted_rank:
                accepted_row = candidate_row
                accepted_rank = candidate_rank

        reconciled[field_name] = accepted_row["value"]
        if rejected_rows:
            reconciliation[field_name] = _compact_dict(
                {
                    "status": "accepted_with_rejections",
                    "accepted_source": accepted_row.get("source"),
                    "rejected": rejected_rows[:6],
                }
            )

    return reconciled, reconciliation


def _split_detail_output_fields(
    record: dict[str, object],
    *,
    allowed_fields: set[str],
    surface: str = "",
) -> tuple[dict[str, object], dict[str, object]]:
    normalized = _normalize_record_fields(record, surface=surface)
    canonical: dict[str, object] = {}
    discovered: dict[str, object] = {}
    for key, value in normalized.items():
        if key in allowed_fields:
            canonical[key] = value
        else:
            discovered[key] = value
    return canonical, discovered


def _resolve_listing_surface(
    *,
    surface: str,
    url: str,
    html: str,
    acq: AcquisitionResult,
) -> str:
    _ = url, html, acq
    # User-owned surface contract: never rewrite requested surface in backend.
    return surface


def _looks_like_job_listing_page(
    *, url: str, html: str, acq: AcquisitionResult
) -> bool:
    _ = url, html, acq
    # Kept only for compatibility with existing imports/tests.
    return False


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
            except regex_lib.error as exc:
                errors.append(
                    f"Row {index} ({field_name or 'unnamed'}): invalid regex ({exc})"
                )
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
    llm_cleanup_suggestions: dict[str, dict] = source_trace.get(
        "llm_cleanup_suggestions", {}
    )
    llm_cleanup_status: dict[str, object] = dict(
        source_trace.get("llm_cleanup_status") or {}
    )
    llm_review_bucket: list[dict[str, object]] = []
    preview_record = (
        _merge_record_fields(adapter_records[0], candidate_values)
        if adapter_records
        else dict(candidate_values)
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
        await _log(
            session,
            run.id,
            "info",
            f"[ANALYZE] LLM XPath discovery for {len(missing_fields)} missing detail fields",
        )
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
            await _log(
                session,
                run.id,
                "warning",
                f"[LLM] XPath discovery failed: {xpath_error}",
            )
            llm_cleanup_status = {
                **llm_cleanup_status,
                "status": "xpath_error",
                "message": xpath_error,
                "xpath_error": xpath_error,
            }
        elif not xpath_rows:
            await _log(
                session,
                run.id,
                "warning",
                "[ANALYZE] LLM XPath discovery returned no usable suggestions",
            )
    else:
        xpath_rows = []
    selector_suggestions: dict[str, list[dict]] = source_trace.get(
        "selector_suggestions", {}
    )
    for row in xpath_rows:
        if not isinstance(row, dict):
            continue
        field_name = str(row.get("field_name") or "").strip()
        xpath = str(row.get("xpath") or "").strip()
        if not field_name or field_name not in missing_fields or not xpath:
            continue
        expected_value = str(row.get("expected_value") or "").strip() or None
        validation = validate_xpath_candidate(
            html, xpath, expected_value=expected_value
        )
        if not validation.get("valid"):
            continue
        matched_value = validation.get("matched_value")
        matched_value = coerce_field_candidate_value(
            field_name, matched_value, base_url=url
        )
        if matched_value in (None, "", [], {}):
            continue
        suggestion = _compact_dict(
            {
                "field_name": field_name,
                "xpath": xpath,
                "css_selector": str(row.get("css_selector") or "").strip() or None,
                "regex": None,
                "status": "validated",
                "sample_value": matched_value or expected_value,
                "source": "llm_xpath",
            }
        )
        selector_suggestions.setdefault(field_name, []).append(suggestion)
        trace_candidates.setdefault(field_name, []).append(
            _compact_dict(
                {
                    "value": matched_value,
                    "source": "llm_xpath",
                    "xpath": xpath,
                    "css_selector": suggestion.get("css_selector"),
                    "sample_value": matched_value or expected_value,
                    "status": "validated",
                }
            )
        )
        if matched_value not in (None, "", [], {}):
            llm_cleanup_suggestions[field_name] = _compact_dict(
                {
                    "field_name": field_name,
                    "suggested_value": matched_value,
                    "source": "llm_xpath",
                    "xpath": xpath,
                    "css_selector": suggestion.get("css_selector"),
                    "status": "pending_review",
                }
            )

    source_trace["selector_suggestions"] = selector_suggestions
    source_trace["llm_cleanup_suggestions"] = llm_cleanup_suggestions

    candidate_evidence = _build_llm_candidate_evidence(trace_candidates, preview_record)
    review_candidate_evidence = _select_llm_review_candidates(
        candidate_evidence, preview_record, target_fields
    )
    deterministic_fields = sorted(
        field_name
        for field_name in target_fields
        if field_name not in missing_fields
        and field_name not in review_candidate_evidence
    )
    discovered_sources = await asyncio.to_thread(
        _build_llm_discovered_sources,
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

    await _log(
        session,
        run.id,
        "info",
        f"[ANALYZE] LLM cleanup review for {len(review_candidate_evidence)} candidate field groups",
    )
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
        await _log(
            session, run.id, "warning", f"[LLM] Cleanup review failed: {llm_error}"
        )
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
        await _log(
            session,
            run.id,
            "warning",
            "[ANALYZE] LLM cleanup review returned no suggestions",
        )
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


def _normalize_detail_candidate_values(
    candidate_values: dict[str, object], *, url: str
) -> dict[str, object]:
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
            part.strip() for part in additional_images.split(",") if part.strip()
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


async def _load_domain_requested_fields(
    session: AsyncSession, *, url: str, surface: str
) -> list[str]:
    resolved = await load_resolved_schema(session, surface, normalize_domain(url))
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
    if not _supports_record_learning(surface):
        return None
    learned = learn_schema_from_record(
        surface=surface,
        domain=base_schema.domain or normalize_domain(url),
        baseline_fields=base_schema.baseline_fields,
        explicit_fields=[
            field
            for field in base_schema.fields
            if field not in set(base_schema.baseline_fields)
        ],
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
        str(source).strip() for source in existing_sources if str(source).strip()
    }
    sources.add(source_label)
    canonical_fields = set(get_canonical_fields(run.surface))
    field_discovery[field_name] = _compact_dict(
        {
            **existing_entry,
            "status": "found",
            "value": _clean_candidate_text(value)
            if value not in (None, "", [], {})
            else None,
            "sources": sorted(sources),
            "is_canonical": existing_entry.get(
                "is_canonical", field_name in canonical_fields
            )
            or None,
        }
    )
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
    review_bucket = (
        discovered_data.get("review_bucket")
        if isinstance(discovered_data.get("review_bucket"), list)
        else []
    )
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
        discovered_data["requested_field_coverage"] = _requested_field_coverage(
            record.data or {}, requested_fields
        )
    record.discovered_data = _compact_dict(discovered_data)


# Domain normalisation delegated to app.services.domain_utils.normalize_domain
_domain = normalize_domain


