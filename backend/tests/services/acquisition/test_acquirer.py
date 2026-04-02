# Tests for acquisition waterfall and proxy rotation.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services.acquisition.acquirer import ProxyRotator, acquire_html


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
        patch("app.services.acquisition.acquirer.fetch_html", new_callable=AsyncMock, return_value=html),
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
        patch("app.services.acquisition.acquirer.fetch_html", new_callable=AsyncMock, return_value=short_html),
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
async def test_acquire_html_advanced_mode_skips_curl():
    """Advanced mode goes directly to Playwright."""
    full_html = "<html><body>" + "x" * 600 + "</body></html>"

    from app.services.acquisition.browser_client import BrowserResult

    with (
        patch("app.services.acquisition.acquirer.fetch_rendered_html", new_callable=AsyncMock, return_value=BrowserResult(html=full_html)),
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            result_html, method, path, payloads = await acquire_html(
                1, "https://example.com/spa", advanced_mode="scroll"
            )
    assert method == "playwright"


@pytest.mark.asyncio
async def test_acquire_with_proxy():
    """Proxy is passed through to HTTP client."""
    html = "<html><body>" + "x" * 600 + "</body></html>"
    with (
        patch("app.services.acquisition.acquirer.fetch_html", new_callable=AsyncMock, return_value=html) as mock_fetch,
        patch("app.services.acquisition.acquirer.settings") as mock_settings,
    ):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_settings.artifacts_dir = Path(tmpdir)
            await acquire_html(1, "https://example.com", proxy_list=["http://myproxy:8080"])
    mock_fetch.assert_called_once_with("https://example.com", proxy="http://myproxy:8080")
