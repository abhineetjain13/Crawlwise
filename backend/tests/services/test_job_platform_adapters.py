from __future__ import annotations

import httpx
import pytest

from app.services.acquisition.http_client import HttpFetchResult, request_result
from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.adapters.registry import registered_adapters, run_adapter
from app.services.adapters.saashr import SaaSHRAdapter
from app.services.adapters.shopify import ShopifyAdapter
from app.services.adapters.ultipro import UltiProAdapter
from app.services.adapters.workday import WorkdayAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.listing_extractor import extract_listing_records
from app.services.platform_url_normalizers import normalize_platform_acquisition_url


class _DummyAdapter(BaseAdapter):
    async def can_handle(self, url: str, html: str) -> bool:
        return True

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        self.captured_surface = surface
        return AdapterResult()

    async def _request_result(self, url: str, **kwargs) -> HttpFetchResult:
        self.captured_expect_json = bool(kwargs.get("expect_json"))
        return HttpFetchResult(
            url=url,
            final_url=url,
            text="<html><body><pre>{\"ok\": true}</pre></body></html>",
            status_code=200,
            headers=httpx.Headers({"content-type": "text/html"}),
            json_data={"ok": True},
        )


class _ExplodingAdapter(BaseAdapter):
    name = "workday"
    platform_family = "workday"

    async def can_handle(self, url: str, html: str) -> bool:
        del url, html
        return True

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        del url, html, surface
        raise RuntimeError("adapter failure")


@pytest.mark.asyncio
async def test_base_adapter_request_json_uses_json_request_contract() -> None:
    adapter = _DummyAdapter()

    payload = await adapter._request_json("https://example.com/api/jobs")

    assert payload == {"ok": True}
    assert adapter.captured_expect_json is True


@pytest.mark.asyncio
async def test_run_adapter_skips_job_platform_adapter_for_commerce_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.adapters.registry.registered_adapters",
        lambda: (_ExplodingAdapter(),),
    )

    result = await run_adapter(
        "https://www.kitchenaid.com/products/widget",
        "<html><body>workday</body></html>",
        "ecommerce_listing",
    )

    assert result is None


@pytest.mark.asyncio
async def test_run_adapter_coerces_nullable_surface_to_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _DummyAdapter()
    adapter.name = "shopify"
    adapter.platform_family = "shopify"
    monkeypatch.setattr(
        "app.services.adapters.registry.registered_adapters",
        lambda: (adapter,),
    )

    result = await run_adapter(
        "https://example.com/products/widget",
        "<html><body>product</body></html>",
        None,
    )

    assert result == AdapterResult()
    assert adapter.captured_surface == ""


@pytest.mark.asyncio
async def test_run_adapter_fails_open_when_adapter_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exploding = _ExplodingAdapter()
    exploding.name = "shopify"
    exploding.platform_family = "shopify"
    monkeypatch.setattr(
        "app.services.adapters.registry.registered_adapters",
        lambda: (exploding,),
    )

    result = await run_adapter(
        "https://example.com/products/widget",
        "<html><body>product</body></html>",
        "ecommerce_detail",
    )

    assert result is None


def test_platform_owned_adp_acquisition_normalization_keeps_generic_flow_generic() -> None:
    normalized = normalize_platform_acquisition_url(
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?jobId= 12345 &lang=en_US"
    )

    assert normalized == (
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?jobId=12345&lang=en_US"
    )


def test_platform_owned_adp_acquisition_normalization_uses_configured_domains() -> None:
    normalized = normalize_platform_acquisition_url(
        "https://acme.wd5.myworkforcenow.com/recruitment/recruitment.html?jobId= 12345 "
    )

    assert normalized == (
        "https://acme.wd5.myworkforcenow.com/recruitment/recruitment.html?jobId=12345"
    )


@pytest.mark.asyncio
async def test_ats_adapter_request_timeout_comes_from_runtime_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()
    observed_timeouts: list[int] = []

    async def _fake_request_json(url: str, **kwargs):
        del url
        observed_timeouts.append(int(kwargs["timeout_seconds"]))
        return {"total": 0, "jobPostings": []}

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)
    monkeypatch.setattr(adapter_runtime_settings, "ats_request_timeout_seconds", 7)

    await adapter.extract(
        "https://example.wd5.myworkdayjobs.com/en-US/External",
        "",
        "job_listing",
    )

    assert observed_timeouts == [7]


@pytest.mark.asyncio
async def test_request_result_uses_direct_http_for_expected_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeResponse:
        status_code = 200
        url = "https://example.com/api/jobs"
        headers = httpx.Headers({"content-type": "application/json"})
        text = '<html><body><pre>{"jobs":[{"id":1}]}</pre></body></html>'

    class _FakeClient:
        async def request(
            self,
            method,
            url,
            headers=None,
            json=None,
            data=None,
            timeout=None,
        ):
            del method, url, headers, json, data, timeout
            return _FakeResponse()

    async def _fake_get_shared(*, proxy=None, force_ipv4=False):
        del proxy, force_ipv4
        return _FakeClient()

    monkeypatch.setattr(
        "app.services.acquisition.http_client.get_shared_http_client",
        _fake_get_shared,
    )

    result = await request_result(
        "https://example.com/api/jobs",
        expect_json=True,
    )

    assert result.json_data == {"jobs": [{"id": 1}]}


@pytest.mark.asyncio
async def test_request_result_does_not_orchestrate_browser_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_methods: list[str] = []

    class _FakeResponse:
        status_code = 200
        url = "https://example.com/jobs/123"
        headers = httpx.Headers({"content-type": "text/html"})
        text = "<html><body>detail page</body></html>"

    class _FakeClient:
        async def request(
            self,
            method,
            url,
            headers=None,
            json=None,
            data=None,
            timeout=None,
        ):
            del url, headers, json, data, timeout
            observed_methods.append(str(method))
            return _FakeResponse()

    async def _fake_get_shared(*, proxy=None, force_ipv4=False):
        del proxy, force_ipv4
        return _FakeClient()

    monkeypatch.setattr(
        "app.services.acquisition.http_client.get_shared_http_client",
        _fake_get_shared,
    )

    result = await request_result(
        "https://example.com/jobs/123",
        prefer_browser=True,
    )

    assert observed_methods == ["GET"]
    assert result.text == "<html><body>detail page</body></html>"


@pytest.mark.asyncio
async def test_request_result_applies_per_request_timeout_with_shared_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.acquisition import runtime as runtime_module

    observed_timeouts: list[float] = []

    class _FakeResponse:
        status_code = 200
        url = "https://example.com/api/jobs"
        headers = httpx.Headers({"content-type": "application/json"})
        text = '{"jobs":[{"id":1}]}'

    class _FakeClient:
        is_closed = False

        async def request(
            self,
            method,
            url,
            headers=None,
            json=None,
            data=None,
            timeout=None,
        ):
            del method, url, headers, json, data
            observed_timeouts.append(float(timeout))
            return _FakeResponse()

        async def aclose(self) -> None:
            self.is_closed = True

    monkeypatch.setattr(
        "app.services.acquisition.runtime.build_async_http_client",
        lambda **kwargs: _FakeClient(),
    )
    runtime_module._SHARED_HTTP_CLIENTS.clear()

    await request_result(
        "https://example.com/api/jobs",
        expect_json=True,
        timeout_seconds=1.5,
    )
    await request_result(
        "https://example.com/api/jobs",
        expect_json=True,
        timeout_seconds=3.0,
    )

    assert observed_timeouts == [1.5, 3.0]


@pytest.mark.asyncio
async def test_request_result_surfaces_dns_failure_without_hidden_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeClient:
        async def request(
            self,
            method,
            url,
            headers=None,
            json=None,
            data=None,
            timeout=None,
        ):
            del method, url, headers, json, data, timeout
            raise OSError(11001, "getaddrinfo failed")

    async def _fake_get_shared(*, proxy=None, force_ipv4=False):
        del proxy, force_ipv4
        return _FakeClient()

    monkeypatch.setattr(
        "app.services.acquisition.http_client.get_shared_http_client",
        _fake_get_shared,
    )

    with pytest.raises(OSError, match="getaddrinfo failed"):
        await request_result(
            "https://example.com/api/jobs",
            expect_json=True,
        )


@pytest.mark.asyncio
async def test_workday_adapter_extracts_listing_from_cxs_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_request_json(url: str, **kwargs):
        calls.append((url, kwargs))
        return {
            "total": 1,
            "jobPostings": [
                {
                    "title": "Sports Medicine Territory Manager (Lexington, KY)",
                    "externalPath": "/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
                    "locationsText": "US - Lexington",
                    "postedOn": "Posted Yesterday",
                    "bulletFields": ["R89546"],
                }
            ],
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)
    html = (
        '<a href="/en-US/External/job/US---Lexington/'
        'Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1">'
        "Sports Medicine Territory Manager (Lexington, KY)</a>"
    )

    result = await adapter.extract(
        "https://smithnephew.wd5.myworkdayjobs.com/External",
        html,
        "job_listing",
    )

    assert calls[0][0] == "https://smithnephew.wd5.myworkdayjobs.com/wday/cxs/smithnephew/External/jobs"
    assert calls[0][1]["method"] == "POST"
    assert result.records == [
        {
            "title": "Sports Medicine Territory Manager (Lexington, KY)",
            "url": "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
            "apply_url": "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
            "location": "US - Lexington",
            "posted_date": "Posted Yesterday",
            "job_id": "R89546",
        }
    ]


@pytest.mark.asyncio
async def test_workday_adapter_normalizes_listing_paths_without_leading_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return {
            "total": 1,
            "jobPostings": [
                {
                    "title": "Assembler",
                    "externalPath": "job/US-WI/Assembler_REQ-1",
                }
            ],
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    result = await adapter.extract(
        "https://example.wd5.myworkdayjobs.com/en-US/External",
        "",
        "job_listing",
    )

    assert result.records[0]["url"] == (
        "https://example.wd5.myworkdayjobs.com/en-US/External/job/US-WI/Assembler_REQ-1"
    )


@pytest.mark.asyncio
async def test_workday_adapter_extracts_detail_from_cxs_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()
    captured_urls: list[str] = []

    async def _fake_request_json(url: str, **kwargs):
        del kwargs
        captured_urls.append(url)
        return {
            "jobPostingInfo": {
                "title": "Sports Medicine Territory Manager (Lexington, KY)",
                "jobDescription": "<p>Lead the territory.</p><h2>Benefits</h2><p>Health and dental.</p>",
                "location": "US - Lexington",
                "postedOn": "Posted Yesterday",
                "timeType": "Full time",
                "jobReqId": "R89546",
                "externalUrl": "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
                "country": "United States",
            },
            "hiringOrganization": {"name": "Smith+Nephew"},
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    result = await adapter.extract(
        "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
        "",
        "job_detail",
    )

    assert captured_urls == [
        "https://smithnephew.wd5.myworkdayjobs.com/wday/cxs/smithnephew/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1"
    ]
    assert result.records == [
        {
            "title": "Sports Medicine Territory Manager (Lexington, KY)",
            "url": "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
            "apply_url": "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
            "location": "US - Lexington",
            "posted_date": "Posted Yesterday",
            "job_type": "Full time",
            "job_id": "R89546",
            "country": "United States",
            "company": "Smith+Nephew",
            "description": "Lead the territory. Benefits Health and dental.",
            "benefits": "Health and dental.",
        }
    ]


@pytest.mark.asyncio
async def test_workday_adapter_falls_back_to_html_when_detail_title_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return {
            "jobPostingInfo": {
                "title": "",
                "jobDescription": "",
            }
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    result = await adapter.extract(
        "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
        "<html><body><h1>HTML fallback title</h1><p>HTML fallback description</p></body></html>",
        "job_detail",
    )

    assert result.records == []


@pytest.mark.asyncio
async def test_workday_adapter_does_not_duplicate_localized_prefix_in_listing_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return {
            "total": 1,
            "jobPostings": [
                {
                    "title": "Assembler",
                    "externalPath": "/en-US/External/job/US-WI/Assembler_REQ-1",
                }
            ],
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    result = await adapter.extract(
        "https://example.wd5.myworkdayjobs.com/en-US/External",
        "",
        "job_listing",
    )

    assert result.records[0]["url"] == (
        "https://example.wd5.myworkdayjobs.com/en-US/External/job/US-WI/Assembler_REQ-1"
    )


@pytest.mark.asyncio
async def test_ultipro_adapter_extracts_listing_from_jobboard_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = UltiProAdapter()
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_request_json(url: str, **kwargs):
        calls.append((url, kwargs))
        return {
            "opportunities": [
                {
                    "Id": "opp-1",
                    "Title": "Assembler",
                    "LocationName": "Grafton, WI",
                    "PostedDate": "2026-04-10",
                    "RequisitionNumber": "REQ-100",
                    "JobCategoryName": "Manufacturing",
                    "PostingId": "post-1",
                }
            ]
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    result = await adapter.extract(
        "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/?q=&o=postedDateDesc",
        "",
        "job_listing",
    )

    assert calls[0][0] == (
        "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/"
        "1e739e24-c237-44f3-9f7a-310b0cec4162/JobBoardView/LoadSearchResults"
    )
    assert calls[0][1]["method"] == "POST"
    assert calls[0][1]["json_body"]["opportunitySearch"]["OrderBy"][0]["Value"] == "postedDateDesc"
    assert result.records == [
        {
            "title": "Assembler",
            "job_id": "opp-1",
            "url": "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/OpportunityDetail?opportunityId=opp-1&postingId=post-1",
            "apply_url": "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/OpportunityDetail?opportunityId=opp-1&postingId=post-1",
            "location": "Grafton, WI",
            "posted_date": "2026-04-10",
            "requisition_id": "REQ-100",
            "category": "Manufacturing",
        }
    ]


@pytest.mark.asyncio
async def test_saashr_detail_mode_filters_to_requested_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SaaSHRAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return {
            "job_requisitions": [
                {
                    "id": 587687242,
                    "job_title": "Behavioral Health Technician",
                    "job_description": "Full description",
                    "location": {"city": "Yankton", "state": "SD"},
                },
                {
                    "id": 111,
                    "job_title": "Should Not Match",
                    "job_description": "Ignore me",
                    "location": {"city": "Sioux Falls", "state": "SD"},
                },
            ]
        }

    async def _fake_fetch_company_name(**kwargs):
        del kwargs
        return "Lewis & Clark Behavioral Health Services"

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)
    monkeypatch.setattr(adapter, "_fetch_company_name", _fake_fetch_company_name)

    records = await adapter.try_public_endpoint(
        "https://secure7.saashr.com/ta/6208610.careers?ein_id=118959061&career_portal_id=6062087&ShowJob=587687242",
        surface="job_detail",
    )

    assert records == [
        {
            "title": "Behavioral Health Technician",
            "job_id": "587687242",
            "url": "https://secure7.saashr.com/ta/6208610.careers?ein_id=118959061&career_portal_id=6062087&ShowJob=587687242",
            "apply_url": "https://secure7.saashr.com/ta/6208610.careers?ein_id=118959061&career_portal_id=6062087&ShowJob=587687242",
            "location": "Yankton, SD",
            "company": "Lewis & Clark Behavioral Health Services",
            "description": "Full description",
        }
    ]


def test_registered_adapters_include_workday_and_ultipro() -> None:
    names = {adapter.name for adapter in registered_adapters()}

    assert "workday" in names
    assert "ultipro_ukg" in names


def test_extract_listing_records_preserves_job_cards_inside_filtered_container() -> None:
    html = """
    <html>
      <body>
        <div class="cmplz-cookiebanner">
          <a href="#">Manage options</a>
        </div>
        <div class="filtered-jobs">
          <div class="pp-content-post pp-content-grid-post job_listing">
            <a class="atlas_js_job_title" href="https://atlasmedstaff.com/job/1475832-rn-telemetry-prescott-arizona/">
              RN: Telemetry
            </a>
            <p>Prescott, Arizona</p>
            <p>$1,886/wk est</p>
          </div>
        </div>
      </body>
    </html>
    """

    records = extract_listing_records(
        html,
        "https://atlasmedstaff.com/job-search/",
        "job_listing",
        max_records=5,
    )

    assert records == [
        {
            "source_url": "https://atlasmedstaff.com/job-search/",
            "_source": "dom_listing",
            "title": "RN: Telemetry",
            "url": "https://atlasmedstaff.com/job/1475832-rn-telemetry-prescott-arizona/",
            "salary": "$1,886",
        }
    ]


def test_shopify_adapter_strips_blank_and_empty_tags() -> None:
    adapter = ShopifyAdapter()

    record = adapter._build_product_record(
        {
            "title": "Widget",
            "vendor": "Acme",
            "handle": "widget",
            "images": [],
            "tags": " featured, , new  , ",
            "variants": [],
        },
        page_url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    assert record["tags"] == ["featured", "new"]


def test_shopify_adapter_treats_blank_tag_string_as_empty_list() -> None:
    adapter = ShopifyAdapter()

    record = adapter._build_product_record(
        {
            "title": "Widget",
            "vendor": "Acme",
            "handle": "widget",
            "images": [],
            "tags": "   ",
            "variants": [],
        },
        page_url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    assert record["tags"] == []
