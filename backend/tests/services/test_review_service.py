from __future__ import annotations

import pytest

from app.models.crawl import CrawlRecord, DomainFieldFeedback, ReviewPromotion
from app.services.crawl_crud import create_crawl_run
from app.services.domain_memory_service import load_domain_memory, save_domain_memory
from app.services.review import (
    apply_domain_recipe_field_action,
    list_domain_field_feedback,
    promote_domain_recipe_selectors,
    save_review,
)
from app.services.schema_service import ResolvedSchema
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


@pytest.mark.asyncio
async def test_save_review_excludes_falsy_normalized_new_fields(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
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
        data={},
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

    async def _fake_load_resolved_schema(*args, **kwargs) -> ResolvedSchema:
        del args, kwargs
        return ResolvedSchema(
            surface="ecommerce_detail",
            domain="example.com",
            baseline_fields=["title"],
            fields=["title"],
            new_fields=[],
            deprecated_fields=[],
            source="baseline",
            saved_at=None,
            stale=False,
        )

    call_counts: dict[str, int] = {}

    def _fake_normalize_review_target(surface: str, value: object) -> str:
        del surface
        text = str(value or "").strip().lower()
        call_counts[text] = call_counts.get(text, 0) + 1
        if text == "materials" and call_counts[text] == 1:
            return "materials"
        if text == "materials":
            return ""
        return text

    monkeypatch.setattr("app.services.review.load_resolved_schema", _fake_load_resolved_schema)
    monkeypatch.setattr(
        "app.services.review.normalize_review_target",
        _fake_normalize_review_target,
    )

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

    promotion = (
        await db_session.execute(
            select(ReviewPromotion)
            .where(ReviewPromotion.run_id == run.id)
            .order_by(ReviewPromotion.id.desc())
            .limit(1)
        )
    ).scalar_one()

    assert result["field_mapping"] == {"material_notes": "materials"}
    assert promotion.approved_schema["new_fields"] == []


@pytest.mark.asyncio
async def test_promote_domain_recipe_selectors_matches_existing_selectors_by_kind(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
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

    update_calls: list[dict[str, object]] = []
    create_calls: list[dict[str, object]] = []

    async def _fake_list_selector_records(*args, **kwargs):
        del args, kwargs
        return [
            {
                "id": 11,
                "field_name": "price",
                "regex": ".price",
            }
        ]

    async def _fake_update_selector_record(*args, **kwargs):
        update_calls.append(dict(kwargs))
        return {"id": 11}

    async def _fake_create_selector_record(*args, **kwargs):
        create_calls.append(dict(kwargs))
        return {"id": 12, **dict(kwargs.get("payload") or {})}

    monkeypatch.setattr("app.services.review.list_selector_records", _fake_list_selector_records)
    monkeypatch.setattr("app.services.review.update_selector_record", _fake_update_selector_record)
    monkeypatch.setattr("app.services.review.create_selector_record", _fake_create_selector_record)

    rows = await promote_domain_recipe_selectors(
        db_session,
        run=run,
        selectors=[
            {
                "field_name": "price",
                "selector_kind": "css_selector",
                "selector_value": ".price",
                "sample_value": "$19.99",
            }
        ],
    )

    assert update_calls == []
    assert len(create_calls) == 1
    assert rows[0]["id"] == 12


@pytest.mark.asyncio
async def test_promote_domain_recipe_selectors_skips_invalid_existing_selector_ids(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
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

    update_calls: list[dict[str, object]] = []
    create_calls: list[dict[str, object]] = []

    async def _fake_list_selector_records(*args, **kwargs):
        del args, kwargs
        return [
            {
                "id": None,
                "field_name": "price",
                "css_selector": ".price",
            }
        ]

    async def _fake_update_selector_record(*args, **kwargs):
        update_calls.append(dict(kwargs))
        return {"id": 11}

    async def _fake_create_selector_record(*args, **kwargs):
        create_calls.append(dict(kwargs))
        return {"id": 12, **dict(kwargs.get("payload") or {})}

    monkeypatch.setattr("app.services.review.list_selector_records", _fake_list_selector_records)
    monkeypatch.setattr("app.services.review.update_selector_record", _fake_update_selector_record)
    monkeypatch.setattr("app.services.review.create_selector_record", _fake_create_selector_record)

    rows = await promote_domain_recipe_selectors(
        db_session,
        run=run,
        selectors=[
            {
                "field_name": "price",
                "selector_kind": "css_selector",
                "selector_value": ".price",
                "sample_value": "$19.99",
            }
        ],
    )

    assert update_calls == []
    assert len(create_calls) == 1
    assert rows[0]["id"] == 12


@pytest.mark.asyncio
async def test_apply_domain_recipe_field_action_reject_deactivates_saved_selector_and_records_feedback(
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
    await save_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        selectors={
            "rules": [
                {
                    "id": 1,
                    "field_name": "price",
                    "css_selector": ".price",
                    "status": "validated",
                    "source": "domain_recipe",
                    "is_active": True,
                }
            ]
        },
    )
    await db_session.commit()

    result = await apply_domain_recipe_field_action(
        db_session,
        run=run,
        action={
            "field_name": "price",
            "action": "reject",
            "selector_kind": "css_selector",
            "selector_value": ".price",
            "source_record_ids": [11],
        },
    )

    feedback_rows = list(
        (
            await db_session.execute(
                select(DomainFieldFeedback).order_by(DomainFieldFeedback.id.asc())
            )
        ).scalars().all()
    )
    memory = await load_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )

    assert result["action"] == "reject"
    assert len(feedback_rows) == 1
    assert feedback_rows[0].field_name == "price"
    assert feedback_rows[0].source_value == ".price"
    assert memory is not None
    assert memory.selectors["rules"][0]["is_active"] is False


@pytest.mark.asyncio
async def test_apply_domain_recipe_field_action_skips_invalid_source_record_ids(
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

    await apply_domain_recipe_field_action(
        db_session,
        run=run,
        action={
            "field_name": "price",
            "action": "keep",
            "selector_kind": None,
            "selector_value": None,
            "source_record_ids": ["11", "bad", -3, "", None],
        },
    )

    feedback_row = (
        await db_session.execute(
            select(DomainFieldFeedback)
            .order_by(DomainFieldFeedback.id.desc())
            .limit(1)
        )
    ).scalar_one()

    assert feedback_row.payload["source_record_ids"] == [11, -3]


@pytest.mark.asyncio
async def test_list_domain_field_feedback_skips_invalid_serialized_source_record_ids(
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
    db_session.add(
        DomainFieldFeedback(
            domain="example.com",
            surface="ecommerce_detail",
            field_name="price",
            action="reject",
            source_kind="selector",
            source_value=".price",
            source_run_id=run.id,
            payload={
                "source_record_ids": ["7", "oops", -2, "", None],
            },
        )
    )
    await db_session.commit()

    rows = await list_domain_field_feedback(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )

    assert rows[0]["source_record_ids"] == [7, -2]


@pytest.mark.asyncio
async def test_apply_domain_recipe_field_action_rolls_back_staged_mutations_on_error(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
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

    async def _failing_promote(session, *, run, selectors, commit=True):
        del run, selectors, commit
        await save_domain_memory(
            session,
            domain="example.com",
            surface="ecommerce_detail",
            selectors={
                "rules": [
                    {
                        "id": 1,
                        "field_name": "price",
                        "css_selector": ".price",
                        "is_active": True,
                    }
                ]
            },
        )
        raise ValueError("selector promotion failed")

    monkeypatch.setattr("app.services.review.promote_domain_recipe_selectors", _failing_promote)

    with pytest.raises(ValueError, match="selector promotion failed"):
        await apply_domain_recipe_field_action(
            db_session,
            run=run,
            action={
                "field_name": "price",
                "action": "keep",
                "selector_kind": "css_selector",
                "selector_value": ".price",
                "source_record_ids": [11],
            },
        )

    memory = await load_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )
    feedback_rows = list(
        (
            await db_session.execute(
                select(DomainFieldFeedback).order_by(DomainFieldFeedback.id.asc())
            )
        ).scalars().all()
    )

    assert memory is None
    assert feedback_rows == []
