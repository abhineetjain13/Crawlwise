# Tests for the shared HTTP acquisition provider.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from app.core.config import settings
from app.services.acquisition.cookie_store import is_persistable_cookie
from app.services.acquisition.http_client import (
    _build_attempt_order,
    _parse_retry_after,
    _retry_backoff_seconds,
    fetch_html_result,
)
from app.services.url_safety import ValidatedTarget
from curl_cffi.const import CurlOpt


@dataclass
class FakeResponse:
    status_code: int
    text: str
    headers: dict[str, str]
    url: str = "https://example.com"


@pytest.mark.asyncio
async def test_fetch_html_result_retries_with_stealth(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_MAX_RETRIES", 0)
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_IMPERSONATION_PROFILES", ("chrome110", "chrome131"))
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_STEALTH_IMPERSONATION_PROFILE", "chrome131")

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
    assert result.impersonate_profile == "chrome131"


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
    assert captured["session_kwargs"]["trust_env"] is False
    assert captured["session_kwargs"]["curl_options"][CurlOpt.RESOLVE] == ["example.com:443:93.184.216.34"]


@pytest.mark.asyncio
async def test_fetch_html_result_stops_retrying_same_impersonation_when_page_is_blocked(monkeypatch):
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_MAX_RETRIES", 2)
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_IMPERSONATION_PROFILES", ("chrome110", "chrome131"))
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_STEALTH_IMPERSONATION_PROFILE", "chrome131")

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


@pytest.mark.asyncio
async def test_fetch_html_result_rotates_across_configured_profiles(monkeypatch):
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_MAX_RETRIES", 0)
    monkeypatch.setattr(
        "app.services.acquisition.http_client.HTTP_IMPERSONATION_PROFILES",
        ("chrome110", "chrome116", "chrome123", "chrome131"),
    )
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_STEALTH_IMPERSONATION_PROFILE", "chrome131")
    monkeypatch.setattr("app.services.acquisition.http_client.IMPERSONATION_TARGET", "chrome110")

    calls: list[str] = []

    class FakeAsyncSession:
        def __init__(self, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            profile = kwargs["impersonate"]
            calls.append(profile)
            if profile == "chrome131":
                return FakeResponse(
                    status_code=200,
                    text="<html><body><h1>Product</h1>" + ("x" * 300) + "</body></html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            return FakeResponse(
                status_code=429,
                text="<html><body>rate limited</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

    monkeypatch.setattr("app.services.acquisition.http_client.requests.AsyncSession", FakeAsyncSession)

    result = await fetch_html_result("https://example.com/product")

    assert result.status_code == 200
    assert result.stealth_used
    assert result.impersonate_profile == "chrome131"
    assert calls == ["chrome110", "chrome116", "chrome123", "chrome131"]


@pytest.mark.asyncio
async def test_fetch_html_result_attaches_harvested_cookies(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cookie_store_dir", tmp_path)
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_IMPERSONATION_PROFILES", ("chrome110",))
    cookie_file = tmp_path / "example.com.json"
    cookie_file.write_text(
        '[{"name":"datadome","value":"token","domain":"example.com","path":"/","expires":4102444800}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.services.acquisition.cookie_store.COOKIE_POLICY",
        {
            "persist_session_cookies": False,
            "max_persisted_ttl_seconds": 0,
            "blocked_name_prefixes": ["cf_", "dd_", "px", "datadome"],
            "blocked_name_contains": ["challenge", "datadome"],
            "harvest_cookie_names": [],
            "reuse_in_http_client": True,
            "domain_overrides": {},
        },
    )
    captured: dict[str, object] = {}

    class FakeAsyncSession:
        def __init__(self, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            captured["cookies"] = kwargs.get("cookies")
            return FakeResponse(
                status_code=200,
                text="<html><body>ok</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

    monkeypatch.setattr("app.services.acquisition.http_client.requests.AsyncSession", FakeAsyncSession)

    result = await fetch_html_result("https://example.com/product", allow_stealth_retry=False)

    assert result.status_code == 200
    assert captured["cookies"] is None


def test_build_attempt_order_rejects_empty_impersonation_profiles(monkeypatch):
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_IMPERSONATION_PROFILES", ("", None))
    monkeypatch.setattr("app.services.acquisition.http_client.IMPERSONATION_TARGET", "")

    with pytest.raises(ValueError, match="No valid HTTP impersonation profile"):
        _build_attempt_order(
            url="https://example.com",
            allow_stealth_retry=True,
            force_stealth=False,
        )


def test_is_persistable_cookie_ignores_invalid_max_ttl_policy(monkeypatch):
    import logging
    from unittest.mock import patch
    future = 4102444800
    monkeypatch.setattr(
        "app.services.acquisition.cookie_store.COOKIE_POLICY",
        {
            "persist_session_cookies": False,
            "max_persisted_ttl_seconds": "not-a-number",
            "blocked_name_prefixes": [],
            "blocked_name_contains": [],
            "harvest_cookie_names": [],
            "reuse_in_http_client": True,
            "domain_overrides": {},
        },
    )

    with patch("app.services.acquisition.cookie_store._log_for_pytest") as mock_log:
        allowed = is_persistable_cookie(
            {"name": "prefs", "value": "1", "domain": "example.com", "path": "/", "expires": future},
            domain="example.com",
        )
        assert allowed is True
        assert mock_log.called
        assert "max_persisted_ttl_seconds" in mock_log.call_args[0][2]


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


def test_parse_retry_after_treats_naive_http_dates_as_utc(monkeypatch):
    retry_at = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.acquisition.http_client.time.time", lambda: retry_at.timestamp() - 30.0)

    delay = _parse_retry_after({"retry-after": "Mon, 06 Apr 2026 12:00:00"})

    assert delay == 30.0


@pytest.mark.asyncio
async def test_fetch_html_result_honors_retry_after_header(monkeypatch):
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_MAX_RETRIES", 1)
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_IMPERSONATION_PROFILES", ("chrome110",))

    calls = 0
    sleeps: list[float] = []

    class FakeAsyncSession:
        def __init__(self, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return FakeResponse(
                    status_code=429,
                    text="<html><body><main><h1>Rate limited</h1><p>" + ("x" * 400) + "</p></main></body></html>",
                    headers={"content-type": "text/html; charset=utf-8", "retry-after": "7"},
                )
            return FakeResponse(
                status_code=200,
                text="<html><body>ok</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

    async def _fake_sleep(delay: float):
        sleeps.append(delay)

    monkeypatch.setattr("app.services.acquisition.http_client.requests.AsyncSession", FakeAsyncSession)
    monkeypatch.setattr("app.services.acquisition.http_client.asyncio.sleep", _fake_sleep)

    result = await fetch_html_result("https://example.com/product", allow_stealth_retry=False)

    assert result.status_code == 200
    assert sleeps == [7.0]


@pytest.mark.asyncio
async def test_fetch_html_result_revalidates_redirect_targets(monkeypatch):
    calls: list[str] = []
    validated_urls: list[str] = []

    class FakeAsyncSession:
        def __init__(self, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            calls.append(str(url))
            if str(url).endswith("/start"):
                return FakeResponse(
                    status_code=302,
                    text="",
                    headers={"location": "/next", "content-type": "text/html"},
                    url=str(url),
                )
            return FakeResponse(
                status_code=200,
                text="<html><body>ok</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
                url=str(url),
            )

    async def _fake_validate(url: str) -> ValidatedTarget:
        validated_urls.append(url)
        return ValidatedTarget(
            hostname="example.com",
            scheme="https",
            port=443,
            resolved_ips=("93.184.216.34",),
        )

    monkeypatch.setattr("app.services.acquisition.http_client.validate_public_target", _fake_validate)
    monkeypatch.setattr("app.services.acquisition.http_client.requests.AsyncSession", FakeAsyncSession)
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_IMPERSONATION_PROFILES", ("chrome110",))

    result = await fetch_html_result("https://example.com/start", allow_stealth_retry=False)

    assert result.status_code == 200
    assert calls == ["https://example.com/start", "https://example.com/next"]
    assert validated_urls == ["https://example.com/start", "https://example.com/next"]


@pytest.mark.asyncio
async def test_fetch_html_result_rejects_non_http_redirect_targets(monkeypatch):
    class FakeAsyncSession:
        def __init__(self, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            _ = kwargs
            return FakeResponse(
                status_code=302,
                text="",
                headers={"location": "file:///etc/passwd", "content-type": "text/html"},
                url=str(url),
            )

    validate_mock = AsyncMock(
        return_value=ValidatedTarget(
            hostname="example.com",
            scheme="https",
            port=443,
            resolved_ips=("93.184.216.34",),
        )
    )
    monkeypatch.setattr("app.services.acquisition.http_client.validate_public_target", validate_mock)
    monkeypatch.setattr("app.services.acquisition.http_client.requests.AsyncSession", FakeAsyncSession)
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_IMPERSONATION_PROFILES", ("chrome110",))

    result = await fetch_html_result("https://example.com/start", allow_stealth_retry=False)

    assert result.error == "invalid_redirect_target"
    assert result.status_code == 302
    # validate_public_target should only run for the initial request URL.
    assert validate_mock.await_count == 1


@pytest.mark.asyncio
async def test_fetch_html_result_rejects_redirect_targets_with_embedded_credentials(monkeypatch):
    class FakeAsyncSession:
        def __init__(self, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            _ = kwargs
            return FakeResponse(
                status_code=302,
                text="",
                headers={
                    "location": "https://user:pass@example.com/next",
                    "content-type": "text/html",
                },
                url=str(url),
            )

    validate_mock = AsyncMock(
        return_value=ValidatedTarget(
            hostname="example.com",
            scheme="https",
            port=443,
            resolved_ips=("93.184.216.34",),
        )
    )
    monkeypatch.setattr("app.services.acquisition.http_client.validate_public_target", validate_mock)
    monkeypatch.setattr("app.services.acquisition.http_client.requests.AsyncSession", FakeAsyncSession)
    monkeypatch.setattr("app.services.acquisition.http_client.HTTP_IMPERSONATION_PROFILES", ("chrome110",))

    result = await fetch_html_result("https://example.com/start", allow_stealth_retry=False)

    assert result.error == "invalid_redirect_target"
    assert result.status_code == 302
    assert validate_mock.await_count == 1
