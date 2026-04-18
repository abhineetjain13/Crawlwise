from __future__ import annotations

import pytest

from app.models.crawl import CrawlRecord, ReviewPromotion
from app.services.crawl_crud import commit_selected_fields, create_crawl_run, delete_run
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_create_crawl_run_sets_pending_and_preserves_surface(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
        },
    )

    assert run.id is not None
    assert run.status == "pending"
    assert run.surface == "ecommerce_detail"
    assert run.result_summary["url_count"] == 1


@pytest.mark.asyncio
async def test_create_crawl_run_expands_domain_and_alias_requested_fields(
    db_session: AsyncSession,
    test_user,
) -> None:
    seed_run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/seed",
            "surface": "ecommerce_detail",
        },
    )
    db_session.add(
        ReviewPromotion(
            run_id=seed_run.id,
            domain="example.com",
            surface="ecommerce_detail",
            approved_schema={"fields": ["title", "materials"]},
            field_mapping={"material_notes": "materials"},
        )
    )
    await db_session.commit()

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "additional_fields": ["care instructions"],
        },
    )

    assert "materials" in run.requested_fields
    assert "care" in run.requested_fields


@pytest.mark.asyncio
async def test_delete_run_rejects_active_runs(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
        },
    )

    with pytest.raises(ValueError, match="Cannot delete run"):
        await delete_run(db_session, run)


@pytest.mark.asyncio
async def test_commit_selected_fields_updates_requested_field_metadata(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "additional_fields": ["description", "number_of_keys"],
        },
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url=run.url,
        data={"title": "Widget"},
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    updated_records, updated_fields = await commit_selected_fields(
        db_session,
        run=run,
        items=[
            {"record_id": record.id, "field_name": "description", "value": "Clean text"},
            {"record_id": record.id, "field_name": "number_of_keys", "value": 61},
        ],
    )

    await db_session.refresh(record)
    assert updated_records == 1
    assert updated_fields == 2
    assert record.data["description"] == "Clean text"
    assert record.data["number_of_keys"] == 61
    assert record.source_trace["field_discovery"]["description"]["status"] == "found"
    assert record.source_trace["field_discovery"]["number_of_keys"]["value"] == "61"
    coverage = record.discovered_data["requested_field_coverage"]
    assert coverage["requested"] >= 1
    assert coverage["found"] >= 1
    assert "description" not in coverage["missing"]
