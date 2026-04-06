from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.domain_utils import normalize_domain
from app.services.knowledge_base.store import get_canonical_fields
from app.services.llm_runtime import run_prompt_task
from app.services.site_memory_service import get_memory, merge_memory

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
    confidence: float
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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


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
    stored_fields = _dedupe_fields(payload.get("fields") if isinstance(payload.get("fields"), list) else [])
    baseline = _dedupe_fields(payload.get("baseline_fields") if isinstance(payload.get("baseline_fields"), list) else baseline_fields)
    new_fields = _dedupe_fields(payload.get("new_fields") if isinstance(payload.get("new_fields"), list) else [])
    deprecated_fields = _dedupe_fields(payload.get("deprecated_fields") if isinstance(payload.get("deprecated_fields"), list) else [])
    fields = _dedupe_fields([*baseline, *stored_fields, *explicit_fields])
    if not new_fields:
        baseline_set = set(baseline)
        new_fields = [field for field in fields if field not in baseline_set]
    if not deprecated_fields:
        field_set = set(fields)
        deprecated_fields = [field for field in baseline if field not in field_set]
    return ResolvedSchema(
        surface=surface,
        domain=domain,
        baseline_fields=baseline,
        fields=fields,
        new_fields=new_fields,
        deprecated_fields=deprecated_fields,
        source=str(payload.get("source") or "static").strip() or "static",
        confidence=_safe_float(payload.get("confidence", 0.0)),
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
        "confidence": schema.confidence,
        "saved_at": schema.saved_at,
    }


async def load_resolved_schema(
    session: AsyncSession,
    surface: str,
    domain: str,
    *,
    explicit_fields: list[str] | None = None,
) -> ResolvedSchema:
    baseline_fields = _dedupe_fields(get_canonical_fields(surface))
    normalized_domain = normalize_domain(domain)
    normalized_explicit = _dedupe_fields(explicit_fields)
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
            confidence=1.0 if baseline_fields else 0.0,
            saved_at=None,
            stale=False,
        )
    memory = await get_memory(session, normalized_domain)
    payload = memory.payload if memory is not None and isinstance(memory.payload, dict) else {}
    schema_map = payload.get("schemas") if isinstance(payload.get("schemas"), dict) else {}
    snapshot = schema_map.get(surface)
    if not isinstance(snapshot, dict):
        legacy_fields = payload.get("fields") if isinstance(payload.get("fields"), list) else []
        if legacy_fields:
            snapshot = {
                "baseline_fields": baseline_fields,
                "fields": _dedupe_fields([*baseline_fields, *_dedupe_fields(legacy_fields)]),
                "new_fields": [field for field in _dedupe_fields(legacy_fields) if field not in set(baseline_fields)],
                "deprecated_fields": [],
                "source": "legacy",
                "confidence": 1.0,
                "saved_at": None,
            }
    return _snapshot_to_resolved(
        surface=surface,
        domain=normalized_domain,
        baseline_fields=baseline_fields,
        snapshot=snapshot,
        explicit_fields=normalized_explicit,
    )


async def persist_resolved_schema(session: AsyncSession, schema: ResolvedSchema) -> ResolvedSchema:
    schema.saved_at = schema.saved_at or _now_iso()
    schema.stale = False
    await merge_memory(
        session,
        schema.domain,
        fields=schema.new_fields,
        schemas={schema.surface: _schema_payload(schema)},
        last_crawl_at=datetime.now(UTC),
    )
    return schema


def learn_schema_from_record(
    *,
    surface: str,
    domain: str,
    baseline_fields: list[str],
    explicit_fields: list[str] | None = None,
    sample_record: dict | None = None,
) -> ResolvedSchema:
    baseline = _dedupe_fields(baseline_fields)
    explicit = _dedupe_fields(explicit_fields)
    record = sample_record if isinstance(sample_record, dict) else {}
    discovered_new_fields: list[str] = []
    baseline_set = set(baseline)
    for key, value in record.items():
        normalized = _normalize_field_name(key)
        if (
            not is_valid_schema_field_name(normalized)
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
        deprecated_fields=[field for field in baseline if field not in record or record.get(field) in (None, "", [], {})],
        source="learned",
        confidence=0.75,
        saved_at=_now_iso(),
        stale=False,
    )


def _prune_html_for_schema_llm(html: str, max_chars: int = 3500) -> str:
    stripped = re.sub(r"<(script|style|svg|noscript)\b[^>]*>.*?</\1\s*>", "", html, flags=re.IGNORECASE | re.DOTALL)
    stripped = re.sub(r"<!--.*?-->", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"\s{3,}", "  ", stripped)
    return stripped[:max_chars]


async def _infer_schema_via_llm(
    session: AsyncSession,
    *,
    surface: str,
    domain: str,
    baseline_fields: list[str],
    explicit_fields: list[str],
    html: str,
    run_id: int | None,
    url: str,
) -> ResolvedSchema | None:
    if not html or surface == "tabular":
        return None
    result = await asyncio.wait_for(
        run_prompt_task(
            session,
            task_type="schema_inference",
            run_id=run_id,
            domain=domain,
            variables={
                "url": url,
                "surface": surface,
                "baseline_fields_json": json.dumps(baseline_fields),
                "html_snippet": _prune_html_for_schema_llm(html),
            },
        ),
        timeout=12.0,
    )
    if result.error_message or not isinstance(result.payload, dict):
        logger.warning(
            "Schema inference LLM unavailable for surface=%s domain=%s: %s",
            surface,
            domain,
            result.error_message or "non-dict payload",
        )
        return None
    payload = result.payload
    confirmed_fields = [
        field for field in _dedupe_fields(payload.get("confirmed_fields") if isinstance(payload.get("confirmed_fields"), list) else [])
        if field in set(baseline_fields)
    ]
    inferred_new_fields = [
        field for field in _dedupe_fields(payload.get("new_fields") if isinstance(payload.get("new_fields"), list) else [])
        if is_valid_schema_field_name(field) and field not in set(baseline_fields)
    ]
    absent_fields = [
        field for field in _dedupe_fields(payload.get("absent_fields") if isinstance(payload.get("absent_fields"), list) else [])
        if field in set(baseline_fields)
    ]
    if not confirmed_fields and not inferred_new_fields and not absent_fields:
        return None
    fields = _dedupe_fields([*baseline_fields, *confirmed_fields, *inferred_new_fields, *explicit_fields])
    return ResolvedSchema(
        surface=surface,
        domain=domain,
        baseline_fields=_dedupe_fields(baseline_fields),
        fields=fields,
        new_fields=[field for field in fields if field not in set(baseline_fields)],
        deprecated_fields=absent_fields,
        source="llm_inferred",
        confidence=0.6,
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
    resolved = await load_resolved_schema(
        session,
        surface,
        domain,
        explicit_fields=explicit_fields,
    )
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
        if (not resolved.saved_at or resolved.stale) and llm_enabled and "detail" in surface and html:
            inferred = await _infer_schema_via_llm(
                session,
                surface=surface,
                domain=resolved.domain,
                baseline_fields=resolved.baseline_fields,
                explicit_fields=_dedupe_fields(explicit_fields),
                html=html,
                run_id=run_id,
                url=url,
            )
            if inferred is not None:
                return await persist_resolved_schema(session, inferred)
    except Exception:
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
        "confidence": schema.confidence,
        "saved_at": schema.saved_at,
        "stale": schema.stale,
    }
