from __future__ import annotations

import json
from typing import Awaitable, Callable

from app.models.crawl import CrawlRun
from app.services.confidence import score_record_confidence
from app.services.config.llm_runtime import llm_runtime_settings
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_utils import normalize_domain
from app.services.field_policy import (
    field_allowed_for_surface,
    repair_target_fields_for_surface,
)
from app.services.db_utils import mapping_or_empty
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
)
from app.services.llm_runtime import extract_missing_fields
from sqlalchemy.ext.asyncio import AsyncSession


ResolveRunConfigFn = Callable[..., Awaitable[dict[str, object] | None]]
ExtractRecordsFn = Callable[..., Awaitable[tuple[list[dict[str, object]] | None, str | None]]]


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

async def apply_direct_record_llm_fallback(
    session: AsyncSession,
    *,
    run: CrawlRun,
    page_url: str,
    html: str,
    page_markdown: str,
    records: list[dict[str, object]],
    resolve_run_config_fn: ResolveRunConfigFn,
    extract_records_fn: ExtractRecordsFn,
) -> list[dict[str, object]]:
    if not _should_run_direct_record_llm_fallback(
        run,
        records=records,
        page_markdown=page_markdown,
    ):
        return records
    config = await resolve_run_config_fn(
        session,
        run_id=run.id,
        task_type="direct_record_extraction",
    )
    if config is None:
        return records
    payload, _error_message = await extract_records_fn(
        session,
        run_id=run.id,
        domain=normalize_domain(page_url),
        url=page_url,
        surface=run.surface,
        html_text=html,
        markdown_text=page_markdown,
        requested_fields=repair_target_fields_for_surface(
            run.surface,
            run.requested_fields or [],
        ),
        existing_records=records,
    )
    if not payload:
        return records
    candidate_records = _normalize_direct_llm_records(
        run,
        page_url=page_url,
        records=payload,
    )
    if not candidate_records:
        return records
    if _record_set_quality_signature(
        candidate_records,
        surface=run.surface,
        requested_fields=repair_target_fields_for_surface(
            run.surface,
            run.requested_fields or [],
        ),
    ) <= _record_set_quality_signature(
        records,
        surface=run.surface,
        requested_fields=repair_target_fields_for_surface(
            run.surface,
            run.requested_fields or [],
        ),
    ):
        return records
    return candidate_records


def _should_run_direct_record_llm_fallback(
    run: CrawlRun,
    *,
    records: list[dict[str, object]],
    page_markdown: str,
) -> bool:
    if not str(page_markdown or "").strip():
        return False
    if "listing" in str(run.surface or "").strip().lower() and not records:
        return False
    min_records = max(
        1,
        int(crawler_runtime_settings.llm_direct_record_extraction_min_records or 3),
    )
    if len(records) < min_records:
        return True
    raw_populated_threshold = (
        crawler_runtime_settings.llm_direct_record_extraction_min_populated_fields_per_record
    )
    try:
        populated_threshold = (
            float(raw_populated_threshold)
            if raw_populated_threshold is not None
            else 3.0
        )
    except (TypeError, ValueError):
        populated_threshold = 3.0
    return _average_record_populated_field_count(records, surface=run.surface) < populated_threshold


def _average_record_populated_field_count(
    records: list[dict[str, object]],
    *,
    surface: str,
) -> float:
    fields = (
        ("title", "url", "price", "image_url", "brand")
        if "listing" in surface
        else ("title", "url", "description", "price", "brand", "specifications")
    )
    counts = [
        sum(record.get(field_name) not in (None, "", [], {}) for field_name in fields)
        for record in records
        if isinstance(record, dict)
    ]
    if not counts:
        return 0.0
    return sum(counts) / max(1, len(counts))


def _record_set_quality_signature(
    records: list[dict[str, object]],
    *,
    surface: str,
    requested_fields: list[str],
) -> tuple[int, int, int]:
    if not records:
        return (0, 0, 0)
    confidence_total = 0
    requested_hits = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        confidence_total += int(
            round(
                float(
                    score_record_confidence(
                        record,
                        surface=surface,
                        requested_fields=requested_fields,
                    )["score"]
                )
                * 10000
            )
        )
        requested_hits += sum(
            record.get(field_name) not in (None, "", [], {})
            for field_name in requested_fields
        )
    return (len(records), requested_hits, confidence_total)


def _normalize_direct_llm_records(
    run: CrawlRun,
    *,
    page_url: str,
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    normalized_records: list[dict[str, object]] = []
    for raw_record in list(records or []):
        if not isinstance(raw_record, dict):
            continue
        normalized: dict[str, object] = {
            "source_url": page_url,
            "url": page_url if "detail" in run.surface else None,
        }
        field_sources: dict[str, list[str]] = {}
        for field_name, value in raw_record.items():
            normalized_field = str(field_name or "").strip().lower()
            if not normalized_field or not field_allowed_for_surface(run.surface, normalized_field):
                continue
            coerced = coerce_field_value(normalized_field, value, page_url)
            if coerced in (None, "", [], {}):
                continue
            normalized[normalized_field] = coerced
            field_sources[normalized_field] = ["llm_direct_record_extraction"]
        canonical_record = finalize_record(
            {
                key: value
                for key, value in normalized.items()
                if not str(key).startswith("_")
            },
            surface=run.surface,
        )
        if "listing" in run.surface and (
            not canonical_record.get("title") or not canonical_record.get("url")
        ):
            continue
        if "detail" in run.surface and not canonical_record.get("title"):
            continue
        canonical_record["_source"] = "llm_direct_record_extraction"
        canonical_record["_field_sources"] = field_sources
        canonical_record["_confidence"] = score_record_confidence(
            canonical_record,
            surface=run.surface,
            requested_fields=repair_target_fields_for_surface(
                run.surface,
                run.requested_fields or [],
            ),
        )
        canonical_record["_self_heal"] = {
            "enabled": True,
            "triggered": True,
            "mode": "direct_record_extraction",
        }
        normalized_records.append(canonical_record)
    return normalized_records


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
    requested_fields = repair_target_fields_for_surface(
        run.surface,
        run.requested_fields or [],
    )
    for record in records:
        next_record = dict(record)
        missing_fields = [
            field_name
            for field_name in requested_fields
            if field_allowed_for_surface(run.surface, field_name)
            and next_record.get(field_name) in (None, "", [], {})
        ]
        should_run = bool(missing_fields)
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
