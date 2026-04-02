# Selector CRUD and testing service.
from __future__ import annotations

from datetime import UTC, datetime

from bs4 import BeautifulSoup
from lxml import etree, html
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.selector import Selector
from app.services.acquisition.http_client import fetch_html
from app.services.knowledge_base.store import save_selector_defaults


async def list_selectors(session: AsyncSession, domain: str = "") -> list[Selector]:
    query = select(Selector).order_by(Selector.created_at.desc())
    if domain:
        query = query.where(Selector.domain == domain)
    result = await session.execute(query)
    return list(result.scalars().all())


async def create_selector(session: AsyncSession, payload: dict) -> Selector:
    selector = Selector(**payload)
    session.add(selector)
    await session.commit()
    await session.refresh(selector)
    save_selector_defaults(
        selector.domain,
        selector.field_name,
        [{"selector": selector.selector, "selector_type": selector.selector_type}],
    )
    return selector


async def update_selector(session: AsyncSession, selector: Selector, payload: dict) -> Selector:
    for key, value in payload.items():
        setattr(selector, key, value)
    selector.last_validated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(selector)
    return selector


async def delete_selector(session: AsyncSession, selector_id: int) -> None:
    await session.execute(delete(Selector).where(Selector.id == selector_id))
    await session.commit()


async def test_selector(url: str, selector: str, selector_type: str) -> tuple[str | None, int]:
    html_text = await fetch_html(url)
    if selector_type == "css":
        soup = BeautifulSoup(html_text, "html.parser")
        matches = soup.select(selector)
        return (matches[0].get_text(" ", strip=True) if matches else None, len(matches))
    tree = html.fromstring(html_text)
    matches = tree.xpath(selector)
    if matches and isinstance(matches[0], etree._Element):
        return (matches[0].text_content().strip(), len(matches))
    values = [str(item).strip() for item in matches if str(item).strip()]
    return (values[0] if values else None, len(matches))


async def suggest_selectors(url: str, expected_columns: list[str]) -> dict[str, list[dict]]:
    html_text = await fetch_html(url)
    soup = BeautifulSoup(html_text, "html.parser")
    suggestions: dict[str, list[dict]] = {}
    for field in expected_columns:
        lower = field.lower().replace("_", " ")
        node = soup.find(attrs={"aria-label": lambda value: value and lower in value.lower()})
        if node is None:
            node = soup.find(attrs={"data-field": lambda value: value and field.lower() in value.lower()})
        sample_value = node.get_text(" ", strip=True) if node else None
        suggestions[field] = [
            {
                "css": f"[aria-label*='{lower}']" if node else "",
                "xpath": f"//*[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lower}')]"
                if node
                else "",
                "confidence": 0.7 if node else 0.1,
                "sample_value": sample_value,
            }
        ]
    return suggestions
