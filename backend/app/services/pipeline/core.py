from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.core.database import SessionLocal
from app.models.crawl import CrawlRun
from app.services.acquisition.acquirer import AcquisitionRequest
from app.services.acquisition.acquirer import acquire as _acquire
from app.services.acquisition_plan import AcquisitionPlan
from app.services.adapters.registry import run_adapter, try_blocked_adapter_recovery
from app.services.acquisition.browser_runtime import build_failed_browser_diagnostics
from app.services.crawl_state import TERMINAL_STATUSES, CrawlStatus, update_run_status
from app.services.domain_memory_service import load_domain_selector_rules
from app.services.domain_utils import normalize_domain
from app.services.confidence import score_record_confidence
from app.services.field_value_utils import coerce_field_value, finalize_record
from app.services.field_policy import field_allowed_for_surface
from app.services.llm_runtime import extract_missing_fields
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

from .pipeline_config import LLMFallbackConfig, PipelineDefaults
from .persistence import persist_acquisition_artifacts, persist_extracted_records
from .runtime_helpers import STAGE_ANALYZE, STAGE_FETCH, STAGE_SAVE, log_event, set_stage
from .types import URLProcessingConfig, URLProcessingResult

logger = logging.getLogger(__name__)

__all__ = [
    "STAGE_FETCH",
    "STAGE_ANALYZE",
    "STAGE_SAVE",
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
    acquisition_result: object
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

def _mapping_or_empty(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _browser_attempted(acquisition_result) -> bool:
    diagnostics = _mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    return bool(diagnostics.get("browser_attempted")) or getattr(
        acquisition_result,
        "method",
        "",
    ) == "browser"


def _browser_outcome(acquisition_result) -> str:
    diagnostics = _mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    return str(diagnostics.get("browser_outcome") or "").strip().lower()


def _screenshot_required(browser_outcome: str) -> bool:
    return browser_outcome in {
        "challenge_page",
        "low_content_shell",
        "navigation_failed",
        "traversal_failed",
        "render_timeout",
    }


def _merge_browser_diagnostics(
    acquisition_result,
    diagnostics: dict[str, object],
) -> None:
    merged = _mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    merged.update(dict(diagnostics or {}))
    acquisition_result.browser_diagnostics = merged


async def _process_single_url(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    config: URLProcessingConfig | None = None,
    *,
    proxy_list: list[str] | None = None,
    traversal_mode: str | None = None,
    max_pages: int = PipelineDefaults.MAX_PAGES,
    max_scrolls: int = PipelineDefaults.MAX_SCROLLS,
    max_records: int = PipelineDefaults.MAX_RECORDS,
    sleep_ms: int = PipelineDefaults.SLEEP_MS,
    checkpoint=None,
    update_run_state: bool = True,
    persist_logs: bool = True,
    prefetched_acquisition=None,
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
    await _enter_fetch_stage(context)
    robots_result = await _run_robots_gate(context)
    if robots_result is not None:
        return robots_result
    fetched = await _run_fetch_stage(
        context,
        prefetched_acquisition=prefetched_acquisition,
    )
    if context.config.prefetch_only:
        return _build_prefetch_only_result(context, fetched)
    await _enter_analyze_stage(context)
    extracted = await _run_extraction_stage(context, fetched)
    return await _run_persistence_stage(context, extracted)


async def _enter_fetch_stage(context: _URLProcessingContext) -> None:
    if context.config.update_run_state:
        await set_stage(context.session, context.run, STAGE_FETCH, current_url=context.url)
        await context.session.commit()


async def _enter_analyze_stage(context: _URLProcessingContext) -> None:
    if context.config.update_run_state:
        await set_stage(
            context.session,
            context.run,
            STAGE_ANALYZE,
            current_url=context.url,
        )
        await context.session.commit()


async def _enter_save_stage(context: _URLProcessingContext) -> None:
    if context.config.update_run_state:
        await set_stage(context.session, context.run, STAGE_SAVE, current_url=context.url)
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
    )


async def _run_fetch_stage(
    context: _URLProcessingContext,
    *,
    prefetched_acquisition,
) -> _FetchedURLStage:
    await _log_pipeline_event(context, "info", f"[FETCH] Fetching {context.url}")
    acquisition_request = _build_acquisition_request(context)
    acquisition_result = prefetched_acquisition or await acquire(acquisition_request)
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
    retry_decision = _empty_extraction_browser_retry_decision(
        acquisition_result,
        records,
    )
    if retry_decision["should_retry"]:
        await _log_pipeline_event(
            context,
            "info",
            f"[EXTRACT] No records via {acquisition_result.method}; retrying browser render for {context.url}",
        )
        retry_request = _build_acquisition_request(context).with_profile_updates(
            prefer_browser=True,
            retry_reason="empty_extraction",
        )
        try:
            browser_result = await acquire(retry_request)
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            _merge_browser_diagnostics(
                acquisition_result,
                build_failed_browser_diagnostics(
                    browser_reason="empty-extraction retry",
                    exc=exc,
                ),
            )
            fetched.url_metrics = build_url_metrics(
                acquisition_result,
                requested_fields=list(context.requested_fields),
            )
            await _log_pipeline_event(
                context,
                "warning",
                f"[EXTRACT] Browser retry failed for {context.url}: {type(exc).__name__}: {exc}",
            )
            raise
        else:
            fetched.acquisition_result = browser_result
            acquisition_result = browser_result
            records, selector_rules = await _extract_records_for_acquisition(
                context,
                fetched,
            )
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
    if context.run.settings_view.llm_enabled() and "detail" in context.surface and records:
        records = await _apply_llm_fallback(
            context.session,
            run=context.run,
            page_url=acquisition_result.final_url,
            html=acquisition_result.html,
            records=records,
        )
    return _ExtractedURLStage(fetched=fetched, records=records)


async def _extract_records_for_acquisition(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    acquisition_result = fetched.acquisition_result
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
    if adapter_result is not None:
        acquisition_result.adapter_records = list(adapter_result.records or [])
        acquisition_result.adapter_name = adapter_result.adapter_name or None
        acquisition_result.adapter_source_type = adapter_result.source_type or None

    platform_family = detect_platform_family(
        acquisition_result.final_url,
        acquisition_result.html,
    )
    if platform_family and not acquisition_result.adapter_name:
        acquisition_result.adapter_name = platform_family

    fetched.url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(context.requested_fields),
    )
    selector_rules = await _load_selector_rules(context, acquisition_result.final_url)
    records = extract_records(
        acquisition_result.html,
        acquisition_result.final_url,
        context.surface,
        max_records=context.config.max_records,
        requested_fields=list(context.requested_fields),
        adapter_records=acquisition_result.adapter_records,
        network_payloads=acquisition_result.network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=context.run.settings_view.extraction_runtime_snapshot(),
        content_type=acquisition_result.content_type,
    )
    return records, selector_rules


def _empty_extraction_browser_retry_decision(
    acquisition_result,
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


def _should_retry_browser_after_empty(
    acquisition_result,
    records: list[dict[str, object]],
) -> bool:
    return bool(
        _empty_extraction_browser_retry_decision(
            acquisition_result,
            records,
        )["should_retry"]
    )


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
    await _enter_save_stage(context)
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
        f"[SAVE] {persisted_count} record(s) persisted for {acquisition_result.final_url}",
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


async def _apply_llm_fallback(
    session: AsyncSession,
    *,
    run: CrawlRun,
    page_url: str,
    html: str,
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    updated_records: list[dict[str, object]] = []
    domain = normalize_domain(page_url)
    requested_fields = list(run.requested_fields or [])
    for record in records:
        next_record = dict(record)
        confidence = _mapping_or_empty(next_record.get("_confidence"))
        self_heal = _mapping_or_empty(next_record.get("_self_heal"))
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
        low_confidence = float_score < LLMFallbackConfig.CONFIDENCE_THRESHOLD
        selector_heal_rerun = str(self_heal.get("mode") or "").strip().lower() == "selector_synthesis"
        should_run = bool(missing_fields) or (
            low_confidence and not selector_heal_rerun
        )
        if not should_run:
            updated_records.append(next_record)
            continue
        payload, error_message = await extract_missing_fields(
            session,
            run_id=run.id,
            domain=domain,
            url=page_url,
            html_text=html,
            missing_fields=missing_fields or requested_fields,
            existing_values={
                key: value
                for key, value in next_record.items()
                if not str(key).startswith("_")
            },
        )
        field_sources = _mapping_or_empty(next_record.get("_field_sources"))
        applied_llm_fields: list[str] = []
        if isinstance(payload, dict):
            for field_name, value in payload.items():
                normalized_field = str(field_name or "").strip().lower()
                if (
                    not normalized_field
                    or not field_allowed_for_surface(run.surface, normalized_field)
                    or next_record.get(normalized_field) not in (None, "", [], {})
                ):
                    continue
                next_record[normalized_field] = coerce_field_value(
                    normalized_field,
                    value,
                    page_url,
                )
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
            "threshold": LLMFallbackConfig.CONFIDENCE_THRESHOLD,
            "mode": "missing_field_extraction",
            "error": error_message or None,
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
            logger.exception("Failure recovery via SessionLocal failed")


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
