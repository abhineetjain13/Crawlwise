# Tests for acquisition waterfall and proxy rotation.
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.acquisition.acquirer import (
    ProxyRotator,
    _artifact_path,
    _diagnostics_path,
    _json_ld_listing_count,
    _is_invalid_job_surface_page,
    _network_payload_path,
    _requested_fields_need_browser,
    acquire,
    acquire_html,
)
from app.services.acquisition.http_client import HttpFetchResult
from app.services.acquisition.host_memory import host_prefers_stealth, remember_stealth_host, reset_host_memory
from app.services.acquisition.pacing import reset_pacing_state


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


def test_json_ld_listing_count_handles_type_arrays_and_empty_itemlists():
    assert _json_ld_listing_count({"@type": ["Thing", "Product"]}) == 1
    assert _json_ld_listing_count({"@type": ["ItemList"], "itemListElement": []}) == 0


@pytest.mark.asyncio
async def test_acquire_html_curl_success():
    """curl_cffi success path — no Playwright fallback needed."""
    html = "<html><body><h1>Product</h1><p>Long enough content to pass threshold check" + "x" * 500 + "</p></body></html>"
    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=html, status_code=200, content_type="html")),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            result_html, method, path, payloads = await acquire_html(1, "https://example.com/product")
    assert method == "curl_cffi"
    assert "Product" in result_html
    assert payloads == []


@pytest.mark.asyncio
async def test_acquire_html_falls_back_to_playwright():
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
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            result_html, method, path, payloads = await acquire_html(1, "https://example.com/spa-page")
    assert method == "playwright"
    assert len(payloads) == 1


@pytest.mark.asyncio
async def test_acquire_html_keeps_curl_when_adapter_can_handle_js_heavy_html():
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
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            result = await acquire(1, "https://example.com/products/widget")

    assert result.method == "curl_cffi"
    assert result.diagnostics["curl_adapter_hint"] == "shopify"
    browser_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_html_keeps_curl_when_js_shell_contains_extractable_structured_data():
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
    """ + ("<script>var x=1;</script>" * 30000) + "</body></html>"

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
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            result = await acquire(1, "https://example.com/products/widget")

    assert result.method == "curl_cffi"
    assert result.diagnostics["curl_needs_browser"] is False
    assert result.diagnostics["js_shell_overridden"] == "structured_data_found"
    browser_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_html_auto_mode_keeps_curl_when_structured_listings_are_extractable():
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
    """ + ("<script>var x=1;</script>" * 30000) + "</body></html>"

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
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            result = await acquire(1, "https://example.com/products/widget", traversal_mode="auto")

    assert result.method == "curl_cffi"
    assert result.diagnostics["js_shell_overridden"] == "structured_data_found"
    browser_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_html_traversal_mode_tries_curl_then_playwright():
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
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            result_html, method, path, payloads = await acquire_html(
                1, "https://example.com/spa", traversal_mode="scroll"
            )
    # Playwright is preferred when traversal mode is set, even though curl worked
    assert method == "playwright"


@pytest.mark.asyncio
async def test_acquire_html_passes_max_scrolls_to_playwright():
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
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            await acquire_html(1, "https://example.com/spa", traversal_mode="scroll", max_scrolls=23)

    assert fetch_rendered_html_mock.await_args.kwargs["max_scrolls"] == 23


@pytest.mark.asyncio
async def test_acquire_html_traversal_mode_falls_back_to_curl_on_playwright_failure():
    """When traversal mode Playwright crashes, fall back to curl_cffi result."""
    curl_html = "<html><body><h1>Product</h1>" + "x" * 600 + "</body></html>"

    from app.services.acquisition.http_client import HttpFetchResult

    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=curl_html, status_code=200, content_type="html")),
        patch("app.services.acquisition.acquirer.fetch_rendered_html", new_callable=AsyncMock, side_effect=RuntimeError("ERR_HTTP2_PROTOCOL_ERROR")),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            result_html, method, path, payloads = await acquire_html(
                1, "https://example.com/spa", traversal_mode="auto"
            )
    assert method == "curl_cffi"
    assert "Product" in result_html


@pytest.mark.asyncio
async def test_acquire_listing_page_does_not_escalate_from_text_only_card_count_heuristics():
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
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            result = await acquire(1, "https://example.com/listings", surface="listing")

    assert result.method == "curl_cffi"
    browser_mock.assert_not_awaited()


def test_is_invalid_job_surface_page_detects_homepage_login_redirect():
    html = """
    <html>
      <head>
        <title>GovernmentJobs | City, State, Federal &amp; Public Sector Jobs</title>
        <link rel="canonical" href="https://www.schooljobs.com/" />
      </head>
      <body><h1>log in</h1></body>
    </html>
    """

    assert _is_invalid_job_surface_page(
        requested_url="https://www.governmentjobs.com/careers/california/jobs/4817400",
        final_url="https://www.governmentjobs.com/",
        html=html,
        surface="job_detail",
    ) is True


def test_is_invalid_job_surface_page_detects_soft_404_job_page():
    html = """
    <html>
      <head><title>Sorry. The page you requested could not be found.</title></head>
      <body><h1>Sorry. The page you requested could not be found.</h1></body>
    </html>
    """

    assert _is_invalid_job_surface_page(
        requested_url="https://www.higheredjobs.com/jobs/details.cfm?JobCode=178200990",
        final_url="https://www.higheredjobs.com/jobs/details.cfm?JobCode=178200990",
        html=html,
        surface="job_detail",
    ) is True


@pytest.mark.asyncio
async def test_acquire_discards_job_redirect_shell_results(tmp_path, monkeypatch):
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
        with pytest.raises(RuntimeError, match="Unable to acquire content"):
            await acquire(42, "https://www.governmentjobs.com/careers/california/jobs/4817400", surface="job_detail")


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
async def test_acquire_with_proxy():
    """Proxy is passed through to HTTP client."""
    html = "<html><body>" + "x" * 600 + "</body></html>"
    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=html, status_code=200, content_type="html")) as mock_fetch,
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            await acquire_html(1, "https://example.com", proxy_list=["http://myproxy:8080"])
    mock_fetch.assert_called_once()
    call_args = mock_fetch.call_args
    assert call_args.args[0] == "https://example.com"


@pytest.mark.asyncio
async def test_acquire_json_content_type():
    """JSON content type should be detected and returned."""
    json_text = '{"jobs": [{"title": "Engineer"}]}'
    json_data = {"jobs": [{"title": "Engineer"}]}
    with (
        patch("app.services.acquisition.acquirer._fetch_with_content_type",
              new_callable=AsyncMock, return_value=HttpFetchResult(text=json_text, status_code=200, content_type="json", json_data=json_data)),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        from pathlib import Path
        import tempfile
        from app.services.acquisition.acquirer import acquire
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            result = await acquire(1, "https://api.example.com/jobs")
    assert result.content_type == "json"
    assert result.json_data == json_data
    assert result.method == "curl_cffi"


@pytest.mark.asyncio
async def test_acquire_writes_diagnostics_artifact(tmp_path, monkeypatch):
    html = "<html><body><h1>Product</h1><p>" + ("x" * 600) + "</p></body></html>"
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)

    with patch(
        "app.services.acquisition.acquirer._fetch_with_content_type",
        new_callable=AsyncMock,
        return_value=HttpFetchResult(
            text=html,
            status_code=200,
            content_type="html",
            attempt_log=[{"attempt": 1, "impersonate": "chrome110", "status_code": 200, "content_type": "html", "blocked": False}],
        ),
    ):
        result = await acquire(42, "https://example.com/product")

    diagnostics_path = _diagnostics_path(42, "https://example.com/product")
    assert result.diagnostics_path == str(diagnostics_path)
    payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == 42
    assert payload["url"] == "https://example.com/product"
    assert payload["method"] == "curl_cffi"
    assert payload["artifact_path"] == result.artifact_path
    assert payload["diagnostics"]["curl_status_code"] == 200
    assert payload["diagnostics"]["curl_needs_browser"] is False
    assert payload["diagnostics"]["curl_attempt_log"] == [
        {"attempt": 1, "impersonate": "chrome110", "status_code": 200, "content_type": "html", "blocked": False}
    ]
    assert payload["status"] == "completed"


@pytest.mark.asyncio
async def test_acquire_writes_failure_diagnostics_when_all_attempts_fail(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)

    async def _always_fail(**_kwargs):
        return None

    monkeypatch.setattr("app.services.acquisition.acquirer._acquire_once", _always_fail)

    with pytest.raises(RuntimeError, match="Unable to acquire content"):
        await acquire(42, "https://example.com/unreachable")

    diagnostics_path = _diagnostics_path(42, "https://example.com/unreachable")
    payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["diagnostics"]["error_code"] == "acquisition_failed"


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


@pytest.fixture(autouse=True)
def _reset_host_memory():
    reset_host_memory()
    reset_pacing_state()
    yield
    reset_host_memory()
    reset_pacing_state()


def test_host_memory_persists_preference(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.host_memory.settings.artifacts_dir", tmp_path)
    assert not host_prefers_stealth("https://example.com/path")
    remember_stealth_host("https://example.com/path", ttl_hours=1)
    assert host_prefers_stealth("https://example.com/path")


def test_artifact_paths_use_readable_hybrid_basename(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)
    url = "https://www.example.com/products/fancy-chair?color=oak&size=large"
    html_path = _artifact_path(42, url)
    network_path = _network_payload_path(42, url)
    diagnostics_path = _diagnostics_path(42, url)
    assert html_path.stem == network_path.stem
    assert html_path.stem == diagnostics_path.stem
    assert html_path.parent == tmp_path / "html"
    assert network_path.parent == tmp_path / "network"
    assert diagnostics_path.parent == tmp_path / "diagnostics"
    assert html_path.stem.startswith("www-example-com-")
    assert html_path.stem.endswith("-run_42")


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


def test_requested_fields_need_browser_normalizes_requested_terms():
    assert _requested_fields_need_browser(
        "<html><body><section>Q and A</section></body></html>",
        "Q and A",
        ["q&a"],
        {},
    ) is False
