# Tests for Playwright browser acquisition hardening helpers.
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest
from app.core.config import settings
from app.services._batch_runtime import _merge_run_acquisition_metrics
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.acquisition.browser_client import (
    _assess_challenge_signals,
    _browser_launch_profiles,
    _build_launch_kwargs,
    _click_and_observe_next_page,
    _click_load_more,
    _collect_frame_sources,
    _collect_paginated_html,
    _context_kwargs,
    _cookie_policy_for_domain,
    _fetch_rendered_html_with_fallback,
    _find_next_page_url,
    _flatten_shadow_dom,
    _goto_with_fallback,
    _is_public_browser_request_target,
    _load_cookies,
    _pause_after_navigation,
    _retryable_browser_error_reason,
    _save_cookies,
    _scroll_to_bottom,
    _wait_for_challenge_resolution,
    _wait_for_listing_readiness,
    expand_all_interactive_elements,
)
from app.services.acquisition.browser_runtime import BrowserRuntimeOptions
from app.services.acquisition.cookie_store import validate_cookie_policy_config
from app.services.acquisition.traversal import AdvanceResult, TraversalResult, apply_traversal_mode
from app.services.crawl_metrics import build_url_metrics


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


@pytest.mark.asyncio
async def test_is_public_browser_request_target_allows_non_http_scheme():
    allowed, reason = await _is_public_browser_request_target("data:text/plain,ok")
    assert allowed is True
    assert reason == "non_http_scheme:allowed_data"


@pytest.mark.asyncio
async def test_is_public_browser_request_target_rejects_private_http_target():
    allowed, reason = await _is_public_browser_request_target("http://127.0.0.1/internal")
    assert allowed is False
    assert reason.startswith("non_public_target:")


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
    assert kwargs["ignore_https_errors"] is False
    assert "bypass_csp" not in kwargs
    assert "extra_http_headers" not in kwargs


def test_context_kwargs_only_relaxes_security_when_explicitly_enabled():
    kwargs = _context_kwargs(
        prefer_stealth=False,
        runtime_options=BrowserRuntimeOptions(ignore_https_errors=True, bypass_csp=True),
    )

    assert kwargs["ignore_https_errors"] is True
    assert kwargs["bypass_csp"] is True


def test_build_launch_kwargs_skips_host_pinning_for_system_chrome():
    target = type("Target", (), {
        "dns_resolved": True,
        "resolved_ips": ["203.0.113.10"],
        "hostname": "example.com",
    })()

    kwargs = _build_launch_kwargs(None, target, browser_channel="chrome")

    assert kwargs["channel"] == "chrome"
    assert "args" not in kwargs


def test_build_launch_kwargs_pins_dns_with_http2_disabled():
    """DNS pinning must be active for bundled Chromium to prevent TOCTOU SSRF."""
    target = type("Target", (), {
        "dns_resolved": True,
        "resolved_ips": ["203.0.113.10"],
        "hostname": "example.com",
    })()

    kwargs = _build_launch_kwargs(None, target)

    assert "args" in kwargs
    args = kwargs["args"]
    assert any("--host-resolver-rules=" in a for a in args)
    assert any("MAP example.com 203.0.113.10" in a for a in args)
    assert "--disable-http2" in args


def test_browser_launch_profiles_uses_bundled_chromium_when_dns_pinning_is_required():
    target = type("Target", (), {
        "dns_resolved": True,
        "resolved_ips": ["203.0.113.10"],
    })()

    profiles = _browser_launch_profiles(BrowserRuntimeOptions(), target=target)

    assert profiles == [
        {"label": "bundled_chromium", "browser_type": "chromium", "channel": None}
    ]


@pytest.mark.asyncio
async def test_browser_acquisition_rejects_loopback_hostname(monkeypatch):
    """A hostname that resolves to 127.0.0.1 must be rejected by the browser
    acquisition layer's validate_public_target gate. This guards against DNS
    rebinding SSRF: the pinned IP would be loopback, so the validation must
    reject before Playwright ever launches."""
    import app.services.url_safety as url_safety_mod

    async def _fake_resolve(hostname, port):
        return ["127.0.0.1"]

    monkeypatch.setattr(url_safety_mod, "_resolve_host_ips", _fake_resolve)

    with pytest.raises(ValueError, match="non-public"):
        await url_safety_mod.validate_public_target("http://rebind-target.example.com/")


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

    async def evaluate(self, _script: str, *_args):
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
        exists = self._exists() if callable(self._exists) else self._exists
        return 1 if exists else 0

    async def is_visible(self):
        return self._exists() if callable(self._exists) else self._exists

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

    async def evaluate(self, _script: str, *_args):
        return ""


class FakeScrollPage:
    def __init__(self, heights: list[int], metrics: list[dict[str, int]]):
        self._heights = heights
        self._metrics = metrics
        self.scroll_calls: list[int] = []
        self.wait_calls: list[int] = []

    async def evaluate(self, script: str, *args):
        if "scrollHeight" in script:
            if "window.scrollTo" in script:
                self.scroll_calls.append(int(args[0] or 0))
                if len(self._heights) > 1:
                    self._heights.pop(0)
                if len(self._metrics) > 1:
                    self._metrics.pop(0)
                return None
            return self._heights[0]
        return self._metrics[0] if self._metrics else {}

    async def wait_for_timeout(self, value: int):
        self.wait_calls.append(value)


class FakeLoadMorePage:
    def __init__(self, metrics: list[dict[str, int]], *, hide_after_click: bool = False):
        self._metrics = metrics
        self._visible = True
        self._hide_after_click = hide_after_click
        self.click_calls: list[int] = []
        self.wait_calls: list[int] = []

    def locator(self, selector: str):
        if selector == "[data-load-more]":
            async def _after_click():
                if len(self._metrics) > 1:
                    self._metrics.pop(0)
                if self._hide_after_click:
                    self._visible = False

            return FakeClickableLocator(self, exists=lambda: self._visible, click_callback=_after_click)
        return FakeClickableLocator(self, exists=False)

    async def evaluate(self, _script: str, *_args):
        return self._metrics[0] if self._metrics else {}

    async def wait_for_timeout(self, value: int):
        self.wait_calls.append(value)


class FakeAutoTraversalPage:
    def __init__(self):
        self.url = "https://example.com/products?page=1"


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


def test_cookie_policy_domain_override_matches_subdomain(monkeypatch):
    monkeypatch.setattr(
        "app.services.acquisition.cookie_store.COOKIE_POLICY",
        {
            "persist_session_cookies": False,
            "max_persisted_ttl_seconds": 2592000,
            "blocked_name_prefixes": [],
            "blocked_name_contains": [],
            "harvest_cookie_names": [],
            "domain_overrides": {
                "example.org": {
                    "allowed_cookie_names": ["consent_state"],
                    "harvest_cookie_names": [],
                }
            },
        },
    )

    policy = _cookie_policy_for_domain("www.example.org")

    assert "consent_state" in policy["allowed_cookie_names"]


def test_validate_cookie_policy_config_rejects_placeholder_override():
    with pytest.raises(ValueError, match="placeholder domain"):
        validate_cookie_policy_config(
            {
                "domain_overrides": {
                    "your-domain.com": {
                        "allowed_cookie_names": ["consent_state"],
                    }
                }
            }
        )


def test_validate_cookie_policy_config_rejects_malformed_override():
    with pytest.raises(ValueError, match="malformed domain"):
        validate_cookie_policy_config(
            {
                "domain_overrides": {
                    "https://example.com/path": {
                        "allowed_cookie_names": ["consent_state"],
                    }
                }
            }
        )


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
        if launch_profile["label"] == "system_chrome":
            raise RuntimeError("browser_navigation_error:dns_name_not_resolved")
        return type("Result", (), {"html": "<html></html>", "diagnostics": {}})()

    monkeypatch.setattr(
        "app.services.acquisition.browser_client._fetch_rendered_html_attempt",
        fake_attempt,
    )

    result = await _fetch_rendered_html_with_fallback(
        object(),
        target=type("Target", (), {"dns_resolved": False, "resolved_ips": []})(),
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

    assert attempt_calls[0][0] == "system_chrome"
    assert attempt_calls[1] == (
        "bundled_chromium",
        [("domcontentloaded", 12000), ("commit", 8000)],
    )
    assert result.diagnostics["browser_launch_profile"] == "bundled_chromium"


@pytest.mark.asyncio
async def test_fetch_rendered_html_with_fallback_keeps_default_navigation_after_generic_profile_error(monkeypatch):
    attempt_calls: list[tuple[str, list[tuple[str, int]] | None]] = []

    async def fake_attempt(*_args, launch_profile, navigation_strategies=None, **_kwargs):
        attempt_calls.append((str(launch_profile["label"]), navigation_strategies))
        if launch_profile["label"] == "system_chrome":
            raise RuntimeError("net::ERR_HTTP2_PROTOCOL_ERROR")
        return type("Result", (), {"html": "<html></html>", "diagnostics": {}})()

    monkeypatch.setattr(
        "app.services.acquisition.browser_client._fetch_rendered_html_attempt",
        fake_attempt,
    )

    await _fetch_rendered_html_with_fallback(
        object(),
        target=type("Target", (), {"dns_resolved": False, "resolved_ips": []})(),
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

    assert attempt_calls[0][0] == "system_chrome"
    assert attempt_calls[1] == ("bundled_chromium", [("load", 15000), ("domcontentloaded", 15000)])


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

    result = await _collect_paginated_html(page, max_pages=2, request_delay_ms=0)

    assert "Page 1" in result.html
    assert "Page 2" in result.html
    assert "Page 3" not in result.html
    assert page.goto_calls == ["https://example.com/products?page=2"]
    assert result.summary["pages_collected"] == 2


@pytest.mark.asyncio
async def test_paginate_run_summary(monkeypatch):
    page = FakePaginationPage()
    monkeypatch.setattr("app.services.acquisition.browser_client._dismiss_cookie_consent", AsyncMock())
    monkeypatch.setattr("app.services.acquisition.browser_client._pause_after_navigation", AsyncMock())

    traversal_result = await _collect_paginated_html(page, max_pages=2, request_delay_ms=0)
    assert traversal_result.summary["pages_collected"] == 2
    assert "page_count" not in traversal_result.summary

    acq = AcquisitionResult(
        method="playwright",
        diagnostics={"traversal_summary": traversal_result.summary},
    )
    url_metrics = build_url_metrics(acq, requested_fields=[])
    run_summary = _merge_run_acquisition_metrics({}, url_metrics)
    result = {
        "pages_collected": traversal_result.summary["pages_collected"],
        "traversal_succeeded": run_summary["traversal_succeeded"],
    }

    assert result["pages_collected"] == 2
    assert result["traversal_succeeded"] == 1


@pytest.mark.asyncio
async def test_collect_paginated_html_rejects_non_public_next_page(monkeypatch, caplog):
    page = FakePaginationPage()
    monkeypatch.setattr("app.services.acquisition.browser_client._dismiss_cookie_consent", AsyncMock())
    monkeypatch.setattr("app.services.acquisition.browser_client._pause_after_navigation", AsyncMock())

    async def _reject_target(_url: str):
        raise ValueError("Target host resolves to a non-public IP address")

    monkeypatch.setattr("app.services.acquisition.browser_client.validate_public_target", _reject_target)

    with caplog.at_level("WARNING"):
        result = await _collect_paginated_html(page, max_pages=3, request_delay_ms=0)

    assert "Page 1" in result.html
    assert "Page 2" not in result.html
    assert page.goto_calls == []
    assert "Rejected pagination URL" in caplog.text
    assert result.summary["stop_reason"] == "rejected_next_page"


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

    async def _fake_advance_next_page(_page, checkpoint=None):
        _ = checkpoint
        if in_place_urls:
            next_url = in_place_urls.pop(0)
            if next_url:
                page_state["index"] += 1
            return AdvanceResult(url=next_url, already_navigated=False)
        return AdvanceResult(url="", already_navigated=False)

    async def _fake_content():
        return f"<html><body><div>Page {page_state['index'] + 1}</div></body></html>"

    page.content = _fake_content
    monkeypatch.setattr("app.services.acquisition.browser_client._advance_next_page", _fake_advance_next_page)
    monkeypatch.setattr("app.services.acquisition.browser_client._dismiss_cookie_consent", AsyncMock())
    monkeypatch.setattr("app.services.acquisition.browser_client._pause_after_navigation", AsyncMock())
    monkeypatch.setattr("app.services.acquisition.browser_client.expand_all_interactive_elements", AsyncMock())

    result = await _collect_paginated_html(page, max_pages=3, request_delay_ms=0)

    assert "Page 1" in result.html
    assert "Page 2" in result.html
    assert page.goto_calls == []
    assert result.summary["pages_collected"] >= 2


@pytest.mark.asyncio
async def test_scroll_to_bottom_stops_when_listing_progress_stalls(monkeypatch):
    page = FakeScrollPage(
        heights=[1000, 1200, 1200],
        metrics=[
            {"link_count": 10, "cardish_count": 12, "text_length": 800, "html_length": 1600},
            {"link_count": 14, "cardish_count": 16, "text_length": 1000, "html_length": 2200},
            {"link_count": 14, "cardish_count": 16, "text_length": 1000, "html_length": 2200},
        ],
    )
    monkeypatch.setattr("app.services.acquisition.browser_client.SCROLL_WAIT_MIN_MS", 1)

    summary = await _scroll_to_bottom(page, 5, request_delay_ms=0)

    assert summary["mode"] == "scroll"
    assert summary["attempt_count"] >= 1
    assert summary["stop_reason"] in {"no_progress_before_scroll", "no_progress_after_scroll", "height_only_progress_exhausted", "max_scrolls_reached"}
    assert "progressed" in summary["steps"][0]


@pytest.mark.asyncio
async def test_scroll_to_bottom_treats_identity_growth_as_progress(monkeypatch):
    page = FakeScrollPage(
        heights=[1000, 1200, 1200],
        metrics=[
            {"link_count": 10, "cardish_count": 12, "text_length": 800, "html_length": 1600, "identity_count": 2, "identities": ["job-1", "job-2"], "dom_signature": "a"},
            {"link_count": 10, "cardish_count": 12, "text_length": 800, "html_length": 1600, "identity_count": 2, "identities": ["job-3", "job-4"], "dom_signature": "b"},
            {"link_count": 10, "cardish_count": 12, "text_length": 800, "html_length": 1600, "identity_count": 2, "identities": ["job-3", "job-4"], "dom_signature": "b"},
        ],
    )
    monkeypatch.setattr("app.services.acquisition.browser_client.SCROLL_WAIT_MIN_MS", 1)

    summary = await _scroll_to_bottom(page, 5, request_delay_ms=0)

    assert summary["steps"][0]["identity_growth"] == 2
    assert summary["steps"][0]["progressed"] is True


@pytest.mark.asyncio
async def test_click_load_more_stops_when_click_adds_no_new_listing_progress(monkeypatch):
    page = FakeLoadMorePage([
        {"link_count": 10, "cardish_count": 12, "text_length": 800, "html_length": 1600},
        {"link_count": 10, "cardish_count": 12, "text_length": 800, "html_length": 1600},
    ])
    monkeypatch.setattr("app.services.acquisition.browser_client.LOAD_MORE_SELECTORS", ["[data-load-more]"])
    monkeypatch.setattr("app.services.acquisition.browser_client.LOAD_MORE_WAIT_MIN_MS", 1)

    summary = await _click_load_more(page, 3, request_delay_ms=0)

    assert summary["mode"] == "load_more"
    assert summary["attempt_count"] == 1
    assert summary["stop_reason"] == "no_progress_after_click"
    assert summary["steps"][0]["progressed"] is False


@pytest.mark.asyncio
async def test_click_load_more_accepts_replacement_when_button_disappears(monkeypatch):
    page = FakeLoadMorePage(
        [
            {"link_count": 10, "cardish_count": 12, "text_length": 800, "html_length": 1600, "identity_count": 2, "identities": ["item-1", "item-2"], "dom_signature": "before"},
            {"link_count": 10, "cardish_count": 12, "text_length": 800, "html_length": 1600, "identity_count": 2, "identities": ["item-3", "item-4"], "dom_signature": "after"},
        ],
        hide_after_click=True,
    )
    monkeypatch.setattr("app.services.acquisition.browser_client.LOAD_MORE_SELECTORS", ["[data-load-more]"])
    monkeypatch.setattr("app.services.acquisition.browser_client.LOAD_MORE_WAIT_MIN_MS", 1)

    summary = await _click_load_more(page, 3, request_delay_ms=0)

    assert summary["steps"][0]["progressed"] is True
    assert summary["steps"][0]["button_disappeared"] is True
    assert summary["stop_reason"] in {"no_load_more_control", "max_clicks_reached"}


@pytest.mark.asyncio
async def test_apply_traversal_mode_auto_combines_scroll_and_paginate_steps(monkeypatch):
    monkeypatch.setattr(
        "app.services.acquisition.traversal.scroll_to_bottom",
        AsyncMock(return_value={"mode": "scroll", "stop_reason": "max_scrolls_reached"}),
    )
    monkeypatch.setattr(
        "app.services.acquisition.traversal.click_load_more",
        AsyncMock(return_value={"mode": "load_more", "stop_reason": "no_load_more_control"}),
    )
    monkeypatch.setattr(
        "app.services.acquisition.traversal.collect_paginated_html",
        AsyncMock(return_value=TraversalResult(
        html="<!-- PAGE BREAK:1:https://example.com/products?page=1 -->",
        summary={"mode": "paginate", "steps": [{"action": "capture_page"}], "stop_reason": "no_next_page"},
    )),
    )

    result = await apply_traversal_mode(
        FakeAutoTraversalPage(),
        "ecommerce_listing",
        "auto",
        5,
        max_pages=3,
        request_delay_ms=0,
        page_content_with_retry=AsyncMock(),
        wait_for_surface_readiness=AsyncMock(),
        wait_for_listing_readiness=AsyncMock(),
        peek_next_page_signal=AsyncMock(return_value={"kind": "click", "selector": "button.next"}),
        click_and_observe_next_page=AsyncMock(return_value="https://example.com/products?page=2"),
        has_load_more_control=AsyncMock(return_value=False),
        dismiss_cookie_consent=AsyncMock(),
        pause_after_navigation=AsyncMock(),
        expand_all_interactive_elements=AsyncMock(return_value={}),
        flatten_shadow_dom=AsyncMock(),
        cooperative_sleep_ms=AsyncMock(),
        snapshot_listing_page_metrics=AsyncMock(),
    )

    assert result.summary["mode"] == "paginate"
    assert result.summary["steps"][0]["mode"] == "scroll"
    assert result.summary["steps"][1]["action"] == "capture_page"


@pytest.mark.asyncio
async def test_apply_traversal_mode_auto_stops_without_pagination_when_no_next_page(monkeypatch):
    monkeypatch.setattr(
        "app.services.acquisition.traversal.scroll_to_bottom",
        AsyncMock(return_value={"mode": "scroll", "stop_reason": "max_scrolls_reached"}),
    )
    monkeypatch.setattr(
        "app.services.acquisition.traversal.click_load_more",
        AsyncMock(return_value={"mode": "load_more", "stop_reason": "no_progress_after_click"}),
    )
    monkeypatch.setattr(
        "app.services.acquisition.traversal.collect_paginated_html",
        AsyncMock(return_value=TraversalResult()),
    )

    result = await apply_traversal_mode(
        FakeAutoTraversalPage(),
        "ecommerce_listing",
        "auto",
        5,
        max_pages=3,
        request_delay_ms=0,
        page_content_with_retry=AsyncMock(),
        wait_for_surface_readiness=AsyncMock(),
        wait_for_listing_readiness=AsyncMock(),
        peek_next_page_signal=AsyncMock(return_value=None),
        click_and_observe_next_page=AsyncMock(return_value=""),
        has_load_more_control=AsyncMock(return_value=True),
        dismiss_cookie_consent=AsyncMock(),
        pause_after_navigation=AsyncMock(),
        expand_all_interactive_elements=AsyncMock(return_value={}),
        flatten_shadow_dom=AsyncMock(),
        cooperative_sleep_ms=AsyncMock(),
        snapshot_listing_page_metrics=AsyncMock(),
    )

    assert result.summary["mode"] == "auto"
    assert result.summary["stop_reason"] == "no_pagination_after_scroll_or_load_more"
    assert len(result.summary["steps"]) == 2


def test_resolve_traversal_mode_prefers_traversal_mode():
    from app.services._batch_runtime import _resolve_traversal_mode

    assert _resolve_traversal_mode({"traversal_mode": "auto"}) is None
    assert (
        _resolve_traversal_mode(
            {"advanced_enabled": True, "advanced_mode": "paginate"}
        )
        == "paginate"
    )


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
