from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.site_memory_service import clear_all_memory, get_memory, merge_memory, replace_selector_field


@pytest.mark.asyncio
async def test_merge_memory_is_additive(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "https://www.example.com/products/widget",
        fields=["materials"],
        selectors={"price": [{"xpath": "//span[@class='price']/text()", "source": "manual"}]},
        source_mappings={"price": "json_ld"},
    )
    await merge_memory(
        db_session,
        "example.com",
        fields=["care"],
        selectors={"price": [{"regex": r"Price:\s*(\$[\d.]+)", "source": "manual"}]},
        source_mappings={"brand": "adapter"},
    )

    memory = await get_memory(db_session, "https://example.com/products/widget")

    assert memory is not None
    assert memory.domain == "example.com"
    assert memory.payload["fields"] == ["materials", "care"]
    assert len(memory.payload["selectors"]["price"]) == 2
    assert memory.payload["source_mappings"]["price"] == "json_ld"
    assert memory.payload["source_mappings"]["brand"] == "adapter"


@pytest.mark.asyncio
async def test_replace_selector_field_removes_empty_selector_sets(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "example.com",
        selectors={"title": [{"xpath": "//h1/text()", "source": "manual"}]},
    )

    await replace_selector_field(db_session, "example.com", "title", [])
    memory = await get_memory(db_session, "example.com")

    assert memory is not None
    assert memory.payload["selectors"] == {}


@pytest.mark.asyncio
async def test_get_memory_returns_none_when_site_memory_table_missing(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession):
    async def _raise_missing_table(*_args, **_kwargs):
        raise OperationalError(
            "SELECT ... FROM site_memory",
            {"domain": "example.com"},
            Exception("no such table: site_memory"),
        )

    monkeypatch.setattr(db_session, "get", _raise_missing_table)
    memory = await get_memory(db_session, "example.com")
    assert memory is None


@pytest.mark.asyncio
async def test_merge_memory_noops_when_site_memory_table_missing(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession):
    async def _raise_missing_table(*_args, **_kwargs):
        raise OperationalError(
            "SELECT ... FROM site_memory",
            {"domain": "example.com"},
            Exception("no such table: site_memory"),
        )

    monkeypatch.setattr(db_session, "get", _raise_missing_table)
    memory = await merge_memory(db_session, "example.com", fields=["title"])
    assert memory.domain == "example.com"
    assert memory.payload["fields"] == ["title"]


@pytest.mark.asyncio
async def test_clear_all_memory_noops_when_site_memory_table_missing(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession):
    async def _raise_missing_table(*_args, **_kwargs):
        raise OperationalError(
            "DELETE FROM site_memory",
            {},
            Exception("no such table: site_memory"),
        )

    monkeypatch.setattr(db_session, "execute", _raise_missing_table)
    deleted = await clear_all_memory(db_session)
    assert deleted == 0
