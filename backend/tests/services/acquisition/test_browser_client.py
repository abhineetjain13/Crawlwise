from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.services.acquisition import browser_client
from app.services.acquisition.browser_runtime import BrowserRuntimeOptions
from app.services.resource_monitor import MemoryPressureLevel


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/listing"

    async def route(self, _pattern, _handler) -> None:
        return None

    def on(self, _event, _handler) -> None:
        return None


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.close = AsyncMock()

    async def new_page(self) -> _FakePage:
        return self._page


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self._context = context

    async def new_context(self, **_kwargs) -> _FakeContext:
        return self._context


@pytest.mark.asyncio
async def test_fetch_rendered_html_attempt_passes_page_content_helper_to_low_value_check(
    monkeypatch: pytest.MonkeyPatch,
):
    page = _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    pw = SimpleNamespace(chromium=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        browser_client,
        "get_memory_pressure_level",
        lambda: MemoryPressureLevel.NORMAL,
    )
    monkeypatch.setattr(browser_client, "_build_launch_kwargs", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        browser_client,
        "_acquire_browser",
        AsyncMock(return_value=(browser, False)),
    )
    monkeypatch.setattr(browser_client, "_context_kwargs", lambda *args, **kwargs: {})
    monkeypatch.setattr(browser_client, "_load_cookies", AsyncMock())
    monkeypatch.setattr(browser_client, "_maybe_warm_origin", AsyncMock(return_value=False))
    monkeypatch.setattr(browser_client, "_goto_with_fallback", AsyncMock())
    monkeypatch.setattr(browser_client, "_dismiss_cookie_consent", AsyncMock())
    monkeypatch.setattr(
        browser_client,
        "_wait_for_challenge_resolution",
        AsyncMock(return_value=(True, "none", [])),
    )
    monkeypatch.setattr(
        browser_client,
        "_wait_for_listing_readiness",
        AsyncMock(return_value={"ready": False}),
    )

    async def _fake_page_looks_low_value(current_page, page_content_with_retry):
        captured["page"] = current_page
        captured["page_content_with_retry"] = page_content_with_retry
        return True

    monkeypatch.setattr(browser_client, "_page_looks_low_value", _fake_page_looks_low_value)
    monkeypatch.setattr(browser_client, "_populate_result", AsyncMock())
    monkeypatch.setattr(browser_client, "_persist_context_cookies", AsyncMock())

    result = await browser_client._fetch_rendered_html_attempt(
        pw,
        target=SimpleNamespace(),
        url="https://example.com/listing",
        proxy=None,
        surface="ecommerce_listing",
        traversal_mode=None,
        max_pages=1,
        max_scrolls=1,
        prefer_stealth=False,
        request_delay_ms=0,
        runtime_options=BrowserRuntimeOptions(wait_for_readiness=True),
        requested_fields=[],
        requested_field_selectors={},
        launch_profile={"browser_type": "chromium", "channel": None},
        navigation_strategies=[],
    )

    assert captured["page"] is page
    assert captured["page_content_with_retry"] is browser_client._page_content_with_retry
    assert result.diagnostics["listing_readiness"] == {"ready": False}
    context.close.assert_awaited_once()
