from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.models.crawl import CrawlRun
from app.services.acquisition import AcquisitionResult
from app.services.crawl_metrics import finalize_url_metrics as _finalize_url_metrics
from app.services.exceptions import PipelineWriteError
from app.services.extract import extract_listing_records, listing_set_quality, strong_identity_key
from app.services.runtime_metrics import incr
from sqlalchemy.ext.asyncio import AsyncSession

from .field_normalization import (
    _normalize_record_fields,
    _surface_public_record_fields,
    _surface_raw_record_payload,
)
from .listing_helpers import (
    _listing_acquisition_blocked,
    _looks_like_loading_listing_shell,
    _sanitize_listing_record_fields,
)
from .record_persistence import (
    ListingPersistenceCandidate,
    dedupe_listing_persistence_candidates,
    listing_fallback_identity_key,
    resolve_record_writer,
)
from .runtime_helpers import (
    STAGE_ANALYZE,
    STAGE_SAVE,
    effective_max_records,
    log_event,
    log_for_pytest,
    set_stage,
)
from .trace_builders import _build_acquisition_trace, _build_manifest_trace
from .types import URLProcessingResult
from .utils import _compact_dict
from .verdict import (
    VERDICT_BLOCKED,
    VERDICT_LISTING_FAILED,
    VERDICT_PARTIAL,
    VERDICT_SUCCESS,
    compute_verdict,
)

if TYPE_CHECKING:
    from .types import PipelineContext

logger = logging.getLogger(__name__)


def listing_quality_flags(
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


async def save_listing_records(
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
    record_writer=None,
) -> tuple[list[dict], dict[str, int]]:
    try:
        max_records = await effective_max_records(session, run, max_records)
        if max_records <= 0:
            return [], {"duplicate_drops": 0}

        writer = resolve_record_writer(session, record_writer)
        saved: list[dict] = []
        persistence_candidates: list[ListingPersistenceCandidate] = []
        for raw_record in records:
            record_source_label = (
                str(raw_record.get("_source") or source_label).strip() or source_label
            )
            public_record = _sanitize_listing_record_fields(
                _surface_public_record_fields(raw_record, surface=surface),
                surface=surface,
                page_base_url=url,
            )
            normalized = _normalize_record_fields(public_record, surface=surface)
            if not normalized:
                continue
            identity_key = strong_identity_key(normalized)
            fallback_key = (
                listing_fallback_identity_key(normalized) if not identity_key else ""
            )
            persistence_candidates.append(
                ListingPersistenceCandidate(
                    source_url=str(raw_record.get("source_url") or raw_record.get("url", url)),
                    data=normalized,
                    raw_data=_surface_raw_record_payload(raw_record, surface=surface),
                    source_trace=_compact_dict(
                        {
                            "type": source_type,
                            **acquisition_trace,
                            "adapter": adapter_name,
                            "source": record_source_label,
                            "surface_used": surface,
                        }
                    ),
                    identity_key=identity_key,
                    fallback_key=fallback_key,
                )
            )

        deduped_candidates, stats = dedupe_listing_persistence_candidates(
            persistence_candidates,
            on_duplicate=lambda collision_key: (
                incr("listing_duplicate_drops_total"),
                log_for_pytest(
                    logging.DEBUG,
                    "Dropping duplicate listing record before persistence for identity key %s",
                    collision_key,
                ),
            ),
        )
        for index, candidate in enumerate(deduped_candidates):
            if len(saved) >= max_records:
                break
            if await writer.persist_listing_candidate(
                run_id=run.id,
                candidate=candidate,
                index=index,
                manifest_trace=manifest_trace,
                raw_html_path=raw_html_path,
            ):
                saved.append(dict(candidate.data))
        return saved, stats
    except PipelineWriteError:
        raise
    except Exception as exc:
        raise PipelineWriteError(
            f"Failed to persist listing records for run {run.id}"
        ) from exc


async def extract_listing(
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
    soup=None,
    update_run_state: bool = True,
    persist_logs: bool = True,
    record_writer=None,
) -> URLProcessingResult:
    adapter_name = adapter_result.adapter_name if adapter_result else None
    url_metrics["listing_surface_used"] = surface
    resolved_writer = resolve_record_writer(session, record_writer)

    extracted_records = await asyncio.to_thread(
        extract_listing_records,
        html=html,
        surface=surface,
        target_fields=set(additional_fields),
        page_url=url,
        max_records=max_records,
        xhr_payloads=acq.network_payloads,
        adapter_records=adapter_records,
        soup=soup,
    )
    source_label = "listing_extractor"
    if not extracted_records and adapter_records:
        extracted_records = adapter_records
        source_label = "adapter"

    if not extracted_records:
        if _listing_acquisition_blocked(acq, html):
            if persist_logs:
                await log_event(
                    session,
                    run.id,
                    "warning",
                    "[ANALYZE] Listing extraction found 0 records because the acquired page was blocked",
                )
            return URLProcessingResult([], VERDICT_BLOCKED, url_metrics)
        if _looks_like_loading_listing_shell(html, surface=surface):
            if persist_logs:
                await log_event(
                    session,
                    run.id,
                    "warning",
                    "[ANALYZE] Listing extraction found 0 records on a loading shell; skipping page fallback so browser retry/failure is explicit",
                )
            return URLProcessingResult([], VERDICT_LISTING_FAILED, url_metrics)
        if surface == "job_listing":
            if persist_logs:
                await log_event(
                    session,
                    run.id,
                    "warning",
                    "[ANALYZE] Job listing extraction found 0 records; skipping page fallback so browser retry/failure is explicit",
                )
            return URLProcessingResult([], VERDICT_LISTING_FAILED, url_metrics)
        if persist_logs:
            await log_event(
                session,
                run.id,
                "warning",
                "[ANALYZE] Listing extraction found 0 records — marking as listing_detection_failed",
            )
        return URLProcessingResult([], VERDICT_LISTING_FAILED, url_metrics)

    if update_run_state:
        await set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await log_event(session, run.id, "info", "[ANALYZE] Normalizing listing records")
    manifest_trace = await asyncio.to_thread(
        _build_manifest_trace,
        html=html,
        xhr_payloads=acq.network_payloads,
        adapter_records=adapter_records,
    )
    saved, save_stats = await save_listing_records(
        session=session,
        run=run,
        records=extracted_records,
        source_type="listing",
        source_label=source_label,
        url=url,
        surface=surface,
        max_records=max_records,
        raw_html_path=acq.artifact_path,
        acquisition_trace=_build_acquisition_trace(acq),
        manifest_trace=manifest_trace,
        adapter_name=adapter_name,
        record_writer=resolved_writer,
    )
    duplicate_drops = int(save_stats.get("duplicate_drops", 0) or 0)
    if duplicate_drops:
        url_metrics["duplicate_listing_drops"] = duplicate_drops

    if update_run_state:
        await set_stage(session, run, STAGE_SAVE)
    verdict = compute_verdict(saved, surface, is_listing=True)
    url_metrics["listing_quality"] = listing_set_quality(saved, surface=surface)
    quality_flags = listing_quality_flags(
        saved,
        surface=surface,
        network_payload_count=len(acq.network_payloads or []),
    )
    if quality_flags:
        url_metrics["listing_quality_flags"] = sorted(quality_flags)
    if verdict == VERDICT_SUCCESS and quality_flags:
        verdict = VERDICT_PARTIAL
        if persist_logs:
            await log_event(
                session,
                run.id,
                "warning",
                "[SAVE] Listing quality gates downgraded verdict to partial: "
                + ", ".join(sorted(quality_flags)),
            )
    if persist_logs:
        await log_event(
            session,
            run.id,
            "info",
            f"[SAVE] Saved {len(saved)} listing records (verdict={verdict})",
        )
    if resolved_writer is not None:
        await resolved_writer.flush()

    _finalize_url_metrics(url_metrics, records=saved, requested_fields=additional_fields)
    return URLProcessingResult(saved, verdict, url_metrics)


async def extract_listing_from_context(ctx: "PipelineContext") -> URLProcessingResult:
    acq = ctx.acquisition_result
    if acq is None:
        raise ValueError(
            f"Missing acquisition_result for listing extraction: {ctx.url}"
        )
    return await extract_listing(
        ctx.session,
        ctx.run,
        ctx.url,
        acq.html,
        acq,
        ctx.adapter_result,
        ctx.adapter_records,
        ctx.additional_fields,
        ctx.surface,
        ctx.config.max_records,
        ctx.url_metrics,
        soup=ctx.soup,
        update_run_state=ctx.update_run_state,
        persist_logs=ctx.persist_logs,
        record_writer=ctx.record_writer,
    )
