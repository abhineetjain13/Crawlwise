from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.services._batch_runtime import process_run
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.crawl_crud import create_crawl_run
from app.services.domain_memory_service import save_domain_memory


@pytest.fixture
async def crawls_api_client(db_session, test_user):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_crawls_domain_recipe_routes_round_trip(
    crawls_api_client: AsyncClient,
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup_before_run = await crawls_api_client.get(
        "/api/crawls/domain-run-profile",
        params={
            "url": "https://example.com/products/domain-recipe-widget",
            "surface": "ecommerce_detail",
        },
    )
    assert lookup_before_run.status_code == 200
    assert lookup_before_run.json() == {
        "domain": "example.com",
        "surface": "ecommerce_detail",
        "saved_run_profile": None,
    }

    await save_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        selectors={
            "rules": [
                {
                    "id": 1,
                    "field_name": "title",
                    "css_selector": ".saved-title",
                    "sample_value": "Saved Selector Widget",
                    "source": "domain_memory",
                    "status": "validated",
                    "is_active": True,
                    "source_run_id": 41,
                }
            ]
        },
    )
    await db_session.commit()

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/domain-recipe-widget",
            "surface": "ecommerce_detail",
            "additional_fields": ["brand"],
            "settings": {
                "extraction_contract": [
                    {
                        "field_name": "price",
                        "css_selector": ".run-price",
                    }
                ]
            },
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="""
            <html>
              <body>
                <div class="saved-title">Saved Selector Widget</div>
                <div class="run-price">$19.99</div>
                <div class="brand">Example Brand</div>
              </body>
            </html>
            """,
            method="browser",
            status_code=200,
            browser_diagnostics={"browser_reason": "http-escalation"},
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    recipe_response = await crawls_api_client.get(f"/api/crawls/{run.id}/domain-recipe")
    assert recipe_response.status_code == 200
    recipe = recipe_response.json()
    assert recipe["requested_field_coverage"] == {
        "requested": ["brand"],
        "found": ["brand"],
        "missing": [],
    }
    assert recipe["affordance_candidates"]["browser_required"] is True
    assert {row["field_name"] for row in recipe["selector_candidates"]} == {"title", "price"}

    save_profile_response = await crawls_api_client.post(
        f"/api/crawls/{run.id}/domain-recipe/save-run-profile",
        json={
            "profile": {
                "fetch_profile": {
                    "fetch_mode": "http_then_browser",
                    "extraction_source": "rendered_dom",
                    "js_mode": "enabled",
                    "include_iframes": False,
                    "traversal_mode": "paginate",
                    "request_delay_ms": 1200,
                    "max_pages": 8,
                    "max_scrolls": 12,
                },
                "locality_profile": {
                    "geo_country": "IN",
                    "language_hint": "en-IN",
                    "currency_hint": "INR",
                },
                "diagnostics_profile": {
                    "capture_html": True,
                    "capture_screenshot": False,
                    "capture_network": "matched_only",
                    "capture_response_headers": True,
                    "capture_browser_diagnostics": True,
                },
            }
        },
    )
    assert save_profile_response.status_code == 200
    saved_profile = save_profile_response.json()
    assert saved_profile["fetch_profile"]["fetch_mode"] == "http_then_browser"
    assert saved_profile["locality_profile"]["geo_country"] == "IN"
    assert saved_profile["source_run_id"] == run.id

    lookup_after_save = await crawls_api_client.get(
        "/api/crawls/domain-run-profile",
        params={
            "url": "https://example.com/products/domain-recipe-widget",
            "surface": "ecommerce_detail",
        },
    )
    assert lookup_after_save.status_code == 200
    assert lookup_after_save.json()["saved_run_profile"]["fetch_profile"]["fetch_mode"] == "http_then_browser"

    promote_response = await crawls_api_client.post(
        f"/api/crawls/{run.id}/domain-recipe/promote-selectors",
        json={
            "selectors": [
                {
                    "candidate_key": "price|css_selector|.run-price",
                    "field_name": "price",
                    "selector_kind": "css_selector",
                    "selector_value": ".run-price",
                    "sample_value": "$19.99",
                }
            ]
        },
    )
    assert promote_response.status_code == 200
    promoted = promote_response.json()
    assert len(promoted) == 1
    assert promoted[0]["field_name"] == "price"
    assert promoted[0]["source"] == "domain_recipe"
    assert promoted[0]["source_run_id"] == run.id

    recipe_after_save = await crawls_api_client.get(f"/api/crawls/{run.id}/domain-recipe")
    assert recipe_after_save.status_code == 200
    saved_recipe = recipe_after_save.json()
    assert saved_recipe["saved_run_profile"]["fetch_profile"]["fetch_mode"] == "http_then_browser"
    assert any(row["field_name"] == "price" for row in saved_recipe["saved_selectors"])
    promoted_candidate = next(
        row for row in saved_recipe["selector_candidates"] if row["field_name"] == "price"
    )
    assert promoted_candidate["already_saved"] is True
    assert promoted_candidate["saved_selector_id"] == promoted[0]["id"]
