from __future__ import annotations

from urllib.error import HTTPError, URLError

import pytest

from app.services import robots_policy


class _FakeHeaders:
    def __init__(self, charset: str | None = None) -> None:
        self._charset = charset

    def get_content_charset(self) -> str | None:
        return self._charset


class _FakeResponse:
    def __init__(self, body: str, *, charset: str | None = "utf-8") -> None:
        self._body = body.encode(charset or "utf-8")
        self.headers = _FakeHeaders(charset)

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_check_url_crawlability_allows_url_when_robots_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    robots_policy.reset_robots_policy_cache()
    monkeypatch.setattr(
        robots_policy,
        "urlopen",
        lambda request, timeout: _FakeResponse("User-agent: *\nDisallow:"),
    )

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    assert result.allowed is True
    assert result.outcome == robots_policy.ROBOTS_ALLOWED
    assert result.robots_url == "https://example.com/robots.txt"


@pytest.mark.asyncio
async def test_check_url_crawlability_blocks_url_when_robots_disallows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    robots_policy.reset_robots_policy_cache()
    monkeypatch.setattr(
        robots_policy,
        "urlopen",
        lambda request, timeout: _FakeResponse("User-agent: *\nDisallow: /private"),
    )

    result = await robots_policy.check_url_crawlability("https://example.com/private/page")

    assert result.allowed is False
    assert result.outcome == robots_policy.ROBOTS_DISALLOWED


@pytest.mark.asyncio
async def test_check_url_crawlability_allows_missing_robots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    robots_policy.reset_robots_policy_cache()

    def _missing(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(robots_policy, "urlopen", _missing)

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    assert result.allowed is True
    assert result.outcome == robots_policy.ROBOTS_MISSING


@pytest.mark.asyncio
async def test_check_url_crawlability_allows_when_robots_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    robots_policy.reset_robots_policy_cache()

    def _fail(request, timeout):
        raise URLError("timeout")

    monkeypatch.setattr(robots_policy, "urlopen", _fail)

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    assert result.allowed is True
    assert result.outcome == robots_policy.ROBOTS_FETCH_FAILURE
    assert result.error


@pytest.mark.asyncio
async def test_check_url_crawlability_treats_forbidden_robots_as_disallow_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    robots_policy.reset_robots_policy_cache()

    def _forbidden(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(robots_policy, "urlopen", _forbidden)

    result = await robots_policy.check_url_crawlability("https://example.com/private")

    assert result.allowed is False
    assert result.outcome == robots_policy.ROBOTS_DISALLOWED
