# Selector CRUD and testing service.
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from lxml import etree
import regex as regex_lib

from app.models.selector import Selector
from app.services.acquisition.http_client import fetch_html
from app.services.knowledge_base.store import save_selector_defaults
from app.services.xpath_service import build_deterministic_selector_suggestions, extract_selector_value


async def list_selectors(session: AsyncSession, domain: str = "") -> list[Selector]:
    query = select(Selector).order_by(Selector.created_at.desc())
    if domain:
        query = query.where(Selector.domain == domain)
    result = await session.execute(query)
    return list(result.scalars().all())


async def create_selector(session: AsyncSession, payload: dict) -> Selector:
    selector = Selector(**_normalize_selector_payload(payload))
    session.add(selector)
    await session.commit()
    await session.refresh(selector)
    await _sync_selector_defaults(session, selector.domain, selector.field_name)
    return selector


async def update_selector(session: AsyncSession, selector: Selector, payload: dict) -> Selector:
    previous_domain = selector.domain
    previous_field_name = selector.field_name
    normalized_payload = _normalize_selector_payload({**selector.__dict__, **payload})
    for key, value in normalized_payload.items():
        setattr(selector, key, value)
    selector.last_validated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(selector)
    await _sync_selector_defaults(session, previous_domain, previous_field_name)
    await _sync_selector_defaults(session, selector.domain, selector.field_name)
    return selector


async def delete_selector(session: AsyncSession, selector_id: int) -> None:
    result = await session.execute(select(Selector).where(Selector.id == selector_id))
    selector = result.scalar_one_or_none()
    if selector is None:
        return
    domain = selector.domain
    field_name = selector.field_name
    await session.execute(delete(Selector).where(Selector.id == selector_id))
    await session.commit()
    await _sync_selector_defaults(session, domain, field_name)


async def test_selector(
    url: str,
    *,
    css_selector: str | None = None,
    xpath: str | None = None,
    regex: str | None = None,
) -> tuple[str | None, int, str | None]:
    html_text = await fetch_html(url)
    return extract_selector_value(
        html_text,
        css_selector=css_selector,
        xpath=xpath,
        regex=regex,
    )


async def suggest_selectors(url: str, expected_columns: list[str]) -> dict[str, list[dict]]:
    html_text = await fetch_html(url)
    return build_deterministic_selector_suggestions(html_text, expected_columns)


async def _sync_selector_defaults(session: AsyncSession, domain: str, field_name: str) -> None:
    result = await session.execute(
        select(Selector)
        .where(
            Selector.domain == domain,
            Selector.field_name == field_name,
            Selector.is_active.is_(True),
            Selector.status.in_(["validated", "manual"]),
        )
        .order_by(Selector.created_at.desc())
    )
    selectors = list(result.scalars().all())
    save_selector_defaults(
        domain,
        field_name,
        [
            {
                "xpath": selector.xpath,
                "css_selector": selector.css_selector,
                "regex": selector.regex,
                "status": selector.status,
                "confidence": selector.confidence,
                "sample_value": selector.sample_value,
                "source": selector.source,
            }
            for selector in selectors
        ],
    )


def _normalize_selector_payload(payload: dict) -> dict:
    normalized = {
        "domain": str(payload.get("domain") or "").strip().lower(),
        "field_name": str(payload.get("field_name") or "").strip(),
        "css_selector": str(payload.get("css_selector") or "").strip() or None,
        "xpath": str(payload.get("xpath") or "").strip() or None,
        "regex": str(payload.get("regex") or "").strip() or None,
        "status": str(payload.get("status") or "validated").strip() or "validated",
        "confidence": payload.get("confidence"),
        "sample_value": str(payload.get("sample_value") or "").strip() or None,
        "source": str(payload.get("source") or "manual").strip() or "manual",
        "source_run_id": payload.get("source_run_id"),
        "is_active": bool(payload.get("is_active", True)),
    }
    if not normalized["domain"]:
        raise ValueError("domain is required")
    if not normalized["field_name"]:
        raise ValueError("field_name is required")
    if not any([normalized["css_selector"], normalized["xpath"], normalized["regex"]]):
        raise ValueError("At least one of css_selector, xpath, or regex is required")
    if normalized["xpath"]:
        try:
            etree.XPath(normalized["xpath"])
        except etree.XPathError as exc:
            raise ValueError(f"Invalid XPath: {exc}") from exc
    if normalized["regex"]:
        try:
            regex_lib.compile(normalized["regex"])
        except regex_lib.error as exc:
            raise ValueError(f"Invalid regex: {exc}") from exc
    return normalized
