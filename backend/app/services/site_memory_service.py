from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import logging

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_memory import SiteMemory
from app.services.domain_utils import normalize_domain

logger = logging.getLogger(__name__)


def _empty_payload() -> dict:
    return {
        "fields": [],
        "selectors": {},
        "source_mappings": {},
        "llm_columns": {},
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


def _normalize_payload(payload: dict | None) -> dict:
    current = payload if isinstance(payload, dict) else {}
    selectors = current.get("selectors") if isinstance(current.get("selectors"), dict) else {}
    source_mappings = current.get("source_mappings") if isinstance(current.get("source_mappings"), dict) else {}
    llm_columns = current.get("llm_columns") if isinstance(current.get("llm_columns"), dict) else {}
    normalized_selectors: dict[str, list[dict]] = {}
    for field_name, rows in selectors.items():
        normalized_field = str(field_name or "").strip().lower()
        if not normalized_field:
            continue
        selector_rows = _normalize_selector_rows(rows if isinstance(rows, list) else [])
        if selector_rows:
            normalized_selectors[normalized_field] = selector_rows
    return {
        "fields": _normalize_fields(current.get("fields") if isinstance(current.get("fields"), list) else []),
        "selectors": normalized_selectors,
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
    }


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
    source_mappings: dict[str, str] | None = None,
    llm_columns: dict[str, object] | None = None,
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

        for field_name, rows in (selectors or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            if not normalized_field:
                continue
            payload["selectors"][normalized_field] = _merge_selector_rows(
                payload["selectors"].get(normalized_field, []),
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
        for field_name, rows in (selectors or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            if normalized_field:
                payload["selectors"][normalized_field] = _normalize_selector_rows(rows)
        for field_name, source in (source_mappings or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            normalized_source = str(source or "").strip()
            if normalized_field and normalized_source:
                payload["source_mappings"][normalized_field] = normalized_source
        for field_name, value in (llm_columns or {}).items():
            normalized_field = str(field_name or "").strip().lower()
            if normalized_field:
                payload["llm_columns"][normalized_field] = deepcopy(value)
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
    source_mappings: dict[str, str] | None = None,
    llm_columns: dict[str, object] | None = None,
    last_crawl_at: datetime | None = None,
) -> SiteMemory:
    return await merge_memory(
        session,
        domain,
        fields=fields,
        selectors=selectors,
        source_mappings=source_mappings,
        llm_columns=llm_columns,
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
