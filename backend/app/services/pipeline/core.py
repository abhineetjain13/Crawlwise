from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

from app.models.crawl import CrawlRun
from app.services.acquisition.acquirer import AcquisitionRequest
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.acquisition.acquirer import PageEvidence
from app.services.acquisition.acquirer import acquire as _acquire
from app.services.acquisition.host_protection_memory import note_host_hard_block
from app.services.acquisition_plan import AcquisitionPlan
from app.services.adapters.base import AdapterResult
from app.services.adapters.registry import run_adapter, try_blocked_adapter_recovery
from app.services.acquisition.browser_runtime import (
    build_failed_browser_diagnostics,
    real_chrome_browser_available,
)
from app.services.domain_memory_service import (
    compose_runtime_selector_rules,
    load_domain_selector_rules,
)
from app.services.db_utils import mapping_or_empty
from app.services.domain_utils import normalize_domain
from app.services.domain_run_profile_service import (
    apply_saved_acquisition_contract_for_url,
    record_acquisition_contract_outcome,
)
from app.services.field_policy import repair_target_fields_for_surface
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.detail_extractor import (
    detail_record_rejection_reason,
    infer_detail_failure_reason,
)
from app.services.field_value_core import validate_record_for_surface
from app.services.llm_config_service import resolve_run_config
from app.services.llm_runtime import extract_records_directly as extract_records_directly_with_llm
from app.services.pipeline.direct_record_fallback import (
    apply_direct_record_llm_fallback as apply_direct_record_llm_fallback_impl,
    apply_llm_fallback,
)
from app.services.platform_policy import detect_platform_family
from app.services.publish import (
    VERDICT_BLOCKED,
    VERDICT_EMPTY,
    VERDICT_LISTING_FAILED,
    build_acquisition_profile,
    build_url_metrics,
    compute_verdict,
    finalize_url_metrics,
)
from app.services.robots_policy import (
    ROBOTS_FETCH_FAILURE,
    ROBOTS_MISSING,
    check_url_crawlability,
)
from app.services.selector_self_heal import apply_selector_self_heal
from app.services.extraction_runtime import extract_records
from sqlalchemy.ext.asyncio import AsyncSession

from .extraction_retry_decision import (
    annotate_field_repair as _annotate_field_repair,
    empty_extraction_browser_retry_decision as _empty_extraction_browser_retry_decision,
    low_quality_extraction_browser_retry_decision as _low_quality_extraction_browser_retry_decision,
)
from .persistence import persist_acquisition_artifacts, persist_extracted_records
from .runtime_helpers import (
    STAGE_ACQUIRE,
    STAGE_EXTRACT,
    STAGE_NORMALIZE,
    STAGE_PERSIST,
    browser_attempted as _browser_attempted,
    browser_launch_log_message as _browser_launch_log_message,
    browser_outcome as _browser_outcome,
    browser_result_is_extractable as _browser_result_is_extractable,
    effective_blocked as _effective_blocked,
    mark_run_failed as _mark_run_failed,
    merge_browser_diagnostics as _merge_browser_diagnostics,
    record_detail_expansion_extraction_outcome as _record_detail_expansion_extraction_outcome,
    screenshot_required as _screenshot_required,
    suppress_empty_downstream_record_logs as _suppress_empty_downstream_record_logs,
    log_event,
    set_stage,
)
from .types import URLProcessingConfig, URLProcessingResult

logger = logging.getLogger(__name__)
__all__ = [
    "STAGE_ACQUIRE",
    "STAGE_EXTRACT",
    "STAGE_NORMALIZE",
    "STAGE_PERSIST",
    "process_single_url",
]

acquire = _acquire
mark_run_failed = _mark_run_failed


@dataclass(slots=True)
class _URLProcessingContext:
    session: AsyncSession
    run: CrawlRun
    url: str
    config: URLProcessingConfig
    url_timeout_seconds: float
    started_at_monotonic: float
    requested_fields: list[str] = field(default_factory=list)
    surface: str = ""


@dataclass(slots=True)
class _FetchedURLStage:
    context: _URLProcessingContext
    acquisition_result: AcquisitionResult
    url_metrics: dict[str, object]


@dataclass(slots=True)
class _ExtractedURLStage:
    fetched: _FetchedURLStage
    records: list[dict[str, object]]
def _resolve_run_param(
    plan_value: object | None,
    config_value: object | None,
    default_value: int,
    *,
    min_value: int = 1,
) -> int:
    for candidate in (plan_value, config_value):
        if candidate is None:
            continue
        try:
            resolved = int(float(candidate) if isinstance(candidate, (int, float)) else float(str(candidate)))
        except (TypeError, ValueError):
            continue
        if resolved >= int(min_value):
            return resolved
    return int(default_value)
def _resolved_url_processing_config(
    config: URLProcessingConfig | None,
    *,
    surface: str,
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
        plan = config.resolved_acquisition_plan(surface=surface)
        resolved_proxy_list = list(plan.proxy_list or config.proxy_list or proxy_list or [])
        resolved_traversal_mode = (
            plan.traversal_mode
            if plan.traversal_mode is not None
            else config.traversal_mode
            if config.traversal_mode is not None
            else traversal_mode
        )
        safety_iteration_cap = int(crawler_runtime_settings.traversal_max_iterations_cap)
        resolved_max_pages = safety_iteration_cap
        resolved_max_scrolls = safety_iteration_cap
        resolved_max_records = _resolve_run_param(
            plan.max_records,
            config.max_records,
            max_records,
        )
        resolved_sleep_ms = _resolve_run_param(
            plan.sleep_ms,
            config.sleep_ms,
            sleep_ms,
            min_value=0,
        )
        return URLProcessingConfig.from_acquisition_plan(
            AcquisitionPlan(
                surface=surface,
                proxy_list=tuple(resolved_proxy_list),
                traversal_mode=resolved_traversal_mode,
                max_pages=resolved_max_pages,
                max_scrolls=resolved_max_scrolls,
                max_records=resolved_max_records,
                sleep_ms=resolved_sleep_ms,
            ),
            update_run_state=config.update_run_state,
            persist_logs=config.persist_logs,
            prefetch_only=config.prefetch_only,
            record_writer=config.record_writer,
        )
    return URLProcessingConfig.from_acquisition_plan(
        AcquisitionPlan(
            surface=surface,
            proxy_list=tuple(list(proxy_list or [])),
            traversal_mode=traversal_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            max_records=max_records,
            sleep_ms=sleep_ms,
        ),
        update_run_state=update_run_state,
        persist_logs=persist_logs,
    )


async def process_single_url(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    config: URLProcessingConfig | None = None,
    *,
    proxy_list: list[str] | None = None,
    traversal_mode: str | None = None,
    max_pages: int | None = None,
    max_scrolls: int | None = None,
    max_records: int | None = None,
    sleep_ms: int | None = None,
    checkpoint=None,
    update_run_state: bool = True,
    persist_logs: bool = True,
    prefetched_acquisition: AcquisitionResult | None = None,
) -> URLProcessingResult:
    del checkpoint
    settings_view = run.settings_view
    url_timeout_seconds = (
        settings_view.url_timeout_seconds()
        if settings_view.get("url_timeout_seconds") not in (None, "")
        else crawler_runtime_settings.default_url_process_timeout_seconds()
    )
    context = _URLProcessingContext(
        session=session,
        run=run,
        url=url,
        config=_resolved_url_processing_config(
            config,
            surface=run.surface,
            proxy_list=proxy_list if proxy_list is not None else settings_view.proxy_list(),
            traversal_mode=traversal_mode if traversal_mode is not None else settings_view.traversal_mode(),
            max_pages=max_pages if max_pages is not None else settings_view.max_pages(),
            max_scrolls=max_scrolls if max_scrolls is not None else settings_view.max_scrolls(),
            max_records=max_records if max_records is not None else settings_view.max_records(),
            sleep_ms=sleep_ms if sleep_ms is not None else settings_view.sleep_ms(),
            update_run_state=update_run_state,
            persist_logs=persist_logs,
        ),
        url_timeout_seconds=float(url_timeout_seconds),
        started_at_monotonic=time.monotonic(),
        requested_fields=list(run.requested_fields or []),
        surface=run.surface,
    )
    await _enter_stage(context, STAGE_ACQUIRE)
    robots_result = await _run_robots_gate(context)
    if robots_result is not None:
        return robots_result
    fetched = await _run_acquisition_stage(
        context,
        prefetched_acquisition=prefetched_acquisition,
    )
    if context.config.prefetch_only:
        return _build_prefetch_only_result(context, fetched)
    await _enter_stage(context, STAGE_EXTRACT)
    extracted = await _run_extraction_stage(context, fetched)
    extracted = await _run_normalization_stage(context, extracted)
    return await _run_persistence_stage(context, extracted)

async def _enter_stage(
    context: _URLProcessingContext,
    stage_name: str,
) -> None:
    if context.config.update_run_state:
        await set_stage(
            context.session,
            context.run,
            stage_name,
            current_url=context.url,
        )
        await context.session.commit()

async def _log_pipeline_event(
    context: _URLProcessingContext,
    level: str,
    message: str,
    *,
    commit: bool = True,
) -> None:
    if not context.config.persist_logs:
        return
    await log_event(context.session, context.run.id, level, message)
    if commit:
        await context.session.commit()

async def _run_robots_gate(
    context: _URLProcessingContext,
) -> URLProcessingResult | None:
    if context.run.settings_view.respect_robots_txt():
        robots_result = await check_url_crawlability(context.url)
        if not robots_result.allowed:
            await _log_pipeline_event(
                context,
                "warning",
                f"[ROBOTS] Blocked by robots.txt: {context.url}",
            )
            return URLProcessingResult(
                records=[],
                verdict=VERDICT_BLOCKED,
                url_metrics=finalize_url_metrics(
                    {
                        "blocked": True,
                        "final_url": context.url,
                        "method": "",
                        "requested_fields": list(context.requested_fields),
                        "robots": {
                            "allowed": False,
                            "outcome": robots_result.outcome,
                            "robots_url": robots_result.robots_url,
                        },
                    },
                    record_count=0,
                ),
            )
        if robots_result.outcome == ROBOTS_MISSING:
            await _log_pipeline_event(
                context,
                "info",
                f"[ROBOTS] No robots.txt found for {context.url}; continuing",
            )
        if robots_result.outcome == ROBOTS_FETCH_FAILURE:
            await _log_pipeline_event(
                context,
                "warning",
                f"[ROBOTS] robots.txt check failed for {context.url}; continuing",
            )
        return None
    return None

async def _build_acquisition_request(context: _URLProcessingContext) -> AcquisitionRequest:
    plan = context.config.resolved_acquisition_plan(surface=context.surface)
    acquisition_profile = dict(build_acquisition_profile(context.run.settings_view))
    acquisition_profile = await apply_saved_acquisition_contract_for_url(
        context.session,
        url=context.url,
        surface=context.surface,
        settings_view=context.run.settings_view,
        acquisition_profile=acquisition_profile,
    )
    acquisition_profile.setdefault(
        "capture_page_markdown",
        bool(context.run.settings_view.llm_enabled()),
    )
    return AcquisitionRequest(
        run_id=context.run.id,
        url=context.url,
        plan=plan,
        requested_fields=list(context.requested_fields),
        requested_field_selectors={},
        acquisition_profile=acquisition_profile,
        on_event=_pipeline_acquisition_event_logger(context),
    )


def _pipeline_acquisition_event_logger(
    context: _URLProcessingContext,
):
    async def _log(level: str, message: str) -> None:
        await _log_pipeline_event(context, level, message)

    return _log

async def _run_acquisition_stage(
    context: _URLProcessingContext,
    *,
    prefetched_acquisition: AcquisitionResult | None,
) -> _FetchedURLStage:
    acquisition_request = await _build_acquisition_request(context)
    acquisition_result = prefetched_acquisition or await acquire(acquisition_request)
    method = getattr(acquisition_result, "method", "unknown")
    if method == "browser":
        if getattr(acquisition_request, "on_event", None) is None:
            diagnostics = mapping_or_empty(
                getattr(acquisition_result, "browser_diagnostics", {})
            )
            timings = mapping_or_empty(diagnostics.get("phase_timings_ms", {}))
            load_ms = timings.get("navigation", 0) or timings.get("total", 0)
            await _log_pipeline_event(
                context,
                "info",
                _browser_launch_log_message(acquisition_result),
            )
            await _log_pipeline_event(
                context,
                "info",
                f"Page loaded in {load_ms}ms",
            )
    else:
        status = getattr(acquisition_result, "status_code", 0)
        await _log_pipeline_event(
            context,
            "info",
            f"Acquired payload via {method} (status={status})",
        )

    browser_attempted = bool(
        getattr(acquisition_result, "browser_diagnostics", {}) and
        getattr(acquisition_result, "browser_diagnostics", {}).get("browser_attempted")
    )
    if _effective_blocked(acquisition_result) and not browser_attempted:
        await _log_pipeline_event(
            context,
            "warning",
            f"Acquisition detected rate limiting or bot protection for {context.url}",
        )

    return _FetchedURLStage(
        context=context,
        acquisition_result=acquisition_result,
        url_metrics=build_url_metrics(
            acquisition_result,
            requested_fields=list(context.requested_fields),
        ),
    )

def _build_prefetch_only_result(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
) -> URLProcessingResult:
    verdict = compute_verdict(
        is_listing="listing" in context.surface,
        blocked=_effective_blocked(fetched.acquisition_result),
        record_count=1 if fetched.acquisition_result.html else 0,
    )
    return URLProcessingResult(
        records=[],
        verdict=verdict,
        url_metrics=finalize_url_metrics(fetched.url_metrics, record_count=0),
    )

async def _run_extraction_stage(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
) -> _ExtractedURLStage:
    acquisition_result = fetched.acquisition_result
    records, selector_rules = await _extract_records_for_acquisition(
        context,
        fetched,
    )
    _record_detail_expansion_extraction_outcome(
        acquisition_result,
        records,
        requested_fields=list(context.requested_fields),
    )
    records, selector_rules = await _retry_empty_extraction_with_browser(
        context,
        fetched,
        records=records,
        selector_rules=selector_rules,
    )
    records, selector_rules = await _retry_low_quality_extraction_with_browser(
        context,
        fetched,
        records=records,
        selector_rules=selector_rules,
    )
    acquisition_result = fetched.acquisition_result
    records, selector_rules = await _apply_extraction_post_processing(
        context,
        acquisition_result=acquisition_result,
        records=records,
        selector_rules=selector_rules,
    )
    records, rejection_reason = _apply_detail_rejection_guard(
        context,
        fetched,
        records=records,
        selector_rules=selector_rules,
    )
    retry_stage = await _retry_detail_challenge_shell_with_real_chrome(
        context,
        fetched,
        rejection_reason=rejection_reason,
    )
    if retry_stage is not None:
        return retry_stage
    await _log_extraction_outcome(context, acquisition_result, records)
    if rejection_reason:
        await _log_pipeline_event(
            context,
            "warning",
            f"Rejected detail extraction for {context.url}: {rejection_reason}",
        )
    return _ExtractedURLStage(fetched=fetched, records=records)


async def _retry_detail_challenge_shell_with_real_chrome(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    rejection_reason: str | None,
) -> _ExtractedURLStage | None:
    if rejection_reason != "challenge_shell":
        return None
    if str(context.surface or "").strip().lower() != "ecommerce_detail":
        return None
    acquisition_result = fetched.acquisition_result
    diagnostics = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    browser_engine = str(diagnostics.get("browser_engine") or "").strip().lower()
    if getattr(acquisition_result, "method", "") != "browser" or browser_engine != "patchright":
        return None
    if not real_chrome_browser_available():
        return None

    await note_host_hard_block(
        acquisition_result.final_url or context.url,
        method="browser:patchright",
        vendor=None,
        status_code=getattr(acquisition_result, "status_code", None),
        proxy_used=False,
    )
    await _log_pipeline_event(
        context,
        "info",
        f"Patchright detail rejected as challenge_shell; retrying real Chrome for {context.url}",
    )

    retry_result = await _acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="post_extraction_challenge_shell",
        forced_browser_engine="real_chrome",
    )
    _merge_browser_diagnostics(
        retry_result,
        {"retry_reason": "post_extraction_challenge_shell"},
    )
    fetched.acquisition_result = retry_result
    retry_records, retry_selector_rules = await _extract_records_for_acquisition(
        context,
        fetched,
    )
    retry_records, retry_selector_rules = await _apply_extraction_post_processing(
        context,
        acquisition_result=retry_result,
        records=retry_records,
        selector_rules=retry_selector_rules,
    )
    retry_records, retry_rejection_reason = _apply_detail_rejection_guard(
        context,
        fetched,
        records=retry_records,
        selector_rules=retry_selector_rules,
    )
    if retry_rejection_reason:
        await _log_pipeline_event(
            context,
            "warning",
            f"Rejected detail extraction for {context.url}: {retry_rejection_reason}",
        )
    else:
        await _log_extraction_outcome(context, retry_result, retry_records)
    return _ExtractedURLStage(fetched=fetched, records=retry_records)


def _challenge_shell_reason(acquisition_result: AcquisitionResult) -> str | None:
    return PageEvidence.from_acquisition_result(acquisition_result).challenge_shell_reason


def _apply_detail_rejection_guard(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    records: list[dict[str, object]],
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], str | None]:
    if "detail" not in context.surface:
        return records, None
    acquisition_result = fetched.acquisition_result
    rejection_reason = _challenge_shell_reason(acquisition_result)
    if rejection_reason is None:
        for record in records:
            if not isinstance(record, dict):
                continue
            rejection_reason = detail_record_rejection_reason(
                dict(record),
                page_url=acquisition_result.final_url,
                requested_page_url=context.url,
            )
            if rejection_reason:
                break
    if rejection_reason is None and not records:
        rejection_reason = infer_detail_failure_reason(
            acquisition_result.html,
            acquisition_result.final_url,
            context.surface,
            list(context.requested_fields),
            requested_page_url=context.url,
            adapter_records=acquisition_result.adapter_records,
            network_payloads=acquisition_result.network_payloads,
            selector_rules=selector_rules,
            extraction_runtime_snapshot=context.run.settings_view.extraction_runtime_snapshot(),
        )
    if not rejection_reason:
        return records, None
    _merge_browser_diagnostics(
        acquisition_result,
        {"failure_reason": rejection_reason},
    )
    if rejection_reason == "challenge_shell":
        acquisition_result.blocked = True
        fetched.url_metrics = build_url_metrics(
            acquisition_result,
            requested_fields=list(context.requested_fields),
        )
        fetched.url_metrics["blocked"] = True
    fetched.url_metrics["failure_reason"] = rejection_reason
    return [], rejection_reason

async def _run_normalization_stage(
    context: _URLProcessingContext,
    extracted: _ExtractedURLStage,
) -> _ExtractedURLStage:
    await _enter_stage(context, STAGE_NORMALIZE)
    acquisition_result = extracted.fetched.acquisition_result
    normalized_records: list[dict[str, object]] = []
    for index, record in enumerate(extracted.records, start=1):
        normalized_record, validation_errors = validate_record_for_surface(
            dict(record),
            context.surface,
            requested_fields=context.requested_fields,
        )
        normalized_records.append(normalized_record)
        if validation_errors:
            await _log_pipeline_event(
                context,
                "warning",
                "Schema validation cleaned record "
                f"{index} for {context.url}: {'; '.join(validation_errors)}",
            )
    if not _suppress_empty_downstream_record_logs(
        acquisition_result,
        normalized_records,
    ):
        await _log_pipeline_event(
            context,
            "info",
            f"Normalized {len(normalized_records)} record(s) for persistence",
        )
    return _ExtractedURLStage(fetched=extracted.fetched, records=normalized_records)

async def _log_extraction_outcome(
    context: _URLProcessingContext,
    acquisition_result,
    records: list[dict[str, object]],
) -> None:
    adapter_name = str(getattr(acquisition_result, "adapter_name", "") or "").strip()
    extraction_label = (
        f"{adapter_name} adapter" if adapter_name else "generic extraction path"
    )
    if records:
        await _log_pipeline_event(
            context,
            "info",
            f"Extracted {len(records)} records using {extraction_label}",
        )
        return
    await _log_pipeline_event(
        context,
        "warning",
        f"Extraction yielded 0 records ({extraction_label})",
    )

async def _retry_empty_extraction_with_browser(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    records: list[dict[str, object]],
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    acquisition_result = fetched.acquisition_result
    retry_decision = _empty_extraction_browser_retry_decision(
        acquisition_result,
        records,
        surface=context.surface,
        requested_fields=list(context.requested_fields),
        selector_rules=selector_rules,
    )
    if not retry_decision["should_retry"]:
        return records, selector_rules
    await _log_extraction_outcome(context, acquisition_result, records)
    await _log_pipeline_event(context, "info", f"No records via {acquisition_result.method}; retrying browser render for {context.url}")
    browser_result = await _acquire_browser_retry_result(context, fetched, retry_reason="empty_extraction")
    fetched.acquisition_result = browser_result
    return await _extract_records_for_acquisition(context, fetched)
async def _retry_low_quality_extraction_with_browser(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    records: list[dict[str, object]],
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    acquisition_result = fetched.acquisition_result
    if "detail" not in context.surface:
        return records, selector_rules
    if getattr(acquisition_result, "method", "") == "browser":
        return records, selector_rules
    if not records or _effective_blocked(acquisition_result):
        return records, selector_rules
    retry_decision = _low_quality_extraction_browser_retry_decision(
        acquisition_result,
        records,
        surface=context.surface,
        requested_fields=list(context.requested_fields),
    )
    if not retry_decision["should_retry"]:
        return records, selector_rules
    raw_missing_fields = retry_decision.get("missing_fields")
    missing_field_values = raw_missing_fields if isinstance(raw_missing_fields, list) else []
    missing_fields = [
        str(field_name)
        for field_name in missing_field_values
        if str(field_name).strip()
    ]
    if not missing_fields:
        return records, selector_rules
    remaining_budget_seconds = _remaining_url_budget_seconds(context)
    min_remaining_seconds = float(
        crawler_runtime_settings.low_quality_browser_retry_min_remaining_seconds
    )
    if remaining_budget_seconds < min_remaining_seconds:
        await _log_pipeline_event(
            context,
            "info",
            "Skipping low-quality browser retry for "
            f"{context.url}: remaining URL budget {remaining_budget_seconds:.1f}s"
            f" < required {min_remaining_seconds:.1f}s",
        )
        return records, selector_rules
    await _log_pipeline_event(
        context,
        "info",
        "Detail record missing high-value fields "
        f"{', '.join(missing_fields)} via {acquisition_result.method}; retrying browser render for {context.url}",
    )
    browser_result = await _acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="low_quality_extraction",
    )
    fetched.acquisition_result = browser_result
    return await _extract_records_for_acquisition(context, fetched)
def _remaining_url_budget_seconds(context: _URLProcessingContext) -> float:
    return max(0.0, float(context.url_timeout_seconds) - max(0.0, time.monotonic() - float(context.started_at_monotonic)))
async def _acquire_browser_retry_result(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    retry_reason: str,
    forced_browser_engine: str | None = None,
):
    acquisition_result = fetched.acquisition_result
    profile_updates: dict[str, object] = {
        "prefer_browser": True,
        "retry_reason": retry_reason,
    }
    if forced_browser_engine:
        profile_updates["forced_browser_engine"] = forced_browser_engine
    retry_request = (await _build_acquisition_request(context)).with_profile_updates(
        **profile_updates
    )
    try:
        return await acquire(retry_request)
    except (RuntimeError, ValueError, TypeError, OSError) as exc:
        _merge_browser_diagnostics(
            acquisition_result,
            build_failed_browser_diagnostics(browser_reason=f"{retry_reason.replace('_', '-')} retry", exc=exc),
        )
        fetched.url_metrics = build_url_metrics(acquisition_result, requested_fields=list(context.requested_fields))
        await _log_pipeline_event(context, "warning", f"Browser retry failed for {context.url}: {type(exc).__name__}: {exc}")
        raise

async def _apply_extraction_post_processing(
    context: _URLProcessingContext,
    *,
    acquisition_result,
    records: list[dict[str, object]],
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if "detail" in context.surface and records:
        records, selector_rules = await apply_selector_self_heal(
            context.session,
            run=context.run,
            page_url=acquisition_result.final_url,
            html=acquisition_result.html,
            records=records,
            adapter_records=acquisition_result.adapter_records,
            network_payloads=acquisition_result.network_payloads,
            selector_rules=selector_rules,
        )
    if not _browser_result_is_extractable(acquisition_result):
        return records, selector_rules
    if not context.run.settings_view.llm_enabled():
        _annotate_field_repair(
            records,
            surface=context.surface,
            requested_fields=list(context.requested_fields),
            llm_enabled=False,
            action="skipped",
            reason="llm_disabled",
        )
        return records, selector_rules
    records = await apply_direct_record_llm_fallback_impl(
        context.session,
        run=context.run,
        page_url=acquisition_result.final_url,
        html=acquisition_result.html,
        page_markdown=str(getattr(acquisition_result, "page_markdown", "") or ""),
        records=records,
        resolve_run_config_fn=resolve_run_config,
        extract_records_fn=extract_records_directly_with_llm,
    )
    if "detail" in context.surface and records:
        records = await apply_llm_fallback(
            context.session,
            run=context.run,
            page_url=acquisition_result.final_url,
            html=acquisition_result.html,
            records=records,
        )
    _annotate_field_repair(
        records,
        surface=context.surface,
        requested_fields=list(context.requested_fields),
        llm_enabled=True,
        action="checked",
        reason=None,
    )
    return records, selector_rules
async def _extract_records_for_acquisition(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    acquisition_result = fetched.acquisition_result
    if not _browser_result_is_extractable(acquisition_result):
        return [], []
    await _populate_adapter_records(context, acquisition_result)
    _assign_platform_family(acquisition_result)

    fetched.url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(context.requested_fields),
    )
    selector_rules = await _load_selector_rules(context, acquisition_result.final_url)
    records = await _run_record_extraction(
        context,
        acquisition_result=acquisition_result,
        selector_rules=selector_rules,
    )
    if (
        not records
        and "listing" in context.surface
        and getattr(acquisition_result, "method", "") == "browser"
    ):
        fallback_records = await _extract_records_from_preserved_browser_html(
            context,
            fetched,
            selector_rules=selector_rules,
        )
        if fallback_records:
            records = fallback_records
    return records, selector_rules

async def _populate_adapter_records(
    context: _URLProcessingContext,
    acquisition_result: AcquisitionResult,
) -> None:
    acquisition_result.adapter_records = []
    acquisition_result.adapter_name = None
    acquisition_result.adapter_source_type = None

    adapter_results = []
    for html in [
        str(acquisition_result.html or ""),
        *_adapter_browser_artifact_htmls(acquisition_result),
    ]:
        adapter_result = await run_adapter(
            acquisition_result.final_url,
            html,
            context.surface,
        )
        if adapter_result is not None and list(adapter_result.records or []):
            adapter_results.append(adapter_result)
    adapter_result = _best_adapter_result(adapter_results)
    if (
        (adapter_result is None or not list(adapter_result.records or []))
        and _effective_blocked(acquisition_result)
    ):
        adapter_result = await try_blocked_adapter_recovery(
            acquisition_result.final_url,
            AcquisitionPlan(
                surface=context.surface,
                proxy_list=tuple(context.config.proxy_list or []),
                traversal_mode=context.config.traversal_mode,
                max_pages=context.config.max_pages,
                max_scrolls=context.config.max_scrolls,
                max_records=context.config.max_records,
                sleep_ms=context.config.sleep_ms,
                adapter_recovery_enabled=True,
            ),
            proxy_list=list(context.config.proxy_list or []),
        )
    if adapter_result is not None and list(adapter_result.records or []):
        acquisition_result.adapter_records = list(adapter_result.records or [])
        acquisition_result.adapter_name = adapter_result.adapter_name or None
        acquisition_result.adapter_source_type = adapter_result.source_type or None

def _best_adapter_result(adapter_results: list[AdapterResult]) -> AdapterResult | None:
    if not adapter_results:
        return None
    best = max(
        adapter_results,
        key=lambda result: _adapter_result_score(list(getattr(result, "records", []) or [])),
    )
    merged_records: dict[str, dict[str, object]] = {}
    unsourced_records: list[dict[str, object]] = []
    seen_unsourced: set[str] = set()
    for result in sorted(
        adapter_results,
        key=lambda item: _adapter_result_score(list(item.records or [])),
        reverse=True,
    ):
        for record in list(result.records or []):
            if not isinstance(record, dict):
                continue
            url = str(record.get("url") or "").strip()
            if not url:
                fingerprint = json.dumps(record, sort_keys=True, default=str)
                if fingerprint in seen_unsourced:
                    continue
                seen_unsourced.add(fingerprint)
                unsourced_records.append(dict(record))
                continue
            existing = merged_records.setdefault(url, {})
            for key, value in record.items():
                if value in (None, "", [], {}):
                    continue
                if existing.get(key) in (None, "", [], {}):
                    existing[key] = value
    return AdapterResult(
        records=[*merged_records.values(), *unsourced_records],
        source_type=best.source_type,
        adapter_name=best.adapter_name,
    )

def _adapter_result_score(records: list[object]) -> tuple[int, int]:
    populated = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        populated += sum(
            value not in (None, "", [], {})
            for key, value in record.items()
            if not str(key).startswith("_")
        )
    return len(records), populated

def _adapter_browser_artifact_htmls(
    acquisition_result: AcquisitionResult,
) -> list[str]:
    artifacts = mapping_or_empty(getattr(acquisition_result, "artifacts", {}))
    seen = {str(getattr(acquisition_result, "html", "") or "").strip()}
    htmls: list[str] = []
    for value in (
        artifacts.get("full_rendered_html"),
        _rendered_listing_fragments_html(artifacts.get("rendered_listing_fragments")),
    ):
        html = str(value or "").strip()
        if not html or html in seen:
            continue
        seen.add(html)
        htmls.append(html)
    return htmls

def _rendered_listing_fragments_html(value: object) -> str:
    if not isinstance(value, list):
        return ""
    fragments = [
        fragment
        for fragment in (str(item or "").strip() for item in value)
        if fragment
    ]
    if not fragments:
        return ""
    joined = "\n".join(fragments)
    return f"<html><body>{joined}</body></html>"

def _assign_platform_family(acquisition_result: AcquisitionResult) -> None:
    platform_family = detect_platform_family(
        acquisition_result.final_url,
        acquisition_result.html,
    )
    if not platform_family and acquisition_result.adapter_name:
        platform_family = acquisition_result.adapter_name
    acquisition_result.platform_family = platform_family or None

async def _run_record_extraction(
    context: _URLProcessingContext,
    *,
    acquisition_result: AcquisitionResult,
    selector_rules: list[dict[str, object]],
) -> list[dict[str, object]]:
    return await asyncio.to_thread(
        extract_records,
        acquisition_result.html,
        acquisition_result.final_url,
        context.surface,
        max_records=context.config.max_records,
        requested_page_url=context.url,
        requested_fields=list(context.requested_fields),
        adapter_records=acquisition_result.adapter_records,
        network_payloads=acquisition_result.network_payloads,
        artifacts=acquisition_result.artifacts,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=context.run.settings_view.extraction_runtime_snapshot(),
        content_type=acquisition_result.content_type,
    )

async def _extract_records_from_preserved_browser_html(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    selector_rules: list[dict[str, object]],
) -> list[dict[str, object]]:
    acquisition_result = fetched.acquisition_result
    browser_diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    if not bool(browser_diagnostics.get("traversal_activated")):
        return []
    artifacts = mapping_or_empty(getattr(acquisition_result, "artifacts", {}))
    rendered_html = str(artifacts.get("full_rendered_html") or "").strip()
    if not rendered_html or rendered_html == str(acquisition_result.html or "").strip():
        return []
    fallback_records = await asyncio.to_thread(
        extract_records,
        rendered_html,
        acquisition_result.final_url,
        context.surface,
        max_records=context.config.max_records,
        requested_page_url=context.url,
        requested_fields=list(context.requested_fields),
        adapter_records=acquisition_result.adapter_records,
        network_payloads=acquisition_result.network_payloads,
        artifacts=acquisition_result.artifacts,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=context.run.settings_view.extraction_runtime_snapshot(),
        content_type=acquisition_result.content_type,
    )
    if not fallback_records:
        await _log_pipeline_event(
            context,
            "warning",
            "Traversal yielded no extractable listing records; fallback extraction on full rendered HTML also returned 0 records",
        )
        _merge_browser_diagnostics(
            acquisition_result,
            {
                "traversal_fallback_used": True,
                "traversal_fallback_recovered": False,
                "traversal_fallback_record_count": 0,
            },
        )
        fetched.url_metrics = build_url_metrics(
            acquisition_result,
            requested_fields=list(context.requested_fields),
        )
        return []
    artifacts["traversal_composed_html"] = str(acquisition_result.html or "")
    acquisition_result.artifacts = artifacts
    acquisition_result.html = rendered_html
    await _log_pipeline_event(
        context,
        "info",
        f"Traversal yielded 0 extractable records; recovered {len(fallback_records)} record(s) from full rendered HTML",
    )
    _merge_browser_diagnostics(
        acquisition_result,
        {
            "traversal_fallback_used": True,
            "traversal_fallback_recovered": True,
            "traversal_fallback_record_count": len(fallback_records),
        },
    )
    fetched.url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(context.requested_fields),
    )
    return fallback_records

async def _load_selector_rules(
    context: _URLProcessingContext,
    page_url: str,
) -> list[dict[str, object]]:
    saved_rules = await load_domain_selector_rules(
            context.session,
            domain=normalize_domain(page_url),
            surface=context.surface,
        )
    return compose_runtime_selector_rules(
        saved_rules,
        context.run.settings_view.extraction_contract(),
    )

async def _run_persistence_stage(
    context: _URLProcessingContext,
    extracted: _ExtractedURLStage,
) -> URLProcessingResult:
    acquisition_result = extracted.fetched.acquisition_result
    raw_html_path = await persist_acquisition_artifacts(
        run_id=context.run.id,
        acquisition_result=acquisition_result,
        browser_attempted=_browser_attempted(acquisition_result),
        screenshot_required=_screenshot_required(_browser_outcome(acquisition_result)),
    )
    await _enter_stage(context, STAGE_PERSIST)
    persisted_count = await persist_extracted_records(
        context.session,
        context.run,
        extracted.records,
        acquisition_result=acquisition_result,
        raw_html_path=raw_html_path,
    )
    verdict = compute_verdict(
        is_listing="listing" in context.surface,
        blocked=_effective_blocked(acquisition_result),
        record_count=persisted_count,
    )
    if not _suppress_empty_downstream_record_logs(
        acquisition_result,
        extracted.records,
    ):
        await _log_pipeline_event(
            context,
            "info",
            f"Persisted {persisted_count} record(s) for {acquisition_result.final_url}",
            commit=False,
        )
    if verdict == VERDICT_EMPTY and "listing" in context.surface and persisted_count == 0:
        verdict = VERDICT_LISTING_FAILED
    await _update_acquisition_contract_memory(
        context,
        acquisition_result=acquisition_result,
        records=extracted.records,
        persisted_count=persisted_count,
        verdict=verdict,
    )
    result_records = []
    for record in extracted.records:
        next_record = dict(record)
        next_record.pop("_field_repair", None)
        result_records.append(next_record)
    return URLProcessingResult(
        records=result_records,
        verdict=verdict,
        url_metrics=finalize_url_metrics(
            extracted.fetched.url_metrics,
            record_count=persisted_count,
        ),
    )
async def _update_acquisition_contract_memory(
    context: _URLProcessingContext,
    *,
    acquisition_result,
    records: list[dict[str, object]],
    persisted_count: int,
    verdict: str,
) -> None:
    domain = normalize_domain(getattr(acquisition_result, "final_url", "") or context.url)
    if not domain:
        return
    diagnostics = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    await record_acquisition_contract_outcome(
        context.session,
        domain=domain,
        surface=context.surface,
        source_run_id=int(context.run.id),
        method=getattr(acquisition_result, "method", None),
        browser_engine=str(diagnostics.get("browser_engine") or "").strip().lower(),
        requested_fields=repair_target_fields_for_surface(
            context.surface,
            list(context.requested_fields),
        ),
        records=records,
        persisted_count=persisted_count,
        quality_success=(
            persisted_count > 0
            and not _effective_blocked(acquisition_result)
            and verdict not in {VERDICT_BLOCKED, VERDICT_EMPTY}
        ),
        count_failure=verdict != VERDICT_LISTING_FAILED,
        stale_threshold=int(crawler_runtime_settings.acquisition_contract_stale_failure_threshold),
    )

