from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.site_memory_service import (
    clear_all_memory,
    clear_all_selector_memory,
    get_memory,
    merge_memory,
    replace_selector_field,
    replace_selector_map,
)


@pytest.mark.asyncio
async def test_merge_memory_is_additive(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "https://www.example.com/products/widget",
        fields=["materials"],
        selectors={"price": [{"xpath": "//span[@class='price']/text()", "source": "manual"}]},
        selector_suggestions={"materials": [{"xpath": "//section[@id='materials']", "source": "crawl"}]},
        source_mappings={"price": "json_ld"},
    )
    await merge_memory(
        db_session,
        "example.com",
        fields=["care"],
        selectors={"price": [{"regex": r"Price:\s*(\$[\d.]+)", "source": "manual"}]},
        selector_suggestions={"materials": [{"xpath": "//button[normalize-space()='Materials']", "source": "browser_click"}]},
        source_mappings={"brand": "adapter"},
    )

    memory = await get_memory(db_session, "https://example.com/products/widget")

    assert memory is not None
    assert memory.domain == "example.com"
    assert memory.payload["fields"] == ["materials", "care"]
    assert len(memory.payload["selectors"]["price"]) == 2
    assert len(memory.payload["selector_suggestions"]["materials"]) == 2
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
async def test_replace_selector_map_replaces_authoritative_selectors_only(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "example.com",
        selectors={"title": [{"xpath": "//h1/text()", "source": "manual"}]},
        selector_suggestions={"materials": [{"xpath": "//section[@id='materials']", "source": "crawl"}]},
    )

    await replace_selector_map(
        db_session,
        "example.com",
        {"price": [{"xpath": "//span[@class='price']/text()", "source": "manual"}]},
    )
    memory = await get_memory(db_session, "example.com")

    assert memory is not None
    assert memory.payload["selectors"] == {
        "price": [{"css_selector": None, "xpath": "//span[@class='price']/text()", "regex": None, "sample_value": None, "source": "manual", "status": "validated"}]
    }
    assert memory.payload["selector_suggestions"] == {
        "materials": [{"css_selector": None, "xpath": "//section[@id='materials']", "regex": None, "sample_value": None, "source": "crawl", "status": "validated"}]
    }


@pytest.mark.asyncio
async def test_clear_all_selector_memory_preserves_other_memory_payload(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "example.com",
        fields=["materials"],
        selectors={"title": [{"xpath": "//h1/text()", "source": "manual"}]},
        selector_suggestions={"materials": [{"xpath": "//section[@id='materials']", "source": "crawl"}]},
    )

    deleted = await clear_all_selector_memory(db_session)
    memory = await get_memory(db_session, "example.com")

    assert deleted == 1
    assert memory is not None
    assert memory.payload["fields"] == ["materials"]
    assert memory.payload["selectors"] == {}
    assert "materials" in memory.payload["selector_suggestions"]


@pytest.mark.asyncio
async def test_clear_all_selector_memory_can_clear_suggestions_too(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "example.com",
        selectors={"title": [{"xpath": "//h1/text()", "source": "manual"}]},
        selector_suggestions={"materials": [{"xpath": "//section[@id='materials']", "source": "crawl"}]},
    )

    deleted = await clear_all_selector_memory(db_session, clear_suggestions=True)
    memory = await get_memory(db_session, "example.com")

    assert deleted == 1
    assert memory is not None
    assert memory.payload["selectors"] == {}
    assert memory.payload["selector_suggestions"] == {}


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


@pytest.mark.asyncio
async def test_merge_memory_preserves_unknown_payload_keys(db_session: AsyncSession):
    memory = await merge_memory(
        db_session,
        "example.com",
        fields=["title"],
    )
    memory.payload = {
        **memory.payload,
        "content_map_cache": {"entries": [{"label": "Reviews"}]},
        "interaction_plan_cache": [{"field_name": "reviews"}],
        "quality_history": {"title": {"runs": [{"score": "GOOD"}]}},
        "content_map_cached_at": "2026-04-05T00:00:00Z",
        "custom_page_intelligence_flag": {"enabled": True},
    }
    await db_session.commit()

    updated = await merge_memory(
        db_session,
        "example.com",
        fields=["price"],
    )

    assert updated.payload["custom_page_intelligence_flag"] == {"enabled": True}


@pytest.mark.asyncio
async def test_merge_memory_updates_acquisition_payload_without_touching_selectors(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "example.com",
        selectors={"title": [{"xpath": "//h1/text()", "source": "manual"}]},
        acquisition={"prefer_stealth": True, "last_success_method": "playwright"},
    )

    memory = await get_memory(db_session, "example.com")

    assert memory is not None
    assert memory.payload["acquisition"] == {
        "prefer_stealth": True,
        "last_success_method": "playwright",
    }
    assert memory.payload["selectors"]["title"][0]["xpath"] == "//h1/text()"


@pytest.mark.asyncio
async def test_merge_memory_persists_surface_scoped_schema_snapshots(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "example.com",
        schemas={
            "ecommerce_detail": {
                "baseline_fields": ["title", "price"],
                "fields": ["title", "price", "materials"],
                "new_fields": ["materials"],
                "deprecated_fields": [],
                "source": "learned",
                "confidence": 0.75,
                "saved_at": "2026-04-06T00:00:00+00:00",
            }
        },
    )

    memory = await get_memory(db_session, "example.com")

    assert memory is not None
    assert memory.payload["schemas"]["ecommerce_detail"]["fields"] == ["title", "price", "materials"]
    assert memory.payload["schemas"]["ecommerce_detail"]["new_fields"] == ["materials"]


@pytest.mark.asyncio
async def test_merge_memory_defaults_invalid_schema_confidence_to_zero(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "example.com",
        schemas={
            "ecommerce_detail": {
                "baseline_fields": ["title"],
                "fields": ["title", "materials"],
                "new_fields": ["materials"],
                "deprecated_fields": [],
                "source": "learned",
                "confidence": "high",
                "saved_at": "2026-04-06T00:00:00+00:00",
            }
        },
    )

    memory = await get_memory(db_session, "example.com")

    assert memory is not None
    assert memory.payload["schemas"]["ecommerce_detail"]["confidence"] == 0.0


@pytest.mark.asyncio
async def test_merge_memory_keeps_surface_schemas_isolated(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "example.com",
        schemas={
            "ecommerce_detail": {
                "baseline_fields": ["title"],
                "fields": ["title", "materials"],
                "new_fields": ["materials"],
                "deprecated_fields": [],
                "source": "learned",
                "confidence": 0.75,
                "saved_at": "2026-04-06T00:00:00+00:00",
            }
        },
    )
    await merge_memory(
        db_session,
        "example.com",
        schemas={
            "job_detail": {
                "baseline_fields": ["title", "company"],
                "fields": ["title", "company", "team"],
                "new_fields": ["team"],
                "deprecated_fields": [],
                "source": "review",
                "confidence": 1.0,
                "saved_at": "2026-04-06T00:00:00+00:00",
            }
        },
    )

    memory = await get_memory(db_session, "example.com")

    assert memory is not None
    assert memory.payload["schemas"]["ecommerce_detail"]["new_fields"] == ["materials"]
    assert memory.payload["schemas"]["job_detail"]["new_fields"] == ["team"]
