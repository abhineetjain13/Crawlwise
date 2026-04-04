# Tests for Playwright browser acquisition hardening helpers.
from __future__ import annotations

import json
import time

import pytest

from app.core.config import settings
from app.services.acquisition.browser_client import (
    _context_kwargs,
    _cookie_policy_for_domain,
    _goto_with_fallback,
    _load_cookies,
    _retryable_browser_error_reason,
    _save_cookies,
    _wait_for_challenge_resolution,
)


class FakePage:
    def __init__(self, contents: list[str]):
        self._contents = contents
        self.timeout_calls: list[int] = []

    async def content(self):
        return self._contents[0] if self._contents else ""

    async def wait_for_timeout(self, value: int):
        self.timeout_calls.append(value)
        if len(self._contents) > 1:
            self._contents.pop(0)


@pytest.mark.asyncio
async def test_wait_for_challenge_resolution_resolves():
    initial = "<html><body>" + "<div></div>" * 80 + "</body></html>"
    resolved = "<html><body>" + ("content " * 80) + "</body></html>"
    page = FakePage([initial, resolved])

    ok, state, reasons = await _wait_for_challenge_resolution(page, max_wait_ms=2000, poll_interval_ms=250)

    assert ok
    assert state == "waiting_resolved"
    assert page.timeout_calls
    assert reasons == []


def test_context_kwargs_does_not_override_host_header():
    kwargs = _context_kwargs(prefer_stealth=False)

    assert kwargs["extra_http_headers"]["Accept-Language"] == "en-US,en;q=0.9"
    assert "Host" not in kwargs["extra_http_headers"]


class FakeCookieContext:
    def __init__(self, cookies: list[dict] | None = None):
        self._cookies = cookies or []
        self.added: list[dict] = []

    async def add_cookies(self, cookies: list[dict]):
        self.added.extend(cookies)

    async def cookies(self):
        return list(self._cookies)


class FakeGotoPage:
    def __init__(self, outcomes: list[dict]):
        self._outcomes = outcomes
        self.url = ""
        self.goto_calls: list[tuple[str, str, int]] = []
        self.wait_calls: list[int] = []

    async def goto(self, url: str, *, wait_until: str, timeout: int):
        self.goto_calls.append((url, wait_until, timeout))
        outcome = self._outcomes.pop(0)
        if "exception" in outcome:
            raise outcome["exception"]
        self.url = outcome.get("page_url", url)
        self._html = outcome.get("html", "")

    async def content(self):
        return getattr(self, "_html", "")

    async def wait_for_timeout(self, value: int):
        self.wait_calls.append(value)


@pytest.mark.asyncio
async def test_load_cookies_filters_sensitive_expired_and_session_cookies(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cookie_store_dir", tmp_path)
    cookie_path = tmp_path / "example.com.json"
    future = int(time.time()) + 3600
    past = int(time.time()) - 3600
    cookie_path.write_text(json.dumps([
        {"name": "cf_chl_rc_ni", "value": "5", "domain": "example.com", "path": "/", "expires": future},
        {"name": "consent_state", "value": "accepted", "domain": "example.com", "path": "/", "expires": future},
        {"name": "sessionid", "value": "abc", "domain": "example.com", "path": "/"},
        {"name": "old_pref", "value": "1", "domain": "example.com", "path": "/", "expires": past}
    ]), encoding="utf-8")
    context = FakeCookieContext()

    loaded = await _load_cookies(context, "example.com")

    assert loaded is True
    assert context.added == [
        {"name": "consent_state", "value": "accepted", "domain": "example.com", "path": "/", "expires": future}
    ]


@pytest.mark.asyncio
async def test_save_cookies_persists_only_allowed_domain_cookies(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cookie_store_dir", tmp_path)
    future = int(time.time()) + 1800
    context = FakeCookieContext(cookies=[
        {"name": "cf_clearance", "value": "secret", "domain": "example.com", "path": "/", "expires": future},
        {"name": "consent_state", "value": "accepted", "domain": "example.com", "path": "/", "expires": future},
        {"name": "sessionid", "value": "abc", "domain": "example.com", "path": "/"},
        {"name": "prefs", "value": "1", "domain": "cdn.example.com", "path": "/", "expires": future},
    ])

    await _save_cookies(context, "example.com")

    stored = json.loads((tmp_path / "example.com.json").read_text(encoding="utf-8"))
    assert stored == [
        {"name": "consent_state", "value": "accepted", "domain": "example.com", "path": "/", "expires": future}
    ]


@pytest.mark.asyncio
async def test_save_cookies_removes_stale_cookie_file_when_no_persistable_cookies(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cookie_store_dir", tmp_path)
    cookie_path = tmp_path / "example.com.json"
    cookie_path.write_text("[]", encoding="utf-8")
    context = FakeCookieContext(cookies=[
        {"name": "cf_clearance", "value": "secret", "domain": "example.com", "path": "/", "expires": int(time.time()) + 1800}
    ])

    await _save_cookies(context, "example.com")

    assert not cookie_path.exists()


def test_cookie_policy_domain_override_matches_subdomain():
    policy = _cookie_policy_for_domain("www.example.com")

    assert "consent_state" in policy["allowed_cookie_names"]


@pytest.mark.asyncio
async def test_retryable_browser_error_reason_detects_chrome_error_url():
    page = FakeGotoPage([{"page_url": "chrome-error://chromewebdata/", "html": "<html></html>"}])
    await page.goto("https://example.com", wait_until="load", timeout=1000)

    assert await _retryable_browser_error_reason(page) == "chrome_error_url"


@pytest.mark.asyncio
async def test_goto_with_fallback_retries_transient_browser_dns_error(monkeypatch):
    page = FakeGotoPage([
        {
            "page_url": "chrome-error://chromewebdata/",
            "html": "<html><body>ERR_NAME_NOT_RESOLVED</body></html>",
        },
        {
            "page_url": "https://example.com",
            "html": "<html><body>ok</body></html>",
        },
    ])
    monkeypatch.setattr("app.services.acquisition.browser_client.BROWSER_ERROR_RETRY_ATTEMPTS", 1)
    monkeypatch.setattr("app.services.acquisition.browser_client.BROWSER_ERROR_RETRY_DELAY_MS", 1)

    await _goto_with_fallback(page, "https://example.com")

    assert len(page.goto_calls) == 2
    assert page.wait_calls == [1]
