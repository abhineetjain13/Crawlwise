from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import logging
import re

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_memory import SiteMemory
from app.services.domain_utils import normalize_domain

logger = logging.getLogger(__name__)
_SURFACE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def _normalize_surface_key(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized or not _SURFACE_KEY_RE.match(normalized):
        return ""
    return normalized


def _empty_payload() -> dict:
    return {
        "fields": [],
        "schemas": {},
        "selectors": {},
        "selector_suggestions": {},
        "source_mappings": {},
        "llm_columns": {},
        "acquisition": {},
    }


def _normalize_fields(fields: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for field in fields or []:
        value = str(field or "").strip().lower()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _normalize_schema_snapshot(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    baseline_fields = _normalize_fields(value.get("baseline_fields") if isinstance(value.get("baseline_fields"), list) else [])
    fields = _normalize_fields(value.get("fields") if isinstance(value.get("fields"), list) else [])
    new_fields = _normalize_fields(value.get("new_fields") if isinstance(value.get("new_fields"), list) else [])
    deprecated_fields = _normalize_fields(value.get("deprecated_fields") if isinstance(value.get("deprecated_fields"), list) else [])
    raw_conf = value.get("confidence", 0.0)
    try:
        confidence = float(raw_conf or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    normalized = {
        "baseline_fields": baseline_fields,
        "fields": fields,
        "new_fields": new_fields,
        "deprecated_fields": deprecated_fields,
        "source": str(value.get("source") or "static").strip() or "static",
        "confidence": confidence,
        "saved_at": str(value.get("saved_at") or "").strip() or None,
    }
    return normalized


def _normalize_schema_map(value: object) -> dict[str, dict]:
    rows = value if isinstance(value, dict) else {}
    normalized: dict[str, dict] = {}
    for surface, snapshot in rows.items():
        normalized_surface = _normalize_surface_key(surface)
        if not normalized_surface:
            continue
        normalized_snapshot = _normalize_schema_snapshot(snapshot)
        if normalized_snapshot is None:
            continue
        normalized[normalized_surface] = normalized_snapshot
    return normalized


def _selector_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("css_selector") or "").strip(),
        str(row.get("xpath") or "").strip(),
        str(row.get("regex") or "").strip(),
    )


def _normalize_selector_rows(rows: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        value = {
            "css_selector": str(row.get("css_selector") or "").strip() or None,
            "xpath": str(row.get("xpath") or "").strip() or None,
            "regex": str(row.get("regex") or "").strip() or None,
            "status": str(row.get("status") or "validated").strip() or "validated",
            "sample_value": str(row.get("sample_value") or "").strip() or None,
            "source": str(row.get("source") or "site_memory").strip() or "site_memory",
        }
        if not any([value["css_selector"], value["xpath"], value["regex"]]):
            continue
        fingerprint = _selector_key(value)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        normalized.append(value)
    return normalized


def _normalize_selector_map(value: object) -> dict[str, list[dict]]:
    selectors = value if isinstance(value, dict) else {}
    normalized: dict[str, list[dict]] = {}
    for field_name, rows in selectors.items():
        normalized_field = str(field_name or "").strip().lower()
        if not normalized_field:
            continue
        selector_rows = _normalize_selector_rows(rows if isinstance(rows, list) else [])
        if selector_rows:
            normalized[normalized_field] = selector_rows
    return normalized


def _normalize_payload(payload: dict | None) -> dict:
    current = payload if isinstance(payload, dict) else {}
    source_mappings = current.get("source_mappings") if isinstance(current.get("source_mappings"), dict) else {}
    llm_columns = current.get("llm_columns") if isinstance(current.get("llm_columns"), dict) else {}
    acquisition = current.get("acquisition") if isinstance(current.get("acquisition"), dict) else {}
    schemas = _normalize_schema_map(current.get("schemas"))
    legacy_fields = _normalize_fields(current.get("fields") if isinstance(current.get("fields"), list) else [])
    if legacy_fields:
        legacy_snapshot = schemas.get("legacy")
        if legacy_snapshot is None:
            schemas["legacy"] = {
                "baseline_fields": [],
                "fields": legacy_fields,
                "new_fields": legacy_fields,
                "deprecated_fields": [],
                "source": "legacy",
                "confidence": 1.0,
                "saved_at": None,
            }
    normalized = {
        "fields": legacy_fields,
        "schemas": schemas,
        "selectors": _normalize_selector_map(current.get("selectors")),
        "selector_suggestions": _normalize_selector_map(current.get("selector_suggestions")),
        "source_mappings": {
            str(field_name or "").strip().lower(): str(source or "").strip()
            for field_name, source in source_mappings.items()
            if str(field_name or "").strip() and str(source or "").strip()
        },
        "llm_columns": {
            str(field_name or "").strip().lower(): value
            for field_name, value in llm_columns.items()
            if str(field_name or "").strip()
        },
        "acquisition": {
            str(key or "").strip(): deepcopy(value)
            for key, value in acquisition.items()
            if str(key or "").strip()
        },
    }
    for key, value in current.items():
        if key in normalized:
            continue
        normalized[key] = deepcopy(value)
    return normalized


def _merge_selector_rows(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = _normalize_selector_rows(existing)
    seen = {_selector_key(row) for row in merged}
    for row in _normalize_selector_rows(incoming):
        fingerprint = _selector_key(row)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        merged.append(row)
    return merged


def _is_missing_site_memory_table(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return "no such table" in message and "site_memory" in message


async def list_memory(session: AsyncSession) -> list[SiteMemory]:
    try:
        result = await session.execute(select(SiteMemory).order_by(SiteMemory.updated_at.desc(), SiteMemory.domain.asc()))
        return list(result.scalars().all())
    except OperationalError as exc:
        if _is_missing_site_memory_table(exc):
            logger.warning("site_memory table missing; returning empty list")
            return []
        raise


async def get_memory(session: AsyncSession, domain: str) -> SiteMemory | None:
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        return None
    try:
        return await session.get(SiteMemory, normalized_domain)
    except OperationalError as exc:
        if _is_missing_site_memory_table(exc):
            logger.warning("site_memory table missing; returning no memory for %s", normalized_domain)
            return None
        raise


async def merge_memory(
    session: AsyncSession,
    domain: str,
    *,
    fields: list[str] | None = None,
    selectors: dict[str, list[dict]] | None = None,
    selector_suggestions: dict[str, list[dict]] | None = None,
    schemas: dict[str, dict] | None = None,
    source_mappings: dict[str, str] | None = None,
    llm_columns: dict[str, object] | None = None,
    acquisition: dict[str, object] | None = None,
    last_crawl_at: datetime | None = None,
) -> SiteMemory:
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        raise ValueError("domain is required")

    try:
        memory = await session.get(SiteMemory, normalized_domain)
        if memory is None:
            memory = SiteMemory(domain=normalized_domain, payload=_empty_payload())
            session.add(memory)

        payload = _normalize_payload(memory.payload)
        payload["fields"] = _normalize_fields([*payload["fields"], *(fields or [])])
        for surface, snapshot in (schemas or {}).items():
            normalized_surface = _normalize_surface_key(surface)
            normalized_snapshot = _normalize_schema_snapshot(snapshot)
            if not normalized_surface or normalized_snapshot is None:
                continue
            payload["schemas"][normalized_surface] = normalized_snapshot

        for field_name, rows in (selectors or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            if not normalized_field:
                continue
            payload["selectors"][normalized_field] = _merge_selector_rows(
                payload["selectors"].get(normalized_field, []),
                rows,
            )

        for field_name, rows in (selector_suggestions or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            if not normalized_field:
                continue
            payload["selector_suggestions"][normalized_field] = _merge_selector_rows(
                payload["selector_suggestions"].get(normalized_field, []),
                rows,
            )

        for field_name, source in (source_mappings or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            normalized_source = str(source or "").strip()
            if not normalized_field or not normalized_source:
                continue
            payload["source_mappings"][normalized_field] = normalized_source

        for field_name, value in (llm_columns or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            if not normalized_field:
                continue
            payload["llm_columns"][normalized_field] = deepcopy(value)
        if acquisition:
            payload["acquisition"] = {
                **dict(payload.get("acquisition") or {}),
                **{
                    str(key or "").strip(): deepcopy(value)
                    for key, value in acquisition.items()
                    if str(key or "").strip()
                },
            }

        memory.payload = payload
        if last_crawl_at is not None:
            memory.last_crawl_at = last_crawl_at
        await session.commit()
        await session.refresh(memory)
        return memory
    except OperationalError as exc:
        if not _is_missing_site_memory_table(exc):
            raise
        logger.warning("site_memory table missing; merge_memory is running in no-op mode")
        payload = _normalize_payload(_empty_payload())
        payload["fields"] = _normalize_fields([*payload["fields"], *(fields or [])])
        for surface, snapshot in (schemas or {}).items():
            normalized_surface = _normalize_surface_key(surface)
            normalized_snapshot = _normalize_schema_snapshot(snapshot)
            if normalized_surface and normalized_snapshot is not None:
                payload["schemas"][normalized_surface] = normalized_snapshot
        for field_name, rows in (selectors or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            if normalized_field:
                payload["selectors"][normalized_field] = _normalize_selector_rows(rows)
        for field_name, rows in (selector_suggestions or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            if normalized_field:
                payload["selector_suggestions"][normalized_field] = _normalize_selector_rows(rows)
        for field_name, source in (source_mappings or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            normalized_source = str(source or "").strip()
            if normalized_field and normalized_source:
                payload["source_mappings"][normalized_field] = normalized_source
        for field_name, value in (llm_columns or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            if normalized_field:
                payload["llm_columns"][normalized_field] = deepcopy(value)
        if acquisition:
            payload["acquisition"] = {
                str(key or "").strip(): deepcopy(value)
                for key, value in acquisition.items()
                if str(key or "").strip()
            }
        return SiteMemory(
            domain=normalized_domain,
            payload=payload,
            last_crawl_at=last_crawl_at,
        )


async def save_memory(
    session: AsyncSession,
    domain: str,
    *,
    fields: list[str] | None = None,
    selectors: dict[str, list[dict]] | None = None,
    selector_suggestions: dict[str, list[dict]] | None = None,
    schemas: dict[str, dict] | None = None,
    source_mappings: dict[str, str] | None = None,
    llm_columns: dict[str, object] | None = None,
    acquisition: dict[str, object] | None = None,
    last_crawl_at: datetime | None = None,
) -> SiteMemory:
    return await merge_memory(
        session,
        domain,
        fields=fields,
        selectors=selectors,
        selector_suggestions=selector_suggestions,
        schemas=schemas,
        source_mappings=source_mappings,
        llm_columns=llm_columns,
        acquisition=acquisition,
        last_crawl_at=last_crawl_at,
    )


async def replace_selector_field(
    session: AsyncSession,
    domain: str,
    field_name: str,
    rows: list[dict],
) -> SiteMemory:
    normalized_domain = normalize_domain(domain)
    normalized_field = str(field_name or "").strip().lower()
    if not normalized_domain or not normalized_field:
        raise ValueError("domain and field_name are required")
    try:
        memory = await session.get(SiteMemory, normalized_domain)
        if memory is None:
            memory = SiteMemory(domain=normalized_domain, payload=_empty_payload())
            session.add(memory)
        payload = _normalize_payload(memory.payload)
        selector_rows = _normalize_selector_rows(rows)
        if selector_rows:
            payload["selectors"][normalized_field] = selector_rows
        else:
            payload["selectors"].pop(normalized_field, None)
        memory.payload = payload
        await session.commit()
        await session.refresh(memory)
        return memory
    except OperationalError as exc:
        if not _is_missing_site_memory_table(exc):
            raise
        logger.warning("site_memory table missing; replace_selector_field is running in no-op mode")
        payload = _normalize_payload(_empty_payload())
        selector_rows = _normalize_selector_rows(rows)
        if selector_rows:
            payload["selectors"][normalized_field] = selector_rows
        return SiteMemory(domain=normalized_domain, payload=payload)


async def replace_selector_map(
    session: AsyncSession,
    domain: str,
    selectors: dict[str, list[dict]],
    *,
    commit: bool = True,
) -> SiteMemory:
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        raise ValueError("domain is required")
    selector_map = _normalize_selector_map(selectors)
    try:
        memory = await session.get(SiteMemory, normalized_domain)
        if memory is None:
            memory = SiteMemory(domain=normalized_domain, payload=_empty_payload())
            session.add(memory)
        payload = _normalize_payload(memory.payload)
        payload["selectors"] = selector_map
        memory.payload = payload
        if commit:
            await session.commit()
            await session.refresh(memory)
        else:
            await session.flush()
        return memory
    except OperationalError as exc:
        if not _is_missing_site_memory_table(exc):
            raise
        logger.warning("site_memory table missing; replace_selector_map is running in no-op mode")
        payload = _normalize_payload(_empty_payload())
        payload["selectors"] = selector_map
        return SiteMemory(domain=normalized_domain, payload=payload)


async def clear_all_selector_memory(
    session: AsyncSession,
    *,
    clear_suggestions: bool = False,
    commit: bool = True,
) -> int:
    try:
        result = await session.execute(select(SiteMemory).order_by(SiteMemory.domain.asc()))
        rows = list(result.scalars().all())
        updated = 0
        for memory in rows:
            payload = _normalize_payload(memory.payload)
            has_selectors = bool(payload["selectors"])
            has_suggestions = clear_suggestions and bool(payload["selector_suggestions"])
            if not has_selectors and not has_suggestions:
                continue
            payload["selectors"] = {}
            if clear_suggestions:
                payload["selector_suggestions"] = {}
            memory.payload = payload
            updated += 1
        if updated and commit:
            await session.commit()
        elif updated:
            await session.flush()
        return updated
    except OperationalError as exc:
        if _is_missing_site_memory_table(exc):
            logger.warning("site_memory table missing; clear_all_selector_memory is a no-op")
            return 0
        raise


async def delete_memory(session: AsyncSession, domain: str) -> int:
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        return 0
    try:
        result = await session.execute(delete(SiteMemory).where(SiteMemory.domain == normalized_domain))
        await session.commit()
        return result.rowcount or 0
    except OperationalError as exc:
        if _is_missing_site_memory_table(exc):
            logger.warning("site_memory table missing; delete_memory is a no-op")
            return 0
        raise


async def clear_all_memory(session: AsyncSession) -> int:
    try:
        result = await session.execute(delete(SiteMemory))
        await session.commit()
        return result.rowcount or 0
    except OperationalError as exc:
        if _is_missing_site_memory_table(exc):
            logger.warning("site_memory table missing; clear_all_memory is a no-op")
            return 0
        raise
