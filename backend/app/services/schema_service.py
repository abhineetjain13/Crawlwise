from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import re
import warnings

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.domain_utils import normalize_domain
from app.services.knowledge_base.store import get_canonical_fields

logger = logging.getLogger(__name__)

_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_NUMERIC_ONLY_RE = re.compile(r"^\d+$")
_MAX_SCHEMA_AGE = timedelta(days=7)


@dataclass
class ResolvedSchema:
    """
    Represents a resolved schema snapshot, including current, baseline, new, and deprecated fields.
    Parameters:
        - surface (str): The surface or entity the schema applies to.
        - domain (str): The domain associated with the schema.
        - baseline_fields (list[str]): The original field set used for comparison.
        - fields (list[str]): The current resolved field list.
        - new_fields (list[str]): Fields newly introduced in the resolved schema.
        - deprecated_fields (list[str]): Fields no longer present in the resolved schema.
        - source (str): The source from which the schema was resolved.
        - saved_at (str | None): Timestamp indicating when the schema was saved, if available.
        - stale (bool): Indicates whether the schema snapshot is outdated.
    Processing Logic:
        - Tracks schema changes by comparing current fields against a baseline.
        - Preserves metadata needed to identify the schema source and recency.
        - Marks whether the schema should be treated as stale.
    """
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
    """Check whether a string is a valid schema field name.
    Parameters:
        - name (str): The field name to validate.
    Returns:
        - bool: True if the name is non-empty, matches the allowed pattern, is not numeric-only, does not contain double underscores, and does not start with an underscore; otherwise False."""
    normalized = str(name or "").strip().lower()
    return bool(
        normalized
        and _FIELD_NAME_RE.match(normalized)
        and not _NUMERIC_ONLY_RE.match(normalized)
        and "__" not in normalized
        and not normalized.startswith("_")
    )


def _normalize_field_name(value: object) -> str:
    """Normalize a value into a lowercase, snake_case field name.
    Parameters:
        - value (object): The input value to normalize into a field name.
    Returns:
        - str: A normalized snake_case string, or an empty string if the input is blank."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    normalized = re.sub(r"\s+", "_", text.lower())
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _dedupe_fields(values: list[str] | None) -> list[str]:
    """Deduplicate and normalize a list of string values.
    Parameters:
        - values (list[str] | None): Input list of values to deduplicate; None is treated as an empty list.
    Returns:
        - list[str]: A list of unique, lowercased, stripped string values in their original order."""
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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_saved_at(value: object) -> datetime | None:
    """Parse a saved-at value into a datetime object.
    Parameters:
        - value (object): Input value to parse, typically a string-like timestamp.
    Returns:
        - datetime | None: Parsed datetime if the value is a valid ISO-formatted timestamp, otherwise None."""
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
    """Resolve a schema snapshot into a normalized ResolvedSchema object.
    Parameters:
        - surface (str): Surface name for the schema.
        - domain (str): Domain name for the schema.
        - baseline_fields (list[str]): Default baseline field names.
        - snapshot (dict | None): Stored snapshot data, or None if unavailable.
        - explicit_fields (list[str]): Additional fields to include explicitly.
    Returns:
        - ResolvedSchema: Normalized schema data including fields, new/deprecated fields, source, saved time, and staleness."""
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
    """Build a dictionary payload from a resolved schema's field metadata.
    Parameters:
        - schema (ResolvedSchema): The resolved schema to serialize into a payload dictionary.
    Returns:
        - dict: A dictionary containing baseline, current, new, deprecated fields, source, and saved timestamp."""
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
    """Resolve and return a schema for a given surface and domain.
    Parameters:
        - session (AsyncSession): Database session parameter, unused in this implementation.
        - surface (str): The surface name used to look up canonical fields.
        - domain (str): The domain to normalize and resolve the schema for.
        - explicit_fields (list[str] | None): Optional additional fields to include in the resolved schema.
    Returns:
        - ResolvedSchema: The resolved schema object for the specified surface and domain."""
    del session
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
    """Learn and resolve a schema from baseline fields, optional explicit fields, and an optional sample record.
    Parameters:
        - surface (str): The target surface used to determine whether record-based learning is allowed.
        - domain (str): The schema domain for the resolved schema.
        - baseline_fields (list[str]): The initial set of fields to preserve and compare against.
        - explicit_fields (list[str] | None): Additional fields to include explicitly, if provided.
        - sample_record (dict | None): Optional record used to discover new fields and mark deprecated ones.
    Returns:
        - ResolvedSchema: A resolved schema containing merged fields, newly discovered fields, deprecated fields, and metadata."""
    baseline = _dedupe_fields(baseline_fields)
    explicit = _dedupe_fields(explicit_fields)
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
    """Resolve and optionally enrich a schema for a given surface and domain.
    Parameters:
        - session (AsyncSession): Database session used to load and persist schema data.
        - surface (str): The target surface for schema resolution.
        - domain (str): The target domain for schema resolution.
        - run_id (int | None): Unused; accepted for compatibility.
        - explicit_fields (list[str] | None): Optional list of fields to force into the resolved schema.
        - html (str): Unused; accepted for compatibility.
        - url (str): Unused; accepted for compatibility.
        - sample_record (dict | None): Optional record used to learn and enrich the schema.
        - llm_enabled (bool): Deprecated flag; if True, emits a warning and falls back to deterministic resolution.
    Returns:
        - ResolvedSchema: The resolved schema, optionally enriched and persisted based on the sample record."""
    del run_id, html, url
    if llm_enabled:
        warnings.warn(
            "LLM-based schema inference is no longer supported; falling back to deterministic schema resolution.",
            DeprecationWarning,
            stacklevel=2,
        )
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
    """Create a dictionary representation of a resolved schema trace payload.
    Parameters:
        - schema (ResolvedSchema): The resolved schema object to serialize.
    Returns:
        - dict: A dictionary containing surface, domain, field lists, source, saved_at, and stale status."""
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
