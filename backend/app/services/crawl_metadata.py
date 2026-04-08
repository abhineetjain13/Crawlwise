from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord, CrawlRun
from app.services.domain_utils import normalize_domain
from app.services.knowledge_base.store import get_canonical_fields
from app.services.requested_field_policy import expand_requested_fields
from app.services.schema_service import load_resolved_schema


def _clean_candidate_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _compact_dict(payload: dict) -> dict:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }


def _requested_field_coverage(
    output_record: dict | None,
    requested_fields: list[str] | None,
) -> dict:
    requested = [field for field in (requested_fields or []) if str(field).strip()]
    if not requested:
        return {"requested": 0, "found": 0, "missing": []}
    output = output_record if isinstance(output_record, dict) else {}
    found = [
        field
        for field in requested
        if output.get(field) not in (None, "", [], {})
    ]
    missing = [field for field in requested if field not in found]
    return {"requested": len(requested), "found": len(found), "missing": missing}


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
    existing_sources = existing_entry.get("sources") or []
    sources = {
        str(source).strip() for source in existing_sources if str(source).strip()
    }
    sources.add(source_label)
    canonical_fields = set(get_canonical_fields(run.surface))
    field_discovery[field_name] = _compact_dict(
        {
            **existing_entry,
            "status": "found",
            "value": _clean_candidate_text(value)
            if value not in (None, "", [], {})
            else None,
            "sources": sorted(sources),
            "is_canonical": existing_entry["is_canonical"]
            if "is_canonical" in existing_entry
            else field_name in canonical_fields,
        }
    )
    missing_fields = [
        str(item).strip()
        for item in (source_trace.get("field_discovery_missing") or [])
        if str(item).strip() and str(item).strip() != field_name
    ]
    source_trace["field_discovery"] = field_discovery
    source_trace["field_discovery_missing"] = missing_fields

    committed_fields = dict(source_trace.get("committed_fields") or {})
    committed_fields[field_name] = {"value": value, "source": source_label}
    source_trace["committed_fields"] = committed_fields
    record.source_trace = source_trace

    discovered_data = dict(record.discovered_data or {})
    review_bucket = (
        discovered_data.get("review_bucket")
        if isinstance(discovered_data.get("review_bucket"), list)
        else []
    )
    if review_bucket:
        discovered_data["review_bucket"] = [
            row
            for row in review_bucket
            if not (
                isinstance(row, dict)
                and str(row.get("key") or "").strip() == field_name
            )
        ]
    requested_fields = list(run.requested_fields or [])
    if requested_fields:
        discovered_data["requested_field_coverage"] = _requested_field_coverage(
            record.data or {}, requested_fields
        )
    record.discovered_data = _compact_dict(discovered_data)
