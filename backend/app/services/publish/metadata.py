from __future__ import annotations

from app.models.crawl import ReviewPromotion
from app.services.domain_utils import normalize_domain
from app.services.field_policy import canonical_requested_fields
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def load_domain_requested_fields(
    session: AsyncSession,
    *,
    url: str,
    surface: str,
) -> list[str]:
    domain = normalize_domain(url)
    if not domain:
        return []
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
    if not isinstance(mapping, dict):
        return []
    fields: list[str] = []
    seen: set[str] = set()
    for value in mapping.values():
        name = str(value or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        fields.append(name)
    return fields


def refresh_record_commit_metadata(
    record,
    *,
    run,
    field_name: str,
    value: object,
    source_label: str = "user_commit",
    preserve_existing_sources: bool = False,
) -> None:
    normalized_field = str(field_name or "").strip().lower()
    if not normalized_field:
        return
    source_trace = dict(record.source_trace or {})
    field_discovery = dict(source_trace.get("field_discovery") or {})
    existing = field_discovery.get(normalized_field)
    sources: list[str]
    if preserve_existing_sources and isinstance(existing, dict):
        existing_sources = existing.get("sources")
        if isinstance(existing_sources, list) and existing_sources:
            sources = [str(item) for item in existing_sources]
        else:
            sources = [source_label]
    else:
        sources = [source_label]
    next_payload: dict[str, object] = {
        "status": "found",
        "value": _stringify_value(value),
        "sources": sources,
    }
    if isinstance(existing, dict) and isinstance(existing.get("selector_trace"), dict):
        next_payload["selector_trace"] = dict(existing["selector_trace"])
    field_discovery[normalized_field] = next_payload
    source_trace["field_discovery"] = field_discovery

    requested_fields = canonical_requested_fields(run.requested_fields or [])
    found_fields = {
        key
        for key, payload in field_discovery.items()
        if isinstance(payload, dict) and payload.get("status") == "found"
    }
    missing = [item for item in requested_fields if item and item not in found_fields]
    if missing:
        source_trace["field_discovery_missing"] = missing
    else:
        source_trace.pop("field_discovery_missing", None)
    record.source_trace = source_trace

    discovered_data = dict(record.discovered_data or {})
    if requested_fields:
        discovered_data["requested_field_coverage"] = {
            "requested": len(requested_fields),
            "found": len([item for item in requested_fields if item in found_fields]),
            "missing": missing,
        }
    record.discovered_data = discovered_data


def _stringify_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return str(value)
    if value is None:
        return ""
    return str(value)
