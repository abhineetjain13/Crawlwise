from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord, EnrichedProduct
from app.schemas.data_enrichment import DataEnrichmentJobDetailResponse
from app.services.llm_types import LLMTaskResult
from app.services.config.data_enrichment import (
    DATA_ENRICHMENT_STATUS_DEGRADED,
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_FAILED,
    DATA_ENRICHMENT_STATUS_PENDING,
    DATA_ENRICHMENT_TAXONOMY_VERSION,
)
from app.services.data_enrichment.service import (
    _build_deterministic_enrichment,
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

    with pytest.raises(
        ValueError, match="No unenriched ecommerce detail records selected"
    ):
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

    with pytest.raises(
        ValueError, match="No unenriched ecommerce detail records selected"
    ):
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
    assert product.taxonomy_version == DATA_ENRICHMENT_TAXONOMY_VERSION
    assert (
        product.diagnostics["product_category"]["category_path"]
        == "Apparel & Accessories > Clothing > Dresses"
    )
    assert (
        product.diagnostics["product_category"]["taxonomy_reference"]["category_path"]
        == "Apparel & Accessories > Clothing > Dresses"
    )
    assert (
        product.diagnostics["product_category"]["taxonomy_version"]
        == DATA_ENRICHMENT_TAXONOMY_VERSION
    )
    assert "fabric" in product.diagnostics["product_attributes"]["present_attributes"]
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
async def test_data_enrichment_reenrichment_clears_taxonomy_version_before_rerun(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
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

    first_job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id]},
    )
    await _run_job(db_session, first_job)
    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.source_record_id == record.id)
        )
    ).one()
    assert product.taxonomy_version == DATA_ENRICHMENT_TAXONOMY_VERSION

    record.enrichment_status = "unenriched"
    await db_session.commit()
    second_job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id]},
    )
    refreshed = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == second_job.id)
        )
    ).one()

    assert refreshed.taxonomy_version is None


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
        taxonomy_version=DATA_ENRICHMENT_TAXONOMY_VERSION,
    )

    context = _llm_prompt_context(
        {
            "title": "Linen Dress",
            "description": "<section>Clean description</section>",
            "raw_html": "<html>secret</html>",
            "_source": "artifact",
        },
        product=product,
        category_candidates=[],
    )

    assert "raw_html" not in context
    assert "_source" not in context
    assert context["description_excerpt"] == "Clean description"
    assert context["taxonomy_version"] == DATA_ENRICHMENT_TAXONOMY_VERSION


def test_data_enrichment_variant_dict_values_do_not_pollute_sizes_or_availability() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "Cotton Shirt",
            "category": "Shirts",
            "variants": [
                {
                    "size": "medium",
                    "color": "blue",
                    "sku": "CD",
                    "image": "https://example.com/image.jpg",
                }
            ],
        },
        source_url="https://example.com/products/shirt",
    )

    assert enrichment["size_normalized"] == ["M"]
    assert enrichment["color_family"] == "blue"
    assert enrichment["availability_normalized"] is None


def test_data_enrichment_variant_fit_does_not_become_size() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "Cotton Trouser",
            "category": "Pants",
            "variants": [
                {
                    "size": "medium",
                    "fit": "regular fit",
                    "width": "wide",
                }
            ],
        },
        source_url="https://example.com/products/trouser",
    )

    assert enrichment["size_normalized"] == ["M"]


def test_data_enrichment_category_uses_primary_category_before_title_noise() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "KitchenAid 13-cup food processor",
            "brand": "KitchenAid",
            "category": "Kitchen Appliances",
        },
        source_url="https://example.com/products/food-processor",
    )

    assert (
        enrichment["category_path"]
        == "Home & Garden > Kitchen & Dining > Kitchen Appliances"
    )
    assert "Cup Sleeves" not in str(enrichment["category_path"])


def test_data_enrichment_uses_apparel_context_for_pant_set_taxonomy() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "Fashion Nova Pant Set",
            "category": "Women Pant Sets",
            "product_type": "Pant Set",
        },
        source_url="https://example.com/products/pant-set",
    )

    assert (
        enrichment["category_path"] == "Apparel & Accessories > Clothing > Outfit Sets"
    )


def test_data_enrichment_maps_apparel_breadcrumb_matching_sets_to_outfit_sets() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "Just Vibes Strapless Pant Set - Yellow",
            "category": "Women > Matching Sets",
        },
        source_url="https://www.fashionnova.com/products/just-vibes-strapless-pant-set-yellow",
    )

    assert (
        enrichment["category_path"] == "Apparel & Accessories > Clothing > Outfit Sets"
    )


def test_data_enrichment_exact_shopify_path_match_wins() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "Navy Linen Midi Dress",
            "category": "Apparel & Accessories > Clothing > Dresses",
        },
        source_url="https://example.com/products/dress",
    )

    assert enrichment["category_path"] == "Apparel & Accessories > Clothing > Dresses"
    assert enrichment["_taxonomy_match"]["source"] == "exact_path"


def test_data_enrichment_scored_match_maps_category_phrase_to_shopify_path() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "Navy Linen Midi Dress",
            "category": "Cocktail Dresses",
        },
        source_url="https://example.com/products/dress",
    )

    assert enrichment["category_path"] == "Apparel & Accessories > Clothing > Dresses"
    assert enrichment["_taxonomy_match"]["source"] == "scored_match"


def test_data_enrichment_seo_keywords_filter_stopwords_from_all_sources() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "Navy Linen Dress",
            "brand": "Acme",
            "category": "Sale Dresses With Linen",
            "materials": "linen",
        },
        source_url="https://example.com/products/dress",
    )

    keywords = set(enrichment["seo_keywords"] or [])
    assert "sale" not in keywords
    assert "with" not in keywords
    assert "linen" in keywords


def test_data_enrichment_does_not_normalize_non_apparel_numeric_size() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "ColourPop 24 pan eyeshadow palette",
            "category": "Beauty > Makeup > Eyeshadow",
            "size": "24",
        },
        source_url="https://example.com/products/palette",
    )

    assert enrichment["size_normalized"] is None
    assert enrichment["size_system"] is None


def test_data_enrichment_materials_ignore_care_instruction_noise() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "Linen Shirt",
            "category": "Shirts",
            "product_attributes": {"Composition": "100% linen"},
            "description": "Care: Iron warm if needed. Cotton denim leather glossary.",
        },
        source_url="https://example.com/products/shirt",
    )

    assert enrichment["materials_normalized"] == ["linen"]


def test_data_enrichment_price_infers_firstcry_currency() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "Black Seascape Stretch Bracelet",
            "price": "868.21",
            "category": "Bracelets",
        },
        source_url="https://www.firstcry.com/example/product-detail",
    )

    assert enrichment["price_normalized"] == {"amount": 868.21, "currency": "INR"}


def test_data_enrichment_seo_keywords_include_title_bigrams() -> None:
    enrichment = _build_deterministic_enrichment(
        {
            "title": "Black Seascape Stretch Bracelet",
            "price": "868.21",
            "category": "Bracelets",
        },
        source_url="https://www.firstcry.com/example/product-detail",
    )

    assert "black seascape" in set(enrichment["seo_keywords"] or [])


@pytest.mark.asyncio
async def test_data_enrichment_rolls_back_after_sqlalchemy_product_failure(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/batch",
        surface="ecommerce_detail",
    )
    bad_record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/bad",
        data={"title": "Bad Shirt", "category": "Shirts"},
    )
    good_record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/good",
        data={"title": "Good Shirt", "category": "Shirts"},
    )
    db_session.add_all([bad_record, good_record])
    await db_session.commit()
    await db_session.refresh(bad_record)
    await db_session.refresh(good_record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [bad_record.id, good_record.id]},
    )
    calls = 0
    original_rollback = db_session.rollback
    rollbacks = 0

    async def counted_rollback() -> None:
        nonlocal rollbacks
        rollbacks += 1
        await original_rollback()

    async def fake_enrich_product(session, *, job, product, record, llm_enabled):
        nonlocal calls
        del session, job, llm_enabled
        calls += 1
        if calls == 1:
            raise PendingRollbackError("flush failed earlier")
        product.category_path = "Apparel & Accessories > Clothing > Shirts"
        product.diagnostics = {"deterministic": True}

    monkeypatch.setattr(db_session, "rollback", counted_rollback)
    monkeypatch.setattr(
        "app.services.data_enrichment.service._enrich_product",
        fake_enrich_product,
    )

    await _run_job(db_session, job)
    products = list(
        (
            await db_session.scalars(
                select(EnrichedProduct)
                .where(EnrichedProduct.job_id == job.id)
                .order_by(EnrichedProduct.id)
            )
        ).all()
    )

    assert rollbacks == 1
    assert job.status == DATA_ENRICHMENT_STATUS_DEGRADED
    assert [product.status for product in products] == [
        DATA_ENRICHMENT_STATUS_FAILED,
        DATA_ENRICHMENT_STATUS_ENRICHED,
    ]


@pytest.mark.asyncio
async def test_data_enrichment_llm_enabled_backfills_missing_fields_in_one_call(
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
                "color_family": "blue",
                "size_normalized": ["Medium (M)"],
                "size_system": "alpha",
                "gender_normalized": "female",
                "materials_normalized": ["linen"],
                "availability_normalized": "in_stock",
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
        data={"title": "Linen Dress", "category": "ZXQ Plinth"},
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
    assert product.category_path == "Apparel & Accessories > Clothing > Dresses"
    assert product.color_family == "blue"
    assert product.size_normalized == ["M"]
    assert product.size_system == "alpha"
    assert product.gender_normalized == "female"
    assert product.materials_normalized == ["linen"]
    assert product.availability_normalized == "in_stock"
    assert product.intent_attributes == ["cocktail"]
    assert product.ai_discovery_tags == ["linen-dress"]
    assert product.diagnostics["llm"]["applied_fields"]


@pytest.mark.asyncio
async def test_data_enrichment_llm_does_not_overwrite_deterministic_fields(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={
                "category_path": "Apparel & Accessories > Clothing > Shirts",
                "color_family": "red",
                "size_normalized": ["XL"],
                "gender_normalized": "male",
                "materials_normalized": ["wool"],
                "availability_normalized": "out_of_stock",
                "intent_attributes": ["useful"],
                "audience": ["men"],
                "style_tags": ["sharp"],
                "ai_discovery_tags": ["linen-dress"],
                "suggested_bundles": ["boots"],
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
        source_url="https://example.com/products/dress",
        data={
            "title": "Linen Dress",
            "category": "Dresses",
            "color": "navy",
            "size": "medium",
            "gender": "women",
            "materials": "linen",
            "availability": "In stock",
        },
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

    assert product.category_path == "Apparel & Accessories > Clothing > Dresses"
    assert product.color_family == "blue"
    assert product.size_normalized == ["M"]
    assert product.gender_normalized == "female"
    assert product.materials_normalized == ["linen"]
    assert product.availability_normalized == "in_stock"
    assert product.intent_attributes == ["useful"]
    assert product.suggested_bundles == ["boots"]


@pytest.mark.asyncio
async def test_data_enrichment_llm_rejects_non_shopify_category_path(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={
                "category_path": "Hardware > Plinths",
                "intent_attributes": ["useful"],
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
    assert "category_path" not in product.diagnostics["llm"]["applied_fields"]


@pytest.mark.asyncio
async def test_data_enrichment_llm_ignores_non_dict_payload(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(payload="bad-payload")

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

    assert product.category_path == "Apparel & Accessories > Clothing > Dresses"
    assert product.diagnostics["llm"]["applied"] is False
