# Tests for platform adapters.
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from app.services.adapters.amazon import AmazonAdapter
from app.services.adapters.adp import ADPAdapter
from app.services.adapters.base import AdapterResult
from app.services.adapters.ebay import EbayAdapter
from app.services.adapters.icims import ICIMSAdapter
from app.services.adapters.indeed import IndeedAdapter
from app.services.adapters.jibe import JibeAdapter
from app.services.adapters.linkedin import LinkedInAdapter
from app.services.adapters.oracle_hcm import OracleHCMAdapter
from app.services.adapters.paycom import PaycomAdapter
from app.services.adapters.registry import resolve_adapter
from app.services.adapters.shopify import ShopifyAdapter


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
async def test_shopify_detail_prefers_embedded_product_over_public_endpoint():
    adapter = ShopifyAdapter()
    html = """
    <html><body>
    <script>var meta = {"product": {"title": "Embedded Shirt", "vendor": "BrandX", "price": 2999, "type": "Apparel"}};</script>
    <script>Shopify.theme = {}</script>
    </body></html>
    """
    with patch("app.services.adapters.shopify.curl_requests.get") as mock_get:
        result = await adapter.extract("https://store.com/products/shirt", html, "ecommerce_detail")
    assert len(result.records) >= 1
    assert result.records[0]["title"] == "Embedded Shirt"
    mock_get.assert_not_called()


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
    assert result.records[0]["price"] == "29.99"
    assert mock_get.call_args.args[0] == "https://store.com/products/shirt.js"


@pytest.mark.asyncio
async def test_shopify_detail_accepts_string_image_array():
    adapter = ShopifyAdapter()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "title": "String Image Shirt",
        "vendor": "BrandX",
        "handle": "shirt",
        "variants": [{"price": "29.99", "sku": "SKU-1", "available": True}],
        "images": ["https://cdn.example.com/shirt.jpg"],
        "product_type": "Apparel",
        "tags": [],
    }
    with patch("app.services.adapters.shopify.curl_requests.get", return_value=response):
        result = await adapter.extract(
            "https://store.com/products/shirt",
            '<script>Shopify.theme = {}</script>',
            "ecommerce_detail",
        )
    assert len(result.records) == 1
    assert result.records[0]["image_url"] == "https://cdn.example.com/shirt.jpg"


@pytest.mark.asyncio
async def test_shopify_listing_uses_collection_specific_endpoint():
    adapter = ShopifyAdapter()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "products": [
            {
                "title": "Collection Item",
                "vendor": "BrandX",
                "handle": "collection-item",
                "variants": [{"price": "19.99", "sku": "SKU-9", "available": True}],
                "images": [{"src": "https://cdn.example.com/item.jpg"}],
                "product_type": "Apparel",
                "tags": "featured, summer",
            }
        ]
    }
    with patch("app.services.adapters.shopify.curl_requests.get", return_value=response) as mock_get:
        result = await adapter.extract(
            "https://store.com/collections/summer-shirts",
            '<script>Shopify.theme = {}</script>',
            "ecommerce_listing",
        )
    assert len(result.records) == 1
    assert result.records[0]["title"] == "Collection Item"
    assert mock_get.call_args.args[0] == "https://store.com/collections/summer-shirts/products.json?limit=250"


@pytest.mark.asyncio
async def test_shopify_public_endpoint_recovery_works_without_html_signals():
    adapter = ShopifyAdapter()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "products": [
            {
                "title": "Recovered Collection Item",
                "vendor": "BrandX",
                "handle": "recovered-item",
                "variants": [{"price": "24.99", "sku": "SKU-22", "available": True}],
                "images": [{"src": "https://cdn.example.com/recovered.jpg"}],
                "product_type": "Apparel",
                "tags": "featured",
            }
        ]
    }
    with patch("app.services.adapters.shopify.curl_requests.get", return_value=response) as mock_get:
        records = await adapter.try_public_endpoint(
            "https://store.com/collections/maternity-dresses",
            "ecommerce_listing",
        )
    assert len(records) == 1
    assert records[0]["title"] == "Recovered Collection Item"
    assert mock_get.call_args.args[0] == "https://store.com/collections/maternity-dresses/products.json?limit=250"


@pytest.mark.asyncio
async def test_shopify_normalizes_protocol_relative_image_urls():
    adapter = ShopifyAdapter()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "title": "Protocol Image Shirt",
        "vendor": "BrandX",
        "handle": "shirt",
        "variants": [{"price": "29.99", "sku": "SKU-1", "available": True}],
        "images": ["//cdn.example.com/shirt.jpg"],
        "product_type": "Apparel",
        "tags": [],
    }
    with patch("app.services.adapters.shopify.curl_requests.get", return_value=response):
        result = await adapter.extract(
            "https://store.com/products/shirt",
            '<script>Shopify.theme = {}</script>',
            "ecommerce_detail",
        )
    assert len(result.records) == 1
    assert result.records[0]["image_url"] == "https://cdn.example.com/shirt.jpg"


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


# --- iCIMS ---

@pytest.mark.asyncio
async def test_icims_can_handle():
    adapter = ICIMSAdapter()
    assert await adapter.can_handle("https://example.icims.com/jobs/search", "")
    assert not await adapter.can_handle("https://linkedin.com/jobs", "")


# --- Jibe ---

@pytest.mark.asyncio
async def test_jibe_can_handle():
    adapter = JibeAdapter()
    html = """
    <html data-jibe-search-version="4.11.178">
      <script>window._jibe = {"cid":"thecheesecakefactory"};</script>
      <script>window.searchConfig = {"query":{"keywords":"Dough Bird","limit":"100"}};</script>
    </html>
    """
    assert await adapter.can_handle("https://www.foxrccareers.com/jobs?keywords=Dough%20Bird", html)
    assert not await adapter.can_handle("https://example.com/jobs", "<html>plain</html>")


@pytest.mark.asyncio
async def test_jibe_extract_listing_uses_public_jobs_endpoint():
    adapter = JibeAdapter()
    html = """
    <html data-jibe-search-version="4.11.178">
      <script>
        window.searchConfig = {
          "query": {
            "tags1": "Doughbird",
            "limit": "100",
            "page": "1",
            "keywords": "Dough Bird"
          }
        };
      </script>
    </html>
    """
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "jobs": [
            {
                "data": {
                    "req_id": "5920",
                    "slug": "5920",
                    "title": "Dishwasher",
                    "description": "<p>Apply Today Hiring - Dishwasher</p>",
                    "full_location": "Phoenix, Arizona",
                    "hiring_organization": "Doughbird",
                    "employment_type": "FULL_TIME",
                    "posted_date": "2026-04-06T15:10:00+0000",
                    "apply_url": "https://apply.example.com/jobs/5920",
                    "categories": [{"name": "Kitchen"}],
                    "tags7": "$16.00 - $19.25 / Hour",
                    "meta_data": {"canonical_url": "https://www.foxrccareers.com/jobs/5920?lang=en-us"},
                }
            }
        ]
    }
    with patch("app.services.adapters.jibe.curl_requests.get", return_value=response) as mock_get:
        result = await adapter.extract(
            "https://www.foxrccareers.com/foxrc-careers-home/jobs?keywords=Dough%20Bird",
            html,
            "job_listing",
        )
    assert len(result.records) == 1
    assert result.records[0]["title"] == "Dishwasher"
    assert result.records[0]["company"] == "Doughbird"
    assert result.records[0]["job_id"] == "5920"
    called_url = mock_get.call_args.args[0]
    assert called_url.startswith("https://www.foxrccareers.com/api/jobs?")
    assert "keywords=Dough+Bird" in called_url
    assert "limit=100" in called_url


# --- Oracle HCM ---

@pytest.mark.asyncio
async def test_oracle_hcm_can_handle():
    adapter = OracleHCMAdapter()
    html = """
    <html><body>
      <script>
        var CX_CONFIG = {
          app: {
            apiBaseUrl: 'https://ibmwjb.fa.ocs.oraclecloud.com:443',
            siteName: 'Brookdale Senior Living Inc.',
            siteNumber: 'CX_1',
            siteLang: 'en'
          }
        };
      </script>
    </body></html>
    """
    assert await adapter.can_handle(
        "https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?mode=location",
        html,
    )
    assert not await adapter.can_handle("https://example.com/jobs", "<html>plain</html>")


@pytest.mark.asyncio
async def test_oracle_hcm_extract_listing_uses_public_requisitions_endpoint():
    adapter = OracleHCMAdapter()
    html = """
    <html><body>
      <meta property="og:site_name" content="Brookdale Senior Living Inc." />
      <script>
        var CX_CONFIG = {
          app: {
            apiBaseUrl: 'https://ibmwjb.fa.ocs.oraclecloud.com:443',
            siteName: 'Brookdale Senior Living Inc.',
            siteNumber: 'CX_1',
            siteLang: 'en'
          }
        };
      </script>
    </body></html>
    """
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "items": [
            {
                "requisitionList": [
                    {
                        "Id": "25019248",
                        "Title": "Server",
                        "PostedDate": "2026-04-06",
                        "PrimaryLocation": "Sparks, NV, United States",
                        "Organization": "Dining",
                        "Department": "Restaurant",
                        "JobType": "Full Time",
                        "ShortDescriptionStr": "<p>Serve residents and guests.</p>",
                        "workLocation": [
                            {
                                "TownOrCity": "Sparks",
                                "Region2": "NV",
                                "Country": "US",
                            }
                        ],
                    }
                ]
            }
        ]
    }
    with patch("app.services.adapters.oracle_hcm.curl_requests.get", return_value=response) as mock_get:
        result = await adapter.extract(
            "https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?mode=location",
            html,
            "job_listing",
        )
    assert len(result.records) == 1
    assert result.records[0]["title"] == "Server"
    assert result.records[0]["job_id"] == "25019248"
    assert result.records[0]["company"] == "Brookdale Senior Living Inc."
    assert result.records[0]["category"] == "Dining"
    assert result.records[0]["department"] == "Restaurant"
    assert result.records[0]["job_type"] == "Full Time"
    assert result.records[0]["description"] == "Serve residents and guests."
    assert result.records[0]["url"] == "https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/25019248/"
    called_url = mock_get.call_args.args[0]
    assert "recruitingCEJobRequisitions" in called_url
    assert "siteNumber=CX_1" in called_url


def test_oracle_hcm_extract_cx_config_accepts_single_quoted_json_fallback():
    adapter = OracleHCMAdapter()
    html = """
    <html><body>
      <script>
        var CX_CONFIG = {'app': {'siteNumber': 'CX_1', 'siteLang': 'en', 'siteName': 'Brookdale Senior Living Inc.', 'enabled': true}};
      </script>
    </body></html>
    """

    config = adapter._extract_cx_config(html)

    assert config["app"]["siteNumber"] == "CX_1"


@pytest.mark.asyncio
async def test_oracle_hcm_listing_paginates_based_on_raw_response_count_not_filtered_records():
    adapter = OracleHCMAdapter()
    html = """
    <html><body>
      <script>
        var CX_CONFIG = {
          app: {
            apiBaseUrl: 'https://ibmwjb.fa.ocs.oraclecloud.com:443',
            siteName: 'Brookdale Senior Living Inc.',
            siteNumber: 'CX_1',
            siteLang: 'en'
          }
        };
      </script>
    </body></html>
    """
    first_response = Mock()
    first_response.status_code = 200
    first_response.json.return_value = {
        "items": (
            [{"requisitionList": [{"Id": "1", "Title": "Role 1"}]}]
            + [{"requisitionList": [{"Id": "2", "Title": "Role 2"}]}]
            + [{"requisitionList": [{"Id": "2", "Title": "Role 2 duplicate"}]} for _ in range(98)]
        )
    }
    second_response = Mock()
    second_response.status_code = 200
    second_response.json.return_value = {
        "items": [
            {"requisitionList": [{"Id": "3", "Title": "Role 3"}]},
        ]
    }

    with patch("app.services.adapters.oracle_hcm.curl_requests.get", side_effect=[first_response, second_response]) as mock_get:
        records = await adapter.try_public_endpoint(
            "https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs",
            html,
            "job_listing",
        )

    assert [record["job_id"] for record in records] == ["1", "2", "3"]
    assert mock_get.call_count == 2


# --- Paycom ---

@pytest.mark.asyncio
async def test_paycom_can_handle():
    adapter = PaycomAdapter()
    html = """
    <html><body>
      <script>
        var configsFromHost = {
          "sessionJWT": "token-123",
          "libConfig": "{\\"locale\\":\\"en-US\\",\\"atsPortalMantleServiceUrl\\":\\"https://portal-applicant-tracking.us-cent.paycomonline.net\\"}"
        };
        var Mountable = {};
      </script>
    </body></html>
    """
    assert await adapter.can_handle(
        "https://www.paycomonline.net/v4/ats/web.php/portal/client/career-page",
        html,
    )
    assert not await adapter.can_handle("https://example.com/jobs", "<html>plain</html>")


@pytest.mark.asyncio
async def test_paycom_extract_listing_uses_public_preview_endpoint():
    adapter = PaycomAdapter()
    html = """
    <html><body>
      <script>
        var configsFromHost = {
          "sessionJWT": "token-123",
          "libConfig": "{\\"locale\\":\\"en-US\\",\\"atsPortalMantleServiceUrl\\":\\"https://portal-applicant-tracking.us-cent.paycomonline.net\\"}"
        };
        var Mountable = {};
      </script>
    </body></html>
    """
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "jobPostingPreviews": [
            {
                "jobId": 62197,
                "jobTitle": "Controller",
                "locations": "Columbus, OH 43215",
                "description": "Lead the financial operations.",
                "postedOn": "2026-04-06",
                "positionType": "Full Time",
            }
        ],
        "jobPostingPreviewsCount": 1,
    }
    with patch("app.services.adapters.paycom.curl_requests.post", return_value=response) as mock_post:
        result = await adapter.extract(
            "https://www.paycomonline.net/v4/ats/web.php/portal/8EC14E985B45C7F52C531F487F62A2B8/career-page",
            html,
            "job_listing",
        )
    assert len(result.records) == 1
    assert result.records[0]["title"] == "Controller"
    assert result.records[0]["job_id"] == "62197"
    assert result.records[0]["location"] == "Columbus, OH 43215"
    assert result.records[0]["job_type"] == "Full Time"
    assert result.records[0]["url"] == "https://www.paycomonline.net/v4/ats/web.php/portal/8EC14E985B45C7F52C531F487F62A2B8/jobs/62197"
    called_url = mock_post.call_args.args[0]
    assert called_url == "https://portal-applicant-tracking.us-cent.paycomonline.net/api/ats/job-posting-previews/search"
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["authorization"] == "token-123"


# --- ADP ---

@pytest.mark.asyncio
async def test_adp_can_handle():
    adapter = ADPAdapter()
    assert await adapter.can_handle(
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=tenant",
        "",
    )
    assert not await adapter.can_handle("https://linkedin.com/jobs", "")


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
async def test_registry_resolves_icims_by_domain():
    adapter = await resolve_adapter("https://example.icims.com/jobs/search", "")
    assert adapter is not None
    assert adapter.name == "icims"


@pytest.mark.asyncio
async def test_registry_resolves_jibe_by_signal():
    adapter = await resolve_adapter(
        "https://www.foxrccareers.com/jobs",
        '<html data-jibe-search-version="4.11.178"><script>window._jibe={};</script></html>',
    )
    assert adapter is not None
    assert adapter.name == "jibe"


@pytest.mark.asyncio
async def test_registry_resolves_oracle_hcm_by_domain():
    adapter = await resolve_adapter(
        "https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?mode=location",
        "",
    )
    assert adapter is not None
    assert adapter.name == "oracle_hcm"


@pytest.mark.asyncio
async def test_registry_resolves_paycom_by_domain():
    adapter = await resolve_adapter(
        "https://www.paycomonline.net/v4/ats/web.php/portal/client/career-page",
        "",
    )
    assert adapter is not None
    assert adapter.name == "paycom"

@pytest.mark.asyncio
async def test_registry_resolves_adp_by_domain():
    adapter = await resolve_adapter(
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=tenant",
        "",
    )
    assert adapter is not None
    assert adapter.name == "adp"


@pytest.mark.asyncio
async def test_registry_returns_none_for_unknown():
    adapter = await resolve_adapter("https://random-site.xyz/page", "<html>plain</html>")
    assert adapter is None
