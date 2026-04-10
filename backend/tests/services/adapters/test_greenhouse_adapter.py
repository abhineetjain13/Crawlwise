# Tests for Greenhouse adapter.
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from app.services.adapters.greenhouse import GreenhouseAdapter


@pytest.mark.asyncio
async def test_can_handle_boards_url():
    adapter = GreenhouseAdapter()
    assert await adapter.can_handle("https://boards.greenhouse.io/stripe", "")


@pytest.mark.asyncio
async def test_can_handle_embedded():
    adapter = GreenhouseAdapter()
    html = '<div id="grnhse_app"></div><script src="https://boards.greenhouse.io/embed/job_board?for=stripe"></script>'
    assert await adapter.can_handle("https://stripe.com/jobs", html)


@pytest.mark.asyncio
async def test_cannot_handle_unrelated():
    adapter = GreenhouseAdapter()
    assert not await adapter.can_handle("https://example.com", "<html>plain</html>")


@pytest.mark.asyncio
async def test_cannot_handle_unrelated_html_with_greenhouse_marker_only():
    adapter = GreenhouseAdapter()
    html = "<html><body><div id='grnhse_app'></div><p>greenhouse careers</p></body></html>"
    assert not await adapter.can_handle("https://example.com/jobs", html)


@pytest.mark.asyncio
async def test_extract_from_api():
    adapter = GreenhouseAdapter()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "jobs": [
            {
                "title": "Software Engineer",
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/123",
                "location": {"name": "San Francisco, CA"},
                "departments": [{"name": "Engineering"}],
                "updated_at": "2026-04-01T00:00:00Z",
            },
            {
                "title": "Product Manager",
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/456",
                "location": {"name": "Remote"},
                "departments": [{"name": "Product"}],
                "updated_at": "2026-04-02T00:00:00Z",
            },
        ]
    }
    with patch("app.services.adapters.greenhouse.curl_requests.get", return_value=response) as mock_get:
        result = await adapter.extract(
            "https://boards.greenhouse.io/stripe",
            "",
            "job_listing",
        )
    assert len(result.records) == 2
    assert result.records[0]["title"] == "Software Engineer"
    assert result.records[0]["location"] == "San Francisco, CA"
    assert result.records[1]["category"] == "Product"
    assert "boards-api.greenhouse.io" in mock_get.call_args.args[0]


@pytest.mark.asyncio
async def test_extract_from_html_fallback():
    adapter = GreenhouseAdapter()
    html = """
    <html><body>
    <div class="opening">
        <a href="/stripe/jobs/123">Software Engineer</a>
        <span class="location">San Francisco, CA</span>
    </div>
    <div class="opening">
        <a href="/stripe/jobs/456">Product Manager</a>
        <span class="location">Remote</span>
    </div>
    </body></html>
    """
    with patch("app.services.adapters.greenhouse.curl_requests.get", side_effect=Exception("API down")):
        result = await adapter.extract(
            "https://boards.greenhouse.io/stripe",
            html,
            "job_listing",
        )
    assert len(result.records) == 2
    assert result.records[0]["title"] == "Software Engineer"
    assert result.records[0]["location"] == "San Francisco, CA"


def test_extract_company_slug_from_embed_url():
    adapter = GreenhouseAdapter()
    assert (
        adapter._extract_company_slug("https://boards.greenhouse.io/embed/job_board?for=stripe", "")
        == "stripe"
    )


@pytest.mark.asyncio
async def test_extract_from_embedded_html_fallback():
    adapter = GreenhouseAdapter()
    html = """
    <html><body>
    <div class="opening">
      <a href="/stripe/jobs/7532733">
        <p class="body body--medium">Administrative Business Partner</p>
        <p class="body body__secondary body--metadata">San Francisco</p>
      </a>
    </div>
    </body></html>
    """
    with patch("app.services.adapters.greenhouse.curl_requests.get", side_effect=Exception("API down")):
        result = await adapter.extract(
            "https://boards.greenhouse.io/embed/job_board?for=stripe",
            html,
            "job_listing",
        )
    assert len(result.records) == 1
    assert result.records[0]["title"] == "Administrative Business Partner"
    assert result.records[0]["location"] == "San Francisco"
