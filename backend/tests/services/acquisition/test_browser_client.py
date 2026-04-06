# Tests for Playwright browser acquisition hardening helpers.
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services.acquisition.browser_runtime import BrowserRuntimeOptions
from app.services.acquisition.browser_client import (
    _assess_challenge_signals,
    _build_launch_kwargs,
    _collect_frame_sources,
    _click_and_observe_next_page,
    _collect_paginated_html,
    _context_kwargs,
    _cookie_policy_for_domain,
    _fetch_rendered_html_with_fallback,
    _flatten_shadow_dom,
    _find_next_page_url,
    _goto_with_fallback,
    _load_cookies,
    _pause_after_navigation,
    _retryable_browser_error_reason,
    _save_cookies,
    _wait_for_challenge_resolution,
    _wait_for_listing_readiness,
    expand_all_interactive_elements,
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

    def locator(self, _selector: str):
        return FakeCountLocator(0)


class FakeCountLocator:
    def __init__(self, count: int):
        self._count = count

    @property
    def first(self):
        return self

    async def count(self):
        return self._count


class FakeSurfaceReadyPage(FakePage):
    def __init__(self, contents: list[str], readiness_counts: list[int]):
        super().__init__(contents)
        self._readiness_counts = readiness_counts

    def locator(self, _selector: str):
        count = self._readiness_counts[0] if self._readiness_counts else 0
        return FakeCountLocator(count)

    async def wait_for_timeout(self, value: int):
        self.timeout_calls.append(value)
        if len(self._contents) > 1:
            self._contents.pop(0)
        if len(self._readiness_counts) > 1:
            self._readiness_counts.pop(0)


class FakeBehavioralListingPage(FakePage):
    def __init__(self, metrics: list[dict[str, int]]):
        super().__init__(["<html><body>jobs</body></html>"] * max(1, len(metrics)))
        self._metrics = metrics

    async def evaluate(self, _script: str):
        return self._metrics[0] if self._metrics else {}

    async def wait_for_timeout(self, value: int):
        self.timeout_calls.append(value)
        if len(self._metrics) > 1:
            self._metrics.pop(0)


class FakeFrame:
    def __init__(self, url: str, html: str):
        self.url = url
        self._html = html

    async def content(self):
        return self._html


class FakeFramePage(FakePage):
    def __init__(self):
        super().__init__(["<html><body><main>Root</main></body></html>"])
        self.url = "https://example.com/careers"
        self.frames = [
            object(),
            FakeFrame("https://example.com/embed/jobs", "<section><a href='/jobs/1'>Role</a></section>"),
            FakeFrame("https://boards.greenhouse.io/embed/job_board?for=example", "<section><a href='/jobs/2'>Other Role</a></section>"),
        ]


@pytest.mark.asyncio
async def test_wait_for_challenge_resolution_resolves():
    initial = "<html><body> captcha verify you are human " + ("a " * 1500) + "</body></html>"
    resolved = "<html><body>" + ("content " * 80) + "</body></html>"
    page = FakePage([initial, resolved])

    ok, state, reasons = await _wait_for_challenge_resolution(page, max_wait_ms=2000, poll_interval_ms=250)

    assert ok
    assert state == "waiting_resolved"
    assert page.timeout_calls
    assert reasons == []


@pytest.mark.asyncio
async def test_wait_for_challenge_resolution_waits_for_surface_readiness_after_interstitial():
    initial = "<html><body>checking your browser just a moment</body></html>"
    resolved_shell = "<html><body><div>loading</div></body></html>"
    ready = "<html><body><h1>Product title</h1><span class='price'>$10</span>" + ("content " * 40) + "</body></html>"
    page = FakeSurfaceReadyPage([initial, resolved_shell, ready], readiness_counts=[0, 0, 1])
    original_detector = __import__(
        "app.services.acquisition.browser_client",
        fromlist=["detect_blocked_page"],
    ).detect_blocked_page
    provider_verdict = type("BlockedVerdict", (), {"is_blocked": True, "provider": "cloudflare"})()
    clear_verdict = type("BlockedVerdict", (), {"is_blocked": False, "provider": None})()

    try:
        __import__(
            "app.services.acquisition.browser_client",
            fromlist=["detect_blocked_page"],
        ).detect_blocked_page = (
            lambda html: provider_verdict if "checking your browser" in html.lower() else clear_verdict
        )

        ok, state, reasons = await _wait_for_challenge_resolution(
            page,
            max_wait_ms=1000,
            poll_interval_ms=250,
            surface="ecommerce_detail",
        )
    finally:
        __import__(
            "app.services.acquisition.browser_client",
            fromlist=["detect_blocked_page"],
        ).detect_blocked_page = original_detector

    assert ok
    assert state == "waiting_resolved"
    assert page.timeout_calls
    assert reasons == []


@pytest.mark.asyncio
async def test_wait_for_listing_readiness_accepts_behavioral_stability_without_selector_match(monkeypatch):
    page = FakeBehavioralListingPage([
        {"link_count": 3, "cardish_count": 4, "text_length": 600, "html_length": 1500, "loading": False},
        {"link_count": 3, "cardish_count": 4, "text_length": 600, "html_length": 1500, "loading": False},
    ])
    monkeypatch.setattr("app.services.acquisition.browser_client.CARD_SELECTORS_JOBS", ["[data-never-matches]"])
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_READINESS_POLL_MS", 10)
    monkeypatch.setattr("app.services.acquisition.browser_client.LISTING_READINESS_MAX_WAIT_MS", 250)

    readiness = await _wait_for_listing_readiness(page, "job_listing")

    assert readiness is not None
    assert readiness["ready"] is True
    assert readiness["reason"] in {"behavioral_stability", "behavioral_links"}


@pytest.mark.asyncio
async def test_collect_frame_sources_inlines_frame_html_and_tracks_promoted_sources():
    html, frame_sources, promoted_sources = await _collect_frame_sources(FakeFramePage())

    assert "FRAME START: https://example.com/embed/jobs" in html
    assert "FRAME START: https://boards.greenhouse.io/embed/job_board?for=example" not in html
    assert len(frame_sources) == 2
    assert promoted_sources == [
        {
            "kind": "iframe",
            "url": "https://boards.greenhouse.io/embed/job_board?for=example",
            "same_origin": False,
            "html_available": True,
        }
    ]


def test_assess_challenge_signals_waits_only_for_provider_signed_short_block(monkeypatch):
    provider_verdict = type("BlockedVerdict", (), {"is_blocked": True, "provider": "cloudflare"})()
    monkeypatch.setattr(
        "app.services.acquisition.browser_client.detect_blocked_page",
        lambda _html: provider_verdict,
    )

    assessment = _assess_challenge_signals("<html><body>temporarily blocked</body></html>")

    assert assessment.state == "waiting_unresolved"
    assert assessment.should_wait is True


def test_assess_challenge_signals_does_not_wait_for_short_unattributed_block(monkeypatch):
    generic_verdict = type("BlockedVerdict", (), {"is_blocked": True, "provider": None})()
    monkeypatch.setattr(
        "app.services.acquisition.browser_client.detect_blocked_page",
        lambda _html: generic_verdict,
    )

    assessment = _assess_challenge_signals("<html><body>blocked</body></html>")

    assert assessment.state == "blocked_signal"
    assert assessment.should_wait is False


def test_context_kwargs_uses_locale_instead_of_overriding_headers():
    kwargs = _context_kwargs(prefer_stealth=False)

    assert kwargs["locale"] == "en-US"
    assert kwargs["timezone_id"] == "UTC"
    assert "extra_http_headers" not in kwargs


def test_build_launch_kwargs_skips_host_pinning_for_system_chrome():
    target = type("Target", (), {
        "dns_resolved": True,
        "resolved_ips": ["203.0.113.10"],
        "hostname": "example.com",
    })()

    kwargs = _build_launch_kwargs(None, target, browser_channel="chrome")

    assert kwargs["channel"] == "chrome"
    assert "args" not in kwargs


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
        self.load_state_calls: list[tuple[str, int]] = []

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

    async def wait_for_load_state(self, state: str, *, timeout: int):
        self.load_state_calls.append((state, timeout))


class FakeLocator:
    def __init__(self, href: str = ""):
        self._href = href

    @property
    def first(self):
        return self

    async def count(self):
        return 1 if self._href else 0

    async def get_attribute(self, name: str):
        return self._href if name == "href" else None


class FakePaginationPage:
    def __init__(self):
        self.url = "https://example.com/products?page=1"
        self._pages = {
            "https://example.com/products?page=1": {
                "html": "<html><body><div>Page 1</div></body></html>",
                "next": "/products?page=2",
            },
            "https://example.com/products?page=2": {
                "html": "<html><body><div>Page 2</div></body></html>",
                "next": "/products?page=3",
            },
            "https://example.com/products?page=3": {
                "html": "<html><body><div>Page 3</div></body></html>",
                "next": "",
            },
        }
        self.goto_calls: list[str] = []
        self.dismissed = 0

    def locator(self, selector: str):
        if selector == "a[rel='next']":
            return FakeLocator(self._pages[self.url]["next"])
        return FakeLocator("")

    async def content(self):
        return self._pages[self.url]["html"]

    async def goto(self, url: str, *, wait_until: str, timeout: int):
        self.goto_calls.append(url)
        self.url = url

    async def evaluate(self, _script: str):
        return ""


class FakeClickableLocator:
    def __init__(self, page, *, exists: bool, click_callback=None, inner_html: str = ""):
        self._page = page
        self._exists = exists
        self._click_callback = click_callback
        self._inner_html = inner_html

    @property
    def first(self):
        return self

    async def count(self):
        return 1 if self._exists else 0

    async def click(self, timeout: int | None = None):
        self._page.click_calls.append(timeout or 0)
        if self._click_callback is not None:
            await self._click_callback()

    async def inner_html(self):
        return self._inner_html


class FakeClickObservePage:
    def __init__(self):
        self.url = "https://example.com/products?page=1"
        self.click_calls: list[int] = []
        self.load_state_calls: list[tuple[str, int]] = []
        self.wait_calls: list[int] = []
        self._container_html = "<div>before</div>"

    def locator(self, selector: str):
        if selector == "a[rel='next']":
            return FakeClickableLocator(self, exists=False)
        if selector == '[class*="product"], [class*="result"], ul.products, main':
            return FakeClickableLocator(self, exists=True, inner_html=self._container_html)
        if selector == '[aria-label*="next" i]':
            async def _after_click():
                self._container_html = "<div>after</div>"

            return FakeClickableLocator(self, exists=True, click_callback=_after_click)
        return FakeClickableLocator(self, exists=False)

    async def wait_for_load_state(self, state: str, *, timeout: int):
        self.load_state_calls.append((state, timeout))

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


@pytest.mark.asyncio
async def test_save_cookies_persists_explicitly_allowed_clearance_cookie(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cookie_store_dir", tmp_path)
    monkeypatch.setattr(
        "app.services.acquisition.cookie_store.COOKIE_POLICY",
        {
            "persist_session_cookies": False,
            "max_persisted_ttl_seconds": 2592000,
            "blocked_name_prefixes": ["cf_", "__cf"],
            "blocked_name_contains": ["challenge"],
            "allowed_cookie_names": ["cf_clearance"],
            "harvest_cookie_names": [],
            "harvest_name_prefixes": [],
            "harvest_name_contains": [],
            "reuse_in_http_client": True,
            "domain_overrides": {},
        },
    )
    future = int(time.time()) + 1800
    context = FakeCookieContext(cookies=[
        {"name": "cf_clearance", "value": "clearance-token", "domain": "example.com", "path": "/", "expires": future},
    ])

    await _save_cookies(context, "example.com")

    stored = json.loads((tmp_path / "example.com.json").read_text(encoding="utf-8"))
    assert stored == [
        {"name": "cf_clearance", "value": "clearance-token", "domain": "example.com", "path": "/", "expires": future}
    ]


def test_cookie_policy_domain_override_matches_subdomain():
    policy = _cookie_policy_for_domain("www.your-domain.com")

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


@pytest.mark.asyncio
async def test_goto_with_fallback_only_uses_load_for_optimistic_wait(monkeypatch):
    page = FakeGotoPage([
        {
            "page_url": "https://example.com",
            "html": "<html><body>ok</body></html>",
        }
    ])
    monkeypatch.setattr(
        "app.services.acquisition.browser_client.BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS",
        2500,
    )

    await _goto_with_fallback(
        page,
        "https://example.com",
        strategies=[
            ("networkidle", 30000),
            ("load", 15000),
            ("domcontentloaded", 15000),
        ],
    )

    assert page.load_state_calls == [("load", 2500)]


@pytest.mark.asyncio
async def test_pause_after_navigation_polls_checkpoint_during_long_wait(monkeypatch):
    checkpoint = AsyncMock()
    monkeypatch.setattr(
        "app.services.acquisition.browser_client.INTERRUPTIBLE_WAIT_POLL_MS",
        100,
    )

    await _pause_after_navigation(350, checkpoint=checkpoint)

    assert checkpoint.await_count >= 4


@pytest.mark.asyncio
async def test_expand_all_interactive_elements_honors_checkpoint(monkeypatch):
    checkpoint = AsyncMock()

    class FakeInteractivePage:
        async def evaluate(self, *_args, **_kwargs):
            return 3

    monkeypatch.setattr(
        "app.services.acquisition.browser_client.ACCORDION_EXPAND_WAIT_MS",
        125,
    )
    monkeypatch.setattr(
        "app.services.acquisition.browser_client.INTERRUPTIBLE_WAIT_POLL_MS",
        50,
    )

    summary = await expand_all_interactive_elements(FakeInteractivePage(), checkpoint=checkpoint)

    assert summary["expanded_count"] == 3
    assert checkpoint.await_count >= 3


@pytest.mark.asyncio
async def test_fetch_rendered_html_with_fallback_retries_system_chrome(monkeypatch):
    attempt_calls: list[tuple[str, list[tuple[str, int]] | None]] = []

    async def fake_attempt(*_args, launch_profile, navigation_strategies=None, **_kwargs):
        attempt_calls.append((str(launch_profile["label"]), navigation_strategies))
        if launch_profile["label"] == "bundled_chromium":
            raise RuntimeError("net::ERR_HTTP2_PROTOCOL_ERROR")
        return type("Result", (), {"diagnostics": {}})()

    monkeypatch.setattr(
        "app.services.acquisition.browser_client._fetch_rendered_html_attempt",
        fake_attempt,
    )

    result = await _fetch_rendered_html_with_fallback(
        object(),
        target=object(),
        url="https://example.com/product",
        proxy=None,
        traversal_mode=None,
        max_pages=1,
        max_scrolls=1,
        prefer_stealth=False,
        request_delay_ms=0,
        runtime_options=BrowserRuntimeOptions(anti_bot_enabled=True, retry_launch_profiles=True),
        requested_fields=[],
        requested_field_selectors={},
    )

    assert attempt_calls[0][0] == "bundled_chromium"
    assert attempt_calls[1] == (
        "system_chrome",
        [("domcontentloaded", 12000), ("commit", 8000)],
    )
    assert result.diagnostics["browser_launch_profile"] == "system_chrome"


@pytest.mark.asyncio
async def test_retryable_browser_error_reason_normalizes_curly_apostrophes():
    page = FakeGotoPage([
        {
            "page_url": "https://example.com",
            "html": "<html><body>This site can’t be reached</body></html>",
        },
    ])
    await page.goto("https://example.com", wait_until="load", timeout=1000)

    assert await _retryable_browser_error_reason(page) == "site_cannot_be_reached"


@pytest.mark.asyncio
async def test_find_next_page_url_uses_rel_next_href():
    page = FakePaginationPage()

    assert await _find_next_page_url(page) == "https://example.com/products?page=2"


@pytest.mark.asyncio
async def test_find_next_page_url_uses_configured_selectors(monkeypatch):
    class FakeCustomPage(FakePaginationPage):
        def locator(self, selector: str):
            if selector == "[data-next-page]":
                return FakeLocator("/products?page=2")
            return FakeLocator("")

    monkeypatch.setattr("app.services.acquisition.browser_client.PAGINATION_NEXT_SELECTORS", ["[data-next-page]"])
    page = FakeCustomPage()

    assert await _find_next_page_url(page) == "https://example.com/products?page=2"


@pytest.mark.asyncio
async def test_click_and_observe_next_page_waits_for_domcontentloaded_after_click():
    page = FakeClickObservePage()

    next_page_url = await _click_and_observe_next_page(page)

    assert next_page_url == "https://example.com/products?page=1"
    assert page.load_state_calls == [("domcontentloaded", 5000)]
    assert page.click_calls == [1500]


@pytest.mark.asyncio
async def test_collect_paginated_html_stops_at_max_pages(monkeypatch):
    page = FakePaginationPage()
    monkeypatch.setattr("app.services.acquisition.browser_client._dismiss_cookie_consent", AsyncMock())
    monkeypatch.setattr("app.services.acquisition.browser_client._pause_after_navigation", AsyncMock())

    html = await _collect_paginated_html(page, max_pages=2, request_delay_ms=0)

    assert "Page 1" in html
    assert "Page 2" in html
    assert "Page 3" not in html
    assert page.goto_calls == ["https://example.com/products?page=2"]


@pytest.mark.asyncio
async def test_collect_paginated_html_rejects_non_public_next_page(monkeypatch, caplog):
    page = FakePaginationPage()
    monkeypatch.setattr("app.services.acquisition.browser_client._dismiss_cookie_consent", AsyncMock())
    monkeypatch.setattr("app.services.acquisition.browser_client._pause_after_navigation", AsyncMock())

    async def _reject_target(_url: str):
        raise ValueError("Target host resolves to a non-public IP address")

    monkeypatch.setattr("app.services.acquisition.browser_client.validate_public_target", _reject_target)

    with caplog.at_level("WARNING"):
        html = await _collect_paginated_html(page, max_pages=3, request_delay_ms=0)

    assert "Page 1" in html
    assert "Page 2" not in html
    assert page.goto_calls == []
    assert "Rejected pagination URL" in caplog.text


@pytest.mark.asyncio
async def test_collect_paginated_html_allows_in_place_pagination_without_goto(monkeypatch):
    page = FakePaginationPage()
    page._pages = {
        "https://example.com/products?page=1": {
            "html": "<html><body><div>Page 1</div></body></html>",
            "next": "",
        }
    }
    in_place_urls = ["https://example.com/products?page=1", "https://example.com/products?page=1", ""]
    page_state = {"index": 0}

    async def _fake_click_and_observe_next_page(_page, checkpoint=None):
        _ = checkpoint
        if in_place_urls:
            next_url = in_place_urls.pop(0)
            if next_url:
                page_state["index"] += 1
            return next_url
        return ""

    async def _fake_content():
        return f"<html><body><div>Page {page_state['index'] + 1}</div></body></html>"

    page.content = _fake_content
    monkeypatch.setattr("app.services.acquisition.browser_client._click_and_observe_next_page", _fake_click_and_observe_next_page)
    monkeypatch.setattr("app.services.acquisition.browser_client._dismiss_cookie_consent", AsyncMock())
    monkeypatch.setattr("app.services.acquisition.browser_client._pause_after_navigation", AsyncMock())
    monkeypatch.setattr("app.services.acquisition.browser_client.expand_all_interactive_elements", AsyncMock())

    html = await _collect_paginated_html(page, max_pages=3, request_delay_ms=0)

    assert "Page 1" in html
    assert "Page 2" in html
    assert page.goto_calls == []


@pytest.mark.asyncio
async def test_flatten_shadow_dom_passes_configured_max_hosts(monkeypatch):
    class FakeShadowPage:
        def __init__(self):
            self.calls: list[tuple[str, int]] = []

        async def evaluate(self, script: str, max_hosts: int):
            self.calls.append((script, max_hosts))
            return 3

    page = FakeShadowPage()
    monkeypatch.setattr("app.services.acquisition.browser_client.SHADOW_DOM_FLATTEN_MAX_HOSTS", 12)

    await _flatten_shadow_dom(page)

    assert page.calls
    assert page.calls[0][1] == 12
