# Tests for the shared HTTP acquisition provider.
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.acquisition.host_memory import host_prefers_stealth, reset_host_memory
from app.services.acquisition.http_client import fetch_html_result


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
