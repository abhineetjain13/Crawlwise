# Review and promotion service.
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord, CrawlRun, ReviewPromotion
from app.models.selector import Selector
from app.services.crawl_service import _normalize_committed_field_name, _refresh_record_commit_metadata
from app.services.knowledge_base.store import (
    get_domain_mapping,
    get_selector_defaults,
    save_domain_mapping,
)
from app.services.normalizers import normalize_value
from app.services.pipeline_config import REVIEW_CONTAINER_KEYS
from app.services.domain_utils import normalize_domain
from app.services.schema_service import load_resolved_schema, persist_resolved_schema
from app.services.xpath_service import extract_selector_value
from app.services.xpath_service import build_deterministic_selector_suggestions


async def build_review_payload(session: AsyncSession, run_id: int) -> dict | None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    records_result = await session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run_id))
    records = list(records_result.scalars().all())
    domain = _domain(run.url)
    selector_result = await session.execute(select(Selector).where(Selector.domain == domain))
    selectors = list(selector_result.scalars().all())
    canonical_fields = (await load_resolved_schema(session, run.surface, domain)).fields
    domain_mapping = get_domain_mapping(domain, run.surface)
    normalized_fields = sorted({
        key for record in records
        for key, val in _safe_dict(record.data).items()
        if val not in (None, "", [], {}) and not str(key).startswith("_")
    })
    discovered_field_names: set[str] = set()
    for record in records:
        for row in _review_bucket_rows(record):
            key = str(row.get("key") or "").strip()
            if key:
                discovered_field_names.add(key)
    if not discovered_field_names:
        for record in records:
            for src in (_safe_dict(record.discovered_data), _safe_dict(record.raw_data), _safe_dict(record.data)):
                for key, val in src.items():
                    if val not in (None, "", [], {}) and not str(key).startswith("_") and key not in REVIEW_CONTAINER_KEYS:
                        discovered_field_names.add(str(key))
    discovered_fields = sorted(discovered_field_names)
    suggested_mapping = {field: domain_mapping.get(field, field) for field in discovered_fields}
    selector_suggestions = _build_selector_suggestions(
        run,
        records,
        selectors,
        discovered_fields,
    )
    return {
        "run": run,
        "records": records,
        "normalized_fields": normalized_fields,
        "discovered_fields": discovered_fields,
        "canonical_fields": canonical_fields,
        "domain_mapping": domain_mapping,
        "suggested_mapping": suggested_mapping,
        "selector_memory": [
            {
                "field_name": row.field_name,
                "css_selector": row.css_selector,
                "xpath": row.xpath,
                "regex": row.regex,
                "status": row.status,
                "sample_value": row.sample_value,
                "source": row.source,
                "source_run_id": row.source_run_id,
                "is_active": row.is_active,
            }
            for row in selectors
        ],
        "selector_suggestions": selector_suggestions,
    }


async def load_review_html(session: AsyncSession, run_id: int) -> str:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return ""
    records_result = await session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run_id))
    records = list(records_result.scalars().all())
    return _load_review_html(records)


async def save_review(session: AsyncSession, run: CrawlRun, selections: list[dict]) -> dict:
    selected_rows = [
        row
        for row in selections
        if bool(row.get("selected", True))
        and str(row.get("source_field") or "").strip()
        and str(row.get("output_field") or "").strip()
    ]
    mapping = {
        str(row["source_field"]).strip(): str(row["output_field"]).strip()
        for row in selected_rows
    }
    domain = _domain(run.url)
    await save_domain_mapping(domain, run.surface, mapping)
    resolved_schema = await load_resolved_schema(session, run.surface, domain)
    next_fields = [
        *resolved_schema.fields,
        *[str(value or "").strip().lower() for value in mapping.values()],
    ]
    updated_schema = await persist_resolved_schema(
        session,
        resolved_schema.__class__(
            surface=resolved_schema.surface,
            domain=resolved_schema.domain,
            baseline_fields=list(resolved_schema.baseline_fields),
            fields=list(dict.fromkeys(field for field in next_fields if field)),
            new_fields=list(dict.fromkeys([
                *resolved_schema.new_fields,
                *[
                    str(value or "").strip().lower()
                    for value in mapping.values()
                    if str(value or "").strip().lower() not in set(resolved_schema.baseline_fields)
                ],
            ])),
            deprecated_fields=list(resolved_schema.deprecated_fields),
            source="review",
            confidence=1.0,
            saved_at=resolved_schema.saved_at,
            stale=False,
        ),
    )
    promotion = ReviewPromotion(
        run_id=run.id,
        domain=domain,
        surface=run.surface,
        approved_schema={
            "fields": updated_schema.fields,
            "baseline_fields": updated_schema.baseline_fields,
            "new_fields": updated_schema.new_fields,
            "deprecated_fields": updated_schema.deprecated_fields,
            "source": updated_schema.source,
            "confidence": updated_schema.confidence,
            "saved_at": updated_schema.saved_at,
        },
        field_mapping=mapping,
        selector_memory={},
    )
    session.add(promotion)
    await _promote_review_bucket_fields(session, run, mapping)
    await session.commit()
    return {
        "run_id": run.id,
        "domain": domain,
        "surface": run.surface,
        "selected_fields": list(dict.fromkeys(mapping.values())),
        "canonical_fields": updated_schema.fields,
        "field_mapping": mapping,
    }


async def preview_selectors(session: AsyncSession, run_id: int, selectors: list[dict]) -> dict | None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    records_result = await session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run_id))
    records = list(records_result.scalars().all())
    normalized_rules = _normalize_selector_rules(selectors)
    if not normalized_rules:
        return {"records": [_serialize_record(record) for record in records]}

    preview_records: list[dict] = []
    for record in records:
        html_text = _load_record_html(record)
        if not html_text:
            preview_records.append(_serialize_record(record))
            continue

        data = dict(_safe_dict(record.data))
        raw_data = dict(_safe_dict(record.raw_data))
        source_trace = dict(_safe_dict(record.source_trace))
        rerun_hits: list[dict] = []

        for rule in normalized_rules:
            value, count, selector_used = extract_selector_value(
                html_text,
                css_selector=rule.get("css_selector"),
                xpath=rule.get("xpath"),
                regex=rule.get("regex"),
            )
            if value in (None, "", [], {}):
                continue
            field_name = str(rule["field_name"])
            data[field_name] = normalize_value(field_name, value)
            raw_data[field_name] = value
            rerun_hits.append({
                "field_name": field_name,
                "matched_value": value,
                "count": count,
                "selector_used": selector_used,
                "xpath": rule.get("xpath"),
                "css_selector": rule.get("css_selector"),
                "regex": rule.get("regex"),
                "status": rule.get("status") or "manual",
                "source": rule.get("source") or "manual",
            })

        if rerun_hits:
            source_trace["selector_rerun"] = rerun_hits
        preview_records.append({
            **_serialize_record(record),
            "data": data,
            "raw_data": raw_data,
            "source_trace": source_trace,
        })

    return {"records": preview_records}


# Domain normalisation delegated to app.services.domain_utils.normalize_domain
_domain = normalize_domain


def _safe_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _build_selector_suggestions(
    run: CrawlRun,
    records: list[CrawlRecord],
    selectors: list[Selector],
    discovered_fields: list[str],
) -> dict[str, list[dict]]:
    if not run.surface.endswith("_detail"):
        return {}
    html_text = _load_review_html(records)
    if not html_text:
        return {}
    domain = _domain(run.url)
    target_fields = sorted(set(discovered_fields) | set(run.requested_fields or []))
    selector_defaults = {field_name: get_selector_defaults(domain, field_name) for field_name in target_fields}
    existing_candidates = _existing_candidate_rows(records)
    suggestions = build_deterministic_selector_suggestions(
        html_text,
        target_fields,
        existing_candidates=existing_candidates,
        selector_defaults=selector_defaults,
    )
    for selector in selectors:
        row = {
            "field_name": selector.field_name,
            "xpath": selector.xpath,
            "css_selector": selector.css_selector,
            "regex": selector.regex,
            "status": selector.status,
            "sample_value": selector.sample_value,
            "source": selector.source,
        }
        if not any([row["xpath"], row["css_selector"], row["regex"]]):
            continue
        suggestions.setdefault(selector.field_name, [])
        if row not in suggestions[selector.field_name]:
            suggestions[selector.field_name].insert(0, row)
    return suggestions


def _existing_candidate_rows(records: list[CrawlRecord]) -> dict[str, list[dict]]:
    aggregated: dict[str, list[dict]] = {}
    for record in records:
        source_trace = _safe_dict(record.source_trace)
        candidate_map = _safe_dict(source_trace.get("candidates"))
        suggestion_map = _safe_dict(source_trace.get("selector_suggestions"))
        for field_name, rows in candidate_map.items():
            if isinstance(rows, list):
                aggregated.setdefault(field_name, []).extend([row for row in rows if isinstance(row, dict)])
        for field_name, rows in suggestion_map.items():
            if isinstance(rows, list):
                aggregated.setdefault(field_name, []).extend([row for row in rows if isinstance(row, dict)])
    return aggregated


def _load_review_html(records: list[CrawlRecord]) -> str:
    for record in records:
        html = _load_record_html(record)
        if html:
            return html
    return ""


def _load_record_html(record: CrawlRecord) -> str:
    raw_path = str(record.raw_html_path or "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _normalize_selector_rules(selectors: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for row in selectors:
        field_name = str(row.get("field_name") or "").strip()
        xpath = str(row.get("xpath") or "").strip() or None
        css_selector = str(row.get("css_selector") or "").strip() or None
        regex = str(row.get("regex") or "").strip() or None
        if not field_name or not any([xpath, css_selector, regex]):
            continue
        key = (field_name, xpath, css_selector, regex)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "field_name": field_name,
            "xpath": xpath,
            "css_selector": css_selector,
            "regex": regex,
            "status": str(row.get("status") or "").strip() or None,
            "source": str(row.get("source") or "").strip() or None,
        })
    return normalized


def _serialize_record(record: CrawlRecord) -> dict:
    return {
        "id": record.id,
        "run_id": record.run_id,
        "source_url": record.source_url,
        "data": _safe_dict(record.data),
        "raw_data": _safe_dict(record.raw_data),
        "discovered_data": _safe_dict(record.discovered_data),
        "source_trace": _safe_dict(record.source_trace),
        "raw_html_path": record.raw_html_path,
        "created_at": record.created_at,
    }


def _review_bucket_rows(record: CrawlRecord) -> list[dict]:
    discovered_data = _safe_dict(record.discovered_data)
    rows = discovered_data.get("review_bucket")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


async def _promote_review_bucket_fields(session: AsyncSession, run: CrawlRun, mapping: dict[str, str]) -> None:
    if not mapping:
        return
    normalized_mapping = {
        _normalize_committed_field_name(source_field): _normalize_committed_field_name(target_field)
        for source_field, target_field in mapping.items()
        if _normalize_committed_field_name(source_field) and _normalize_committed_field_name(target_field)
    }
    if not normalized_mapping:
        return
    records_result = await session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run.id))
    records = list(records_result.scalars().all())
    for record in records:
        review_bucket = _review_bucket_rows(record)
        if not review_bucket:
            continue

        selected_values: dict[str, dict] = {}
        remaining_rows: list[dict] = []
        for row in review_bucket:
            source_field = _normalize_committed_field_name(row.get("key"))
            output_field = normalized_mapping.get(source_field)
            if not source_field or not output_field:
                remaining_rows.append(row)
                continue
            current_value = _safe_dict(record.data).get(output_field)
            if current_value not in (None, "", [], {}):
                remaining_rows.append(row)
                continue
            existing = selected_values.get(output_field)
            current_confidence = _safe_int(row.get("confidence_score"), 0)
            existing_confidence = _safe_int(existing.get("confidence_score"), 0) if existing else -1
            if existing is None or current_confidence > existing_confidence:
                selected_values[output_field] = row

        if not selected_values and len(remaining_rows) == len(review_bucket):
            continue

        data = dict(_safe_dict(record.data))
        for output_field, row in selected_values.items():
            normalized_value = normalize_value(output_field, row.get("value"))
            data[output_field] = normalized_value
        record.data = data

        discovered_data = dict(_safe_dict(record.discovered_data))
        mapped_source_fields = {
            source_field
            for source_field in normalized_mapping.keys()
            if source_field
        }
        discovered_data["review_bucket"] = [
            row for row in remaining_rows
            if _normalize_committed_field_name(row.get("key")) not in mapped_source_fields
            or _safe_dict(record.data).get(normalized_mapping.get(_normalize_committed_field_name(row.get("key")), ""))
            not in (None, "", [], {})
        ]
        record.discovered_data = {
            key: value
            for key, value in discovered_data.items()
            if value not in (None, "", [], {})
        }

        for output_field, row in selected_values.items():
            _refresh_record_commit_metadata(
                record,
                run=run,
                field_name=output_field,
                value=data[output_field],
                source_label="review_promotion",
            )
