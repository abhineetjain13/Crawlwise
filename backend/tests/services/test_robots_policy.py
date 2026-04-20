from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services import robots_policy


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    def __init__(self, response_factory) -> None:
        self._response_factory = response_factory

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str) -> _FakeResponse:
        return await self._response_factory(url)


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    response_factory,
) -> None:
    monkeypatch.setattr(
        robots_policy.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response_factory),
    )


@pytest.mark.asyncio
async def test_check_url_crawlability_allows_url_when_robots_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()

    async def _response(url: str) -> _FakeResponse:
        assert url == "https://example.com/robots.txt"
        return _FakeResponse(200, "User-agent: *\nDisallow:")

    _patch_client(monkeypatch, _response)

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    assert result.allowed is True
    assert result.outcome == robots_policy.ROBOTS_ALLOWED
    assert result.robots_url == "https://example.com/robots.txt"


@pytest.mark.asyncio
async def test_check_url_crawlability_blocks_url_when_robots_disallows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()

    async def _response(url: str) -> _FakeResponse:
        del url
        return _FakeResponse(200, "User-agent: *\nDisallow: /private")

    _patch_client(monkeypatch, _response)

    result = await robots_policy.check_url_crawlability("https://example.com/private/page")

    assert result.allowed is False
    assert result.outcome == robots_policy.ROBOTS_DISALLOWED


@pytest.mark.asyncio
async def test_check_url_crawlability_allows_missing_robots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()

    async def _response(url: str) -> _FakeResponse:
        del url
        return _FakeResponse(404)

    _patch_client(monkeypatch, _response)

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    assert result.allowed is True
    assert result.outcome == robots_policy.ROBOTS_MISSING


@pytest.mark.asyncio
async def test_check_url_crawlability_allows_when_robots_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()

    async def _response(url: str) -> _FakeResponse:
        del url
        request = httpx.Request("GET", "https://example.com/robots.txt")
        raise httpx.ReadTimeout("timeout", request=request)

    _patch_client(monkeypatch, _response)

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    assert result.allowed is True
    assert result.outcome == robots_policy.ROBOTS_FETCH_FAILURE
    assert result.error


@pytest.mark.asyncio
async def test_check_url_crawlability_treats_forbidden_robots_as_disallow_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()

    async def _response(url: str) -> _FakeResponse:
        del url
        return _FakeResponse(403)

    _patch_client(monkeypatch, _response)

    result = await robots_policy.check_url_crawlability("https://example.com/private")

    assert result.allowed is False
    assert result.outcome == robots_policy.ROBOTS_DISALLOWED


@pytest.mark.asyncio
async def test_check_url_crawlability_reuses_inflight_fetch_for_same_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()
    calls = 0

    async def _response(url: str) -> _FakeResponse:
        nonlocal calls
        del url
        calls += 1
        await asyncio.sleep(0.05)
        return _FakeResponse(200, "User-agent: *\nDisallow:")

    _patch_client(monkeypatch, _response)

    results = await asyncio.gather(
        robots_policy.check_url_crawlability("https://example.com/public"),
        robots_policy.check_url_crawlability("https://example.com/public?page=2"),
    )

    assert calls == 1
    assert all(result.allowed for result in results)
