# Tests for platform adapters.
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from app.services.adapters.amazon import AmazonAdapter
from app.services.adapters.base import AdapterResult
from app.services.adapters.ebay import EbayAdapter
from app.services.adapters.indeed import IndeedAdapter
from app.services.adapters.linkedin import LinkedInAdapter
from app.services.adapters.registry import resolve_adapter
from app.services.adapters.shopify import ShopifyAdapter
from app.services.adapters.walmart import WalmartAdapter


# --- Shopify ---

@pytest.mark.asyncio
async def test_shopify_can_handle():
    adapter = ShopifyAdapter()
    assert await adapter.can_handle("https://myshopify.com/store", "")
    assert await adapter.can_handle("https://store.com", '<script>Shopify.theme = {}</script>')
    assert not await adapter.can_handle("https://example.com", "<html>plain page</html>")


@pytest.mark.asyncio
async def test_shopify_embedded_product():
    adapter = ShopifyAdapter()
    html = """
    <html><body>
    <script>var meta = {"product": {"title": "Cool Shirt", "vendor": "BrandX", "price": 2999, "type": "Apparel"}};</script>
    <script>Shopify.theme = {}</script>
    </body></html>
    """
    result = await adapter.extract("https://store.com/products/shirt", html, "ecommerce_detail")
    assert isinstance(result, AdapterResult)
    assert len(result.records) >= 1
    assert result.records[0]["title"] == "Cool Shirt"


@pytest.mark.asyncio
async def test_shopify_detail_uses_handle_specific_endpoint():
    adapter = ShopifyAdapter()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "title": "Scoped Shirt",
        "vendor": "BrandX",
        "handle": "shirt",
        "variants": [{"price": "29.99", "sku": "SKU-1", "available": True}],
        "images": [{"src": "https://cdn.example.com/shirt.jpg"}],
        "product_type": "Apparel",
        "tags": "summer, cotton",
    }
    with patch("app.services.adapters.shopify.curl_requests.get", return_value=response) as mock_get:
        result = await adapter.extract(
            "https://store.com/products/shirt",
            '<script>Shopify.theme = {}</script>',
            "ecommerce_detail",
        )
    assert len(result.records) == 1
    assert result.records[0]["title"] == "Scoped Shirt"
    assert mock_get.call_args.args[0] == "https://store.com/products/shirt.js"


# --- Amazon ---

@pytest.mark.asyncio
async def test_amazon_can_handle():
    adapter = AmazonAdapter()
    assert await adapter.can_handle("https://www.amazon.com/dp/B08N5", "")
    assert not await adapter.can_handle("https://ebay.com/item", "")


@pytest.mark.asyncio
async def test_amazon_detail_extraction():
    adapter = AmazonAdapter()
    html = """
    <html><body>
    <span id="productTitle">Amazing Widget</span>
    <span class="a-price"><span class="a-offscreen">$24.99</span></span>
    <a id="bylineInfo">Brand: WidgetCo</a>
    </body></html>
    """
    result = await adapter.extract("https://www.amazon.com/dp/B123", html, "ecommerce_detail")
    assert len(result.records) == 1
    assert result.records[0]["title"] == "Amazing Widget"
    assert result.records[0]["price"] == "$24.99"


@pytest.mark.asyncio
async def test_amazon_listing_extraction():
    adapter = AmazonAdapter()
    html = """
    <html><body>
    <div data-component-type="s-search-result">
        <h2><a href="/dp/B1"><span>Product One</span></a></h2>
        <span class="a-price-whole">19.</span><span class="a-price-fraction">99</span>
        <img class="s-image" src="https://img.amazon.com/1.jpg" />
    </div>
    <div data-component-type="s-search-result">
        <h2><a href="/dp/B2"><span>Product Two</span></a></h2>
    </div>
    </body></html>
    """
    result = await adapter.extract("https://www.amazon.com/s?k=widget", html, "ecommerce_listing")
    assert len(result.records) == 2
    assert result.records[0]["price"] == "19.99"


# --- eBay ---

@pytest.mark.asyncio
async def test_ebay_can_handle():
    adapter = EbayAdapter()
    assert await adapter.can_handle("https://www.ebay.com/itm/123", "")
    assert not await adapter.can_handle("https://amazon.com/dp/B1", "")


# --- Indeed ---

@pytest.mark.asyncio
async def test_indeed_can_handle():
    adapter = IndeedAdapter()
    assert await adapter.can_handle("https://www.indeed.com/viewjob?jk=abc", "")
    assert not await adapter.can_handle("https://linkedin.com/jobs", "")


@pytest.mark.asyncio
async def test_indeed_detail_extraction():
    adapter = IndeedAdapter()
    html = """
    <html><body>
    <h1 class="jobsearch-JobInfoHeader-title">Senior Developer</h1>
    <div data-company-name><a>TechCorp</a></div>
    <div id="jobDescriptionText">Build cool stuff</div>
    </body></html>
    """
    result = await adapter.extract("https://www.indeed.com/viewjob", html, "job_detail")
    assert len(result.records) == 1
    assert result.records[0]["title"] == "Senior Developer"
    assert result.records[0]["company"] == "TechCorp"


# --- LinkedIn ---

@pytest.mark.asyncio
async def test_linkedin_can_handle():
    adapter = LinkedInAdapter()
    assert await adapter.can_handle("https://www.linkedin.com/jobs/view/123", "")
    assert not await adapter.can_handle("https://www.linkedin.com/in/profile", "")


# --- Registry ---

@pytest.mark.asyncio
async def test_registry_resolves_amazon():
    adapter = await resolve_adapter("https://www.amazon.com/dp/B1", "")
    assert adapter is not None
    assert adapter.name == "amazon"


@pytest.mark.asyncio
async def test_registry_resolves_shopify_by_signal():
    adapter = await resolve_adapter("https://custom-store.com/products/shirt", '<script>Shopify.theme = {}</script>')
    assert adapter is not None
    assert adapter.name == "shopify"


@pytest.mark.asyncio
async def test_registry_returns_none_for_unknown():
    adapter = await resolve_adapter("https://random-site.xyz/page", "<html>plain</html>")
    assert adapter is None
