from __future__ import annotations

from typing import Awaitable, Callable

from app.models.crawl import CrawlRun
from app.services.confidence import score_record_confidence
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_utils import normalize_domain
from app.services.field_policy import canonical_requested_fields, field_allowed_for_surface
from app.services.field_value_core import coerce_field_value, finalize_record
from sqlalchemy.ext.asyncio import AsyncSession


ResolveRunConfigFn = Callable[..., Awaitable[dict[str, object] | None]]
ExtractRecordsFn = Callable[..., Awaitable[tuple[list[dict[str, object]] | None, str | None]]]


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
        requested_fields=canonical_requested_fields(run.requested_fields or []),
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
        requested_fields=canonical_requested_fields(run.requested_fields or []),
    ) <= _record_set_quality_signature(
        records,
        surface=run.surface,
        requested_fields=canonical_requested_fields(run.requested_fields or []),
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
            requested_fields=canonical_requested_fields(run.requested_fields or []),
        )
        canonical_record["_self_heal"] = {
            "enabled": True,
            "triggered": True,
            "mode": "direct_record_extraction",
        }
        normalized_records.append(canonical_record)
    return normalized_records
