from __future__ import annotations

import asyncio
import hashlib

from app.models.crawl import CrawlRun
from app.services.acquisition import AcquisitionResult
from app.services.crawl_metrics import finalize_url_metrics as _finalize_url_metrics
from app.services.domain_utils import normalize_domain
from app.services.extract import (
    FieldDecisionEngine,
    coerce_field_candidate_value,
    extract_candidates,
)
from app.services.schema_service import ResolvedSchema, resolve_schema, schema_trace_payload
from app.services.xpath_service import validate_xpath_candidate
from sqlalchemy.ext.asyncio import AsyncSession

from .field_normalization import (
    _merge_record_fields,
    _normalize_record_fields,
    _public_record_fields,
    _raw_record_payload,
    _requested_field_coverage,
)
from .llm_integration import (
    _apply_llm_suggestions_to_candidate_values,
    _build_llm_candidate_evidence,
    _build_llm_discovered_sources,
    _normalize_llm_cleanup_review,
    _select_llm_review_candidates,
    _split_llm_cleanup_payload,
)
from .record_persistence import (
    collect_winning_sources,
    resolve_record_writer,
)
from .runtime_helpers import (
    STAGE_ANALYZE,
    STAGE_SAVE,
    effective_max_records,
    is_error_page_record,
    log_event,
    set_stage,
)
from .review_helpers import _merge_review_bucket_entries
from .trace_builders import (
    _build_acquisition_trace,
    _build_field_discovery_summary,
    _build_manifest_trace,
    _build_review_bucket,
)
from .types import URLProcessingResult
from .utils import _compact_dict, parse_html
from .verdict import VERDICT_SCHEMA_MISS, compute_verdict

_domain = normalize_domain


async def process_json_response(
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
    record_writer=None,
) -> tuple[list[dict], str, dict]:
    from .listing_flow import save_listing_records
    from app.services.extract import extract_json_detail, extract_json_listing

    max_records = await effective_max_records(session, run, max_records)
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
            await log_event(
                session,
                run.id,
                "warning",
                "[ANALYZE] JSON response parsed but no records found",
            )
        return URLProcessingResult([], VERDICT_SCHEMA_MISS, url_metrics)

    if update_run_state:
        await set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await log_event(session, run.id, "info", "[ANALYZE] Normalizing JSON records")
    writer = resolve_record_writer(session, record_writer)

    if is_listing:
        saved, save_stats = await save_listing_records(
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
            record_writer=writer,
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
            normalized, discovered_fields = split_detail_output_fields(
                public_fields,
                allowed_fields=allowed_fields,
                surface=run.surface,
            )
            if not normalized or is_error_page_record(normalized):
                continue
            raw_data = _raw_record_payload(raw_record)
            requested_coverage = _requested_field_coverage(normalized, requested_fields)
            review_bucket = _build_review_bucket(
                discovered_fields,
                fallback_source=str(raw_record.get("_source") or "json_api"),
            )
            if await writer.persist_normalized_record(
                run_id=run.id,
                source_url=raw_record.get("source_url") or raw_record.get("url", url),
                data=normalized,
                raw_data=raw_data,
                review_bucket=review_bucket,
                requested_field_coverage=requested_coverage,
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
                                if acq.json_data is not None
                                else None,
                            },
                        )
                        or None,
                    }
                ),
                raw_html_path=acq.artifact_path,
            ):
                saved.append(normalized)

    if update_run_state:
        await set_stage(session, run, STAGE_SAVE)
    verdict = compute_verdict(saved, run.surface, is_listing=is_listing)
    if persist_logs:
        await log_event(
            session,
            run.id,
            "info",
            f"[SAVE] Saved {len(saved)} JSON records (verdict={verdict})",
        )
    await writer.flush()
    _finalize_url_metrics(url_metrics, records=saved, requested_fields=requested_fields)
    return URLProcessingResult(saved, verdict, url_metrics)


async def extract_detail(
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
    soup=None,
    update_run_state: bool = True,
    persist_logs: bool = True,
    record_writer=None,
) -> tuple[list[dict], str, dict]:
    if await effective_max_records(
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
    writer = resolve_record_writer(session, record_writer)
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

    soup = soup if soup is not None else (await parse_html(html) if html else None)
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
    candidate_values, reconciliation = reconcile_detail_candidate_values(
        candidates,
        allowed_fields=persisted_field_names,
        url=url,
    )
    semantic = (
        source_trace.get("semantic")
        if isinstance(source_trace.get("semantic"), dict)
        else {}
    )
    source_trace = {**_build_acquisition_trace(acq), **source_trace}
    detail_manifest_trace = await asyncio.to_thread(
        _build_manifest_trace,
        html=html,
        xhr_payloads=acq.network_payloads,
        adapter_records=adapter_records,
        semantic=semantic,
    )
    source_trace = _build_field_discovery_summary(
        source_trace,
        candidates,
        candidate_values,
        additional_fields,
        surface,
    )

    extracted_records = adapter_records if adapter_records else []
    llm_review_bucket: list[dict[str, object]] = []
    if html and run.settings_view.llm_enabled():
        source_trace, llm_review_bucket = await collect_detail_llm_suggestions(
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
            source_trace,
            source_trace.get("candidates") or candidates,
            candidate_values,
            additional_fields,
            surface,
        )

    saved: list[dict] = []
    if update_run_state:
        await set_stage(session, run, STAGE_ANALYZE)
    if persist_logs:
        await log_event(session, run.id, "info", "[ANALYZE] Normalizing detail record")

    if extracted_records:
        for raw_record in extracted_records[:1]:
            merged_record, merge_reconciliation = _merge_record_fields(
                raw_record,
                candidate_values,
                return_reconciliation=True,
            )
            combined_reconciliation = merge_detail_reconciliation(
                reconciliation,
                merge_reconciliation,
            )
            public_fields = _public_record_fields(merged_record)
            normalized, discovered_fields = split_detail_output_fields(
                public_fields,
                allowed_fields=persisted_field_names,
                surface=surface,
            )
            if not normalized or is_error_page_record(normalized):
                continue
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
            if await writer.persist_normalized_record(
                run_id=run.id,
                source_url=url,
                data=normalized,
                raw_data=raw_data,
                review_bucket=review_bucket,
                requested_field_coverage=requested_coverage,
                source_trace=_compact_dict(
                    {
                        **source_trace,
                        "type": "detail",
                        "adapter": adapter_name,
                        "schema_resolution": schema_trace_payload(resolved_schema),
                        "reconciliation": combined_reconciliation or None,
                        "requested_fields": additional_fields or None,
                        "requested_field_coverage": requested_coverage or None,
                        "manifest_trace": detail_manifest_trace or None,
                    }
                ),
                raw_html_path=acq.artifact_path,
            ):
                saved.append(normalized)
    elif candidate_values or source_trace.get("llm_cleanup_suggestions"):
        normalized, discovered_fields = split_detail_output_fields(
            candidate_values,
            allowed_fields=persisted_field_names,
            surface=surface,
        )
        if is_error_page_record(normalized):
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
        if normalized and await writer.persist_normalized_record(
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
        ):
            saved.append(normalized)

    if update_run_state:
        await set_stage(session, run, STAGE_SAVE)
    verdict = compute_verdict(saved, surface, is_listing=False)

    winning_sources = collect_winning_sources(source_trace, saved[0] if saved else None)
    if winning_sources:
        url_metrics["winning_sources"] = winning_sources[:5]
    if persist_logs:
        source_summary = ", ".join(winning_sources[:5]) + ("..." if len(winning_sources) > 5 else "")
        await log_event(
            session,
            run.id,
            "info",
            f"[SAVE] Saved {len(saved)} detail records (verdict={verdict}). Sources: [{source_summary}]",
        )

    await writer.flush()
    _finalize_url_metrics(url_metrics, records=saved, requested_fields=additional_fields)
    return URLProcessingResult(saved, verdict, url_metrics)


def reconcile_detail_candidate_values(
    candidates: dict[str, list[dict]],
    *,
    allowed_fields: set[str],
    url: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
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


def merge_detail_reconciliation(
    base: dict[str, dict[str, object]],
    merge: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    if not merge:
        return dict(base)
    combined = dict(base)
    for field_name, merge_entry in merge.items():
        existing_entry = combined.get(field_name)
        if not isinstance(existing_entry, dict):
            combined[field_name] = {"merge": merge_entry}
            continue
        combined[field_name] = {**existing_entry, "merge": merge_entry}
    return combined


def split_detail_output_fields(
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


async def collect_detail_llm_suggestions(
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
    from . import core as pipeline_core

    trace_candidates = source_trace.setdefault("candidates", {})
    llm_cleanup_suggestions: dict[str, dict] = source_trace.get("llm_cleanup_suggestions", {})
    llm_cleanup_status: dict[str, object] = dict(source_trace.get("llm_cleanup_status") or {})
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
        await log_event(
            session,
            run.id,
            "info",
            f"[ANALYZE] LLM XPath discovery for {len(missing_fields)} missing detail fields",
        )
        xpath_rows, xpath_error = await pipeline_core.discover_xpath_candidates(
            session,
            run_id=run.id,
            domain=domain,
            url=url,
            html_text=html,
            missing_fields=missing_fields,
            existing_values=preview_record,
        )
        if xpath_error:
            await log_event(session, run.id, "warning", f"[LLM] XPath discovery failed: {xpath_error}")
            llm_cleanup_status = {
                **llm_cleanup_status,
                "status": "xpath_error",
                "message": xpath_error,
                "xpath_error": xpath_error,
            }
        elif not xpath_rows:
            await log_event(
                session,
                run.id,
                "warning",
                "[ANALYZE] LLM XPath discovery returned no usable suggestions",
            )
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
        matched_value = coerce_field_candidate_value(
            field_name,
            validation.get("matched_value"),
            base_url=url,
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
        if field_name not in missing_fields and field_name not in review_candidate_evidence
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

    await log_event(
        session,
        run.id,
        "info",
        f"[ANALYZE] LLM cleanup review for {len(review_candidate_evidence)} candidate field groups",
    )
    llm_reviews, llm_error = await pipeline_core.review_field_candidates(
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
        await log_event(session, run.id, "warning", f"[LLM] Cleanup review failed: {llm_error}")
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
        await log_event(
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


def normalize_detail_candidate_values(
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
        image_parts = [part.strip() for part in additional_images.split(",") if part.strip()]
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
