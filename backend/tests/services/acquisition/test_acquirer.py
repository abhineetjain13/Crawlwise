# Tests for acquisition waterfall and proxy rotation.
from __future__ import annotations

import itertools
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from app.services.acquisition.acquirer import (
    AcquisitionRequest,
    AcquisitionResult,
    ProxyRotator,
    acquire,
    acquire_html,
)
from app.services.acquisition.http_client import HttpFetchResult
from app.services.acquisition.pacing import reset_pacing_state
from app.services.exceptions import AcquisitionTimeoutError

_TMP_COUNTER = itertools.count()
_WORKSPACE_TMP_ROOT = (
    Path(__file__).resolve().parents[3] / ".pytest-tmp" / "test_acquirer"
)


@pytest.fixture
def tmp_path() -> Path:
    path = _WORKSPACE_TMP_ROOT / f"case-{next(_TMP_COUNTER)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def _redirect_tempdir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    yield
    monkeypatch.setattr(tempfile, "tempdir", None)


async def _run_acquire_case(
    tmp_path: Path,
    *,
    url: str,
    fetch_result: HttpFetchResult | None = None,
    fetch_side_effect: list[HttpFetchResult] | None = None,
    browser_result=None,
    resolve_adapter_result=None,
    surface: str | None = None,
    requested_fields: list[str] | None = None,
):
    fetch_patch_kwargs = {"new_callable": AsyncMock}
    if fetch_side_effect is not None:
        fetch_patch_kwargs["side_effect"] = fetch_side_effect
    else:
        fetch_patch_kwargs["return_value"] = fetch_result

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            **fetch_patch_kwargs,
        ),
        patch(
            "app.services.acquisition.acquirer.resolve_adapter",
            new_callable=AsyncMock,
            return_value=resolve_adapter_result,
        ),
        patch(
            "app.services.acquisition.acquirer.fetch_rendered_html",
            new_callable=AsyncMock,
            return_value=browser_result,
        ) as browser_mock,
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(
            1,
            url,
            surface=surface,
            requested_fields=requested_fields,
        )

    return result, browser_mock


class TestProxyRotator:
    def test_no_proxies(self):
        r = ProxyRotator([])
        assert r.next() is None

    def test_none_proxies(self):
        r = ProxyRotator(None)
        assert r.next() is None

    def test_returns_proxy(self):
        r = ProxyRotator(["http://proxy1:8080"])
        assert r.next() == "http://proxy1:8080"

    def test_returns_from_list(self):
        proxies = ["http://p1:8080", "http://p2:8080"]
        r = ProxyRotator(proxies)
        # Should return one of the proxies
        result = r.next()
        assert result in proxies

    def test_strips_whitespace(self):
        r = ProxyRotator(["  http://proxy:8080  ", ""])
        assert r.next() == "http://proxy:8080"

@pytest.mark.asyncio
async def test_acquire_html_curl_success(tmp_path):
    """curl_cffi success path — no Playwright fallback needed."""
    html = "<html><body><h1>Product</h1><p>Long enough content to pass threshold check" + "x" * 500 + "</p></body></html>"
    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=html, status_code=200, content_type="html")),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result_html, method, path, payloads = await acquire_html(1, "https://example.com/product")
    assert method == "curl_cffi"
    assert "Product" in result_html
    assert payloads == []


@pytest.mark.asyncio
async def test_acquire_html_falls_back_to_playwright(tmp_path):
    """Short HTML triggers Playwright fallback."""
    short_html = "<html><body>tiny</body></html>"
    full_html = "<html><body>" + "x" * 600 + "</body></html>"

    from app.services.acquisition.browser_client import BrowserResult

    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=short_html, status_code=200, content_type="html")),
        patch("app.services.acquisition.acquirer.fetch_rendered_html", new_callable=AsyncMock, return_value=BrowserResult(html=full_html, network_payloads=[{"url": "https://api.example.com", "body": {}}])),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result_html, method, path, payloads = await acquire_html(1, "https://example.com/spa-page")
    assert method == "playwright"
    assert len(payloads) == 1


@pytest.mark.asyncio
async def test_acquire_html_keeps_curl_when_adapter_can_handle_js_heavy_html(tmp_path):
    js_heavy_html = (
        "<html><body>"
        + ("<script>var x=1;</script>" * 30000)
        + "<h1>Product</h1><p>"
        + ("Visible product copy " * 40)
        + "</p></body></html>"
    )

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(text=js_heavy_html, status_code=200, content_type="html"),
        ),
        patch("app.services.acquisition.acquirer.resolve_adapter", new_callable=AsyncMock) as resolve_adapter_mock,
        patch("app.services.acquisition.acquirer.fetch_rendered_html", new_callable=AsyncMock) as browser_mock,
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        resolve_adapter_mock.return_value = type("Adapter", (), {"name": "shopify"})()
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(1, "https://example.com/products/widget")

    assert result.method == "curl_cffi"
    assert result.diagnostics["curl_adapter_hint"] == "shopify"
    assert result.diagnostics["curl_platform_family"] == "generic_commerce"
    browser_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_html_keeps_curl_when_js_shell_contains_extractable_structured_data(tmp_path):
    js_heavy_html = """
    <html><body>
      <div>ok</div>
      <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "WebPage",
          "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
              {"item": {"@type": "Product", "name": "Filter A", "url": "/p/filter-a"}},
              {"item": {"@type": "Product", "name": "Filter B", "url": "/p/filter-b"}}
            ]
          }
        }
      </script>
    """ + ("<script>var x=1;</script>" * 5000) + "</body></html>"

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(text=js_heavy_html, status_code=200, content_type="html"),
        ),
        patch("app.services.acquisition.acquirer.resolve_adapter", new_callable=AsyncMock, return_value=None),
        patch("app.services.acquisition.acquirer.fetch_rendered_html", new_callable=AsyncMock) as browser_mock,
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(1, "https://example.com/products/widget")

    assert result.method == "curl_cffi"
    assert result.diagnostics["curl_needs_browser"] is False
    assert result.diagnostics["js_shell_overridden"] == "structured_data_found"
    browser_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_raises_acquisition_timeout_with_preserved_cause(tmp_path):
    timeout_exc = TimeoutError("attempt timed out")

    with (
        patch("app.services.acquisition.acquirer.asyncio.wait_for", side_effect=timeout_exc),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        with pytest.raises(AcquisitionTimeoutError) as exc_info:
            await acquire(1, "https://example.com/slow-page")

    assert exc_info.value.__cause__ is timeout_exc





@pytest.mark.asyncio
async def test_acquire_listing_search_shell_without_extractable_records_escalates_to_browser(tmp_path):
    shell_html = """
    <html data-jibe-search-version="4.11.178">
      <body>
        <h1>FoxRC Careers Home Job Search</h1>
        <p>Search jobs by keyword and location.</p>
        <script>
          window._jibe = {"cid":"thecheesecakefactory"};
          window.searchConfig = {"query":{"keywords":"Dough Bird","limit":"100","page":"1"}};
        </script>
      </body>
    </html>
    """
    browser_html = """
    <html><body>
      <ul>
        <li><a href="https://example.com/jobs/1">Dishwasher</a></li>
        <li><a href="https://example.com/jobs/2">Server</a></li>
      </ul>
    </body></html>
    """

    from app.services.acquisition.browser_client import BrowserResult

    result, browser_mock = await _run_acquire_case(
        tmp_path,
        url="https://example.com/jobs?keywords=Dough%20Bird",
        fetch_result=HttpFetchResult(text=shell_html, status_code=200, content_type="html"),
        browser_result=BrowserResult(html=browser_html),
        surface="job_listing",
    )

    assert result.method == "playwright"
    browser_mock.assert_awaited()


@pytest.mark.asyncio
async def test_acquire_job_listing_iframe_shell_escalates_to_browser(tmp_path):
    shell_html = """
    <html><body>
      <main>
        <h1>Careers</h1>
        <iframe src="https://boards.greenhouse.io/embed/job_board?for=example"></iframe>
      </main>
    </body></html>
    """
    browser_html = """
    <html><body>
      <div class="job-card">
        <a href="https://example.com/jobs/1"><h3>Platform Engineer</h3><p>Remote</p></a>
      </div>
      <div class="job-card">
        <a href="https://example.com/jobs/2"><h3>Data Engineer</h3><p>Austin, TX</p></a>
      </div>
    </body></html>
    """

    from app.services.acquisition.browser_client import BrowserResult

    result, browser_mock = await _run_acquire_case(
        tmp_path,
        url="https://example.com/careers",
        fetch_result=HttpFetchResult(text=shell_html, status_code=200, content_type="html"),
        browser_result=BrowserResult(
            html=browser_html,
            promoted_sources=[{"kind": "iframe", "url": "https://boards.greenhouse.io/embed/job_board?for=example"}],
        ),
        surface="job_listing",
    )

    assert result.method == "playwright"
    assert result.promoted_sources
    assert result.diagnostics["browser_retry_reason"] == "iframe_shell"
    browser_mock.assert_awaited()


@pytest.mark.asyncio
async def test_acquire_job_listing_iframe_shell_still_escalates_with_adapter_hint(tmp_path):
    shell_html = """
    <html><body>
      <main>
        <h1>Careers</h1>
        <iframe src="https://secure7.saashr.com/ta/6208610.careers?CareersSearch&InFrameset=1"></iframe>
      </main>
    </body></html>
    """
    browser_html = """
    <html><body>
      <div class="job-card">
        <a href="https://example.com/jobs/1"><h3>Platform Engineer</h3></a>
      </div>
    </body></html>
    """

    from app.services.acquisition.browser_client import BrowserResult

    result, browser_mock = await _run_acquire_case(
        tmp_path,
        url="https://lcbhs.net/careers",
        fetch_result=HttpFetchResult(text=shell_html, status_code=200, content_type="html"),
        browser_result=BrowserResult(html=browser_html),
        resolve_adapter_result=SimpleNamespace(name="saashr"),
        surface="job_listing",
    )

    assert result.method == "playwright"
    assert result.diagnostics["browser_retry_reason"] == "iframe_shell"
    browser_mock.assert_awaited()


@pytest.mark.asyncio
async def test_acquire_iframe_shell_promoted_source_used_before_browser(tmp_path):
    shell_html = """
    <html><body>
      <main>
        <h1>Careers</h1>
        <iframe src="https://secure7.saashr.com/ta/6208610.careers?CareersSearch&InFrameset=1"></iframe>
      </main>
    </body></html>
    """
    promoted_html = """
    <html><body>
      <ul>
        <li><a href="https://example.com/jobs/1">Behavioral Health Tech</a></li>
        <li><a href="https://example.com/jobs/2">Crisis Care EMT</a></li>
      </ul>
    </body></html>
    """

    parent_result = HttpFetchResult(text=shell_html, status_code=200, content_type="html")
    promoted_result = HttpFetchResult(text=promoted_html, status_code=200, content_type="html")
    from app.services.acquisition.browser_client import BrowserResult

    result, browser_mock = await _run_acquire_case(
        tmp_path,
        url="https://lcbhs.net/careers",
        fetch_side_effect=[parent_result, promoted_result],
        browser_result=BrowserResult(html=promoted_html),
        surface="job_listing",
    )

    assert result.method == "curl_cffi"
    assert result.diagnostics.get("promoted_source_used")
    browser_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_detail_requested_fields_are_not_overridden_by_listing_structured_data(tmp_path):
    js_heavy_html = """
    <html><body>
      <div>ok</div>
      <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "WebPage",
          "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
              {"item": {"@type": "Product", "name": "Filter A", "url": "/p/filter-a"}}
            ]
          }
        }
      </script>
    """ + ("<script>var x=1;</script>" * 30000) + "</body></html>"

    from app.services.acquisition.browser_client import BrowserResult

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(text=js_heavy_html, status_code=200, content_type="html"),
        ),
        patch("app.services.acquisition.acquirer.resolve_adapter", new_callable=AsyncMock, return_value=None),
        patch(
            "app.services.acquisition.acquirer.fetch_rendered_html",
            new_callable=AsyncMock,
            return_value=BrowserResult(
                html=(
                    "<html><body><main><details open><summary>Returns</summary>"
                    "<p>30 day returns on unused items with original packaging and proof of purchase.</p>"
                    "<p>Customers may start a return online or contact support for assisted processing.</p>"
                    "</details></main></body></html>"
                )
            ),
        ) as browser_mock,
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(
            1,
            "https://example.com/products/widget",
            surface="ecommerce_detail",
            requested_fields=["returns"],
        )

    assert result.method == "playwright"
    browser_mock.assert_awaited()


@pytest.mark.asyncio
async def test_acquire_html_traversal_mode_tries_curl_then_playwright(tmp_path):
    """Traversal mode tries curl_cffi first, then escalates to Playwright."""
    curl_html = "<html><body>" + "x" * 600 + "</body></html>"
    playwright_html = "<html><body>" + "y" * 600 + "</body></html>"

    from app.services.acquisition.browser_client import BrowserResult

    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=curl_html, status_code=200, content_type="html")),
        patch("app.services.acquisition.acquirer.fetch_rendered_html", new_callable=AsyncMock, return_value=BrowserResult(html=playwright_html)),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result_html, method, path, payloads = await acquire_html(
            1, "https://example.com/spa", traversal_mode="scroll"
        )
    # Playwright is preferred when traversal mode is set, even though curl worked
    assert method == "playwright"


@pytest.mark.asyncio
async def test_acquire_html_passes_max_scrolls_to_playwright(tmp_path):
    curl_html = "<html><body>" + "x" * 600 + "</body></html>"
    playwright_html = "<html><body>" + "y" * 600 + "</body></html>"

    from app.services.acquisition.browser_client import BrowserResult

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(text=curl_html, status_code=200, content_type="html"),
        ),
        patch(
            "app.services.acquisition.acquirer.fetch_rendered_html",
            new_callable=AsyncMock,
            return_value=BrowserResult(html=playwright_html),
        ) as fetch_rendered_html_mock,
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        await acquire_html(1, "https://example.com/spa", traversal_mode="scroll", max_scrolls=23)

    assert fetch_rendered_html_mock.await_args.kwargs["max_scrolls"] == 23


@pytest.mark.asyncio
async def test_acquire_html_traversal_mode_falls_back_to_curl_on_playwright_failure(tmp_path):
    """When traversal mode Playwright crashes, fall back to curl_cffi result."""
    curl_html = "<html><body><h1>Product</h1>" + "x" * 600 + "</body></html>"

    from app.services.acquisition.http_client import HttpFetchResult

    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=curl_html, status_code=200, content_type="html")),
        patch("app.services.acquisition.acquirer.fetch_rendered_html", new_callable=AsyncMock, side_effect=RuntimeError("ERR_HTTP2_PROTOCOL_ERROR")),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result_html, method, path, payloads = await acquire_html(
            1, "https://example.com/spa", traversal_mode="auto"
        )
    assert method == "curl_cffi"
    assert "Product" in result_html


@pytest.mark.asyncio
async def test_acquire_listing_page_does_not_escalate_from_text_only_card_count_heuristics(tmp_path):
    html = """
    <html><body>
      <main>
        <h1>Electronic listings</h1>
        <p>Browse thousands of seller listings with grading, shipping, and release metadata.</p>
        <p>This catalog is available without JavaScript and should not require browser escalation.</p>
        <p>""" + ("Rich catalog copy " * 40) + """</p>
      </main>
    </body></html>
    """

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(text=html, status_code=200, content_type="html"),
        ),
        patch("app.services.acquisition.acquirer.fetch_rendered_html", new_callable=AsyncMock) as browser_mock,
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(1, "https://example.com/listings", surface="listing")

    assert result.method == "curl_cffi"
    browser_mock.assert_not_awaited()

@pytest.mark.asyncio
async def test_acquire_keeps_job_redirect_shell_results_but_records_surface_warning(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    shell_html = """
    <html>
      <head>
        <title>GovernmentJobs | City, State, Federal &amp; Public Sector Jobs</title>
        <link rel=\"canonical\" href=\"https://www.schooljobs.com/\" />
      </head>
      <body><h1>log in</h1></body>
    </html>
    """

    from app.services.acquisition.browser_client import BrowserResult

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(
                text=shell_html,
                status_code=200,
                content_type="html",
                final_url="https://www.governmentjobs.com/",
            ),
        ),
        patch(
            "app.services.acquisition.acquirer.fetch_rendered_html",
            new_callable=AsyncMock,
            return_value=BrowserResult(
                html=shell_html,
                diagnostics={"final_url": "https://www.governmentjobs.com/"},
            ),
        ),
    ):
        result = await acquire(
            42,
            "https://www.governmentjobs.com/careers/california/jobs/4817400",
            surface="job_detail",
        )

    assert result.method == "playwright"
    warnings = result.diagnostics.get("surface_selection_warnings") or []
    assert warnings
    assert warnings[0]["surface_requested"] == "job_detail"
    assert "redirect_shell_title" in warnings[0]["signals"]


@pytest.mark.asyncio
async def test_acquire_discards_commerce_root_redirect_shell_results(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    shell_html = """
    <html>
      <head><title>AutoZone - Auto Parts, Accessories, and Advice for Cars & Trucks</title></head>
      <body><h1>Home</h1></body>
    </html>
    """

    from app.services.acquisition.browser_client import BrowserResult

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(
                text=shell_html,
                status_code=200,
                content_type="html",
                final_url="https://www.autozone.com/",
            ),
        ),
        patch(
            "app.services.acquisition.acquirer.fetch_rendered_html",
            new_callable=AsyncMock,
            return_value=BrowserResult(
                html=shell_html,
                diagnostics={"final_url": "https://www.autozone.com/"},
            ),
        ),
    ):
        with pytest.raises(RuntimeError, match="Unable to acquire content"):
            await acquire(
                42,
                "https://www.autozone.com/p/real-product",
                surface="ecommerce_detail",
            )


@pytest.mark.asyncio
async def test_acquire_with_proxy(tmp_path):
    """Proxy is passed through to HTTP client."""
    html = "<html><body>" + "x" * 600 + "</body></html>"
    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=html, status_code=200, content_type="html")) as mock_fetch,
        patch("app.services.acquisition.acquirer.validate_proxy_endpoint", new_callable=AsyncMock),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        await acquire_html(1, "https://example.com", proxy_list=["http://myproxy:8080"])
    mock_fetch.assert_called_once()
    call_args = mock_fetch.call_args
    assert call_args.args[0] == "https://example.com"


@pytest.mark.asyncio
async def test_acquire_rejects_private_proxy_endpoint():
    with pytest.raises(ValueError, match="non-public IP"):
        await acquire_html(
            1,
            "https://example.com",
            proxy_list=["http://10.0.0.5:8080"],
        )


@pytest.mark.asyncio
async def test_acquire_rejects_browser_non_public_final_url_and_keeps_curl_fallback(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    short_html = "<html><body>tiny</body></html>"

    from app.services.acquisition.browser_client import BrowserResult

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(
                text=short_html,
                status_code=200,
                content_type="html",
                final_url="https://example.com/product",
            ),
        ),
        patch(
            "app.services.acquisition.acquirer.fetch_rendered_html",
            new_callable=AsyncMock,
            return_value=BrowserResult(
                html="<html><body><h1>Rendered</h1>" + ("x" * 500) + "</body></html>",
                diagnostics={"final_url": "http://127.0.0.1/internal"},
            ),
        ),
    ):
        result = await acquire(42, "https://example.com/product", surface="ecommerce_detail")

    assert result.method == "curl_cffi"
    assert result.diagnostics.get("browser_non_public_target") is True


@pytest.mark.asyncio
async def test_acquire_json_content_type(tmp_path):
    """JSON content type should be detected and returned."""
    json_text = '{"jobs": [{"title": "Engineer"}]}'
    json_data = {"jobs": [{"title": "Engineer"}]}
    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=json_text, status_code=200, content_type="json", json_data=json_data)),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        from app.services.acquisition.acquirer import acquire
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(1, "https://api.example.com/jobs")
    assert result.content_type == "json"
    assert result.json_data == json_data
    assert result.method == "curl_cffi"


@pytest.mark.asyncio
async def test_acquire_accepts_typed_request(tmp_path, monkeypatch):
    html = "<html><body><h1>Typed</h1><p>" + ("x" * 600) + "</p></body></html>"
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)

    with patch(
        "app.services.acquisition.acquirer._fetch_with_content_type",
        new_callable=AsyncMock,
        return_value=HttpFetchResult(text=html, status_code=200, content_type="html"),
    ):
        result = await acquire(
            request=AcquisitionRequest(
                run_id=21,
                url="https://example.com/typed",
                surface="ecommerce_detail",
                requested_fields=["title"],
            )
        )

    assert result.method == "curl_cffi"
    assert result.artifact_path.endswith(".html")


@pytest.mark.asyncio
async def test_acquire_diagnostics_include_platform_family_for_real_family_url(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    html = "<html><body><h1>Jobs</h1><p>" + ("Open roles " * 80) + "</p><table class='iCIMS_JobsTable'></table></body></html>"

    with patch(
        "app.services.acquisition.acquirer._fetch_with_content_type",
        new_callable=AsyncMock,
        return_value=HttpFetchResult(text=html, status_code=200, content_type="html"),
    ):
        result = await acquire(
            42,
            "https://ehccareers-emory.icims.com/jobs/search?pr=0&searchRelation=keyword_all",
            surface="job_listing",
        )

    assert result.diagnostics["curl_platform_family"] == "icims"


@pytest.mark.asyncio
async def test_acquire_returns_blocked_html_instead_of_raising_when_challenge_page_persists(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    blocked_html = """
    <html>
      <head><title>Just a moment...</title></head>
      <body>
        <div class="cf-browser-verification">Verification successful. Waiting for demo.opencart.com to respond...</div>
      </body>
    </html>
    """

    from app.services.acquisition.browser_client import BrowserResult

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(
                text=blocked_html,
                status_code=403,
                content_type="html",
                final_url="https://demo.opencart.com/",
            ),
        ),
        patch(
            "app.services.acquisition.acquirer.fetch_rendered_html",
            new_callable=AsyncMock,
            return_value=BrowserResult(
                html=blocked_html,
                challenge_state="blocked_signal",
                diagnostics={"final_url": "https://demo.opencart.com/"},
            ),
        ),
    ):
        result = await acquire(42, "https://demo.opencart.com/", surface="ecommerce_listing")

    assert result.method == "playwright"
    assert "Just a moment" in result.html
    assert result.diagnostics["browser_blocked"] is True


@pytest_asyncio.fixture(autouse=True)
async def _reset_acquisition_state():
    await reset_pacing_state()
    yield
    await reset_pacing_state()


@pytest.mark.asyncio
async def test_acquire_uses_memory_prefer_stealth(monkeypatch, tmp_path):
    captured: list[bool] = []

    async def _fake_acquire_once(**kwargs):
        captured.append(bool(kwargs.get("prefer_stealth")))
        return type("Result", (), {
            "html": "<html>ok</html>",
            "json_data": None,
            "content_type": "html",
            "method": "curl_cffi",
            "artifact_path": "",
            "diagnostics_path": "",
            "network_payloads": [],
            "diagnostics": {},
        })()

    monkeypatch.setattr("app.services.acquisition.acquirer._acquire_once", _fake_acquire_once)
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)

    result = await acquire(
        42,
        "https://example.com/products/widget",
        acquisition_profile={"prefer_stealth": True},
    )

    assert result.method == "curl_cffi"
    assert captured == [False]


@pytest.mark.asyncio
async def test_acquire_enables_stealth_only_when_anti_bot_mode_is_enabled(monkeypatch, tmp_path):
    captured: list[bool] = []

    async def _fake_acquire_once(**kwargs):
        captured.append(bool(kwargs.get("prefer_stealth")))
        return type("Result", (), {
            "html": "<html>ok</html>",
            "json_data": None,
            "content_type": "html",
            "method": "curl_cffi",
            "artifact_path": "",
            "diagnostics_path": "",
            "network_payloads": [],
            "diagnostics": {},
        })()

    monkeypatch.setattr("app.services.acquisition.acquirer._acquire_once", _fake_acquire_once)
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)

    result = await acquire(
        42,
        "https://example.com/products/widget",
        acquisition_profile={"prefer_stealth": True, "anti_bot_enabled": True},
    )

    assert result.method == "curl_cffi"
    assert captured == [True]


@pytest.mark.asyncio
async def test_acquire_browser_first_platform_family_enables_anti_bot_runtime(
    monkeypatch, tmp_path
):
    captured: list[bool] = []

    async def _fake_acquire_once(**kwargs):
        runtime_options = kwargs.get("runtime_options")
        captured.append(bool(getattr(runtime_options, "anti_bot_enabled", False)))
        return type("Result", (), {
            "html": "<html>ok</html>",
            "json_data": None,
            "content_type": "html",
            "method": "playwright",
            "artifact_path": "",
            "diagnostics_path": "",
            "network_payloads": [],
            "diagnostics": {},
        })()

    monkeypatch.setattr("app.services.acquisition.acquirer._acquire_once", _fake_acquire_once)
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)

    result = await acquire(
        42,
        "https://myjobs.adp.com/cx/search-jobs",
        surface="job_listing",
    )

    assert result.method == "playwright"
    assert captured == [True]


@pytest.mark.asyncio
async def test_acquire_browser_first_platform_family_overrides_explicit_anti_bot_false(
    monkeypatch, tmp_path
):
    captured: list[bool] = []

    async def _fake_acquire_once(**kwargs):
        runtime_options = kwargs.get("runtime_options")
        captured.append(bool(getattr(runtime_options, "anti_bot_enabled", False)))
        return type("Result", (), {
            "html": "<html>ok</html>",
            "json_data": None,
            "content_type": "html",
            "method": "playwright",
            "artifact_path": "",
            "diagnostics_path": "",
            "network_payloads": [],
            "diagnostics": {},
        })()

    monkeypatch.setattr("app.services.acquisition.acquirer._acquire_once", _fake_acquire_once)
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)

    result = await acquire(
        42,
        "https://myjobs.adp.com/cx/search-jobs",
        surface="job_listing",
        acquisition_profile={"anti_bot_enabled": False},
    )

    assert result.method == "playwright"
    assert captured == [True]


@pytest.mark.asyncio
async def test_acquire_prefer_browser_profile_enables_anti_bot_runtime(monkeypatch, tmp_path):
    captured: list[bool] = []

    async def _fake_acquire_once(**kwargs):
        runtime_options = kwargs.get("runtime_options")
        captured.append(bool(getattr(runtime_options, "anti_bot_enabled", False)))
        return type("Result", (), {
            "html": "<html>ok</html>",
            "json_data": None,
            "content_type": "html",
            "method": "playwright",
            "artifact_path": "",
            "diagnostics_path": "",
            "network_payloads": [],
            "diagnostics": {},
        })()

    monkeypatch.setattr("app.services.acquisition.acquirer._acquire_once", _fake_acquire_once)
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)

    result = await acquire(
        42,
        "https://example.com/products/widget",
        acquisition_profile={"prefer_browser": True},
    )

    assert result.method == "playwright"
    assert captured == [True]
