from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user, get_db
from app.main import app


@pytest.fixture
async def selector_api_client(db_session, test_user):
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
async def test_selectors_api_crud_round_trip(selector_api_client: AsyncClient) -> None:
    create_response = await selector_api_client.post(
        "/api/selectors",
        json={
            "domain": "example.com",
            "surface": "ecommerce_detail",
            "field_name": "title",
            "css_selector": ".custom-title",
            "source": "manual",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    selector_id = created["id"]

    list_response = await selector_api_client.get(
        "/api/selectors",
        params={"domain": "example.com", "surface": "ecommerce_detail"},
    )
    assert list_response.status_code == 200
    assert [row["field_name"] for row in list_response.json()] == ["title"]

    update_response = await selector_api_client.put(
        f"/api/selectors/{selector_id}",
        json={"sample_value": "Widget Prime"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["sample_value"] == "Widget Prime"

    delete_response = await selector_api_client.delete(f"/api/selectors/{selector_id}")
    assert delete_response.status_code == 204

    final_list = await selector_api_client.get(
        "/api/selectors",
        params={"domain": "example.com", "surface": "ecommerce_detail"},
    )
    assert final_list.status_code == 200
    assert final_list.json() == []


@pytest.mark.asyncio
async def test_selectors_api_preview_test_and_suggest(
    selector_api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_preview(url: str):
        return {"url": url, "html": "<html><body><div>Preview</div></body></html>"}

    async def _fake_test(**kwargs):
        assert kwargs["css_selector"] == ".price"
        return {"matched_value": "$19.99", "count": 1, "selector_used": ".price"}

    async def _fake_suggest(session, *, url: str, expected_columns: list[str], surface: str | None):
        del session
        assert expected_columns == ["title"]
        return {
            "surface": surface or "ecommerce_detail",
            "preview_url": url,
            "iframe_promoted": False,
            "suggestions": {
                "title": [
                    {
                        "field_name": "title",
                        "css_selector": ".custom-title",
                        "source": "auto_css",
                    }
                ]
            },
        }

    monkeypatch.setattr("app.api.selectors.fetch_selector_document", _fake_preview)
    monkeypatch.setattr("app.api.selectors.test_selector", _fake_test)
    monkeypatch.setattr("app.api.selectors.suggest_selectors", _fake_suggest)

    preview_response = await selector_api_client.get(
        "/api/selectors/preview-html",
        params={"url": "https://example.com/products/widget"},
    )
    assert preview_response.status_code == 200
    assert "<base href=\"https://example.com/products/widget\"" in preview_response.text

    test_response = await selector_api_client.post(
        "/api/selectors/test",
        json={"url": "https://example.com/products/widget", "css_selector": ".price"},
    )
    assert test_response.status_code == 200
    assert test_response.json()["matched_value"] == "$19.99"

    suggest_response = await selector_api_client.post(
        "/api/selectors/suggest",
        json={
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
            "expected_columns": ["title"],
        },
    )
    assert suggest_response.status_code == 200
    assert suggest_response.json()["suggestions"]["title"][0]["css_selector"] == ".custom-title"


@pytest.mark.asyncio
async def test_selectors_api_lists_all_domain_records_when_surface_is_omitted(
    selector_api_client: AsyncClient,
) -> None:
    first_response = await selector_api_client.post(
        "/api/selectors",
        json={
            "domain": "example.com",
            "surface": "ecommerce_detail",
            "field_name": "price",
            "css_selector": ".detail-price",
        },
    )
    second_response = await selector_api_client.post(
        "/api/selectors",
        json={
            "domain": "example.com",
            "surface": "generic",
            "field_name": "title",
            "css_selector": "h1",
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    list_response = await selector_api_client.get(
        "/api/selectors",
        params={"domain": "example.com"},
    )

    assert list_response.status_code == 200
    assert {
        (row["surface"], row["field_name"])
        for row in list_response.json()
    } == {
        ("ecommerce_detail", "price"),
        ("generic", "title"),
    }
