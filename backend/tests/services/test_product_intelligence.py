from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import (
    CrawlRecord,
    ProductIntelligenceCandidate,
    ProductIntelligenceJob,
    ProductIntelligenceMatch,
    ProductIntelligenceSourceProduct,
)
from app.schemas.product_intelligence import ProductIntelligenceDiscoveryRequest
from app.services.config.product_intelligence import (
    GOOGLE_NATIVE_HOME_URL,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT,
    ProductIntelligenceSettings,
    product_intelligence_settings,
)
from app.services.llm_config_service import get_prompt_task
from app.services.product_intelligence.discovery import (
    SearchResult,
    _google_native_blocked,
    _google_native_session,
    _parse_google_native_results,
    build_search_queries,
    classify_source_type,
    discover_candidates,
)
from app.services.product_intelligence.matching import (
    build_search_result_intelligence,
    extract_product_snapshot,
    extract_search_result_snapshot,
    normalize_brand,
    score_candidate,
)
from app.services.llm_circuit_breaker import LLMErrorCategory
from app.services.llm_types import LLMTaskResult
from app.services.product_intelligence.service import (
    _backfill_candidate_brand,
    _poll_candidate_and_score,
    _resolve_source_snapshot,
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
    assert all("-site:belk.com" in query for query in queries)
    assert any("levi's" in query for query in queries)
    assert len(queries) <= 5


def test_product_intelligence_query_keeps_brand_in_all_queries_when_brand_exists() -> None:
    queries = build_search_queries(
        {
            "brand": "Mamaearth",
            "title": "Vit. C Daily Glow Cream 150g",
            "sku": "20510856",
        },
        source_domain_value="myntra.com",
    )

    assert queries
    assert any("mamaearth" in query for query in queries)
    assert all("-site:myntra.com" in query for query in queries)
    assert queries[0] == 'mamaearth vit c daily glow cream 150g 20510856 -site:myntra.com'
    assert len(queries) <= 5


def test_product_intelligence_query_prefers_clean_brand_query_before_buy_for_aggregator_sources() -> None:
    queries = build_search_queries(
        {
            "brand": "Asaya",
            "title": "Even Evermore Cream 50g",
            "sku": "31145778",
        },
        source_domain_value="flipkart.com",
    )

    assert queries
    assert queries[0] == 'asaya even evermore cream 50g 31145778 -site:flipkart.com'
    assert len(queries) <= 4


def test_product_intelligence_query_uses_brandless_fallback_only_when_brand_missing() -> None:
    queries = build_search_queries(
        {
            "title": "Vit. C Daily Glow Cream 150g",
            "sku": "20510856",
        },
        source_domain_value="myntra.com",
    )

    assert queries
    assert any('20510856' in query for query in queries)
    assert all("mamaearth" not in query for query in queries)
    assert len(queries) == 2


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


def test_product_intelligence_classifies_common_aggregator_sources() -> None:
    assert classify_source_type("www.myntra.com", {}) == "retailer"
    assert classify_source_type("www.nykaa.com", {}) == "retailer"
    assert classify_source_type("www.flipkart.com", {}) == "marketplace"


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
    assert 'modern southern home' in queries[0]


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
                "search_provider": "serpapi",
            },
        }
    )

    assert request.options.max_source_products == 17
    assert request.options.max_candidates_per_product == 1


def test_product_intelligence_search_result_snapshot_keeps_description() -> None:
    snapshot = extract_search_result_snapshot(
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


def test_product_intelligence_search_result_snapshot_infers_known_brand_from_compact_domain() -> None:
    snapshot = extract_search_result_snapshot(
        {"title": "Bifold RFID Wallet", "snippet": "Leather wallet."},
        url="https://www.kennethcole.com/collections/kenneth-cole-reaction",
        domain="kennethcole.com",
    )

    assert snapshot["brand"] == "kenneth cole"
    assert snapshot["normalized_brand"] == "kenneth cole"


def test_product_intelligence_search_result_snapshot_tries_brand_from_title_marker() -> None:
    snapshot = extract_search_result_snapshot(
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


def test_product_intelligence_settings_default_provider_is_serpapi() -> None:
    settings = ProductIntelligenceSettings(_env_file=None)

    assert settings.default_search_provider == "serpapi"


def test_product_intelligence_settings_accepts_google_native_provider() -> None:
    settings = ProductIntelligenceSettings(
        _env_file=None,
        default_search_provider="google_native",
    )

    assert settings.default_search_provider == "google_native"


def test_product_intelligence_settings_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        ProductIntelligenceSettings(_env_file=None, default_search_provider="bogus")


def test_product_intelligence_settings_rejects_legacy_duckduckgo_provider() -> None:
    with pytest.raises(ValueError):
        ProductIntelligenceSettings(_env_file=None, default_search_provider="duckduckgo")


def test_parse_google_native_results_extracts_redirect_targets() -> None:
    html = """
    <html><body>
      <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget&sa=U"><h3>Widget</h3></a>
      <a href="https://www.google.com/preferences"><h3>Settings</h3></a>
    </body></html>
    """

    results = _parse_google_native_results(html, limit=5)

    assert results[0].url == "https://shop.example.com/p/widget"
    assert results[0].payload["provider"] == "google_native"


def test_parse_google_native_results_skips_anchors_without_h3() -> None:
    """Non-organic anchors (shopping carousel, PAA, ads, knowledge panels)
    have anchor text but no inner h3; they must be ignored."""
    html = """
    <html><body>
      <a href="https://www.amazon.com/sponsored">Sponsored amazon link</a>
      <a href="https://en.wikipedia.org/wiki/Widget">People also ask: what is a widget?</a>
      <div class="result">
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget&sa=U">
          <h3>Widget Pro Edition</h3>
        </a>
      </div>
    </body></html>
    """

    results = _parse_google_native_results(html, limit=5)

    assert len(results) == 1
    assert results[0].url == "https://shop.example.com/p/widget"


def test_parse_google_native_results_prefers_h3_over_anchor_text() -> None:
    html = """
    <html><body>
      <div class="result">
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget&sa=U">
          <h3>Widget Pro Edition</h3>
          <span>shop.example.com &rsaquo; p &rsaquo; widget</span>
        </a>
      </div>
    </body></html>
    """

    results = _parse_google_native_results(html, limit=5)

    assert results[0].payload["title"] == "Widget Pro Edition"


def test_parse_google_native_results_extracts_thumbnail_from_result_container() -> None:
    html = """
    <html><body>
      <div class="result-block">
        <img src="https://example.com/thumb.jpg" alt="thumb">
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget&sa=U">
          <h3>Widget</h3>
        </a>
      </div>
    </body></html>
    """

    results = _parse_google_native_results(html, limit=5)

    assert results[0].payload["thumbnail"] == "https://example.com/thumb.jpg"


def test_google_native_block_detection_flags_google_unusual_traffic_page() -> None:
    html = """
    <html><body>
      <p>Our systems have detected unusual traffic from your computer network.</p>
      <p>This page checks to see if it's really you sending the requests.</p>
    </body></html>
    """

    assert _google_native_blocked("https://www.google.com/sorry/index", html) is True


def test_google_native_thumbnail_flows_into_snapshot_image_url() -> None:
    snapshot = extract_search_result_snapshot(
        {
            "provider": "google_native",
            "title": "Widget",
            "thumbnail": "https://example.com/thumb.jpg",
        },
        url="https://shop.example.com/p/widget",
        domain="example.com",
    )

    assert snapshot["image_url"] == "https://example.com/thumb.jpg"


def test_google_native_intelligence_keeps_provider_label() -> None:
    intelligence = build_search_result_intelligence(
        source={"title": "Nike Air Max", "brand": "Nike"},
        candidate_payload={"provider": "google_native", "title": "Nike Air Max"},
        candidate_url="https://www.nike.com/in/w/air-max",
        candidate_domain="nike.com",
        source_type="brand_dtc",
    )

    assert intelligence["cleanup_source"] == "deterministic_google_native"


@pytest.mark.asyncio
async def test_google_native_session_reuses_single_page_across_queries(monkeypatch) -> None:
    actions: list[str] = []
    current_url = GOOGLE_NATIVE_HOME_URL
    html_by_url: dict[str, str] = {}

    class _Page:
        async def goto(self, url: str, *, wait_until: str, timeout: int):
            nonlocal current_url
            current_url = url
            actions.append(f"goto:{url}")

        async def wait_for_timeout(self, timeout_ms: int) -> None:
            actions.append(f"wait:{timeout_ms}")

        @property
        def url(self) -> str:
            return current_url

    class _Runtime:
        def page(self, **kwargs):
            actions.append(f"page-acquired:{kwargs.get('domain')}")

            class _Context:
                async def __aenter__(self):
                    return _Page()

                async def __aexit__(self, exc_type, exc, tb):
                    actions.append("page-released")
                    return None

            return _Context()

    async def _fake_runtime(*, browser_engine: str):
        actions.append(f"engine:{browser_engine}")
        return _Runtime()

    async def _fake_behavior(_page):
        actions.append("behavior")
        return {"enabled": True}

    async def _fake_html(_page):
        return html_by_url.get(
            current_url,
            """
            <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget"><h3>Widget</h3></a>
            """,
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.get_browser_runtime",
        _fake_runtime,
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.get_page_html",
        _fake_html,
    )

    async with _google_native_session() as run_query:
        html_by_url[_fake_search_url("blue shoe", 3)] = """
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget"><h3>Widget</h3></a>
        """
        html_by_url[_fake_search_url("red shoe", 3)] = """
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fother"><h3>Other Widget</h3></a>
        """
        html_by_url[_fake_search_url("green shoe", 3)] = """
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fthird"><h3>Third Widget</h3></a>
        """
        first = await run_query("blue shoe", 3)
        second = await run_query("red shoe", 3)
        third = await run_query("green shoe", 3)

    # One runtime acquisition, then a fresh page per query.
    assert actions.count("page-acquired:google.com") == 1
    assert actions.count("page-released") == 1
    search_navs = [action for action in actions if action.startswith("goto:") and "/search" in action]
    assert len(search_navs) == 3
    assert first[0].url == "https://shop.example.com/p/widget"
    assert second and third


@pytest.mark.asyncio
async def test_google_native_session_stops_after_google_sorry_page(monkeypatch) -> None:
    actions: list[str] = []
    current_url = GOOGLE_NATIVE_HOME_URL
    html_by_url: dict[str, str] = {}

    class _Page:
        async def goto(self, url: str, *, wait_until: str, timeout: int):
            nonlocal current_url
            current_url = url
            actions.append(f"goto:{url}")

        async def wait_for_timeout(self, timeout_ms: int) -> None:
            actions.append(f"wait:{timeout_ms}")

        @property
        def url(self) -> str:
            return current_url

    class _Runtime:
        def page(self, **kwargs):
            actions.append(f"page-acquired:{kwargs.get('domain')}")

            class _Context:
                async def __aenter__(self):
                    return _Page()

                async def __aexit__(self, exc_type, exc, tb):
                    actions.append("page-released")
                    return None

            return _Context()

    async def _fake_runtime(*, browser_engine: str):
        actions.append(f"engine:{browser_engine}")
        return _Runtime()

    async def _fake_behavior(_page):
        actions.append("behavior")
        return {"enabled": True}

    async def _fake_html(_page):
        return html_by_url.get(current_url, "")

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.get_browser_runtime",
        _fake_runtime,
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.get_page_html",
        _fake_html,
    )

    blocked_url = _fake_search_url("blue shoe", 3)
    html_by_url[blocked_url] = """
    <html><body>
      <p>Our systems have detected unusual traffic from your computer network.</p>
      <p>This page checks to see if it's really you sending the requests.</p>
    </body></html>
    """

    async with _google_native_session() as run_query:
        first = await run_query("blue shoe", 3)
        second = await run_query("red shoe", 3)

    assert first == []
    assert second == []
    search_navs = [action for action in actions if action.startswith("goto:") and "/search" in action]
    assert len(search_navs) == 1


def _fake_search_url(query: str, limit: int) -> str:
    from urllib.parse import urlencode

    return (
        f"https://www.google.com/search?"
        f"{urlencode({'q': query, 'num': str(limit)})}"
    )


def test_product_intelligence_llm_prompt_registered() -> None:
    task = get_prompt_task("product_intelligence_enrichment")

    assert task is not None
    assert task["system_file"] == "product_intelligence_enrichment.system.txt"


def test_product_intelligence_brand_inference_prompt_registered() -> None:
    task = get_prompt_task("product_intelligence_brand_inference")

    assert task is not None
    assert task["system_file"] == "product_intelligence_brand_inference.system.txt"
    assert task["user_file"] == "product_intelligence_brand_inference.user.txt"


@pytest.mark.asyncio
async def test_resolve_source_snapshot_skips_llm_when_brand_present(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_run_prompt_task(*args, **kwargs):
        calls.append(kwargs.get("task_type", ""))
        raise AssertionError("LLM must not be called when brand already resolved")

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await _resolve_source_snapshot(
        session=None,  # never used because LLM path is gated off
        raw={"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "url": "https://www.belk.com/p/1.html"},
        llm_enabled=True,
    )

    assert snapshot["brand"] == "Levis"
    assert snapshot["normalized_brand"] == "levi's"
    assert calls == []


@pytest.mark.asyncio
async def test_resolve_source_snapshot_skips_llm_when_disabled(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called when llm_enabled is False")

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await _resolve_source_snapshot(
        session=None,
        raw={"title": "Wundermost Bodysuit", "url": "https://shop.example.com/products/wundermost.html"},
        llm_enabled=False,
    )

    assert snapshot["brand"] == ""
    assert snapshot["normalized_brand"] == ""


@pytest.mark.asyncio
async def test_resolve_source_snapshot_uses_llm_brand_when_confident(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        captured["task_type"] = task_type
        captured["domain"] = domain
        captured["variables"] = variables
        return LLMTaskResult(
            payload={"brand": "Lululemon", "confidence": 0.92, "rationale": "DTC URL match"},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await _resolve_source_snapshot(
        session=None,
        raw={
            "title": "Wundermost Bodysuit",
            "url": "https://www.lululemon.com/products/p/wundermost-bodysuit.html",
        },
        llm_enabled=True,
    )

    assert snapshot["brand"] == "Lululemon"
    assert snapshot["normalized_brand"] == "lululemon"
    assert captured["task_type"] == "product_intelligence_brand_inference"
    assert captured["domain"] == "lululemon.com"
    assert captured["variables"]["product_title"] == "Wundermost Bodysuit"
    assert captured["variables"]["source_domain"] == "lululemon.com"


@pytest.mark.asyncio
async def test_resolve_source_snapshot_drops_low_confidence_llm_brand(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={"brand": "MaybeBrand", "confidence": 0.2, "rationale": "weak signal"},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await _resolve_source_snapshot(
        session=None,
        raw={"title": "Random Title", "url": "https://retailer.example.com/p/123.html"},
        llm_enabled=True,
    )

    assert snapshot["brand"] == ""
    assert snapshot["normalized_brand"] == ""


@pytest.mark.asyncio
async def test_resolve_source_snapshot_swallows_llm_error(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload=None,
            error_message="provider unavailable",
            error_category=LLMErrorCategory.PROVIDER_ERROR,
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await _resolve_source_snapshot(
        session=None,
        raw={"title": "Random Title", "url": "https://retailer.example.com/p/123.html"},
        llm_enabled=True,
    )

    assert snapshot["brand"] == ""
    assert snapshot["normalized_brand"] == ""


@pytest.mark.asyncio
async def test_resolve_source_snapshot_skips_llm_when_no_inputs(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called without title or url")

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await _resolve_source_snapshot(
        session=None,
        raw={},
        llm_enabled=True,
    )

    assert snapshot["brand"] == ""


def _build_candidate_intelligence(*, brand: str = "", title: str = "Wundermost Bodysuit") -> dict[str, object]:
    return {
        "canonical_record": {
            "title": title,
            "brand": brand,
            "normalized_brand": normalize_brand(brand),
            "url": "https://www.lululemon.com/products/p/wundermost-bodysuit/1.html",
            "snippet": "",
            "description": "",
        },
        "confidence_score": 0.30,
        "confidence_label": "uncertain",
        "score_reasons": {"brand_match": False},
        "cleanup_source": "deterministic_google_native",
        "llm_enrichment": {"requested": False, "applied": False},
    }


@pytest.mark.asyncio
async def test_backfill_candidate_brand_skips_when_disabled(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called when llm_enabled is False")

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    result = await _backfill_candidate_brand(
        session=None,
        source={"title": "Lululemon Wundermost Bodysuit", "brand": "Lululemon"},
        intelligence=intelligence,
        source_type="brand_dtc",
        llm_enabled=False,
    )

    assert result is intelligence


@pytest.mark.asyncio
async def test_backfill_candidate_brand_skips_when_brand_present(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called when candidate brand is set")

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence(brand="Lululemon")
    result = await _backfill_candidate_brand(
        session=None,
        source={"title": "Lululemon Wundermost Bodysuit", "brand": "Lululemon"},
        intelligence=intelligence,
        source_type="brand_dtc",
        llm_enabled=True,
    )

    assert result is intelligence


@pytest.mark.asyncio
async def test_backfill_candidate_brand_applies_llm_brand_and_rescores(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={"brand": "Lululemon", "confidence": 0.91, "rationale": "DTC URL match"},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    source = {
        "title": "Lululemon Wundermost Bodysuit",
        "brand": "Lululemon",
        "normalized_brand": "lululemon",
    }
    result = await _backfill_candidate_brand(
        session=None,
        source=source,
        intelligence=intelligence,
        source_type="brand_dtc",
        llm_enabled=True,
    )

    canonical = result["canonical_record"]
    assert canonical["brand"] == "Lululemon"
    assert canonical["normalized_brand"] == "lululemon"
    assert result["score_reasons"]["brand_match"] is True
    assert result["confidence_score"] > intelligence["confidence_score"]


@pytest.mark.asyncio
async def test_backfill_candidate_brand_drops_low_confidence(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={"brand": "Maybe", "confidence": 0.1, "rationale": "weak"},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    result = await _backfill_candidate_brand(
        session=None,
        source={"title": "Wundermost Bodysuit", "brand": ""},
        intelligence=intelligence,
        source_type="unknown",
        llm_enabled=True,
    )

    assert result is intelligence


@pytest.mark.asyncio
async def test_backfill_candidate_brand_handles_llm_error(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload=None,
            error_message="provider down",
            error_category=LLMErrorCategory.PROVIDER_ERROR,
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    result = await _backfill_candidate_brand(
        session=None,
        source={"title": "Anything", "brand": ""},
        intelligence=intelligence,
        source_type="retailer",
        llm_enabled=True,
    )

    assert result is intelligence


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
    monkeypatch.setattr(product_intelligence_settings, "discovery_pool_multiplier", 4)

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
async def test_product_intelligence_discovery_skips_invalid_result_urls(monkeypatch) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        return [
            SearchResult(
                url="javascript:void(0)",
                payload={"provider": provider, "title": "Bad scheme"},
            ),
            SearchResult(
                url="",
                payload={"provider": provider, "title": "Empty"},
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
        provider="serpapi",
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
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://www.belk.com/category",
        surface="ecommerce_listing",
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
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://www.belk.com/category",
        surface="ecommerce_listing",
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
    assert response["candidates"][0]["intelligence"]["canonical_record"]["price"] is None
    assert response["candidates"][0]["intelligence"]["confidence_score"] >= 0
    persisted_match = await db_session.scalar(
        select(ProductIntelligenceMatch).where(
            ProductIntelligenceMatch.job_id == response["job_id"]
        )
    )
    assert persisted_match is not None
    assert persisted_match.candidate_price is None


@pytest.mark.asyncio
async def test_product_intelligence_discovery_prefers_row_source_url_for_query_exclusion(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    seen_queries: list[str] = []

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        del provider, limit
        seen_queries.append(query)
        return [
            SearchResult(
                url="https://www.example-brand.com/p/item.html",
                payload={"provider": "google_native", "title": "Example Item"},
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
                    "source_url": "https://www.myntra.com/shoes/example-item",
                    "data": {
                        "title": "Example Item",
                        "brand": "Example Brand",
                        "url": "https://www.belk.com/p/stale-item.html",
                    },
                }
            ],
            "options": {
                "max_source_products": 1,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
            },
        },
    )

    assert seen_queries
    assert all("-site:myntra.com" in query for query in seen_queries)
    assert all("-site:belk.com" not in query for query in seen_queries)
    assert response["candidates"][0]["source_url"] == "https://www.myntra.com/shoes/example-item"


@pytest.mark.asyncio
async def test_product_intelligence_discovery_reuses_one_query_runner_for_multiple_sources(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    enter_count = 0
    seen_queries: list[str] = []

    class _Runner:
        async def __aenter__(self):
            nonlocal enter_count
            enter_count += 1

            async def _run(query: str, limit: int) -> list[SearchResult]:
                del limit
                seen_queries.append(query)
                token = len(seen_queries)
                return [
                    SearchResult(
                        url=f"https://www.levi.com/p/{token}.html",
                        payload={"provider": "google_native", "title": f"Result {token}", "price": "$55.00"},
                    )
                ]

            return _run

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "app.services.product_intelligence.service.shared_query_runner",
        lambda provider: _Runner(),
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/one.html",
                    "data": {
                        "brand": "Levis",
                        "title": "Product One 511 Jeans",
                        "url": "https://www.belk.com/p/one.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/two.html",
                    "data": {
                        "brand": "Levis",
                        "title": "Product Two 511 Jeans",
                        "url": "https://www.belk.com/p/two.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 1,
                "search_provider": "google_native",
            },
        },
    )

    assert response["candidate_count"] == 2
    assert enter_count == 1
    assert len(seen_queries) >= 2


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
        title_token = query.split()[0]
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
