# Tests for acquisition waterfall and proxy rotation.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services.acquisition.acquirer import ProxyRotator, _artifact_path, _network_payload_path, acquire_html
from app.services.acquisition.http_client import HttpFetchResult
from app.services.acquisition.host_memory import host_prefers_stealth, remember_stealth_host, reset_host_memory


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
async def test_acquire_html_advanced_mode_tries_curl_then_playwright():
    """Advanced mode tries curl_cffi first, then escalates to Playwright."""
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
                1, "https://example.com/spa", advanced_mode="scroll"
            )
    # Playwright is preferred when advanced_mode is set, even though curl worked
    assert method == "playwright"


@pytest.mark.asyncio
async def test_acquire_html_advanced_mode_falls_back_to_curl_on_playwright_failure():
    """When advanced mode Playwright crashes, fall back to curl_cffi result."""
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
                1, "https://example.com/spa", advanced_mode="auto"
            )
    assert method == "curl_cffi"
    assert "Product" in result_html


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


@pytest.fixture(autouse=True)
def _reset_host_memory():
    reset_host_memory()
    yield
    reset_host_memory()


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
    assert html_path.stem == network_path.stem
    assert html_path.stem.startswith("www-example-com__run-42__products-fancy-chair-color-oak-size-large__")
