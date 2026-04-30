from __future__ import annotations

import pytest

from app.services.domain_memory_service import load_domain_memory, save_domain_memory
from app.services.selectors_runtime import (
    _coerce_int,
    create_selector_record,
    fetch_selector_document,
    list_selector_records,
    update_selector_record,
)


@pytest.mark.asyncio
async def test_create_selector_record_uses_global_unique_ids(db_session) -> None:
    first = await create_selector_record(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        payload={
            "field_name": "title",
            "css_selector": "h1",
            "source": "manual",
        },
    )
    second = await create_selector_record(
        db_session,
        domain="other.example",
        surface="ecommerce_detail",
        payload={
            "field_name": "price",
            "css_selector": ".price",
            "source": "manual",
        },
    )

    assert first["id"] == 1
    assert second["id"] == 2


@pytest.mark.asyncio
async def test_create_selector_record_normalizes_duplicate_ids_before_append(db_session) -> None:
    await save_domain_memory(
        db_session,
        domain="one.example",
        surface="ecommerce_detail",
        selectors={
            "rules": [
                {"id": 1, "field_name": "title", "css_selector": "h1"},
            ]
        },
    )
    await save_domain_memory(
        db_session,
        domain="two.example",
        surface="ecommerce_detail",
        selectors={
            "rules": [
                {"id": 1, "field_name": "price", "css_selector": ".price"},
            ]
        },
    )
    await db_session.commit()

    created = await create_selector_record(
        db_session,
        domain="three.example",
        surface="ecommerce_detail",
        payload={
            "field_name": "brand",
            "css_selector": ".brand",
            "source": "manual",
        },
    )
    second_memory = await load_domain_memory(
        db_session,
        domain="two.example",
        surface="ecommerce_detail",
    )

    assert created["id"] == 3
    assert second_memory is not None
    assert second_memory.selectors["rules"][0]["id"] == 2


@pytest.mark.asyncio
async def test_fetch_selector_document_rejects_private_targets() -> None:
    with pytest.raises(ValueError):
        await fetch_selector_document("http://localhost/internal")


@pytest.mark.asyncio
async def test_update_selector_record_returns_committed_memory_timestamps(db_session) -> None:
    created = await create_selector_record(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        payload={
            "field_name": "title",
            "css_selector": "h1",
            "source": "manual",
        },
    )

    updated = await update_selector_record(
        db_session,
        selector_id=created["id"],
        payload={"sample_value": "Widget Prime"},
    )
    memory = await load_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )

    assert updated is not None
    assert memory is not None
    assert updated["updated_at"] == memory.updated_at


@pytest.mark.asyncio
async def test_list_selector_records_without_surface_returns_all_domain_surfaces(
    db_session,
) -> None:
    await create_selector_record(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        payload={
            "field_name": "title",
            "css_selector": "h1",
            "source": "manual",
        },
    )
    await create_selector_record(
        db_session,
        domain="example.com",
        surface="job_detail",
        payload={
            "field_name": "title",
            "css_selector": ".job-title",
            "source": "manual",
        },
    )

    rows = await list_selector_records(
        db_session,
        domain="example.com",
    )

    assert {(row["surface"], row["field_name"]) for row in rows} == {
        ("ecommerce_detail", "title"),
        ("job_detail", "title"),
    }


def test_coerce_int_preserves_zero() -> None:
    assert _coerce_int(0, default=9) == 0
    assert _coerce_int(" 0 ", default=9) == 0
