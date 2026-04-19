# Review and promotion service.
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.models.crawl import CrawlRecord, CrawlRun, ReviewPromotion
from app.services.config.extraction_rules import REVIEW_CONTAINER_KEYS
from app.services.publish import refresh_record_commit_metadata
from app.services.crawl_utils import normalize_committed_field_name
from app.services.domain_utils import normalize_domain
from app.services.normalizers import normalize_value
from app.services.field_policy import normalize_review_target
from app.services.schema_service import load_resolved_schema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _load_domain_mapping(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> dict[str, str]:
    result = await session.execute(
        select(ReviewPromotion.field_mapping)
        .where(
            ReviewPromotion.domain == domain,
            ReviewPromotion.surface == surface,
        )
        .order_by(ReviewPromotion.created_at.desc(), ReviewPromotion.id.desc())
        .limit(1)
    )
    mapping = result.scalar_one_or_none()
    return dict(mapping) if isinstance(mapping, dict) else {}


async def build_review_payload(session: AsyncSession, run_id: int) -> dict | None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    records_result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run_id)
    )
    records = list(records_result.scalars().all())
    domain = _domain(run.url)
    canonical_fields = (await load_resolved_schema(session, run.surface, domain)).fields
    domain_mapping = await _load_domain_mapping(
        session,
        domain=domain,
        surface=run.surface,
    )
    normalized_fields = sorted(
        {
            key
            for record in records
            for key, val in _safe_dict(record.data).items()
            if val not in (None, "", [], {}) and not str(key).startswith("_")
        }
    )
    discovered_field_names: set[str] = set()
    for record in records:
        for row in _review_bucket_rows(record):
            key = str(row.get("key") or "").strip()
            if key:
                discovered_field_names.add(key)
    if not discovered_field_names:
        for record in records:
            for src in (
                _safe_dict(record.discovered_data),
                _safe_dict(record.raw_data),
                _safe_dict(record.data),
            ):
                for key, val in src.items():
                    if (
                        val not in (None, "", [], {})
                        and not str(key).startswith("_")
                        and key not in REVIEW_CONTAINER_KEYS
                    ):
                        discovered_field_names.add(str(key))
    discovered_fields = sorted(discovered_field_names)
    suggested_mapping = {
        field: domain_mapping.get(field, field) for field in discovered_fields
    }
    return {
        "run": run,
        "records": records,
        "normalized_fields": normalized_fields,
        "discovered_fields": discovered_fields,
        "canonical_fields": canonical_fields,
        "domain_mapping": domain_mapping,
        "suggested_mapping": suggested_mapping,
    }


async def load_review_html(session: AsyncSession, run_id: int) -> str:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return ""
    records_result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run_id)
    )
    records = list(records_result.scalars().all())
    return _load_review_html(records)


async def save_review(
    session: AsyncSession, run: CrawlRun, selections: list[dict]
) -> dict:
    selected_rows = [
        row
        for row in selections
        if bool(row.get("selected", True))
        and str(row.get("source_field") or "").strip()
        and str(row.get("output_field") or "").strip()
    ]
    domain = _domain(run.url)
    mapping: dict[str, str] = {}
    for row in selected_rows:
        source_field = normalize_committed_field_name(row.get("source_field"))
        target_field = normalize_review_target(run.surface, row.get("output_field"))
        if source_field and target_field:
            mapping[source_field] = target_field
    resolved_schema = await load_resolved_schema(session, run.surface, domain)
    next_fields = [
        *resolved_schema.fields,
        *list(mapping.values()),
    ]
    normalized_baseline_fields = list(
        dict.fromkeys(
            normalized_field
            for field in resolved_schema.baseline_fields
            if (
                normalized_field := normalize_review_target(run.surface, field)
            )
        )
    )
    normalized_new_fields = list(
        dict.fromkeys(
            normalized_field
            for field in resolved_schema.new_fields
            if (
                normalized_field := normalize_review_target(run.surface, field)
            )
        )
    )
    normalized_baseline_field_set = set(normalized_baseline_fields)
    updated_schema = resolved_schema.__class__(
        surface=resolved_schema.surface,
        domain=resolved_schema.domain,
        baseline_fields=normalized_baseline_fields,
        fields=list(dict.fromkeys(field for field in next_fields if field)),
        new_fields=list(
            dict.fromkeys(
                [
                    *normalized_new_fields,
                    *[
                        normalized_value
                        for value in mapping.values()
                        if (
                            normalized_value := normalize_review_target(
                                run.surface, value
                            )
                        )
                        not in normalized_baseline_field_set
                    ],
                ]
            )
        ),
        deprecated_fields=list(resolved_schema.deprecated_fields),
        source="review",
        saved_at=None,
        stale=False,
    )
    db_run = await session.get(CrawlRun, run.id)
    if db_run is None:
        raise RuntimeError(f"CrawlRun not found for review save: run_id={run.id}")
    saved_at = datetime.now(UTC).isoformat()
    promotion = ReviewPromotion(
        run_id=db_run.id,
        domain=domain,
        surface=db_run.surface,
        approved_schema={
            "fields": updated_schema.fields,
            "baseline_fields": updated_schema.baseline_fields,
            "new_fields": updated_schema.new_fields,
            "deprecated_fields": updated_schema.deprecated_fields,
            "source": updated_schema.source,
            "saved_at": saved_at,
        },
        field_mapping=mapping,
    )
    session.add(promotion)
    await _promote_review_bucket_fields(session, db_run, mapping)
    await session.commit()
    return {
        "run_id": run.id,
        "domain": domain,
        "surface": run.surface,
        "selected_fields": list(dict.fromkeys(mapping.values())),
        "canonical_fields": updated_schema.fields,
        "field_mapping": mapping,
    }


# Domain normalisation delegated to app.services.domain_utils.normalize_domain
_domain = normalize_domain


def _safe_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


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


async def _promote_review_bucket_fields(
    session: AsyncSession, run: CrawlRun, mapping: dict[str, str]
) -> None:
    if not mapping:
        return
    normalized_mapping = {
        normalize_committed_field_name(source_field): normalize_committed_field_name(
            target_field
        )
        for source_field, target_field in mapping.items()
        if normalize_committed_field_name(source_field)
        and normalize_committed_field_name(target_field)
    }
    if not normalized_mapping:
        return
    records_result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )
    records = list(records_result.scalars().all())
    for record in records:
        review_bucket = _review_bucket_rows(record)
        if not review_bucket:
            continue

        selected_values: dict[str, dict] = {}
        remaining_rows: list[dict] = []
        for row in review_bucket:
            source_field = normalize_committed_field_name(row.get("key"))
            output_field = normalized_mapping.get(source_field)
            if not source_field or not output_field:
                remaining_rows.append(row)
                continue
            current_value = _safe_dict(record.data).get(output_field)
            if current_value not in (None, "", [], {}):
                remaining_rows.append(row)
                continue
            existing = selected_values.get(output_field)
            if existing is None:
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
            source_field for source_field in normalized_mapping.keys() if source_field
        }
        discovered_data["review_bucket"] = [
            row
            for row in remaining_rows
            if normalize_committed_field_name(row.get("key"))
            not in mapped_source_fields
            or _safe_dict(record.data).get(
                normalized_mapping.get(
                    normalize_committed_field_name(row.get("key")), ""
                )
            )
            not in (None, "", [], {})
        ]
        record.discovered_data = {
            key: value
            for key, value in discovered_data.items()
            if value not in (None, "", [], {})
        }

        for output_field, _row in selected_values.items():
            refresh_record_commit_metadata(
                record,
                run=run,
                field_name=output_field,
                value=data[output_field],
                source_label="review_promotion",
            )
