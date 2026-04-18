from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import DomainMemory


async def load_domain_memory(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> DomainMemory | None:
    result = await session.execute(
        select(DomainMemory)
        .where(
            DomainMemory.domain == str(domain or "").strip().lower(),
            DomainMemory.surface == str(surface or "").strip().lower(),
        )
        .order_by(DomainMemory.updated_at.desc(), DomainMemory.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def save_domain_memory(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    selectors: dict[str, object],
    platform: str | None = None,
) -> DomainMemory:
    normalized_domain = str(domain or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    existing = await load_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    if existing is None:
        existing = DomainMemory(
            domain=normalized_domain,
            surface=normalized_surface,
            platform=str(platform or "").strip().lower() or None,
            selectors=dict(selectors or {}),
        )
        session.add(existing)
    else:
        existing.platform = str(platform or "").strip().lower() or existing.platform
        existing.selectors = dict(selectors or {})
    await session.flush()
    return existing


def selector_rules_from_memory(memory: DomainMemory | None) -> list[dict[str, object]]:
    if memory is None or not isinstance(memory.selectors, dict):
        return []
    selectors = dict(memory.selectors or {})
    rules = selectors.get("rules")
    if isinstance(rules, list):
        normalized: list[dict[str, object]] = []
        for row in rules:
            if not isinstance(row, dict):
                continue
            normalized.append(dict(row))
        return normalized

    fallback_rules: list[dict[str, object]] = []
    next_id = 1
    for field_name, payload in selectors.items():
        if str(field_name).startswith("_") or not isinstance(payload, dict):
            continue
        fallback_rules.append(
            {
                "id": next_id,
                "field_name": str(field_name or "").strip().lower(),
                "css_selector": payload.get("css_selector") or payload.get("css"),
                "xpath": payload.get("xpath"),
                "regex": payload.get("regex"),
                "sample_value": payload.get("sample_value"),
                "source": payload.get("source") or "domain_memory",
                "status": payload.get("status") or "validated",
                "is_active": bool(payload.get("is_active", True)),
            }
        )
        next_id += 1
    return fallback_rules


def selector_payload_from_rules(rules: list[dict[str, object]]) -> dict[str, object]:
    max_id = 0
    normalized_rules: list[dict[str, object]] = []
    for row in rules:
        if not isinstance(row, dict):
            continue
        try:
            row_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            row_id = 0
        max_id = max(max_id, row_id)
        normalized_rules.append(
            {
                "id": row_id,
                "field_name": str(row.get("field_name") or "").strip().lower(),
                "css_selector": str(row.get("css_selector") or "").strip() or None,
                "xpath": str(row.get("xpath") or "").strip() or None,
                "regex": str(row.get("regex") or "").strip() or None,
                "sample_value": str(row.get("sample_value") or "").strip() or None,
                "source": str(row.get("source") or "domain_memory").strip(),
                "status": str(row.get("status") or "validated").strip(),
                "is_active": bool(row.get("is_active", True)),
            }
        )
    return {
        "_meta": {"next_id": max_id + 1},
        "rules": normalized_rules,
    }


async def load_domain_selector_rules(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate_surface in [str(surface or "").strip().lower(), "generic"]:
        if not candidate_surface:
            continue
        memory = await load_domain_memory(
            session,
            domain=domain,
            surface=candidate_surface,
        )
        for row in selector_rules_from_memory(memory):
            key = (
                str(row.get("field_name") or "").strip().lower(),
                str(row.get("css_selector") or "").strip(),
                str(row.get("xpath") or "").strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            rules.append(row)
    return rules
