from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import (
    CrawlRecord,
    ProductIntelligenceCandidate,
    ProductIntelligenceJob,
    ProductIntelligenceSourceProduct,
)
from app.schemas.product_intelligence import ProductIntelligenceDiscoveryRequest
from app.services.crawl_crud import create_crawl_run
from app.services.config.product_intelligence import (
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT,
    ProductIntelligenceSettings,
    product_intelligence_settings,
)
from app.services.llm_config_service import get_prompt_task
from app.services.product_intelligence.discovery import SearchResult, build_search_queries, classify_source_type, discover_candidates
from app.services.product_intelligence.matching import (
    extract_product_snapshot,
    extract_serpapi_snapshot,
    normalize_brand,
    score_candidate,
)
from app.services.product_intelligence.service import (
    _poll_candidate_and_score,
    create_product_intelligence_job,
    discover_product_intelligence_candidates,
)


def test_product_intelligence_query_excludes_source_and_uses_identifier() -> None:
    queries = build_search_queries(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "sku": "04511-2406",
        },
        source_domain_value="belk.com",
    )

    assert queries
    assert "site:levi.com" in queries[0]
    assert any("04511-2406" in query for query in queries)
    assert all("-site:belk.com" in query for query in queries)


def test_product_intelligence_scorer_returns_breakdown() -> None:
    result = score_candidate(
        source={
            "title": "Levi's 511 Slim Fit Jeans",
            "brand": "Levis",
            "sku": "04511",
            "price": 59.99,
        },
        candidate={
            "title": "Levi's Men's 511 Slim Fit Jeans",
            "brand": "Levi's",
            "sku": "04511",
            "price": 62.0,
        },
        source_type="brand_dtc",
    )

    assert result["score"] >= 0.7
    assert result["reasons"]["brand_match"] is True
    assert result["reasons"]["identifier_match"] is True


def test_product_intelligence_price_band_requires_positive_candidate_price() -> None:
    result = score_candidate(
        source={"title": "Levi's 511 Slim Fit Jeans", "brand": "Levis", "price": 59.99},
        candidate={"title": "Levi's 511 Slim Fit Jeans", "brand": "Levi's", "price": 0},
        source_type="brand_dtc",
    )

    assert result["reasons"]["price_band_match"] is False


def test_product_intelligence_scorer_parses_european_price_formats() -> None:
    result = score_candidate(
        source={"title": "Widget", "brand": "Acme", "price": "1.234,56"},
        candidate={"title": "Widget", "brand": "Acme", "price": "1234.56"},
        source_type="retailer",
    )

    assert result["reasons"]["price_band_match"] is True


def test_product_intelligence_classification_avoids_suffix_collisions() -> None:
    assert classify_source_type("badamazon.com", {}) == "unknown"
    assert classify_source_type("shop.amazon.com", {}) == "marketplace"


def test_product_intelligence_classifies_known_mall_mirrors_as_aggregators() -> None:
    assert classify_source_type("thesummitbirmingham.com", {}) == "aggregator"
    assert classify_source_type("www.coolspringsgalleria.com", {}) == "aggregator"


def test_product_intelligence_normalizes_childrenswear_brand_alias() -> None:
    assert normalize_brand("Ralph Lauren Childrenswear") == "ralph lauren"


def test_product_intelligence_normalizes_common_brand_aliases() -> None:
    assert normalize_brand("Kenneth Cole Reaction") == "kenneth cole"
    assert normalize_brand("Tommy Bahama®") == "tommy bahama"
    assert normalize_brand("Collection by Michael Strahan ™") == "collection by michael strahan"


def test_product_intelligence_infers_brand_from_source_url() -> None:
    snapshot = extract_product_snapshot(
        {
            "url": "https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
            "title": "Varick Slim Straight Garment-Dyed Jeans",
        }
    )

    assert snapshot["brand"] == "ralph lauren"
    assert snapshot["normalized_brand"] == "ralph lauren"


def test_product_intelligence_query_uses_brand_and_currency_inferred_from_belk_slug() -> None:
    snapshot = extract_product_snapshot(
        {
            "url": "https://www.belk.com/p/modern-southern-home--checkerboard-quilt-set/710097411786005.html",
            "title": "Checkerboard Quilt Set",
            "price": "$22.50",
        }
    )
    queries = build_search_queries(snapshot, source_domain_value="belk.com")

    assert snapshot["brand"] == "Modern Southern Home"
    assert snapshot["normalized_brand"] == "modern southern home"
    assert snapshot["currency"] == "USD"
    assert queries
    assert '"modern southern home"' in queries[0]


def test_product_intelligence_request_accepts_max_sources_and_url_aliases() -> None:
    request = ProductIntelligenceDiscoveryRequest.model_validate(
        {
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/1.html",
                    "data": {"title": "Wallet"},
                }
            ],
            "options": {
                "max_sources": 17,
                "max_urls": 1,
                "search_provider": "duckduckgo",
            },
        }
    )

    assert request.options.max_source_products == 17
    assert request.options.max_candidates_per_product == 1


def test_product_intelligence_serpapi_snapshot_keeps_description() -> None:
    snapshot = extract_serpapi_snapshot(
        {
            "title": "Varick Slim Straight Jean",
            "snippet": "Garment-dyed denim with a slim straight fit.",
            "price": "$125.00",
        },
        url="https://www.ralphlauren.com/p/varick.html",
        domain="ralphlauren.com",
    )

    assert snapshot["description"] == "Garment-dyed denim with a slim straight fit."
    assert snapshot["price"] == 125.0
    assert snapshot["currency"] == "USD"


def test_product_intelligence_serpapi_snapshot_infers_known_brand_from_compact_domain() -> None:
    snapshot = extract_serpapi_snapshot(
        {"title": "Bifold RFID Wallet", "snippet": "Leather wallet."},
        url="https://www.kennethcole.com/collections/kenneth-cole-reaction",
        domain="kennethcole.com",
    )

    assert snapshot["brand"] == "kenneth cole"
    assert snapshot["normalized_brand"] == "kenneth cole"


def test_product_intelligence_serpapi_snapshot_tries_brand_from_title_marker() -> None:
    snapshot = extract_serpapi_snapshot(
        {
            "title": "Crown & Ivy™ Hydrangea Vase",
            "snippet": "Ceramic vase for spring decor.",
            "price": "$39.99",
        },
        url="https://www.belk.com/p/crown-ivy-hydrangea-vase/760161676226SPH0073IJ.html",
        domain="belk.com",
    )

    assert snapshot["brand"] == "Crown & Ivy™"
    assert snapshot["normalized_brand"] == "crown ivy"
    assert snapshot["currency"] == "USD"


def test_product_intelligence_settings_accepts_serp_api_key_alias() -> None:
    settings = ProductIntelligenceSettings(_env_file=None, SERP_API_KEY="serp-secret")

    assert settings.serpapi_key == "serp-secret"


def test_product_intelligence_settings_falls_back_without_serpapi_key() -> None:
    settings = ProductIntelligenceSettings(_env_file=None)

    assert settings.default_search_provider == "duckduckgo"


def test_product_intelligence_settings_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        ProductIntelligenceSettings(_env_file=None, default_search_provider="bogus")


def test_product_intelligence_llm_prompt_registered() -> None:
    task = get_prompt_task("product_intelligence_enrichment")

    assert task is not None
    assert task["system_file"] == "product_intelligence_enrichment.system.txt"


@pytest.mark.asyncio
async def test_product_intelligence_discovery_preserves_serpapi_payload(monkeypatch) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        return [
            SearchResult(
                url="https://www.levi.com/p/04511.html",
                payload={
                    "provider": "serpapi",
                    "title": "Levi's 511 Slim Fit Jeans",
                    "snippet": "Official product page",
                },
            )
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "sku": "04511",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
    )

    assert candidates[0].payload["provider"] == "serpapi"
    assert candidates[0].payload["snippet"] == "Official product page"


@pytest.mark.asyncio
async def test_product_intelligence_discovery_passes_pool_limit_to_search(monkeypatch) -> None:
    limits: list[int | None] = []

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        limits.append(limit)
        return [
            SearchResult(url="https://www.levi.com/p/04511.html", payload={"title": "Levi 511"}),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(product_intelligence_settings, "discovery_pool_multiplier", 4)

    await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511"},
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=5,
    )

    assert limits
    assert set(limits) == {20}


@pytest.mark.asyncio
async def test_product_intelligence_discovery_spreads_result_domains(monkeypatch) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        return [
            SearchResult(url="https://www.levi.com/p/1.html", payload={"title": "Levi 511"}),
            SearchResult(url="https://www.levi.com/p/2.html", payload={"title": "Levi 511 sale"}),
            SearchResult(url="https://www.macys.com/p/1.html", payload={"title": "Levi 511"}),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "sku": "04511",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=2,
    )

    assert [candidate.domain for candidate in candidates] == ["levi.com", "macys.com"]


@pytest.mark.asyncio
async def test_product_intelligence_discovery_prioritizes_brand_site_over_aggregator_pool(monkeypatch) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        if "site:levi.com" in query:
            return [
                SearchResult(url="https://thesummitbirmingham.com/buy/product/511", payload={"title": "Levi 511"}),
                SearchResult(url="https://www.hamiltonplace.com/products/product/511", payload={"title": "Levi 511"}),
                SearchResult(url="https://www.coolspringsgalleria.com/products/product/511", payload={"title": "Levi 511"}),
            ]
        return [
            SearchResult(url="https://www.levi.com/p/04511.html", payload={"title": "Levi 511"}),
            SearchResult(url="https://www.macys.com/p/04511.html", payload={"title": "Levi 511"}),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "sku": "04511",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=2,
    )

    assert [candidate.domain for candidate in candidates] == ["levi.com", "macys.com"]


@pytest.mark.asyncio
async def test_product_intelligence_discovery_skips_duckduckgo_ads(monkeypatch) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        return [
            SearchResult(
                url="https://duckduckgo.com/y.js?u3=https%3A%2F%2Fad.example%2Fp",
                payload={"provider": provider, "title": "Ad"},
            ),
            SearchResult(
                url="https://www.levi.com/p/04511.html",
                payload={"provider": provider, "title": "Levi 511"},
            ),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    candidates = await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511"},
        source_domain_value="belk.com",
        provider="duckduckgo",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
    )

    assert len(candidates) == 1
    assert candidates[0].domain == "levi.com"


@pytest.mark.asyncio
async def test_product_intelligence_discovery_keeps_search_delay_while_filling_pool(monkeypatch) -> None:
    recorded_delays: list[float] = []

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        if query == "query one":
            return [
                SearchResult(url="https://www.levi.com/p/04511.html", payload={"title": "Levi 511"}),
            ]
        return [
            SearchResult(url="https://www.macys.com/p/04511.html", payload={"title": "Levi 511"}),
        ]

    async def fake_sleep(delay: float) -> None:
        recorded_delays.append(delay)

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.build_search_queries",
        lambda product, *, source_domain_value: ["query one", "query two"],
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.asyncio.sleep",
        fake_sleep,
    )
    monkeypatch.setattr(product_intelligence_settings, "search_delay_ms", 25)
    monkeypatch.setattr(product_intelligence_settings, "discovery_pool_multiplier", 2)

    candidates = await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511"},
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
    )

    assert recorded_delays == [0.025]
    assert len(candidates) == 1
    assert candidates[0].domain == "levi.com"


@pytest.mark.asyncio
async def test_product_intelligence_job_stores_source_products_and_llm_option(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://www.belk.com/category",
            "surface": "ecommerce_listing",
        },
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://www.belk.com/p/new-directions-shirt/1.html",
        data={
            "brand": "New Directions",
            "title": "Relaxed Shirt",
            "price": "$19.99",
            "url": "https://www.belk.com/p/new-directions-shirt/1.html",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    job = await create_product_intelligence_job(
        db_session,
        user=test_user,
        payload={
            "source_run_id": run.id,
            "source_record_ids": [record.id],
            "options": {
                "llm_enrichment_enabled": True,
                "private_label_mode": "flag",
            },
        },
    )

    assert job.options["llm_enrichment_enabled"] is True
    source = await db_session.scalar(
        select(ProductIntelligenceSourceProduct).where(
            ProductIntelligenceSourceProduct.job_id == job.id
        )
    )
    assert source is not None
    assert source.is_private_label is True
    assert source.price == 19.99


@pytest.mark.asyncio
async def test_product_intelligence_discovery_preview_returns_source_and_payload(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://www.belk.com/category",
            "surface": "ecommerce_listing",
        },
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
        data={
            "title": "Varick Slim Straight Garment-Dyed Jeans",
            "price": "$125.00",
            "url": "https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        return [
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans/varick/123.html",
                payload={"provider": provider, "title": "Varick jean"},
            )
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_run_id": run.id,
            "source_record_ids": [record.id],
            "options": {
                "max_source_products": 1,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
            },
        },
    )

    assert response["source_count"] == 1
    assert response["candidate_count"] == 1
    assert isinstance(response["job_id"], int)
    assert response["candidates"][0]["source_brand"] == "ralph lauren"
    assert response["candidates"][0]["payload"]["provider"] == "serpapi"
    assert response["candidates"][0]["intelligence"]["canonical_record"]["title"] == "Varick jean"
    assert response["candidates"][0]["intelligence"]["confidence_score"] >= 0


@pytest.mark.asyncio
async def test_product_intelligence_discovery_returns_max_urls_per_input_source(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        quoted = query.split('"')
        title_source = quoted[3] if len(quoted) > 3 else quoted[1] if len(quoted) > 1 else quoted[0]
        title_token = title_source.split()[0]
        return [
            SearchResult(url=f"https://www.levi.com/p/{title_token}.html", payload={"provider": provider, "title": title_token}),
            SearchResult(url=f"https://www.macys.com/p/{title_token}.html", payload={"provider": provider, "title": title_token}),
            SearchResult(url=f"https://www.nordstrom.com/p/{title_token}.html", payload={"provider": provider, "title": title_token}),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": f"https://www.belk.com/p/{index}.html",
                    "data": {
                        "brand": "Levis",
                        "title": f"Product {index} 511 Jeans",
                        "url": f"https://www.belk.com/p/{index}.html",
                    },
                }
                for index in range(4)
            ],
            "options": {
                "max_source_products": 4,
                "max_candidates_per_product": 3,
                "search_provider": "serpapi",
            },
        },
    )

    assert response["source_count"] == 4
    assert response["candidate_count"] == 12
    assert {candidate["source_index"] for candidate in response["candidates"]} == {0, 1, 2, 3}


@pytest.mark.asyncio
async def test_product_intelligence_discovery_source_count_excludes_private_label(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        del query
        return [
            SearchResult(
                url="https://www.levi.com/p/511.html",
                payload={"provider": provider, "title": "511 Jeans"},
            )
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/private.html",
                    "data": {
                        "brand": "New Directions",
                        "title": "Private label shirt",
                        "url": "https://www.belk.com/p/private.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/branded.html",
                    "data": {
                        "brand": "Levis",
                        "title": "511 Jeans",
                        "url": "https://www.belk.com/p/branded.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 1,
                "private_label_mode": "exclude",
                "search_provider": "serpapi",
            },
        },
    )

    assert response["source_count"] == 1
    assert response["candidate_count"] == 1
    assert response["candidates"][0]["source_index"] == 1


@pytest.mark.asyncio
async def test_product_intelligence_discovery_searches_title_only_sources(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        title_token = query.split('"')[1].split()[0]
        return [
            SearchResult(url=f"https://www.example-retailer.com/p/{title_token}-1.html", payload={"provider": provider, "title": title_token}),
            SearchResult(url=f"https://www.example-brand.com/p/{title_token}-2.html", payload={"provider": provider, "title": title_token}),
            SearchResult(url=f"https://www.example-market.com/p/{title_token}-3.html", payload={"provider": provider, "title": title_token}),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/branded.html",
                    "data": {
                        "brand": "Levis",
                        "title": "Branded 511 Jeans",
                        "url": "https://www.belk.com/p/branded.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/unbranded.html",
                    "data": {
                        "title": "Unbranded Slim Jeans",
                        "url": "https://www.belk.com/p/unbranded.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 3,
                "search_provider": "serpapi",
            },
        },
    )

    assert response["source_count"] == 2
    assert response["candidate_count"] == 6
    assert {candidate["source_index"] for candidate in response["candidates"]} == {0, 1}


@pytest.mark.asyncio
async def test_product_intelligence_candidate_poll_marks_timeout(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = ProductIntelligenceJob(user_id=test_user.id, options={}, summary={})
    db_session.add(job)
    await db_session.flush()
    source = ProductIntelligenceSourceProduct(
        job_id=job.id,
        source_url="https://www.belk.com/p/1",
        brand="Levi's",
        normalized_brand="levi's",
        title="511 Jeans",
        payload={},
    )
    db_session.add(source)
    await db_session.flush()
    candidate = ProductIntelligenceCandidate(
        job_id=job.id,
        source_product_id=source.id,
        url="https://www.levi.com/p/1",
        status=PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED,
        payload={},
    )
    db_session.add(candidate)
    await db_session.flush()

    monkeypatch.setattr(product_intelligence_settings, "candidate_poll_seconds", 0.0)
    await _poll_candidate_and_score(db_session, job, candidate)

    assert candidate.status == PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT
