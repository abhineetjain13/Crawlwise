from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord, EnrichedProduct
from app.schemas.data_enrichment import DataEnrichmentJobDetailResponse
from app.services.llm_types import LLMTaskResult
from app.services.config.data_enrichment import (
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_PENDING,
)
from app.services.data_enrichment.service import (
    _llm_prompt_context,
    _run_job,
    build_data_enrichment_job_payload,
    create_data_enrichment_job,
    get_data_enrichment_job,
    list_data_enrichment_jobs,
)


@pytest.mark.asyncio
async def test_data_enrichment_job_creates_pending_rows(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/linen-dress",
        data={
            "title": "Navy Linen Dress",
            "price": "$49.99",
            "currency": "USD",
            "category": "Women > Dresses",
            "gender": "women",
        },
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id]},
    )

    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
        )
    ).one()
    await db_session.refresh(record)

    assert job.status == DATA_ENRICHMENT_STATUS_PENDING
    assert job.summary["accepted_count"] == 1
    assert record.enrichment_status == DATA_ENRICHMENT_STATUS_PENDING
    assert product.source_record_id == record.id
    assert product.status == DATA_ENRICHMENT_STATUS_PENDING
    assert product.price_normalized is None
    assert product.gender_normalized is None


@pytest.mark.asyncio
async def test_data_enrichment_skips_already_enriched_records(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/linen-dress",
        data={"title": "Linen Dress"},
        enrichment_status=DATA_ENRICHMENT_STATUS_ENRICHED,
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    with pytest.raises(ValueError, match="No unenriched ecommerce detail records selected"):
        await create_data_enrichment_job(
            db_session,
            user=test_user,
            payload={"source_record_ids": [record.id]},
        )


@pytest.mark.asyncio
async def test_data_enrichment_rejects_non_ecommerce_detail_records(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://jobs.example.com/job/123",
        surface="job_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://jobs.example.com/job/123",
        data={"title": "Engineer"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    with pytest.raises(ValueError, match="No unenriched ecommerce detail records selected"):
        await create_data_enrichment_job(
            db_session,
            user=test_user,
            payload={"source_record_ids": [record.id]},
        )


@pytest.mark.asyncio
async def test_data_enrichment_job_detail_payload_serializes(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/linen-dress",
        data={"title": "Linen Dress"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id]},
    )

    jobs = await list_data_enrichment_jobs(db_session, user=test_user)
    loaded = await get_data_enrichment_job(db_session, user=test_user, job_id=job.id)
    payload = await build_data_enrichment_job_payload(db_session, job=loaded)
    response = DataEnrichmentJobDetailResponse.model_validate(payload)

    assert [row.id for row in jobs] == [job.id]
    assert response.job.id == job.id
    assert len(response.enriched_products) == 1


@pytest.mark.asyncio
async def test_data_enrichment_deterministic_job_populates_enriched_fields(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/navy-linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/navy-linen-dress",
        data={
            "title": "Navy Linen Midi Dress",
            "brand": "Acme",
            "price": "$49.99",
            "currency": "USD",
            "color": "navy",
            "size": "medium",
            "gender": "women",
            "materials": "100% linen",
            "availability": "In stock",
            "category": "Dresses",
            "description": "<p>Elegant linen dress for events.</p>",
        },
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id], "options": {"llm_enabled": False}},
    )

    await _run_job(db_session, job)
    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
        )
    ).one()
    await db_session.refresh(record)

    assert job.status == DATA_ENRICHMENT_STATUS_ENRICHED
    assert record.enrichment_status == DATA_ENRICHMENT_STATUS_ENRICHED
    assert product.status == DATA_ENRICHMENT_STATUS_ENRICHED
    assert product.price_normalized == {"amount": 49.99, "currency": "USD"}
    assert product.color_family == "blue"
    assert product.size_normalized == ["M"]
    assert product.size_system == "alpha"
    assert product.gender_normalized == "female"
    assert product.materials_normalized == ["linen"]
    assert product.availability_normalized == "in_stock"
    assert product.category_path
    assert product.category_path == "Apparel & Accessories > Clothing > Dresses"
    assert product.diagnostics["product_category"]["category_path"] == "Apparel & Accessories > Clothing > Dresses"
    assert "material" in product.diagnostics["product_attributes"]["present_attributes"]
    assert "image_link" in product.diagnostics["product_attributes"]["null_attributes"]
    assert "linen" in product.seo_keywords
    assert product.intent_attributes is None


@pytest.mark.asyncio
async def test_data_enrichment_category_low_confidence_stays_null(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/mystery",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/mystery",
        data={"title": "ZXQ Plinth", "category": "ZXQ Plinth"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id]},
    )

    await _run_job(db_session, job)
    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
        )
    ).one()

    assert product.category_path is None


@pytest.mark.asyncio
async def test_data_enrichment_llm_disabled_makes_no_call(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
) -> None:
    async def fail_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not run when llm_enabled is false")

    monkeypatch.setattr(
        "app.services.data_enrichment.service.run_prompt_task",
        fail_run_prompt_task,
    )
    run = await create_test_run(
        url="https://example.com/products/dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/dress",
        data={"title": "Linen Dress", "category": "Dresses"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id], "options": {"llm_enabled": False}},
    )

    await _run_job(db_session, job)

    assert job.status == DATA_ENRICHMENT_STATUS_ENRICHED


def test_data_enrichment_llm_prompt_context_excludes_raw_artifacts() -> None:
    product = EnrichedProduct(
        job_id=1,
        source_url="https://example.com/products/dress",
        status=DATA_ENRICHMENT_STATUS_PENDING,
        price_normalized={"amount": 49.99, "currency": "USD"},
        color_family="blue",
        size_normalized=["M"],
        size_system="alpha",
        gender_normalized="female",
        materials_normalized=["linen"],
        availability_normalized="in_stock",
        seo_keywords=["linen", "dress"],
        category_path="Apparel & Accessories > Clothing > Dresses",
    )

    context = _llm_prompt_context(
        {
            "title": "Linen Dress",
            "description": "<section>Clean description</section>",
            "raw_html": "<html>secret</html>",
            "_source": "artifact",
        },
        product=product,
    )

    assert "raw_html" not in context
    assert "_source" not in context
    assert context["description_excerpt"] == "Clean description"


@pytest.mark.asyncio
async def test_data_enrichment_llm_enabled_applies_valid_payload(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        captured["task_type"] = task_type
        captured["variables"] = variables
        return LLMTaskResult(
            payload={
                "category_path": "Apparel & Accessories > Clothing > Dresses",
                "intent_attributes": ["cocktail"],
                "audience": ["women"],
                "style_tags": ["classic"],
                "ai_discovery_tags": ["linen-dress"],
                "suggested_bundles": ["heels"],
            },
            provider="anthropic",
            model="claude",
        )

    monkeypatch.setattr(
        "app.services.data_enrichment.service.run_prompt_task",
        fake_run_prompt_task,
    )
    run = await create_test_run(
        url="https://example.com/products/dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/dress",
        data={"title": "Linen Dress", "category": "Dresses"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id], "options": {"llm_enabled": True}},
    )

    await _run_job(db_session, job)
    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
        )
    ).one()

    assert captured["task_type"] == "data_enrichment_semantic"
    assert "product_json" in captured["variables"]
    assert product.intent_attributes == ["cocktail"]
    assert product.ai_discovery_tags == ["linen-dress"]


@pytest.mark.asyncio
async def test_data_enrichment_llm_rejects_invalid_taxonomy_category(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={
                "category_path": "Not A Real Taxonomy Path",
                "intent_attributes": ["useful"],
                "audience": [],
                "style_tags": [],
                "ai_discovery_tags": [],
                "suggested_bundles": [],
            }
        )

    monkeypatch.setattr(
        "app.services.data_enrichment.service.run_prompt_task",
        fake_run_prompt_task,
    )
    run = await create_test_run(
        url="https://example.com/products/mystery",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/mystery",
        data={"title": "ZXQ Plinth", "category": "ZXQ Plinth"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id], "options": {"llm_enabled": True}},
    )

    await _run_job(db_session, job)
    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
        )
    ).one()

    assert product.category_path is None
    assert product.intent_attributes == ["useful"]
