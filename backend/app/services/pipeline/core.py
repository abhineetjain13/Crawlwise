from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from app.core.database import SessionLocal
from app.models.crawl import CrawlRun
from app.services.acquisition.acquirer import AcquisitionRequest
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.acquisition.acquirer import acquire as _acquire
from app.services.acquisition_plan import AcquisitionPlan
from app.services.adapters.registry import run_adapter, try_blocked_adapter_recovery
from app.services.acquisition.browser_runtime import build_failed_browser_diagnostics
from app.services.crawl_state import TERMINAL_STATUSES, CrawlStatus, update_run_status
from app.services.domain_memory_service import load_domain_selector_rules
from app.services.db_utils import mapping_or_empty
from app.services.domain_utils import normalize_domain
from app.services.confidence import score_record_confidence
from app.services.config.llm_runtime import llm_runtime_settings
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_value_core import (
    IMAGE_FIELDS,
    LONG_TEXT_FIELDS,
    STRUCTURED_MULTI_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    URL_FIELDS,
    coerce_field_value,
    finalize_record,
    strip_html_tags,
    validate_record_for_surface,
)
from app.services.field_policy import (
    canonical_requested_fields,
    field_allowed_for_surface,
    normalize_requested_field,
)
from app.services.llm_config_service import resolve_run_config
from app.services.llm_runtime import (
    extract_missing_fields,
    extract_records_directly as extract_records_directly_with_llm,
)
from app.services.pipeline.direct_record_fallback import (
    apply_direct_record_llm_fallback as apply_direct_record_llm_fallback_impl,
)
from app.services.platform_policy import detect_platform_family
from app.services.publish import (
    VERDICT_BLOCKED,
    VERDICT_EMPTY,
    VERDICT_ERROR,
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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .persistence import persist_acquisition_artifacts, persist_extracted_records
from .runtime_helpers import (
    STAGE_ACQUIRE,
    STAGE_EXTRACT,
    STAGE_NORMALIZE,
    STAGE_PERSIST,
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
]

acquire = _acquire


@dataclass(slots=True)
class _URLProcessingContext:
    session: AsyncSession
    run: CrawlRun
    url: str
    config: URLProcessingConfig
    requested_fields: list[str] = field(default_factory=list)
    surface: str = ""

    @classmethod
    def build(
        cls,
        *,
        session: AsyncSession,
        run: CrawlRun,
        url: str,
        config: URLProcessingConfig,
    ) -> "_URLProcessingContext":
        return cls(
            session=session,
            run=run,
            url=url,
            config=config,
            requested_fields=list(run.requested_fields or []),
            surface=run.surface,
        )


@dataclass(slots=True)
class _FetchedURLStage:
    context: _URLProcessingContext
    acquisition_result: AcquisitionResult
    url_metrics: dict[str, object]


@dataclass(slots=True)
class _ExtractedURLStage:
    fetched: _FetchedURLStage
    records: list[dict[str, object]]


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
        return config
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
def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]

def _sanitize_llm_existing_values(record: dict[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    max_chars = max(1, int(llm_runtime_settings.existing_values_max_chars or 1))
    for key, value in record.items():
        if str(key).startswith("_"):
            continue
        if isinstance(value, str):
            truncated = value
            if "<" in truncated and ">" in truncated:
                truncated = strip_html_tags(truncated)
            truncated = truncated[:max_chars]
            sanitized[key] = truncated
        elif isinstance(value, (list, dict)):
            serialized = json.dumps(value, default=str)
            if len(serialized) > max_chars:
                serialized = serialized[:max_chars]
            sanitized[key] = serialized
        else:
            sanitized[key] = value
    return sanitized


_STRING_FIELDS = URL_FIELDS | IMAGE_FIELDS | LONG_TEXT_FIELDS
_LIST_FIELDS = STRUCTURED_MULTI_FIELDS | STRUCTURED_OBJECT_LIST_FIELDS
_DICT_FIELDS = STRUCTURED_OBJECT_FIELDS

def _validate_llm_field_type(field_name: str, value: object) -> bool:
    if value in (None, "", [], {}):
        return True
    normalized = str(field_name or "").strip().lower()
    if normalized in _STRING_FIELDS:
        return isinstance(value, str)
    if normalized in _LIST_FIELDS:
        return isinstance(value, list)
    if normalized in _DICT_FIELDS:
        return isinstance(value, dict)
    return True

def _browser_attempted(acquisition_result: AcquisitionResult) -> bool:
    diagnostics = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    return bool(diagnostics.get("browser_attempted")) or getattr(
        acquisition_result,
        "method",
        "",
    ) == "browser"

def _browser_outcome(acquisition_result: AcquisitionResult) -> str:
    diagnostics = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    return str(diagnostics.get("browser_outcome") or "").strip().lower()

def _screenshot_required(browser_outcome: str) -> bool:
    return browser_outcome in {
        "challenge_page",
        "low_content_shell",
        "navigation_failed",
        "traversal_failed",
        "render_timeout",
    }

def _browser_result_is_extractable(acquisition_result: AcquisitionResult) -> bool:
    if getattr(acquisition_result, "method", "") != "browser":
        return True
    return _browser_outcome(acquisition_result) in {"", "usable_content"}

def _merge_browser_diagnostics(
    acquisition_result: AcquisitionResult,
    diagnostics: dict[str, object],
) -> None:
    merged = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    merged.update(dict(diagnostics or {}))
    acquisition_result.browser_diagnostics = merged

async def process_single_url(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    config: URLProcessingConfig | None = None,
    *,
    proxy_list: list[str] | None = None,
    traversal_mode: str | None = None,
    max_pages: int = crawler_runtime_settings.default_max_pages,
    max_scrolls: int = crawler_runtime_settings.default_max_scrolls,
    max_records: int = crawler_runtime_settings.default_max_records,
    sleep_ms: int = crawler_runtime_settings.default_sleep_ms,
    checkpoint=None,
    update_run_state: bool = True,
    persist_logs: bool = True,
    prefetched_acquisition: AcquisitionResult | None = None,
) -> URLProcessingResult:
    del checkpoint
    context = _URLProcessingContext.build(
        session=session,
        run=run,
        url=url,
        config=_resolved_url_processing_config(
            config,
            surface=run.surface,
            proxy_list=proxy_list,
            traversal_mode=traversal_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            max_records=max_records,
            sleep_ms=sleep_ms,
            update_run_state=update_run_state,
            persist_logs=persist_logs,
        ),
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
    await _log_pipeline_event(
        context,
        "info",
        f"[ROBOTS] Ignoring robots.txt for {context.url}",
    )
    return None

def _build_acquisition_request(context: _URLProcessingContext) -> AcquisitionRequest:
    plan = context.config.resolved_acquisition_plan(surface=context.surface)
    return AcquisitionRequest(
        run_id=context.run.id,
        url=context.url,
        plan=plan,
        requested_fields=list(context.requested_fields),
        requested_field_selectors={},
        acquisition_profile=dict(build_acquisition_profile(context.run.settings_view)),
        on_event=_build_live_acquisition_logger(context),
    )

async def _run_acquisition_stage(
    context: _URLProcessingContext,
    *,
    prefetched_acquisition: AcquisitionResult | None,
) -> _FetchedURLStage:
    acquisition_request = _build_acquisition_request(context)
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
                "Launched headless browser (chromium, proxy: direct)",
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

    if getattr(acquisition_result, "blocked", False):
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
        blocked=bool(fetched.acquisition_result.blocked),
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
        context,
        acquisition_result,
        records,
    )
    await _log_extraction_outcome(context, acquisition_result, records)
    records, selector_rules = await _retry_empty_extraction_with_browser(
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
    return _ExtractedURLStage(fetched=fetched, records=records)

def _record_detail_expansion_extraction_outcome(
    context: _URLProcessingContext,
    acquisition_result: AcquisitionResult,
    records: list[dict[str, object]],
) -> None:
    if str(getattr(acquisition_result, "method", "") or "").strip().lower() != "browser":
        return
    browser_diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    detail_expansion = mapping_or_empty(browser_diagnostics.get("detail_expansion"))
    try:
        clicked_count = int(str(detail_expansion.get("clicked_count", 0) or 0))
    except (TypeError, ValueError):
        clicked_count = 0
    if clicked_count <= 0:
        return
    requested_fields = {
        normalized
        for value in context.requested_fields
        if (normalized := normalize_requested_field(value))
    }
    extracted_fields = sorted(
        {
            str(field_name).strip().lower()
            for record in records
            if isinstance(record, dict)
            for field_name, value in record.items()
            if (
                not str(field_name).startswith("_")
                and value not in (None, "", [], {})
                and (
                    not requested_fields
                    or str(field_name).strip().lower() in requested_fields
                    or str(field_name).strip().lower() in LONG_TEXT_FIELDS
                )
            )
        }
    )
    detail_expansion["extraction_consumed"] = bool(extracted_fields or records)
    detail_expansion["extracted_fields"] = extracted_fields
    browser_diagnostics["detail_expansion"] = detail_expansion
    acquisition_result.browser_diagnostics = browser_diagnostics

async def _run_normalization_stage(
    context: _URLProcessingContext,
    extracted: _ExtractedURLStage,
) -> _ExtractedURLStage:
    await _enter_stage(context, STAGE_NORMALIZE)
    normalized_records: list[dict[str, object]] = []
    for index, record in enumerate(extracted.records, start=1):
        normalized_record, validation_errors = validate_record_for_surface(
            dict(record),
            context.surface,
        )
        normalized_records.append(normalized_record)
        if validation_errors:
            await _log_pipeline_event(
                context,
                "warning",
                "Schema validation cleaned record "
                f"{index} for {context.url}: {'; '.join(validation_errors)}",
            )
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
    adapter = getattr(acquisition_result, "adapter_name", "generic") or "generic"
    if records:
        await _log_pipeline_event(
            context,
            "info",
            f"Extracted {len(records)} records using {adapter} adapter",
        )
        return
    await _log_pipeline_event(
        context,
        "warning",
        f"Extraction yielded 0 records (adapter: {adapter})",
    )

async def _retry_empty_extraction_with_browser(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    records: list[dict[str, object]],
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    acquisition_result = fetched.acquisition_result
    retry_decision = _empty_extraction_browser_retry_decision(acquisition_result, records)
    if not retry_decision["should_retry"]:
        return records, selector_rules
    await _log_pipeline_event(context, "info", f"No records via {acquisition_result.method}; retrying browser render for {context.url}")
    browser_result = await _acquire_browser_retry_result(context, fetched, retry_reason="empty_extraction")
    fetched.acquisition_result = browser_result
    return await _extract_records_for_acquisition(context, fetched)

async def _acquire_browser_retry_result(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    retry_reason: str,
):
    acquisition_result = fetched.acquisition_result
    retry_request = _build_acquisition_request(context).with_profile_updates(prefer_browser=True, retry_reason=retry_reason)
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
    if not context.run.settings_view.llm_enabled():
        return records, selector_rules
    records = await _apply_direct_record_llm_fallback(
        context.session,
        run=context.run,
        page_url=acquisition_result.final_url,
        html=acquisition_result.html,
        page_markdown=str(getattr(acquisition_result, "page_markdown", "") or ""),
        records=records,
    )
    if "detail" in context.surface and records:
        records = await apply_llm_fallback(
            context.session,
            run=context.run,
            page_url=acquisition_result.final_url,
            html=acquisition_result.html,
            records=records,
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

    adapter_result = await run_adapter(
        acquisition_result.final_url,
        acquisition_result.html,
        context.surface,
    )
    if (
        (adapter_result is None or not list(adapter_result.records or []))
        and acquisition_result.blocked
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

def _empty_extraction_browser_retry_decision(
    acquisition_result: AcquisitionResult,
    records: list[dict[str, object]],
) -> dict[str, object]:
    if records:
        return {"should_retry": False, "reason": "records_present"}
    browser_attempted = _browser_attempted(acquisition_result)
    browser_outcome = _browser_outcome(acquisition_result)
    if browser_attempted:
        return {
            "should_retry": False,
            "reason": "browser_already_attempted",
            "browser_outcome": browser_outcome or None,
        }
    if acquisition_result.blocked:
        return {"should_retry": False, "reason": "blocked"}
    content_type = str(getattr(acquisition_result, "content_type", "") or "").lower()
    if "json" in content_type:
        return {"should_retry": False, "reason": "json_response"}
    return {"should_retry": True, "reason": "empty_non_browser_html"}

async def _load_selector_rules(
    context: _URLProcessingContext,
    page_url: str,
) -> list[dict[str, object]]:
    return [
        *await load_domain_selector_rules(
            context.session,
            domain=normalize_domain(page_url),
            surface=context.surface,
        ),
        *[
            {
                "field_name": row.get("field_name"),
                "css_selector": row.get("css_selector"),
                "xpath": row.get("xpath"),
                "regex": row.get("regex"),
                "source": "run_config",
                "status": "validated",
                "is_active": True,
            }
            for row in context.run.settings_view.extraction_contract()
            if isinstance(row, dict)
        ],
    ]

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
        extracted.records[: context.config.max_records],
        acquisition_result=acquisition_result,
        raw_html_path=raw_html_path,
    )
    verdict = compute_verdict(
        is_listing="listing" in context.surface,
        blocked=bool(acquisition_result.blocked),
        record_count=persisted_count,
    )
    await _log_pipeline_event(
        context,
        "info",
        f"Persisted {persisted_count} record(s) for {acquisition_result.final_url}",
        commit=False,
    )
    if verdict == VERDICT_EMPTY and "listing" in context.surface and persisted_count == 0:
        verdict = VERDICT_LISTING_FAILED
    return URLProcessingResult(
        records=extracted.records[: context.config.max_records],
        verdict=verdict,
        url_metrics=finalize_url_metrics(
            extracted.fetched.url_metrics,
            record_count=persisted_count,
        ),
    )

async def _apply_direct_record_llm_fallback(
    session: AsyncSession,
    *,
    run: CrawlRun,
    page_url: str,
    html: str,
    page_markdown: str,
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    return await apply_direct_record_llm_fallback_impl(
        session,
        run=run,
        page_url=page_url,
        html=html,
        page_markdown=page_markdown,
        records=records,
        resolve_run_config_fn=resolve_run_config,
        extract_records_fn=extract_records_directly_with_llm,
    )

async def apply_llm_fallback(
    session: AsyncSession,
    *,
    run: CrawlRun,
    page_url: str,
    html: str,
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    updated_records: list[dict[str, object]] = []
    domain = normalize_domain(page_url)
    requested_fields = canonical_requested_fields(run.requested_fields or [])
    for record in records:
        next_record = dict(record)
        confidence = mapping_or_empty(next_record.get("_confidence"))
        self_heal = mapping_or_empty(next_record.get("_self_heal"))
        missing_fields = [
            field_name
            for field_name in requested_fields
            if field_allowed_for_surface(run.surface, field_name)
            and next_record.get(field_name) in (None, "", [], {})
        ]
        raw_score = confidence.get("score", 1.0)
        try:
            float_score = float(str(raw_score)) if raw_score is not None else 1.0
        except (TypeError, ValueError):
            float_score = 1.0
        low_confidence = (
            float_score < crawler_runtime_settings.llm_confidence_threshold
        )
        selector_heal_rerun = str(self_heal.get("mode") or "").strip().lower() == "selector_synthesis"
        should_run = bool(missing_fields) or (
            low_confidence and not selector_heal_rerun
        )
        if not should_run:
            updated_records.append(next_record)
            continue
        sanitized_existing = _sanitize_llm_existing_values(next_record)
        payload, error_message = await extract_missing_fields(
            session,
            run_id=run.id,
            domain=domain,
            url=page_url,
            html_text=html,
            missing_fields=missing_fields or requested_fields,
            existing_values=sanitized_existing,
        )
        field_sources = mapping_or_empty(next_record.get("_field_sources"))
        applied_llm_fields: list[str] = []
        llm_rejected_fields: list[str] = []
        if isinstance(payload, dict):
            for field_name, value in payload.items():
                normalized_field = str(field_name or "").strip().lower()
                if (
                    not normalized_field
                    or not field_allowed_for_surface(run.surface, normalized_field)
                    or next_record.get(normalized_field) not in (None, "", [], {})
                ):
                    continue
                coerced = coerce_field_value(
                    normalized_field,
                    value,
                    page_url,
                )
                if not _validate_llm_field_type(normalized_field, coerced):
                    llm_rejected_fields.append(normalized_field)
                    continue
                if coerced in (None, "", [], {}):
                    continue
                next_record[normalized_field] = coerced
                applied_llm_fields.append(normalized_field)
                current_sources = _string_list(field_sources.get(normalized_field))
                if "llm_missing_field_extraction" not in current_sources:
                    current_sources.append("llm_missing_field_extraction")
                field_sources[normalized_field] = current_sources
        if applied_llm_fields:
            canonical_record = {
                key: value
                for key, value in next_record.items()
                if not str(key).startswith("_")
            }
            next_record.update(finalize_record(canonical_record, surface=run.surface))
        next_record["_field_sources"] = field_sources
        next_record["_confidence"] = score_record_confidence(
            next_record,
            surface=run.surface,
            requested_fields=requested_fields,
        )
        if applied_llm_fields and not str(next_record.get("_source") or "").strip():
            next_record["_source"] = "llm_missing_field_extraction"
        next_record["_self_heal"] = {
            "enabled": True,
            "triggered": True,
            "threshold": crawler_runtime_settings.llm_confidence_threshold,
            "mode": "missing_field_extraction",
            "error": error_message or None,
            "rejected_fields": llm_rejected_fields or None,
        }
        updated_records.append(next_record)
    return updated_records

async def _mark_run_failed(session: AsyncSession, run_id: int, error_msg: str) -> None:
    try:
        await session.rollback()
    except SQLAlchemyError:
        logger.debug("Session rollback failed before failure persistence", exc_info=True)
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
        logger.critical(
            "Failure recovery via SessionLocal failed for run_id=%s — "
            "run may be stuck in RUNNING state (zombie run). "
            "Original error: %s",
            run_id,
            error_msg,
            exc_info=True,
        )
        return

async def _persist_failure_state(
    session: AsyncSession,
    run_id: int,
    error_msg: str,
) -> None:
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

def _build_live_acquisition_logger(context: _URLProcessingContext):
    if not context.config.persist_logs:
        return None

    async def _on_event(level: str, message: str) -> None:
        await log_event(context.session, context.run.id, level, message)
        await context.session.commit()

    return _on_event
