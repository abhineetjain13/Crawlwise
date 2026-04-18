from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import crawl_fetch_runtime
from app.services.acquisition import browser_identity


def test_build_playwright_context_options_uses_generated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1440, height=900, devicePixelRatio=2),
        navigator=SimpleNamespace(
            userAgent="Mozilla/5.0 TestBrowser/145.0",
            language="en-US",
            maxTouchPoints=0,
            userAgentData={"mobile": False},
        ),
        headers={
            "User-Agent": "Mozilla/5.0 TestBrowser/145.0",
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

    assert options["user_agent"] == "Mozilla/5.0 TestBrowser/145.0"
    assert options["viewport"] == {"width": 1440, "height": 900}
    assert options["locale"] == "en-US"
    assert options["device_scale_factor"] == 2.0
    assert options["has_touch"] is False
    assert options["is_mobile"] is False
    assert options["extra_http_headers"] == {
        "Accept": "text/html",
        "Accept-Language": "en-US;q=1.0",
        "sec-ch-ua": '"Google Chrome";v="145"',
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


@pytest.mark.asyncio
async def test_shared_browser_runtime_passes_generated_context_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []
    created_pages: list[object] = []

    class FakeContext:
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
        lambda: {
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
