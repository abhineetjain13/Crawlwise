from __future__ import annotations

from app.models.crawl import CrawlRecord, CrawlRun
from app.services.config.field_mappings import CANONICAL_SCHEMAS
from app.services.domain_utils import normalize_domain
from app.services.requested_field_policy import expand_requested_fields
from app.services.schema_service import load_resolved_schema
from sqlalchemy.ext.asyncio import AsyncSession


def get_canonical_fields(surface: str) -> list[str]:
    return list(CANONICAL_SCHEMAS.get(str(surface or "").strip(), []))


def _clean_candidate_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _compact_dict(payload: dict) -> dict:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }


def _clean_committed_value(value: object) -> str | None:
    return _clean_candidate_text(value) if value not in (None, "", [], {}) else None


def _merged_field_discovery_entry(
    existing_entry: dict,
    *,
    field_name: str,
    cleaned_value: str | None,
    source_label: str,
    canonical_fields: set[str],
) -> dict:
    existing_sources = existing_entry.get("sources") or []
    sources = {
        str(source).strip() for source in existing_sources if str(source).strip()
    }
    sources.add(source_label)
    return _compact_dict(
        {
            **existing_entry,
            "status": "found",
            "value": cleaned_value,
            "sources": sorted(sources),
            "is_canonical": existing_entry["is_canonical"]
            if "is_canonical" in existing_entry
            else field_name in canonical_fields,
        }
    )


def _field_discovery_missing_without(
    missing_fields: list[object],
    *,
    field_name: str,
) -> list[str]:
    return [
        str(item).strip()
        for item in missing_fields
        if str(item).strip() and str(item).strip() != field_name
    ]


def _prune_review_bucket_entries(
    review_bucket: object,
    *,
    field_name: str,
) -> list[object]:
    if not isinstance(review_bucket, list):
        return []
    return [
        row
        for row in review_bucket
        if not (
            isinstance(row, dict)
            and str(row.get("key") or "").strip() == field_name
        )
    ]


async def load_domain_requested_fields(
    session: AsyncSession, *, url: str, surface: str
) -> list[str]:
    resolved = await load_resolved_schema(session, surface, normalize_domain(url))
    return expand_requested_fields(list(resolved.new_fields))


def refresh_record_commit_metadata(
    record: CrawlRecord,
    *,
    run: CrawlRun,
    field_name: str,
    value: object,
    source_label: str = "user_commit",
) -> None:
    source_trace = dict(record.source_trace or {})
    field_discovery = dict(source_trace.get("field_discovery") or {})
    existing_entry = dict(field_discovery.get(field_name) or {})
    canonical_fields = set(get_canonical_fields(run.surface))
    cleaned_value = _clean_committed_value(value)
    field_discovery[field_name] = _merged_field_discovery_entry(
        existing_entry,
        field_name=field_name,
        cleaned_value=cleaned_value,
        source_label=source_label,
        canonical_fields=canonical_fields,
    )
    missing_fields = _field_discovery_missing_without(
        list(source_trace.get("field_discovery_missing") or []),
        field_name=field_name,
    )
    source_trace["field_discovery"] = field_discovery
    source_trace["field_discovery_missing"] = missing_fields

    committed_fields = dict(source_trace.get("committed_fields") or {})
    committed_fields[field_name] = {"value": cleaned_value, "source": source_label}
    source_trace["committed_fields"] = committed_fields
    record.source_trace = source_trace

    discovered_data = dict(record.discovered_data or {})
    review_bucket = _prune_review_bucket_entries(
        discovered_data.get("review_bucket"),
        field_name=field_name,
    )
    discovered_data["review_bucket"] = review_bucket
    requested_fields = list(run.requested_fields or [])
    if requested_fields:
        from app.services.pipeline.field_normalization import _requested_field_coverage

        discovered_data["requested_field_coverage"] = _requested_field_coverage(
            record.data or {}, requested_fields
        )
    record.discovered_data = _compact_dict(discovered_data)
