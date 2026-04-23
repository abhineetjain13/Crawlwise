from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import crawl_fetch_runtime
from app.services.acquisition import browser_identity
from app.services.acquisition import cookie_store
from app.services.acquisition import browser_runtime as acquisition_browser_runtime


def test_build_playwright_context_options_uses_generated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1440, height=900, devicePixelRatio=2),
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            language="en-US",
            maxTouchPoints=0,
            userAgentData={
                "brands": [{"brand": "Google Chrome", "version": "145"}],
                "mobile": False,
            },
        ),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html",
            "Accept-Language": "en-US;q=1.0",
            "sec-ch-ua": '"Google Chrome";v="145"',
            "Accept-Encoding": "gzip, br",
            "Sec-Fetch-Mode": "navigate",
        },
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )

    options = browser_identity.build_playwright_context_options()

    assert options["user_agent"].endswith("Chrome/145.0.0.0 Safari/537.36")
    assert options["viewport"] == {"width": 1440, "height": 900}
    assert options["locale"] == "en-US"
    assert options["device_scale_factor"] == 2.0
    assert options["has_touch"] is False
    assert options["is_mobile"] is False
    assert options["extra_http_headers"] == {
        "Accept": "text/html",
        "Accept-Language": "en-US;q=1.0",
        "sec-ch-ua": (
            '"Not.A/Brand";v="24", "Chromium";v="145", "Google Chrome";v="145"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }


def test_build_playwright_context_options_keeps_security_invariants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1280, height=720, devicePixelRatio=1),
        navigator=SimpleNamespace(
            userAgent="Mozilla/5.0 MobileTest/145.0",
            language="en-US",
            maxTouchPoints=5,
            userAgentData={"mobile": True},
        ),
        headers={"User-Agent": "Mozilla/5.0 MobileTest/145.0"},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )

    options = browser_identity.build_playwright_context_options()

    assert options["service_workers"] == "block"
    assert options["bypass_csp"] is False
    assert options["has_touch"] is True
    assert options["is_mobile"] is True


def test_build_playwright_context_options_repairs_incoherent_client_hints_after_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1366, height=768, devicePixelRatio=1),
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            language="en-US",
            maxTouchPoints=0,
            userAgentData={
                "brands": [{"brand": "Brave", "version": "130"}],
                "mobile": False,
                "platform": "Windows",
                "uaFullVersion": "130.0.0.0",
            },
        ),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html",
            "sec-ch-ua": '"Brave";v="130"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    )
    attempts = {"count": 0}

    def _generate():
        attempts["count"] += 1
        return bad_fingerprint

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=_generate),
    )

    options = browser_identity.build_playwright_context_options()

    assert attempts["count"] == 3
    assert options["user_agent"].endswith("Chrome/145.0.0.0 Safari/537.36")
    assert options["extra_http_headers"]["sec-ch-ua"] == (
        '"Not.A/Brand";v="24", "Chromium";v="145", "Google Chrome";v="145"'
    )
    assert options["extra_http_headers"]["sec-ch-ua-mobile"] == "?0"
    assert options["extra_http_headers"]["sec-ch-ua-platform"] == '"Windows"'


def test_build_playwright_context_options_replaces_malformed_client_hints_without_rejecting_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1366, height=768, devicePixelRatio=1),
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            language="en-US",
            maxTouchPoints=0,
            userAgentData={
                "brands": [{"brand": "Google Chrome", "version": "145"}],
                "mobile": False,
                "platform": "Windows",
                "uaFullVersion": "145.0.0.0",
            },
        ),
        headers={
            "Accept": "text/html",
            "Accept-Language": "en-US;q=1.0",
            "sec-ch-ua": '"Google Chrome";v="145", "Chromium";v="145", "Not(A:Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )

    options = browser_identity.build_playwright_context_options()

    assert options["extra_http_headers"]["Accept-Language"] == "en-US;q=1.0"
    assert options["extra_http_headers"]["sec-ch-ua"] == (
        '"Not.A/Brand";v="24", "Chromium";v="145", "Google Chrome";v="145"'
    )
    assert options["extra_http_headers"]["sec-ch-ua-mobile"] == "?0"
    assert options["extra_http_headers"]["sec-ch-ua-platform"] == '"Windows"'


def test_fingerprint_generator_rebuilds_when_runtime_settings_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = []

    class _FakeGenerator:
        def __init__(self, *, browser, os, device, locale) -> None:
            del os
            constructed.append((tuple(browser), tuple(device), tuple(locale)))

        def generate(self):
            return SimpleNamespace(
                screen=SimpleNamespace(width=1280, height=720, devicePixelRatio=1),
                navigator=SimpleNamespace(
                    userAgent="Mozilla/5.0 Chrome/145.0.0.0",
                    language="en-US",
                    maxTouchPoints=0,
                    userAgentData={"brands": [], "mobile": False},
                ),
                headers={"Accept": "text/html"},
            )

    monkeypatch.setattr(browser_identity, "FingerprintGenerator", _FakeGenerator)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR", None)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR_CONFIG", None)
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_browser",
        ["chrome"],
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_device",
        ["desktop"],
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_locale",
        ["en-US"],
    )

    browser_identity._fingerprint_generator()
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_browser",
        ["firefox"],
    )
    browser_identity._fingerprint_generator()

    assert constructed == [
        (("chrome",), ("desktop",), ("en-US",)),
        (("firefox",), ("desktop",), ("en-US",)),
    ]


def test_fingerprint_generator_normalizes_default_string_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = []

    class _FakeGenerator:
        def __init__(self, *, browser, os, device, locale) -> None:
            del os
            constructed.append((tuple(browser), tuple(device), tuple(locale)))

        def generate(self):
            return SimpleNamespace(
                screen=SimpleNamespace(width=1280, height=720, devicePixelRatio=1),
                navigator=SimpleNamespace(
                    userAgent="Mozilla/5.0 Chrome/145.0.0.0",
                    language="en-US",
                    maxTouchPoints=0,
                    userAgentData={"brands": [], "mobile": False},
                ),
                headers={"Accept": "text/html"},
            )

    monkeypatch.setattr(browser_identity, "FingerprintGenerator", _FakeGenerator)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR", None)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR_CONFIG", None)
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_browser",
        "chrome",
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_device",
        "desktop",
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_locale",
        "en-US",
    )

    browser_identity._fingerprint_generator()

    assert constructed == [(("chrome",), ("desktop",), ("en-US",))]


def test_fingerprint_generator_ignores_mapping_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = []

    class _FakeGenerator:
        def __init__(self, *, browser, os, device, locale) -> None:
            del os
            constructed.append((tuple(browser), tuple(device), tuple(locale)))

        def generate(self):
            return SimpleNamespace(
                screen=SimpleNamespace(width=1280, height=720, devicePixelRatio=1),
                navigator=SimpleNamespace(
                    userAgent="Mozilla/5.0 Chrome/145.0.0.0",
                    language="en-US",
                    maxTouchPoints=0,
                    userAgentData={"brands": [], "mobile": False},
                ),
                headers={"Accept": "text/html"},
            )

    monkeypatch.setattr(browser_identity, "FingerprintGenerator", _FakeGenerator)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR", None)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR_CONFIG", None)
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_browser",
        {"chrome": True},
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_device",
        {"desktop": True},
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_locale",
        {"en-US": True},
    )

    browser_identity._fingerprint_generator()

    assert constructed == [((), (), ())]


def test_coherent_sec_ch_headers_accepts_tuple_brand_entries() -> None:
    headers = browser_identity._coherent_sec_ch_headers(
        {
            "brands": (
                {"brand": "Chromium", "version": "145"},
                {"brand": "Google Chrome", "version": "145"},
            ),
            "mobile": False,
            "platform": "Windows",
        }
    )

    assert headers["sec-ch-ua"] == (
        '"Chromium";v="145", "Google Chrome";v="145"'
    )
    assert headers["sec-ch-ua-mobile"] == "?0"
    assert headers["sec-ch-ua-platform"] == '"Windows"'


@pytest.mark.asyncio
async def test_load_storage_state_for_run_ignores_invalid_run_id() -> None:
    assert await cookie_store.load_storage_state_for_run("invalid") is None


@pytest.mark.asyncio
async def test_persist_storage_state_for_run_replaces_existing_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()

    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "stale",
                    "value": "1",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [{"name": "old", "value": "1"}],
                }
            ],
        },
    )
    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "fresh",
                    "value": "2",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [{"name": "new", "value": "2"}],
                }
            ],
        },
    )

    assert await cookie_store.load_storage_state_for_run(77) == {
        "cookies": [
            {
                "name": "fresh",
                "value": "2",
                "domain": ".example.com",
                "path": "/",
            }
        ],
        "origins": [
            {
                "origin": "https://example.com",
                "localStorage": [{"name": "new", "value": "2"}],
            }
        ],
    }


@pytest.mark.asyncio
async def test_shared_browser_runtime_passes_generated_context_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []
    created_pages: list[object] = []
    routed_patterns: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del handler
            routed_patterns.append(pattern)

        async def new_page(self):
            page = object()
            created_pages.append(page)
            return page

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_options",
        lambda **_: {
            "user_agent": "Mozilla/5.0 Runtime/145.0",
            "viewport": {"width": 1600, "height": 900},
            "extra_http_headers": {"Accept": "text/html"},
            "locale": "en-US",
            "device_scale_factor": 1.0,
            "has_touch": False,
            "is_mobile": False,
            "service_workers": "block",
            "bypass_csp": False,
        },
    )

    async with runtime.page() as page:
        assert page in created_pages

    assert captured_kwargs == [
        {
            "user_agent": "Mozilla/5.0 Runtime/145.0",
            "viewport": {"width": 1600, "height": 900},
            "extra_http_headers": {"Accept": "text/html"},
            "locale": "en-US",
            "device_scale_factor": 1.0,
            "has_touch": False,
            "is_mobile": False,
            "service_workers": "block",
            "bypass_csp": False,
        }
    ]
    assert routed_patterns == ["**/*"]


@pytest.mark.asyncio
async def test_shared_browser_runtime_reuses_run_storage_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []
    persisted_states: list[tuple[int, dict[str, object]]] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            return {
                "cookies": [
                    {
                        "name": "dd_session",
                        "value": "next-cookie",
                        "domain": ".etsy.com",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": "https://www.etsy.com",
                        "localStorage": [
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            }

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_options",
        lambda **_: {},
    )

    async def _fake_load_storage_state_for_run(run_id: int | None):
        assert run_id == 77
        return {
            "cookies": [
                {
                    "name": "dd_session",
                    "value": "existing-cookie",
                    "domain": ".etsy.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://www.etsy.com",
                    "localStorage": [
                        {"name": "consent", "value": "accepted"},
                    ],
                }
            ],
        }

    async def _fake_persist_storage_state_for_run(
        run_id: int | None,
        storage_state: dict[str, object],
    ) -> None:
        assert run_id == 77
        persisted_states.append((int(run_id), dict(storage_state)))

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "load_storage_state_for_run",
        _fake_load_storage_state_for_run,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "persist_storage_state_for_run",
        _fake_persist_storage_state_for_run,
    )

    async with runtime.page(run_id=77):
        pass

    assert captured_kwargs == [
        {
            "storage_state": {
                "cookies": [
                    {
                        "name": "dd_session",
                        "value": "existing-cookie",
                        "domain": ".etsy.com",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": "https://www.etsy.com",
                        "localStorage": [
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            }
        }
    ]
    assert persisted_states == [
        (
            77,
            {
                "cookies": [
                    {
                        "name": "dd_session",
                        "value": "next-cookie",
                        "domain": ".etsy.com",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": "https://www.etsy.com",
                        "localStorage": [
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            },
        )
    ]


@pytest.mark.asyncio
async def test_shared_browser_runtime_suppresses_storage_state_persist_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            return {"cookies": [], "origins": []}

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_options",
        lambda **_: {},
    )
    async def _boom(*args, **kwargs) -> None:
        del args, kwargs
        raise RuntimeError("boom")
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "persist_storage_state_for_run",
        _boom,
    )
    async def _no_state(run_id: int | None):
        del run_id
        return None
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "load_storage_state_for_run",
        _no_state,
    )

    with caplog.at_level("ERROR", logger=acquisition_browser_runtime.logger.name):
        async with runtime.page(run_id=77):
            pass

    assert any(
        "Failed to persist browser storage state for run_id=77" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_shared_browser_runtime_snapshot_tracks_queue_without_private_semaphore_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_options",
        lambda **_: {},
    )

    async def _hold_page() -> None:
        async with runtime.page():
            entered.set()
            await release.wait()

    first = asyncio.create_task(_hold_page())
    await entered.wait()
    second = asyncio.create_task(_hold_page())
    await asyncio.sleep(0)

    snapshot = runtime.snapshot()

    assert snapshot["active"] == 1
    assert snapshot["queued"] == 1

    release.set()
    await asyncio.gather(first, second)


@pytest.mark.asyncio
async def test_shared_browser_runtime_recycles_browser_without_deadlocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_events: list[str] = []
    new_events: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            new_events.append("context_closed")

    class FakeBrowser:
        def __init__(self, events: list[str]) -> None:
            self._events = events

        def is_connected(self) -> bool:
            return True

        async def new_context(self, **kwargs):
            del kwargs
            self._events.append("new_context")
            return FakeContext()

        async def close(self) -> None:
            self._events.append("browser_closed")

    class FakePlaywrightInstance:
        def __init__(self, events: list[str]) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)
            self._events = events

        async def _launch(self, *, headless: bool):
            del headless
            self._events.append("launched")
            return FakeBrowser(self._events)

        async def stop(self) -> None:
            self._events.append("playwright_stopped")

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance(new_events)

    class OldPlaywright:
        async def stop(self) -> None:
            old_events.append("playwright_stopped")

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser(old_events)
    runtime._playwright = OldPlaywright()
    runtime._browser_launched_at = 1.0
    runtime._total_contexts_created = 1

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_options",
        lambda **_: {},
    )
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_max_contexts_before_recycle",
        1,
    )
    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: FakePlaywrightManager())

    async with asyncio.timeout(1):
        async with runtime.page():
            pass

    assert old_events == ["browser_closed", "playwright_stopped"]
    assert new_events == ["launched", "new_context", "context_closed"]

def test_browser_runtime_snapshot_reports_runtime_capacity_without_host_cache() -> None:
    snapshot = crawl_fetch_runtime.browser_runtime_snapshot()

    assert "preferred_hosts" not in snapshot
    assert "capacity" in snapshot
