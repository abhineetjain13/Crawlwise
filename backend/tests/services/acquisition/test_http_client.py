# Tests for the shared HTTP acquisition provider.
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from curl_cffi.const import CurlOpt

from app.services.acquisition.host_memory import host_prefers_stealth, reset_host_memory
from app.services.acquisition.http_client import _retry_backoff_seconds, fetch_html_result
from app.services.url_safety import ValidatedTarget


@dataclass
class FakeResponse:
    status_code: int
    text: str
    headers: dict[str, str]
    url: str = "https://example.com"


@pytest.fixture(autouse=True)
def _reset_memory():
    reset_host_memory()
    yield
    reset_host_memory()


@pytest.mark.asyncio
async def test_fetch_html_result_retries_with_stealth(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.acquisition.host_memory.settings.artifacts_dir", tmp_path)
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_MAX_RETRIES", 0)

    calls: list[str] = []

    class FakeAsyncSession:
        def __init__(self, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            calls.append(kwargs["impersonate"])
            if kwargs["impersonate"] == "chrome131":
                return FakeResponse(
                    status_code=200,
                    text="<html><body><h1>Product</h1>" + ("x" * 300) + "</body></html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            return FakeResponse(
                status_code=403,
                text="<html><body>Access Denied</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

    monkeypatch.setattr("app.services.acquisition.http_client.requests.AsyncSession", FakeAsyncSession)

    result = await fetch_html_result("https://example.com/product")

    assert result.status_code == 200
    assert result.stealth_used
    assert calls == ["chrome110", "chrome131"]
    assert host_prefers_stealth("https://example.com/product")


@pytest.mark.asyncio
async def test_fetch_html_result_pins_dns_without_rewriting_hostname(monkeypatch):
    captured: dict[str, object] = {}

    class FakeAsyncSession:
        def __init__(self, **kwargs):
            captured["session_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse(
                status_code=200,
                text="<html><body>ok</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
                url=str(url),
            )

    monkeypatch.setattr(
        "app.services.acquisition.http_client.validate_public_target",
        AsyncMock(
            return_value=ValidatedTarget(
                hostname="example.com",
                scheme="https",
                port=443,
                resolved_ips=("93.184.216.34",),
            )
        ),
    )
    monkeypatch.setattr("app.services.acquisition.http_client.requests.AsyncSession", FakeAsyncSession)

    result = await fetch_html_result("https://example.com/product")

    assert result.status_code == 200
    assert captured["url"] == "https://example.com/product"
    assert "headers" not in captured["kwargs"]
    assert captured["session_kwargs"]["curl_options"][CurlOpt.RESOLVE] == ["example.com:443:93.184.216.34"]


@pytest.mark.asyncio
async def test_fetch_html_result_stops_retrying_same_impersonation_when_page_is_blocked(monkeypatch):
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_MAX_RETRIES", 2)

    calls: list[str] = []

    class FakeAsyncSession:
        def __init__(self, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            calls.append(kwargs["impersonate"])
            return FakeResponse(
                status_code=429,
                text="<html><body><script src=\"/fp?x-kpsdk\"></script><h1>Access Denied</h1></body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

    monkeypatch.setattr("app.services.acquisition.http_client.requests.AsyncSession", FakeAsyncSession)

    result = await fetch_html_result("https://example.com/product")

    assert result.status_code == 429
    assert calls == ["chrome110", "chrome131"]
    assert result.attempts == 1


def test_retry_backoff_seconds_is_bounded(monkeypatch):
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_RETRY_BACKOFF_BASE_MS", 400)
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_RETRY_BACKOFF_MAX_MS", 1000)

    assert _retry_backoff_seconds(1) == 0.4
    assert _retry_backoff_seconds(2) == 0.8
    assert _retry_backoff_seconds(3) == 1.0


def test_retry_backoff_seconds_rejects_invalid_bounds(monkeypatch):
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_RETRY_BACKOFF_BASE_MS", 400)
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_RETRY_BACKOFF_MAX_MS", 200)

    with pytest.raises(ValueError, match="HTTP_RETRY_BACKOFF_MAX_MS"):
        _retry_backoff_seconds(1)
