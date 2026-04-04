# Tests for acquisition waterfall and proxy rotation.
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.acquisition.acquirer import (
    ProxyRotator,
    _artifact_path,
    _diagnostics_path,
    _network_payload_path,
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
    assert html_path.stem.startswith("www-example-com__run-42__products-fancy-chair-color-oak-size-large__")


@pytest.mark.asyncio
async def test_acquire_retries_same_host_after_learning_stealth_preference(monkeypatch, tmp_path):
    from pathlib import Path

    calls: list[bool] = []

    async def _fake_acquire_once(**kwargs):
        calls.append(bool(kwargs.get("prefer_stealth")))
        if len(calls) == 1:
            monkeypatch.setattr("app.services.acquisition.acquirer.host_prefers_stealth", lambda _url: True)
            return None
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
    monkeypatch.setattr("app.services.acquisition.acquirer.host_prefers_stealth", lambda _url: False)
    monkeypatch.setattr("app.services.acquisition.acquirer.settings.artifacts_dir", tmp_path)

    result = await acquire(42, "https://www.wayfair.com/example")

    assert result.html == "<html>ok</html>"
    assert calls == [False, True]
