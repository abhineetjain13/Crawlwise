from __future__ import annotations

import asyncio
import hashlib
import logging
import re

from app.core.database import SessionLocal
from app.models.crawl import CrawlRecord, CrawlRun
from app.services.acquisition.acquirer import AcquisitionRequest, AcquisitionResult
from app.services.crawl_events import (
    append_log_event,
    prepare_log_event,
)
from app.services.crawl_metadata import refresh_record_commit_metadata
from app.services.crawl_metrics import (
    build_acquisition_profile as _build_acquisition_profile,
)
from app.services.crawl_metrics import (
    finalize_url_metrics as _finalize_url_metrics,
)
from app.services.crawl_state import (
    TERMINAL_STATUSES,
    CrawlStatus,
    update_run_status,
)
from app.services.domain_utils import normalize_domain
from app.services.exceptions import PipelineWriteError
from app.services.extract.json_extractor import (
    extract_json_detail,
    extract_json_listing,
)
from app.services.extract.listing_extractor import extract_listing_records
from app.services.extract.listing_identity import strong_identity_key
from app.services.extract.listing_quality import listing_set_quality
from app.services.extract.service import (
    coerce_field_candidate_value,
    extract_candidates,
)
from app.services.knowledge_base.store import (
    get_selector_defaults,
)
from app.services.llm_runtime import discover_xpath_candidates, review_field_candidates
from app.services.requested_field_policy import expand_requested_fields
from app.services.runtime_metrics import incr
from app.services.schema_service import (
    ResolvedSchema,
    load_resolved_schema,
    resolve_schema,
    schema_trace_payload,
)
from app.services.xpath_service import validate_xpath_candidate
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .field_normalization import (
    _merge_record_fields,
    _normalize_record_fields,
    _public_record_fields,
    _raw_record_payload,
    _requested_field_coverage,
)
from .listing_helpers import (
    _listing_acquisition_blocked,
    _looks_like_loading_listing_shell,
    _sanitize_listing_record_fields,
)
from .llm_integration import (
    _apply_llm_suggestions_to_candidate_values,
    _build_llm_candidate_evidence,
    _build_llm_discovered_sources,
    _normalize_llm_cleanup_review,
    _select_llm_review_candidates,
    _split_llm_cleanup_payload,
)
from .review_helpers import (
    _merge_review_bucket_entries,
)
from .runner import PipelineRunner, build_default_stages
from .trace_builders import (
    _build_acquisition_trace,
    _build_field_discovery_summary,
    _build_manifest_trace,
    _build_review_bucket,
)

# Import from sibling modules in pipeline package
from .utils import (
    _compact_dict,
    parse_html,
)
from .types import PipelineContext, URLProcessingConfig, URLProcessingResult
from .verdict import (
    VERDICT_BLOCKED,
    VERDICT_EMPTY,
    VERDICT_ERROR,
    VERDICT_LISTING_FAILED,
    VERDICT_PARTIAL,
    VERDICT_SCHEMA_MISS,
    VERDICT_SUCCESS,
    _compute_verdict,
)

logger = logging.getLogger(__name__)
HTTP_URL_PREFIXES = ("http://", "https://")
_TRAVERSAL_MODES = {"auto", "scroll", "load_more", "paginate"}
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
# Batch runtime helpers now live directly in _batch_runtime.


def _log_for_pytest(level: int, message: str, *args: object) -> None:
    logger.log(level, message, *args)
    root_logger = logging.getLogger()
    if any(type(handler).__name__ == "LogCaptureHandler" for handler in root_logger.handlers):
        root_logger.log(level, message, *args)


def _is_error_page_record(record: dict) -> bool:
    """Return True if the record appears to be an error/blocked page, not real content."""
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


def _resolved_url_processing_config(
    *,
    config: URLProcessingConfig | None,
    proxy_list: list[str] | None,
    traversal_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    max_records: int,
    sleep_ms: int,
    update_run_state: bool,
    persist_logs: bool,
) -> URLProcessingConfig:
    if config is not None:
        return config
    return URLProcessingConfig(
        proxy_list=list(proxy_list or []),
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        max_records=max_records,
        sleep_ms=sleep_ms,
        update_run_state=update_run_state,
        persist_logs=persist_logs,
        prefetch_only=False,
    )


async def _pipeline_stage_checkpoint(_stage_name: str, ctx: PipelineContext) -> None:
    if ctx.checkpoint is not None:
        await ctx.checkpoint()


async def _count_run_records(session: AsyncSession, run_id: int) -> int:
    if not hasattr(session, "execute"):
        return 0
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


async def _effective_max_records(
    session: AsyncSession,
    run: CrawlRun,
    requested_max_records: int,
) -> int:
    settings_view = getattr(run, "settings_view", None)
    if settings_view is not None and hasattr(settings_view, "max_records"):
        configured_max = settings_view.max_records()
    else:
        configured_max = int(requested_max_records or 0)
    budget_limit = max(0, min(int(requested_max_records or 0), configured_max))
    run_id = int(getattr(run, "id", 0) or 0)
    existing_records = await _count_run_records(session, run_id) if run_id else 0
    return max(0, budget_limit - existing_records)


async def _process_single_url(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    config: URLProcessingConfig | None = None,
    *,
    # Legacy keyword arguments — prefer passing a URLProcessingConfig instead.
    proxy_list: list[str] | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = 3,
    max_records: int = 100,
    sleep_ms: int = 0,
    checkpoint=None,
    update_run_state: bool = True,
    persist_logs: bool = True,
    prefetched_acquisition: AcquisitionResult | None = None,
) -> URLProcessingResult:
    """Run the single-URL pipeline.

    Returns a ``URLProcessingResult`` with records, verdict, and metrics.
    """
    resolved_config = _resolved_url_processing_config(
        config=config,
        proxy_list=proxy_list,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        max_records=max_records,
        sleep_ms=sleep_ms,
        update_run_state=update_run_state,
        persist_logs=persist_logs,
    )
    surface = run.surface
    settings_view = run.settings_view
    additional_fields = expand_requested_fields(run.requested_fields or [])
    extraction_contract = settings_view.extraction_contract()
    is_listing = surface in ("ecommerce_listing", "job_listing")
    requested_field_selectors = {
        field_name: get_selector_defaults(normalize_domain(url), field_name)
        for field_name in additional_fields
        if field_name
    }
    acquisition_profile = _build_acquisition_profile(settings_view)
    base_acquisition_request = AcquisitionRequest(
        run_id=run.id,
        url=url,
        surface=surface,
        proxy_list=list(resolved_config.proxy_list or []),
        traversal_mode=resolved_config.traversal_mode,
        max_pages=resolved_config.max_pages,
        max_scrolls=resolved_config.max_scrolls,
        sleep_ms=resolved_config.sleep_ms,
        requested_fields=list(additional_fields),
        requested_field_selectors=dict(requested_field_selectors),
        acquisition_profile=dict(acquisition_profile or {}),
        checkpoint=checkpoint,
    )
    effective_max_records = await _effective_max_records(
        session,
        run,
        resolved_config.max_records,
    )
    resolved_config = URLProcessingConfig(
        proxy_list=list(resolved_config.proxy_list or []),
        traversal_mode=resolved_config.traversal_mode,
        max_pages=resolved_config.max_pages,
        max_scrolls=resolved_config.max_scrolls,
        max_records=effective_max_records,
        sleep_ms=resolved_config.sleep_ms,
        update_run_state=resolved_config.update_run_state,
        persist_logs=resolved_config.persist_logs,
        prefetch_only=resolved_config.prefetch_only,
    )
    ctx = PipelineContext(
        session=session,
        run=run,
        url=url,
        config=resolved_config,
        acquisition_request=base_acquisition_request,
        additional_fields=additional_fields,
        extraction_contract=extraction_contract,
        is_listing=is_listing,
        surface=surface,
        update_run_state=resolved_config.update_run_state,
        persist_logs=resolved_config.persist_logs,
        checkpoint=checkpoint,
        acquisition_result=prefetched_acquisition,
        acquisition_ms=0,
    )
    runner = PipelineRunner(
        build_default_stages(prefetch_only=resolved_config.prefetch_only),
        on_before_stage=_pipeline_stage_checkpoint,
    )
    await runner.execute(ctx)
    if resolved_config.prefetch_only:
        ctx.url_metrics["prefetch_only"] = True
        if not ctx.verdict:
            acq = ctx.acquisition_result
            if acq is None:
                ctx.verdict = VERDICT_ERROR
            elif acq.content_type == "json" and acq.json_data is not None:
                ctx.verdict = VERDICT_SUCCESS
            elif acq.html:
                ctx.verdict = VERDICT_SUCCESS
            else:
                ctx.verdict = VERDICT_EMPTY
    return ctx.to_result()


def _supports_parallel_batch_sessions(session: AsyncSession) -> bool:
    return session.bind is not None


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
    max_records = await _effective_max_records(session, run, max_records)
    if max_records <= 0:
        _finalize_url_metrics(url_metrics, records=[], requested_fields=requested_fields)
        return URLProcessingResult([], VERDICT_SCHEMA_MISS, url_metrics)
    if is_listing:
        extracted = await asyncio.to_thread(
            extract_json_listing,
            acq.json_data,
            url,
            max_records,
            surface=run.surface,
            requested_fields=requested_fields,
        )
    else:
        extracted = await asyncio.to_thread(
            extract_json_detail,
            acq.json_data,
            url,
            surface=run.surface,
            requested_fields=requested_fields,
        )

    if not extracted:
        if persist_logs:
            await _log(
                session,
                run.id,
                "warning",
                "[ANALYZE] JSON response parsed but no records found",
            )
        return URLProcessingResult([], VERDICT_SCHEMA_MISS, url_metrics)

    if update_run_state:
        await _set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await _log(session, run.id, "info", "[ANALYZE] Normalizing JSON records")
    if is_listing:
        saved, save_stats = await _save_listing_records(
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
        duplicate_drops = int(save_stats.get("duplicate_drops", 0) or 0)
        if duplicate_drops:
            url_metrics["duplicate_listing_drops"] = duplicate_drops
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
            llm_enabled=run.settings_view.llm_enabled(),
        )
        for raw_record in extracted:
            if len(saved) >= max_records:
                break
            allowed_fields = set(resolved_schema.fields)
            public_fields = _public_record_fields(raw_record)
            normalized, discovered_fields = _split_detail_output_fields(
                public_fields,
                allowed_fields=allowed_fields,
                surface=run.surface,
            )
            if not normalized:
                continue
            if _is_error_page_record(normalized):
                logger.debug(
                    "Skipping error-page record: title=%r",
                    normalized.get("title"),
                )
                continue
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
                        "discovered_fields": review_bucket or None,
                        "review_bucket": review_bucket or None,
                        "requested_field_coverage": requested_coverage or None,
                    }
                ),
                source_trace=_compact_dict(
                    {
                        "type": "json_api",
                        "method": acq.method,
                        "schema_resolution": schema_trace_payload(resolved_schema),
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
    verdict = _compute_verdict(saved, run.surface, is_listing=is_listing)
    if persist_logs:
        await _log(
            session,
            run.id,
            "info",
            f"[SAVE] Saved {len(saved)} JSON records (verdict={verdict})",
        )
    await session.flush()
    _finalize_url_metrics(url_metrics, records=saved, requested_fields=requested_fields)
    return URLProcessingResult(saved, verdict, url_metrics)


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
            return URLProcessingResult([], VERDICT_BLOCKED, url_metrics)
        if _looks_like_loading_listing_shell(html, surface=effective_surface):
            if persist_logs:
                await _log(
                    session,
                    run.id,
                    "warning",
                    "[ANALYZE] Listing extraction found 0 records on a loading shell; skipping page fallback so browser retry/failure is explicit",
                )
            return URLProcessingResult([], VERDICT_LISTING_FAILED, url_metrics)
        if effective_surface == "job_listing":
            if persist_logs:
                await _log(
                    session,
                    run.id,
                    "warning",
                    "[ANALYZE] Job listing extraction found 0 records; skipping page fallback so browser retry/failure is explicit",
                )
            return URLProcessingResult([], VERDICT_LISTING_FAILED, url_metrics)
        if persist_logs:
            await _log(
                session,
                run.id,
                "warning",
                "[ANALYZE] Listing extraction found 0 records — marking as listing_detection_failed",
            )
        return URLProcessingResult([], VERDICT_LISTING_FAILED, url_metrics)

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
    saved, save_stats = await _save_listing_records(
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
    duplicate_drops = int(save_stats.get("duplicate_drops", 0) or 0)
    if duplicate_drops:
        url_metrics["duplicate_listing_drops"] = duplicate_drops

    if update_run_state:
        await _set_stage(session, run, STAGE_SAVE)
    verdict = _compute_verdict(saved, effective_surface, is_listing=True)
    url_metrics["listing_quality"] = listing_set_quality(
        saved,
        surface=effective_surface,
    )
    quality_flags = _listing_quality_flags(
        saved,
        surface=effective_surface,
        network_payload_count=len(acq.network_payloads or []),
    )
    if quality_flags:
        url_metrics["listing_quality_flags"] = sorted(quality_flags)
    if verdict == VERDICT_SUCCESS and quality_flags:
        verdict = VERDICT_PARTIAL
        if persist_logs:
            await _log(
                session,
                run.id,
                "warning",
                "[SAVE] Listing quality gates downgraded verdict to partial: "
                + ", ".join(sorted(quality_flags)),
            )
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
    return URLProcessingResult(saved, verdict, url_metrics)


def _listing_quality_flags(
    records: list[dict],
    *,
    surface: str,
    network_payload_count: int,
) -> set[str]:
    flags: set[str] = set()
    normalized_surface = str(surface or "").strip().lower()
    if not records:
        return flags
    if listing_set_quality(records, surface=normalized_surface) != "meaningful":
        flags.add("non_meaningful_listing_set")
    if normalized_surface == "job_listing" and network_payload_count > 0:
        strong_job_fields = {
            "company",
            "location",
            "salary",
            "department",
            "job_id",
            "posted_date",
            "job_type",
            "apply_url",
            "description",
            "category",
        }
        if not any(
            any(
                record.get(field_name) not in (None, "", [], {})
                for field_name in strong_job_fields
            )
            for record in records
        ):
            flags.add("job_payload_missing_context")
    if "ecommerce" in normalized_surface:
        urls = [
            str(record.get("url") or "").strip().lower()
            for record in records
            if str(record.get("url") or "").strip()
        ]
        distinct_urls = {url for url in urls if url}
        if urls and len(distinct_urls) < len(urls):
            flags.add("duplicate_listing_urls")
    return flags


def _listing_fallback_identity_key(record: dict[str, object]) -> str:
    return "|".join(
        [
            str(record.get("title") or "").strip().lower(),
            str(record.get("url") or record.get("apply_url") or "").strip().lower(),
        ]
    ).strip("|")


def _dedupe_listing_persistence_candidates(
    candidates: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, int]]:
    deduped: list[dict[str, object]] = []
    stats = {"duplicate_drops": 0}
    seen_identity_keys: set[str] = set()
    seen_fallback_keys: set[str] = set()

    for candidate in candidates:
        identity_key = str(candidate.get("identity_key") or "").strip()
        fallback_key = str(candidate.get("fallback_key") or "").strip()
        collision_key = ""

        if identity_key and identity_key in seen_identity_keys:
            collision_key = identity_key
        elif fallback_key and fallback_key in seen_fallback_keys:
            collision_key = fallback_key

        if collision_key:
            stats["duplicate_drops"] += 1
            incr("listing_duplicate_drops_total")
            _log_for_pytest(
                logging.DEBUG,
                "Dropping duplicate listing record before persistence for identity key %s",
                collision_key,
            )
            continue

        if identity_key:
            seen_identity_keys.add(identity_key)
        if fallback_key:
            seen_fallback_keys.add(fallback_key)
        deduped.append(candidate)

    return deduped, stats


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
) -> tuple[list[dict], dict[str, int]]:
    try:
        max_records = await _effective_max_records(session, run, max_records)
        if max_records <= 0:
            return [], {"duplicate_drops": 0}
        saved: list[dict] = []
        persistence_candidates: list[dict[str, object]] = []
        for raw_record in records:
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
            identity_key = strong_identity_key(normalized)
            fallback_key = (
                _listing_fallback_identity_key(normalized) if not identity_key else ""
            )
            persistence_candidates.append(
                {
                    "source_url": raw_record.get("source_url")
                    or raw_record.get("url", url),
                    "data": normalized,
                    "raw_data": _raw_record_payload(raw_record),
                    "source_trace": _compact_dict(
                        {
                            "type": source_type,
                            **acquisition_trace,
                            "adapter": adapter_name,
                            "source": record_source_label,
                            "surface_used": surface,
                            "surface_requested": surface_requested,
                        }
                    ),
                    "identity_key": identity_key,
                    "fallback_key": fallback_key,
                }
            )

        deduped_candidates, stats = _dedupe_listing_persistence_candidates(
            persistence_candidates
        )
        for index, candidate in enumerate(deduped_candidates):
            if len(saved) >= max_records:
                break
            # Compute url_identity_key: SHA-256 hash of URL + identity_key
            # for database-level deduplication on resume/overlap.
            raw_identity = str(candidate.get("identity_key") or "").strip()
            if not raw_identity:
                raw_identity = str(candidate.get("fallback_key") or "").strip()
            url_identity_key: str | None = None
            if raw_identity:
                hash_input = f"{candidate['source_url']}|{raw_identity}"
                url_identity_key = hashlib.sha256(
                    hash_input.encode("utf-8", errors="replace")
                ).hexdigest()[:64]
            # Attach manifest_trace only to the first listing record to avoid
            # duplicating the same page-level payload across every record.
            record_source_trace = dict(candidate["source_trace"])
            if index == 0 and manifest_trace:
                record_source_trace["manifest_trace"] = manifest_trace
            db_record = CrawlRecord(
                run_id=run.id,
                source_url=str(candidate["source_url"]),
                url_identity_key=url_identity_key,
                data=dict(candidate["data"]),
                raw_data=dict(candidate["raw_data"]),
                discovered_data={},
                source_trace=record_source_trace,
                raw_html_path=raw_html_path,
            )
            session.add(db_record)
            saved.append(dict(candidate["data"]))
        return saved, stats
    except PipelineWriteError:
        raise
    except Exception as exc:
        raise PipelineWriteError(
            f"Failed to persist listing records for run {run.id}"
        ) from exc


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
    if await _effective_max_records(
        session,
        run,
        run.settings_view.max_records(),
    ) <= 0:
        _finalize_url_metrics(
            url_metrics,
            records=[],
            requested_fields=additional_fields,
        )
        return URLProcessingResult([], VERDICT_SCHEMA_MISS, url_metrics)
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
        llm_enabled=run.settings_view.llm_enabled(),
    )

    # Parse HTML once and reuse the soup object for all downstream extractors.
    # Offloaded to a thread to avoid blocking the async event loop.
    soup = await parse_html(html) if html else None
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
        soup=soup,
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
    if html and run.settings_view.llm_enabled():
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
            if not normalized:
                continue
            if _is_error_page_record(normalized):
                logger.debug(
                    "Skipping error-page record: title=%r",
                    normalized.get("title"),
                )
                continue
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
                        "discovered_fields": review_bucket or None,
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
        if _is_error_page_record(normalized):
            logger.debug(
                "Skipping error-page record: title=%r",
                normalized.get("title"),
            )
            normalized = {}
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
                "discovered_fields": review_bucket or None,
                "review_bucket": review_bucket or None,
                "requested_field_coverage": requested_coverage or None,
            }
        )
        if normalized:
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
    verdict = _compute_verdict(saved, surface, is_listing=False)

    winning_sources = []
    if saved:
        for field in saved[0].keys():
            src_map = source_trace.get("committed_fields", {}).get(
                field
            ) or source_trace.get("field_discovery", {}).get(field, {})
            if isinstance(src_map, dict):
                source = src_map.get("source")
                if source:
                    winning_sources.append(f"{field}:{source}")
                else:
                    sources = src_map.get("sources")
                    if isinstance(sources, list) and sources:
                        winning_sources.append(f"{field}:{sources[0]}")
                    elif isinstance(sources, str):
                        winning_sources.append(f"{field}:{sources}")
                    else:
                        winning_sources.append(f"{field}:unknown")
            else:
                winning_sources.append(f"{field}:unknown")
    if winning_sources:
        url_metrics["winning_sources"] = winning_sources[:5]

    if persist_logs:
        # Add critical telemetry revealing which extraction layer won arbitration
        source_summary = ", ".join(winning_sources[:5]) + (
            "..." if len(winning_sources) > 5 else ""
        )

        await _log(
            session,
            run.id,
            "info",
            f"[SAVE] Saved {len(saved)} detail records (verdict={verdict}). Sources: [{source_summary}]",
        )

    await session.flush()
    _finalize_url_metrics(
        url_metrics, records=saved, requested_fields=additional_fields
    )
    return URLProcessingResult(saved, verdict, url_metrics)


# ---------------------------------------------------------------------------
# Verdict helpers
# ---------------------------------------------------------------------------
# Note: These are imported from .verdict module at the top of the file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _log(session: AsyncSession, run_id: int, level: str, message: str) -> None:
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
    run.update_summary(**summary_patch)
    await session.flush()


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
    """Write failure state."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    result_summary = run.summary_dict()
    run.update_summary(
        error=error_msg,
        progress=result_summary.get("progress", 0),
        extraction_verdict=VERDICT_ERROR,
    )
    if run.status_value not in TERMINAL_STATUSES:
        update_run_status(run, CrawlStatus.FAILED)
    await session.commit()


def _reconcile_detail_candidate_values(
    candidates: dict[str, list[dict]],
    *,
    allowed_fields: set[str],
    url: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    from app.services.extract.field_decision import FieldDecisionEngine

    engine = FieldDecisionEngine(base_url=url)
    reconciled: dict[str, object] = {}
    reconciliation: dict[str, dict[str, object]] = {}

    for field_name in sorted(allowed_fields):
        rows = list(candidates.get(field_name) or [])
        if not rows:
            continue

        decision = engine.decide_from_rows(field_name, rows)

        if not decision.accepted:
            if decision.rejected_rows:
                reconciliation[field_name] = {
                    "status": "rejected",
                    "rejected": decision.rejected_rows[:6],
                }
            continue

        reconciled[field_name] = decision.value
        if decision.rejected_rows:
            reconciliation[field_name] = _compact_dict(
                {
                    "status": "accepted_with_rejections",
                    "accepted_source": decision.source,
                    "rejected": decision.rejected_rows[:6],
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
    acq: AcquisitionResult,
) -> str:
    diagnostics = acq.diagnostics if isinstance(acq.diagnostics, dict) else {}
    effective_surface = str(diagnostics.get("surface_effective") or "").strip().lower()
    if effective_surface in {
        "job_listing",
        "job_detail",
        "ecommerce_listing",
        "ecommerce_detail",
    }:
        return effective_surface
    return surface


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


def _refresh_record_commit_metadata(
    record: CrawlRecord,
    *,
    run: CrawlRun,
    field_name: str,
    value: object,
    source_label: str = "user_commit",
) -> None:
    refresh_record_commit_metadata(
        record,
        run=run,
        field_name=field_name,
        value=value,
        source_label=source_label,
    )


# Domain normalisation delegated to app.services.domain_utils.normalize_domain
_domain = normalize_domain
