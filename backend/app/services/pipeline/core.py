from __future__ import annotations

import hashlib
import logging

from app.core.database import SessionLocal
from app.models.crawl import CrawlRecord, CrawlRun
from app.services.acquisition import AcquisitionRequest
from app.services.acquisition.acquirer import acquire as _acquire
from app.services.adapters.registry import run_adapter
from app.services.artifact_store import persist_html_artifact
from app.services.crawl_state import TERMINAL_STATUSES, CrawlStatus, update_run_status
from app.services.domain_memory_service import load_domain_selector_rules
from app.services.domain_utils import normalize_domain
from app.services.confidence import score_record_confidence
from app.services.field_value_utils import coerce_field_value
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
from app.services.publish.metadata import refresh_record_commit_metadata
from app.services.crawl_engine import extract_records
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .pipeline_config import LLMFallbackConfig, PipelineDefaults
from .runtime_helpers import STAGE_ANALYZE, STAGE_FETCH, STAGE_SAVE, log_event, set_stage
from .types import URLProcessingConfig, URLProcessingResult

logger = logging.getLogger(__name__)

__all__ = [
    "STAGE_FETCH",
    "STAGE_ANALYZE",
    "STAGE_SAVE",
]

acquire = _acquire


def get_selector_defaults(_domain: str, _field_name: str) -> list[dict]:
    return []


def get_canonical_fields(surface: str) -> list[str]:
    del surface
    return []


def _resolved_url_processing_config(
    config: URLProcessingConfig | None,
    *,
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
    )


def _record_identity_key(source_url: str) -> str | None:
    text = str(source_url or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mapping_or_empty(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _build_source_trace(acquisition_result, record: dict[str, object]) -> dict[str, object]:
    field_discovery = {}
    field_sources = _mapping_or_empty(record.get("_field_sources"))
    for key, value in record.items():
        if str(key).startswith("_"):
            continue
        field_discovery[str(key)] = {
            "status": "found",
            "value": str(value),
            "sources": _string_list(
                field_sources.get(str(key), [str(record.get("_source") or "extraction")])
            ),
        }
    return {
        "acquisition": {
            "method": acquisition_result.method,
            "status_code": acquisition_result.status_code,
            "final_url": acquisition_result.final_url,
            "blocked": acquisition_result.blocked,
            "adapter_name": acquisition_result.adapter_name,
            "adapter_source_type": acquisition_result.adapter_source_type,
            "network_payload_count": len(list(acquisition_result.network_payloads or [])),
            "browser_diagnostics": _mapping_or_empty(acquisition_result.browser_diagnostics),
        },
        "extraction": {
            "source": str(record.get("_source") or "extraction"),
            "confidence": _mapping_or_empty(record.get("_confidence")),
            "self_heal": _mapping_or_empty(record.get("_self_heal")),
        },
        "field_discovery": field_discovery,
    }


async def _persist_records(
    session: AsyncSession,
    run: CrawlRun,
    records: list[dict[str, object]],
    *,
    acquisition_result,
    raw_html_path: str | None = None,
) -> int:
    persisted = 0
    seen_identities: set[str] = set()
    for record in records:
        data = {
            key: value
            for key, value in dict(record).items()
            if value not in (None, "", [], {}) and not str(key).startswith("_")
        }
        if not data:
            continue
        source_url = str(
            data.get("url") or data.get("source_url") or acquisition_result.final_url
        )
        identity_key = _record_identity_key(source_url)
        if identity_key and identity_key in seen_identities:
            continue
        if identity_key is not None:
            seen_identities.add(identity_key)
        crawl_record = CrawlRecord(
            run_id=run.id,
            source_url=source_url,
            url_identity_key=identity_key,
            data=data,
            raw_data=dict(record),
            discovered_data=(
                {"confidence": _mapping_or_empty(record.get("_confidence"))}
                if isinstance(record.get("_confidence"), dict)
                else {}
            ),
            source_trace=_build_source_trace(acquisition_result, record),
            raw_html_path=raw_html_path,
        )
        session.add(crawl_record)
        await session.flush()
        for field_name, value in data.items():
            refresh_record_commit_metadata(
                crawl_record,
                run=run,
                field_name=field_name,
                value=value,
                source_label=str(record.get("_source") or "extraction"),
            )
        persisted += 1
    return persisted


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
    resolved_config = _resolved_url_processing_config(
        config,
        proxy_list=proxy_list,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        max_records=max_records,
        sleep_ms=sleep_ms,
        update_run_state=update_run_state,
        persist_logs=persist_logs,
    )
    if resolved_config.update_run_state:
        await set_stage(session, run, STAGE_FETCH, current_url=url)
        await session.commit()
    robots_result = None
    if run.settings_view.respect_robots_txt():
        robots_result = await check_url_crawlability(url)
        if not robots_result.allowed:
            if resolved_config.persist_logs:
                await log_event(
                    session,
                    run.id,
                    "warning",
                    f"[ROBOTS] Blocked by robots.txt: {url}",
                )
                await session.commit()
            return URLProcessingResult(
                records=[],
                verdict=VERDICT_BLOCKED,
                url_metrics=finalize_url_metrics(
                    {
                        "blocked": True,
                        "final_url": url,
                        "method": "",
                        "requested_fields": list(run.requested_fields or []),
                        "robots": {
                            "allowed": False,
                            "outcome": robots_result.outcome,
                            "robots_url": robots_result.robots_url,
                        },
                    },
                    record_count=0,
                ),
            )
        if resolved_config.persist_logs and robots_result.outcome == ROBOTS_MISSING:
            await log_event(
                session,
                run.id,
                "info",
                f"[ROBOTS] No robots.txt found for {url}; continuing",
            )
            await session.commit()
        if resolved_config.persist_logs and robots_result.outcome == ROBOTS_FETCH_FAILURE:
            await log_event(
                session,
                run.id,
                "warning",
                f"[ROBOTS] robots.txt check failed for {url}; continuing",
            )
            await session.commit()
    elif resolved_config.persist_logs:
        await log_event(session, run.id, "info", f"[ROBOTS] Ignoring robots.txt for {url}")
        await session.commit()
    if resolved_config.persist_logs:
        await log_event(session, run.id, "info", f"[FETCH] Fetching {url}")
        await session.commit()

    acquisition_request = AcquisitionRequest(
        run_id=run.id,
        url=url,
        surface=run.surface,
        proxy_list=list(resolved_config.proxy_list or []),
        traversal_mode=resolved_config.traversal_mode,
        max_pages=resolved_config.max_pages,
        max_scrolls=resolved_config.max_scrolls,
        sleep_ms=resolved_config.sleep_ms,
        requested_fields=list(run.requested_fields or []),
        requested_field_selectors={
            field_name: get_selector_defaults(normalize_domain(url), field_name)
            for field_name in list(run.requested_fields or [])
            if field_name
        },
        acquisition_profile=dict(build_acquisition_profile(run.settings_view)),
    )
    acquisition_result = prefetched_acquisition or await acquire(acquisition_request)
    url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(run.requested_fields or []),
    )
    if resolved_config.prefetch_only:
        verdict = compute_verdict(
            is_listing="listing" in run.surface,
            blocked=bool(acquisition_result.blocked),
            record_count=1 if acquisition_result.html else 0,
        )
        return URLProcessingResult(
            records=[],
            verdict=verdict,
            url_metrics=finalize_url_metrics(url_metrics, record_count=0),
        )

    if resolved_config.update_run_state:
        await set_stage(session, run, STAGE_ANALYZE, current_url=url)
        await session.commit()
    adapter_result = await run_adapter(
        acquisition_result.final_url,
        acquisition_result.html,
        run.surface,
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
    url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(run.requested_fields or []),
    )
    selector_rules = [
        *await load_domain_selector_rules(
            session,
            domain=normalize_domain(acquisition_result.final_url),
            surface=run.surface,
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
            for row in run.settings_view.extraction_contract()
            if isinstance(row, dict)
        ],
    ]
    records = extract_records(
        acquisition_result.html,
        acquisition_result.final_url,
        run.surface,
        max_records=resolved_config.max_records,
        requested_fields=list(run.requested_fields or []),
        adapter_records=acquisition_result.adapter_records,
        network_payloads=acquisition_result.network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=run.settings_view.extraction_runtime_snapshot(),
    )
    if "detail" in run.surface and records:
        records, selector_rules = await apply_selector_self_heal(
            session,
            run=run,
            page_url=acquisition_result.final_url,
            html=acquisition_result.html,
            records=records,
            adapter_records=acquisition_result.adapter_records,
            network_payloads=acquisition_result.network_payloads,
            selector_rules=selector_rules,
        )
    if run.settings_view.llm_enabled() and "detail" in run.surface and records:
        records = await _apply_llm_fallback(
            session,
            run=run,
            page_url=acquisition_result.final_url,
            html=acquisition_result.html,
            records=records,
        )
    raw_html_path = persist_html_artifact(
        run_id=run.id,
        source_url=acquisition_result.final_url,
        html=acquisition_result.html,
    )
    if resolved_config.update_run_state:
        await set_stage(session, run, STAGE_SAVE, current_url=url)
        await session.commit()
    persisted_count = await _persist_records(
        session,
        run,
        records[: resolved_config.max_records],
        acquisition_result=acquisition_result,
        raw_html_path=raw_html_path,
    )
    verdict = compute_verdict(
        is_listing="listing" in run.surface,
        blocked=bool(acquisition_result.blocked),
        record_count=persisted_count,
    )
    if resolved_config.persist_logs:
        await log_event(
            session,
            run.id,
            "info",
            f"[SAVE] {persisted_count} record(s) persisted for {acquisition_result.final_url}",
        )
    if verdict == VERDICT_EMPTY and "listing" in run.surface and persisted_count == 0:
        verdict = VERDICT_LISTING_FAILED
    return URLProcessingResult(
        records=records[: resolved_config.max_records],
        verdict=verdict,
        url_metrics=finalize_url_metrics(url_metrics, record_count=persisted_count),
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
        float_score = float(str(raw_score)) if raw_score is not None else 1.0
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
                current_sources = _string_list(field_sources.get(normalized_field))
                if "llm_missing_field_extraction" not in current_sources:
                    current_sources.append("llm_missing_field_extraction")
                field_sources[normalized_field] = current_sources
        next_record["_field_sources"] = field_sources
        next_record["_confidence"] = score_record_confidence(
            next_record,
            surface=run.surface,
            requested_fields=requested_fields,
        )
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
        pass
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
