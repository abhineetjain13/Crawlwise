from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.services.config.field_mappings import (
    ECOMMERCE_ONLY_FIELDS,
    INTERNAL_ONLY_FIELDS,
    JOB_ONLY_FIELDS,
)
from app.services.domain_utils import normalize_domain
from app.services.knowledge_base.store import get_canonical_fields
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_NUMERIC_ONLY_RE = re.compile(r"^\d+$")
_MAX_SCHEMA_AGE = timedelta(days=7)


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


def is_valid_schema_field_name(name: str) -> bool:
    normalized = str(name or "").strip().lower()
    return bool(
        normalized
        and _FIELD_NAME_RE.match(normalized)
        and not _NUMERIC_ONLY_RE.match(normalized)
        and "__" not in normalized
        and not normalized.startswith("_")
    )


def _normalize_field_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    normalized = re.sub(r"\s+", "_", text.lower())
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _dedupe_fields(values: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = str(value or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return deduped


def _supports_record_learning(surface: str) -> bool:
    normalized = str(surface or "").strip().lower()
    return normalized not in {"job_listing", "job_detail"}


def _field_allowed_for_surface(surface: str, field_name: str) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    normalized_field = str(field_name or "").strip().lower()
    if not normalized_field or normalized_field in INTERNAL_ONLY_FIELDS:
        return False
    if normalized_surface in {"job_listing", "job_detail"}:
        return normalized_field not in ECOMMERCE_ONLY_FIELDS
    if normalized_surface in {"ecommerce_listing", "ecommerce_detail"}:
        return normalized_field not in JOB_ONLY_FIELDS
    return True


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
    stale = bool(saved_at_dt and datetime.now(UTC) - saved_at_dt > _MAX_SCHEMA_AGE)
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
        stored_field_set = set(stored_fields)
        deprecated_fields = [field for field in baseline if field not in stored_field_set]
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


def _schema_payload(schema: ResolvedSchema) -> dict:
    return {
        "baseline_fields": list(schema.baseline_fields),
        "fields": list(schema.fields),
        "new_fields": list(schema.new_fields),
        "deprecated_fields": list(schema.deprecated_fields),
        "source": schema.source,
        "saved_at": schema.saved_at,
    }


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


def learn_schema_from_record(
    *,
    surface: str,
    domain: str,
    baseline_fields: list[str],
    explicit_fields: list[str] | None = None,
    sample_record: dict | None = None,
) -> ResolvedSchema:
    baseline = _dedupe_fields(
        field
        for field in baseline_fields
        if _field_allowed_for_surface(surface, field)
    )
    explicit = _dedupe_fields(
        field
        for field in (explicit_fields or [])
        if _field_allowed_for_surface(surface, field)
    )
    record = sample_record if isinstance(sample_record, dict) else {}
    normalized_record_values: dict[str, object] = {}
    discovered_new_fields: list[str] = []
    baseline_set = set(baseline)
    allow_record_learning = _supports_record_learning(surface)
    for key, value in record.items():
        normalized = _normalize_field_name(key)
        if normalized and normalized not in normalized_record_values:
            normalized_record_values[normalized] = value
        if (
            not allow_record_learning
            or
            not is_valid_schema_field_name(normalized)
            or not _field_allowed_for_surface(surface, normalized)
            or normalized in baseline_set
            or normalized in discovered_new_fields
            or value in (None, "", [], {})
            or isinstance(value, (dict, list))
        ):
            continue
        discovered_new_fields.append(normalized)
    fields = _dedupe_fields([*baseline, *discovered_new_fields, *explicit])
    return ResolvedSchema(
        surface=surface,
        domain=domain,
        baseline_fields=baseline,
        fields=fields,
        new_fields=[field for field in fields if field not in baseline_set],
        deprecated_fields=[
            field
            for field in baseline
            if field not in normalized_record_values or normalized_record_values.get(field) in (None, "", [], {})
        ],
        source="learned",
        saved_at=_now_iso(),
        stale=False,
    )


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
    del run_id, html, url, llm_enabled
    resolved = await load_resolved_schema(
        session,
        surface,
        domain,
        explicit_fields=explicit_fields,
    )
    if not _supports_record_learning(surface):
        return resolved
    if not resolved.domain:
        return resolved
    try:
        if (not resolved.saved_at or resolved.stale) and isinstance(sample_record, dict) and sample_record:
            learned = learn_schema_from_record(
                surface=surface,
                domain=resolved.domain,
                baseline_fields=resolved.baseline_fields,
                explicit_fields=explicit_fields,
                sample_record=sample_record,
            )
            return await persist_resolved_schema(session, learned)
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        logger.exception(
            "Schema resolution enrichment failed for surface=%s domain=%s; returning fallback resolved schema",
            surface,
            resolved.domain,
            extra={"resolved": _schema_payload(resolved)},
        )
        return resolved
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
