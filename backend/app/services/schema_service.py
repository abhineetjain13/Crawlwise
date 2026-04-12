from __future__ import annotations
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.services.config.field_mappings import (
    CANONICAL_SCHEMAS,
    field_allowed_for_surface as _field_allowed_for_surface,
)
from app.services.domain_utils import normalize_domain
from app.services.pipeline.pipeline_config import SCHEMA_MAX_AGE_DAYS
from sqlalchemy.ext.asyncio import AsyncSession

_SCHEMA_MAX_AGE = timedelta(days=SCHEMA_MAX_AGE_DAYS)


def get_canonical_fields(surface: str) -> list[str]:
    return list(CANONICAL_SCHEMAS.get(str(surface or "").strip().lower(), []))


@dataclass
class ResolvedSchema:
    surface: str
    domain: str
    baseline_fields: list[str]
    fields: list[str]
    new_fields: list[str]
    deprecated_fields: list[str]
    source: str
    saved_at: str | None
    stale: bool


def _dedupe_fields(values: Iterable[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = str(value or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return deduped
def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_saved_at(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _snapshot_to_resolved(
    *,
    surface: str,
    domain: str,
    baseline_fields: list[str],
    snapshot: dict | None,
    explicit_fields: list[str],
) -> ResolvedSchema:
    payload = snapshot if isinstance(snapshot, dict) else {}
    saved_at = str(payload.get("saved_at") or "").strip() or None
    saved_at_dt = _parse_saved_at(saved_at)
    stale = bool(saved_at_dt and datetime.now(UTC) - saved_at_dt > _SCHEMA_MAX_AGE)
    stored_fields = _dedupe_fields(
        field
        for field in (
            payload.get("fields") if isinstance(payload.get("fields"), list) else []
        )
        if _field_allowed_for_surface(surface, field)
    )
    baseline = _dedupe_fields(
        field
        for field in (
            payload.get("baseline_fields")
            if isinstance(payload.get("baseline_fields"), list)
            else baseline_fields
        )
        if _field_allowed_for_surface(surface, field)
    )
    new_fields = _dedupe_fields(
        field
        for field in (
            payload.get("new_fields") if isinstance(payload.get("new_fields"), list) else []
        )
        if _field_allowed_for_surface(surface, field)
    )
    deprecated_fields = _dedupe_fields(
        field
        for field in (
            payload.get("deprecated_fields")
            if isinstance(payload.get("deprecated_fields"), list)
            else []
        )
        if _field_allowed_for_surface(surface, field)
    )
    fields = _dedupe_fields(
        field
        for field in [*baseline, *stored_fields, *explicit_fields]
        if _field_allowed_for_surface(surface, field)
    )
    if not new_fields:
        baseline_set = set(baseline)
        new_fields = [field for field in fields if field not in baseline_set]
    if not deprecated_fields:
        if stored_fields:
            stored_field_set = set(stored_fields)
            deprecated_fields = [
                field for field in baseline if field not in stored_field_set
            ]
        else:
            deprecated_fields = []
    return ResolvedSchema(
        surface=surface,
        domain=domain,
        baseline_fields=baseline,
        fields=fields,
        new_fields=new_fields,
        deprecated_fields=deprecated_fields,
        source=str(payload.get("source") or "static").strip() or "static",
        saved_at=saved_at,
        stale=stale,
    )


async def load_resolved_schema(
    session: AsyncSession,
    surface: str,
    domain: str,
    *,
    explicit_fields: list[str] | None = None,
) -> ResolvedSchema:
    del session
    baseline_fields = _dedupe_fields(
        field
        for field in get_canonical_fields(surface)
        if _field_allowed_for_surface(surface, field)
    )
    normalized_domain = normalize_domain(domain)
    normalized_explicit = _dedupe_fields(
        field
        for field in (explicit_fields or [])
        if _field_allowed_for_surface(surface, field)
    )
    if not normalized_domain:
        fields = _dedupe_fields([*baseline_fields, *normalized_explicit])
        return ResolvedSchema(
            surface=surface,
            domain="",
            baseline_fields=baseline_fields,
            fields=fields,
            new_fields=[field for field in fields if field not in set(baseline_fields)],
            deprecated_fields=[],
            source="static",
            saved_at=None,
            stale=False,
        )
    return _snapshot_to_resolved(
        surface=surface,
        domain=normalized_domain,
        baseline_fields=baseline_fields,
        snapshot=None,
        explicit_fields=normalized_explicit,
    )


async def persist_resolved_schema(session: AsyncSession, schema: ResolvedSchema) -> ResolvedSchema:
    del session
    schema.saved_at = schema.saved_at or _now_iso()
    schema.stale = False
    return schema


async def resolve_schema(
    session: AsyncSession,
    surface: str,
    domain: str,
    *,
    run_id: int | None = None,
    explicit_fields: list[str] | None = None,
    html: str = "",
    url: str = "",
    sample_record: dict | None = None,
    llm_enabled: bool = False,
) -> ResolvedSchema:
    del run_id, html, url, sample_record, llm_enabled
    resolved = await load_resolved_schema(
        session,
        surface,
        domain,
        explicit_fields=explicit_fields,
    )
    return resolved


def schema_trace_payload(schema: ResolvedSchema) -> dict:
    return {
        "surface": schema.surface,
        "domain": schema.domain,
        "baseline_fields": list(schema.baseline_fields),
        "resolved_fields": list(schema.fields),
        "new_fields": list(schema.new_fields),
        "deprecated_fields": list(schema.deprecated_fields),
        "source": schema.source,
        "saved_at": schema.saved_at,
        "stale": schema.stale,
    }
