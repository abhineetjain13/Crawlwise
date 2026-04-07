# Review and promotion service.
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord, CrawlRun, ReviewPromotion
from app.services.crawl_service import _normalize_committed_field_name, _refresh_record_commit_metadata
from app.services.knowledge_base.store import (
    get_domain_mapping,
    save_domain_mapping,
)
from app.services.normalizers import normalize_value
from app.services.pipeline_config import REVIEW_CONTAINER_KEYS
from app.services.domain_utils import normalize_domain
from app.services.schema_service import load_resolved_schema, persist_resolved_schema


async def build_review_payload(session: AsyncSession, run_id: int) -> dict | None:
    """Build a review payload for a crawl run, including records and field mappings.
    Parameters:
        - session (AsyncSession): Database session used to load the crawl run and related records.
        - run_id (int): Identifier of the crawl run to build the payload for.
    Returns:
        - dict | None: A payload containing the run, records, normalized fields, discovered fields, canonical fields, domain mapping, and suggested mapping, or None if the run is not found."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    records_result = await session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run_id))
    records = list(records_result.scalars().all())
    domain = _domain(run.url)
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
    records_result = await session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run_id))
    records = list(records_result.scalars().all())
    return _load_review_html(records)


async def save_review(session: AsyncSession, run: CrawlRun, selections: list[dict]) -> dict:
    """Persist a review’s selected field mappings and promote the resolved schema.
    Parameters:
        - session (AsyncSession): Database session used to load, update, and commit schema data.
        - run (CrawlRun): The crawl run associated with the review and target domain.
        - selections (list[dict]): Review rows containing source and output field mappings, with optional selection flags.
    Returns:
        - dict: A summary containing the run ID, domain, surface, selected fields, canonical fields, and saved field mapping."""
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
            "saved_at": updated_schema.saved_at,
        },
        field_mapping=mapping,
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
    """Load the raw HTML content for a crawl record from disk.
    Parameters:
        - record (CrawlRecord): The crawl record containing the path to the raw HTML file.
    Returns:
        - str: The file contents as a string, or an empty string if the path is missing, invalid, or unreadable."""
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
    """Serialize a CrawlRecord instance into a JSON-serializable dictionary.
    Parameters:
        - record (CrawlRecord): The crawl record to serialize.
    Returns:
        - dict: A dictionary containing the record's fields and safely converted nested data."""
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


async def _promote_review_bucket_fields(session: AsyncSession, run: CrawlRun, mapping: dict[str, str]) -> None:
    """Promote selected review bucket fields into a record's committed data and update review metadata.
    Parameters:
        - session (AsyncSession): Database session used to load and persist crawl records.
        - run (CrawlRun): The crawl run whose records will be processed.
        - mapping (dict[str, str]): Mapping of source field names in the review bucket to target committed field names.
    Returns:
        - None: This function updates records in place and returns nothing."""
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
