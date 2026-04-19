from __future__ import annotations

import pytest

from app.models.crawl import CrawlRecord, ReviewPromotion
from app.services.crawl_crud import create_crawl_run
from app.services.review import save_review
from app.services.schema_service import load_resolved_schema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_save_review_persists_mapping_and_promotes_values(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
        },
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url=run.url,
        data={"title": "Widget Prime"},
        raw_data={},
        discovered_data={
            "review_bucket": [
                {
                    "key": "material_notes",
                    "value": "Cotton blend",
                    "source": "dom",
                }
            ]
        },
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    result = await save_review(
        db_session,
        run,
        [
            {
                "source_field": "material_notes",
                "output_field": "materials",
                "selected": True,
            }
        ],
    )

    await db_session.refresh(record)
    promotion = (
        await db_session.execute(
            select(ReviewPromotion)
            .where(ReviewPromotion.run_id == run.id)
            .order_by(ReviewPromotion.id.desc())
            .limit(1)
        )
    ).scalar_one()

    assert result["field_mapping"] == {"material_notes": "materials"}
    assert "materials" in result["canonical_fields"]
    assert record.data["materials"] == "Cotton blend"
    assert "review_bucket" not in record.discovered_data
    assert promotion.field_mapping == {"material_notes": "materials"}
    assert promotion.approved_schema["fields"] == result["canonical_fields"]
    assert promotion.approved_schema["saved_at"]


@pytest.mark.asyncio
async def test_load_resolved_schema_reads_latest_review_promotion_snapshot(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
        },
    )
    db_session.add_all(
        [
            ReviewPromotion(
                run_id=run.id,
                domain="example.com",
                surface="ecommerce_detail",
                approved_schema={
                    "fields": ["title", "materials"],
                    "baseline_fields": ["title"],
                    "new_fields": ["materials"],
                    "deprecated_fields": [],
                    "source": "review",
                    "saved_at": "2026-04-10T12:00:00+00:00",
                },
                field_mapping={"material_notes": "materials"},
            ),
            ReviewPromotion(
                run_id=run.id,
                domain="example.com",
                surface="ecommerce_detail",
                approved_schema={
                    "fields": ["title", "materials", "care"],
                    "baseline_fields": ["title"],
                    "new_fields": ["materials", "care"],
                    "deprecated_fields": [],
                    "source": "review",
                    "saved_at": "2026-04-11T12:00:00+00:00",
                },
                field_mapping={
                    "material_notes": "materials",
                    "care_instructions": "care",
                },
            ),
        ]
    )
    await db_session.commit()

    schema = await load_resolved_schema(
        db_session,
        "ecommerce_detail",
        "https://example.com/products/widget",
        explicit_fields=["materials", "dimensions"],
    )

    assert schema.domain == "example.com"
    assert schema.source == "review"
    assert schema.saved_at == "2026-04-11T12:00:00+00:00"
    assert "title" in schema.fields
    assert "materials" in schema.fields
    assert "care" in schema.fields
    assert "dimensions" in schema.fields
