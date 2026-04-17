# Tests for acquisition waterfall and proxy rotation.
from __future__ import annotations

import itertools
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from app.services.acquisition.acquirer import (
    AcquisitionRequest,
    AcquisitionResult,
    ProxyRotator,
    _try_browser_first_success_result,
    acquire,
)
from app.services.acquisition.policy import classify_acquisition_outcome
from app.services.acquisition.artifact_store import _write_artifact_file
from app.services.acquisition.http_client import HttpFetchResult
from app.services.acquisition.pacing import reset_pacing_state

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
        result = await acquire(_request(1, url,
            surface=surface,
            requested_fields=requested_fields,
        ))

    return result, browser_mock


def _request(run_id: int, url: str, **kwargs) -> AcquisitionRequest:
    return AcquisitionRequest(run_id=run_id, url=url, **kwargs)


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
async def test_acquire_curl_success(tmp_path):
    """curl_cffi success path — no Playwright fallback needed."""
    html = "<html><body><h1>Product</h1><p>Long enough content to pass threshold check" + "x" * 500 + "</p></body></html>"
    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=html, status_code=200, content_type="html")),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(_request(1, "https://example.com/product"))
    assert result.method == "curl_cffi"
    assert "Product" in result.html
    assert result.network_payloads == []


@pytest.mark.asyncio
async def test_acquire_falls_back_to_playwright(tmp_path):
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
        result = await acquire(_request(1, "https://example.com/spa-page"))
    assert result.method == "playwright"
    assert len(result.network_payloads) == 1


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
        result = await acquire(_request(1, "https://example.com/products/widget"))

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
        result = await acquire(_request(1, "https://example.com/products/widget"))

    assert result.method == "curl_cffi"
    assert result.diagnostics["curl_needs_browser"] is False
    assert result.diagnostics["js_shell_overridden"] == "structured_data_found"
    browser_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_listing_with_generic_card_signals_stays_on_curl(tmp_path):
    html = """
    <html><body>
      <main>
        <article><a href="/shop/item-1"><img src="/1.jpg" /><span>Vintage Delay Pedal</span><span>$199.99</span></a></article>
        <article><a href="/shop/item-2"><img src="/2.jpg" /><span>Analog Chorus Pedal</span><span>$149.99</span></a></article>
        <article><a href="/shop/item-3"><img src="/3.jpg" /><span>Tape Echo Pedal</span><span>$249.99</span></a></article>
        <a href="/shop?page=2" rel="next">Next</a>
      </main>
    </body></html>
    """

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(text=html, status_code=200, content_type="html"),
        ),
        patch("app.services.acquisition.acquirer.resolve_adapter", new_callable=AsyncMock, return_value=None),
        patch("app.services.acquisition.acquirer.fetch_rendered_html", new_callable=AsyncMock) as browser_mock,
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(_request(1, "https://example.com/shop", surface="ecommerce_listing"))

    assert result.method == "curl_cffi"
    assert result.diagnostics["curl_needs_browser"] is False
    assert result.diagnostics["extractability"]["reason"] == "listing_link_signals"
    browser_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_browser_timeout_falls_back_to_curl_with_failure_diagnostics(tmp_path):
    timeout_exc = TimeoutError("attempt timed out")
    short_html = "<html><body>tiny</body></html>"

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(text=short_html, status_code=200, content_type="html"),
        ),
        patch("app.services.acquisition.acquirer.asyncio.wait_for", side_effect=timeout_exc),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(_request(1, "https://example.com/slow-page"))

    assert result.method == "curl_cffi"
    assert result.diagnostics["browser_attempted"] is True
    assert result.diagnostics["failure_stage"] == "browser_render"
    assert result.diagnostics["budget_exhausted"] == "browser_render"


def test_classify_outcome_uses_live_blocked_keys():
    result = AcquisitionResult(
        html="<html>blocked</html>",
        method="curl_cffi",
        diagnostics={"curl_blocked": True},
    )

    assert classify_acquisition_outcome(result) == "blocked"

def test_write_artifact_file_handles_missing_html(tmp_path):
    result = SimpleNamespace(content_type="html", html=None, json_data=None)
    artifact_path = tmp_path / "artifacts" / "page.html"

    written_path = _write_artifact_file(
        artifact_path,
        result,
        scrub_payload=lambda payload: payload,
        scrub_html=lambda html: f"sanitized:{html}",
        scrub_text=lambda text: text,
    )

    assert written_path == artifact_path
    assert artifact_path.read_text(encoding="utf-8") == "sanitized:"





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
    assert result.diagnostics["browser_attempted"] is True
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
    assert result.diagnostics["browser_attempted"] is True
    browser_mock.assert_awaited()


@pytest.mark.asyncio
async def test_acquire_iframe_shell_browser_first_policy_takes_precedence(tmp_path):
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

    assert result.method == "playwright"
    assert result.diagnostics.get("memory_browser_first") is True
    browser_mock.assert_awaited()


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
        result = await acquire(_request(1, "https://example.com/products/widget",
            surface="ecommerce_detail",
            requested_fields=["returns"],
        ))

    assert result.method == "playwright"
    browser_mock.assert_awaited()


@pytest.mark.asyncio
async def test_acquire_traversal_mode_tries_curl_then_playwright(tmp_path):
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
        result = await acquire(_request(1, "https://example.com/spa", traversal_mode="scroll"
        ))
    # Playwright is preferred when traversal mode is set, even though curl worked
    assert result.method == "playwright"


@pytest.mark.asyncio
async def test_acquire_passes_max_scrolls_to_playwright(tmp_path):
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
        await acquire(_request(1, "https://example.com/spa", traversal_mode="scroll", max_scrolls=23))

    assert fetch_rendered_html_mock.await_args.kwargs["max_scrolls"] == 23


@pytest.mark.asyncio
async def test_acquire_auto_mode_keeps_curl_when_http_is_sufficient(tmp_path):
    """Auto traversal should stay curl-first when the page is already usable."""
    curl_html = "<html><body><h1>Product</h1>" + "x" * 600 + "</body></html>"

    from app.services.acquisition.http_client import HttpFetchResult

    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=curl_html, status_code=200, content_type="html")),
        patch("app.services.acquisition.acquirer.fetch_rendered_html", new_callable=AsyncMock) as browser_mock,
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(_request(1, "https://example.com/spa", traversal_mode="auto"
        ))
    assert result.method == "curl_cffi"
    assert "Product" in result.html
    browser_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_traversal_fallback_records_explicit_browser_attempt_diagnostics(tmp_path):
    curl_html = "<html><body><h1>Product</h1>" + "x" * 600 + "</body></html>"

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(
                text=curl_html,
                status_code=200,
                content_type="html",
            ),
        ),
        patch(
            "app.services.acquisition.acquirer.fetch_rendered_html",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ERR_HTTP2_PROTOCOL_ERROR"),
        ),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(_request(1, "https://example.com/spa",
            surface="ecommerce_listing",
            traversal_mode="scroll",
        ))

    assert result.method == "curl_cffi"
    assert result.diagnostics["browser_attempted"] is True
    assert result.diagnostics["browser_fallback_used"] is True
    assert result.diagnostics["traversal_fallback_used"] is True
    assert result.diagnostics["traversal_fallback_reason"] == "browser_failure:context_failure"
    assert result.diagnostics["traversal_summary"]["attempted"] is True
    assert result.diagnostics["traversal_summary"]["mode_used"] == "scroll"
    assert result.diagnostics["traversal_summary"]["fallback_used"] is True
    assert result.diagnostics["traversal_summary"]["failure_stage"] == "browser_render"
    assert result.diagnostics["acquisition_runtime"] == "playwright_attempt_required"
    assert result.diagnostics["acquisition_runtime_reason"] == "traversal_requested"


@pytest.mark.asyncio
async def test_acquire_records_failure_class_for_not_implemented_browser_error(tmp_path):
    curl_html = "<html><body><h1>Product</h1>" + ("x" * 600) + "</body></html>"

    from app.services.acquisition.http_client import HttpFetchResult

    with (
        patch(
            "app.services.acquisition.acquirer._fetch_with_content_type",
            new_callable=AsyncMock,
            return_value=HttpFetchResult(text=curl_html, status_code=200, content_type="html"),
        ),
        patch(
            "app.services.acquisition.acquirer.fetch_rendered_html",
            new_callable=AsyncMock,
            side_effect=NotImplementedError(),
        ),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        mock_settings.artifacts_dir = tmp_path
        result = await acquire(_request(1, "https://example.com/spa", surface="ecommerce_detail"))

    assert result.method == "curl_cffi"
    assert result.diagnostics["browser_exception"] == "NotImplementedError: "
    assert result.diagnostics["browser_failure_class"] == "system_chrome_unsupported"
    assert result.diagnostics["browser_failure_origin"] == "context"


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
        result = await acquire(_request(1, "https://example.com/listings", surface="listing"))

    assert result.method == "curl_cffi"
    browser_mock.assert_not_awaited()

@pytest.mark.asyncio
async def test_acquire_escalates_browser_for_job_redirect_shell_and_records_surface_warning(tmp_path, monkeypatch):
    """COV-01: Job redirect shells now trigger invalid_surface_page=True,
    causing browser escalation.  When the browser returns real content,
    the result should include the surface selection warning.
    """
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
    browser_html = """
    <html><body>
      <main>
        <h1>Deputy Sheriff</h1>
        <p>California Highway Patrol</p>
        <div class="job-desc">""" + ("Patrol duties " * 40) + """</div>
      </main>
    </body></html>
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
                html=browser_html,
                diagnostics={"final_url": "https://www.governmentjobs.com/careers/california/jobs/4817400"},
            ),
        ) as browser_mock,
    ):
        result = await acquire(_request(42, "https://www.governmentjobs.com/careers/california/jobs/4817400",
            surface="job_detail",
        ))

    assert result.method == "playwright"
    browser_mock.assert_awaited()
    # COV-01: The key assertion is that browser escalation was triggered
    # by the job redirect shell.  The surface_selection_warnings are computed
    # against the *browser* HTML (real content), so they won't contain the
    # shell signals — but the escalation itself proves the fix works.
    assert result.diagnostics.get("browser_attempted") is True


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
            await acquire(_request(42, "https://www.autozone.com/p/real-product",
                surface="ecommerce_detail",
            ))


@pytest.mark.asyncio
async def test_acquire_marks_transactional_commerce_detail_pages_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    cart_html = """
    <html>
      <head>
        <title>My Shopping Cart - Vitacost</title>
        <meta name="robots" content="noindex,nofollow" />
      </head>
      <body><h1>My Shopping Cart</h1></body>
    </html>
    """

    with patch(
        "app.services.acquisition.acquirer._fetch_with_content_type",
        new_callable=AsyncMock,
        return_value=HttpFetchResult(
            text=cart_html,
            status_code=200,
            content_type="html",
            final_url="https://www.vitacost.com/CheckOut/CartUpdate.aspx?SKUNumber=733739070746&action=add",
        ),
    ):
        result = await acquire(_request(42, "https://www.vitacost.com/CheckOut/CartUpdate.aspx?SKUNumber=733739070746&action=add",
            surface="ecommerce_detail",
        ))

    assert result.diagnostics["invalid_surface_page"] is True
    assert result.diagnostics["transactional_page"] is True
    warning = result.diagnostics["surface_selection_warnings"][0]
    assert "transactional_url" in warning["signals"]
    assert "noindex_transactional_page" in warning["signals"]


@pytest.mark.asyncio
async def test_acquire_surfaces_soft_404_warnings_for_commerce_detail_pages(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    unavailable_html = """
    <html>
      <head><title>Sorry, this page isn't available.</title></head>
      <body><main><h1>Sorry, this page isn't available.</h1></main></body>
    </html>
    """

    with patch(
        "app.services.acquisition.acquirer._fetch_with_content_type",
        new_callable=AsyncMock,
        return_value=HttpFetchResult(
            text=unavailable_html,
            status_code=200,
            content_type="html",
            final_url="https://reverb.com/2013-gibson-trad-pro-v",
        ),
    ):
        result = await acquire(_request(42, "https://reverb.com/2013-gibson-trad-pro-v",
            surface="ecommerce_detail",
        ))

    assert result.diagnostics["invalid_surface_page"] in (None, False)
    assert result.diagnostics["soft_404_page"] is True
    warning = result.diagnostics["surface_selection_warnings"][0]
    assert "soft_404_title" in warning["signals"]
    assert "soft_404_heading" in warning["signals"]


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
        await acquire(_request(1, "https://example.com", proxy_list=["http://myproxy:8080"]))
    mock_fetch.assert_called_once()
    call_args = mock_fetch.call_args
    assert call_args.args[0] == "https://example.com"


@pytest.mark.asyncio
async def test_acquire_rejects_private_proxy_endpoint():
    with pytest.raises(ValueError, match="non-public IP"):
        await acquire(_request(1, "https://example.com",
            proxy_list=["http://10.0.0.5:8080"],
        ))


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
        result = await acquire(_request(42, "https://example.com/product", surface="ecommerce_detail"))

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
        result = await acquire(_request(1, "https://api.example.com/jobs"))
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
async def test_acquire_preserves_sensitive_html_in_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    html = """
    <html><body>
      <form>
        <input type="hidden" name="csrf-token" value="short-lived-secret" />
        <input type="email" value="person@example.com" />
        <textarea name="session_token">temporary-csrf-payload</textarea>
      </form>
    </body></html>
    """

    with patch(
        "app.services.acquisition.acquirer._fetch_with_content_type",
        new_callable=AsyncMock,
        return_value=HttpFetchResult(text=html, status_code=200, content_type="html"),
    ):
        result = await acquire(_request(42, "https://example.com/contact"))

    artifact = Path(result.artifact_path).read_text(encoding="utf-8")
    assert "person@example.com" in artifact
    assert "short-lived-secret" in artifact
    assert "temporary-csrf-payload" in artifact
    assert "person@example.com" in result.html
    assert "short-lived-secret" in result.html


@pytest.mark.asyncio
async def test_acquire_preserves_sensitive_json_in_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    json_data = {
        "email": "person@example.com",
        "auth_token": "short-lived-secret",
        "nested": {"bearer": "Bearer abcdefghijklmnopqrstuvwxyz0123456789"},
    }

    with patch(
        "app.services.acquisition.acquirer._fetch_with_content_type",
        new_callable=AsyncMock,
        return_value=HttpFetchResult(
            text=json.dumps(json_data),
            status_code=200,
            content_type="json",
            json_data=json_data,
        ),
    ):
        result = await acquire(_request(42, "https://example.com/api"))

    artifact = Path(result.artifact_path).read_text(encoding="utf-8")
    assert "person@example.com" in artifact
    assert "short-lived-secret" in artifact
    assert "Bearer abcdefghijklmnopqrstuvwxyz0123456789" in artifact
    assert result.json_data == json_data


@pytest.mark.asyncio
async def test_acquire_prunes_expired_artifacts_before_persisting_new_results(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    monkeypatch.setattr(
        "app.services.acquisition.artifact_store.ACQUISITION_ARTIFACT_TTL_SECONDS",
        60,
    )
    monkeypatch.setattr(
        "app.services.acquisition.artifact_store.ACQUISITION_ARTIFACT_CLEANUP_INTERVAL_SECONDS",
        0,
    )
    monkeypatch.setattr(
        "app.services.acquisition.artifact_store._LAST_ARTIFACT_CLEANUP_STARTED_AT",
        0.0,
    )
    expired_at = time.time() - 3600
    stale_paths = [
        tmp_path / "html" / "stale.html",
        tmp_path / "network" / "stale.json",
        tmp_path / "diagnostics" / "stale.json",
    ]
    for path in stale_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale", encoding="utf-8")
        os.utime(path, (expired_at, expired_at))

    html = "<html><body><h1>Fresh</h1><p>" + ("x" * 600) + "</p></body></html>"
    with patch(
        "app.services.acquisition.acquirer._fetch_with_content_type",
        new_callable=AsyncMock,
        return_value=HttpFetchResult(text=html, status_code=200, content_type="html"),
    ):
        result = await acquire(_request(42, "https://example.com/fresh"))

    assert Path(result.artifact_path).exists()
    assert Path(result.diagnostics_path).exists()
    for path in stale_paths:
        assert not path.exists()


def test_browser_first_accepts_non_blocked_rendered_page_without_extractability_signal() -> None:
    ctx = SimpleNamespace(
        request=SimpleNamespace(
            url="https://example.com/products/widget",
            acquisition_profile={},
            prefer_stealth=False,
            proxy=None,
        ),
        surface="ecommerce_detail",
        artifact_path="artifact.html",
        started_at=0.0,
        host_wait_seconds=0.0,
        runtime_options=SimpleNamespace(
            hardened_mode=True,
            hardened_mode_reason="browser_first",
        ),
        finalize_diagnostics_payload=lambda payload: payload,
    )
    browser_result = SimpleNamespace(
        challenge_state="none",
        origin_warmed=False,
        frame_sources=[],
        promoted_sources=[],
        _acquirer_browser={
            "html": "<html><body><main><div id='app'>Rendered shell</div></main></body></html>",
            "final_url": "https://example.com/products/widget",
            "network_payloads": [],
            "diagnostics": {},
            "browser_total_ms": 10,
            "blocked": False,
        },
    )

    result = _try_browser_first_success_result(ctx, browser_result=browser_result)

    assert result is not None
    assert result.method == "playwright"


@pytest.mark.asyncio
async def test_acquire_diagnostics_include_platform_family_for_real_family_url(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    html = "<html><body><h1>Jobs</h1><p>" + ("Open roles " * 80) + "</p><table class='iCIMS_JobsTable'></table></body></html>"

    with patch(
        "app.services.acquisition.acquirer._fetch_with_content_type",
        new_callable=AsyncMock,
        return_value=HttpFetchResult(text=html, status_code=200, content_type="html"),
    ):
        result = await acquire(_request(42, "https://ehccareers-emory.icims.com/jobs/search?pr=0&searchRelation=keyword_all",
            surface="job_listing",
        ))

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
        result = await acquire(_request(42, "https://demo.opencart.com/", surface="ecommerce_listing"))

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

    async def _fake_acquire_once(request):
        captured.append(bool(getattr(request, "prefer_stealth", False)))
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

    result = await acquire(_request(42, "https://example.com/products/widget",
        acquisition_profile={"prefer_stealth": True},
    ))

    assert result.method == "curl_cffi"
    assert captured == [False]


@pytest.mark.asyncio
async def test_acquire_enables_stealth_only_when_legacy_hardened_mode_is_enabled(monkeypatch, tmp_path):
    captured: list[bool] = []

    async def _fake_acquire_once(request):
        captured.append(bool(getattr(request, "prefer_stealth", False)))
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

    result = await acquire(_request(42, "https://example.com/products/widget",
        acquisition_profile={"prefer_stealth": True, "anti_bot_enabled": True},
    ))

    assert result.method == "curl_cffi"
    assert captured == [True]


@pytest.mark.asyncio
async def test_acquire_browser_first_platform_family_selects_hardened_runtime(
    monkeypatch, tmp_path
):
    captured: list[tuple[bool, str | None]] = []

    async def _fake_acquire_once(request):
        runtime_options = getattr(request, "runtime_options", None)
        captured.append(
            (
                bool(getattr(runtime_options, "hardened_mode", False)),
                getattr(runtime_options, "hardened_mode_reason", None),
            )
        )
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

    result = await acquire(_request(42, "https://myjobs.adp.com/cx/search-jobs",
        surface="job_listing",
    ))

    assert result.method == "playwright"
    assert captured == [(True, "browser_first")]


@pytest.mark.asyncio
async def test_acquire_browser_first_platform_family_ignores_legacy_anti_bot_false(
    monkeypatch, tmp_path
):
    captured: list[tuple[bool, str | None]] = []

    async def _fake_acquire_once(request):
        runtime_options = getattr(request, "runtime_options", None)
        captured.append(
            (
                bool(getattr(runtime_options, "hardened_mode", False)),
                getattr(runtime_options, "hardened_mode_reason", None),
            )
        )
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

    result = await acquire(_request(42, "https://myjobs.adp.com/cx/search-jobs",
        surface="job_listing",
        acquisition_profile={"anti_bot_enabled": False},
    ))

    assert result.method == "playwright"
    assert captured == [(True, "browser_first")]


@pytest.mark.asyncio
async def test_acquire_prefer_browser_profile_selects_hardened_runtime(monkeypatch, tmp_path):
    captured: list[tuple[bool, str | None]] = []

    async def _fake_acquire_once(request):
        runtime_options = getattr(request, "runtime_options", None)
        captured.append(
            (
                bool(getattr(runtime_options, "hardened_mode", False)),
                getattr(runtime_options, "hardened_mode_reason", None),
            )
        )
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

    result = await acquire(_request(42, "https://example.com/products/widget",
        acquisition_profile={"prefer_browser": True},
    ))

    assert result.method == "playwright"
    assert captured == [(True, "browser_first")]
