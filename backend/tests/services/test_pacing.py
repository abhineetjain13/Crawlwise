from __future__ import annotations

import pytest

from app.services.acquisition import pacing
from app.services.acquisition.pacing import _normalized_host


def test_normalized_host_preserves_port_information() -> None:
    assert _normalized_host("https://example.com:8443/path?q=1") == "example.com:8443"
    assert _normalized_host("example.com:8443") == "example.com:8443"


@pytest.mark.asyncio
async def test_apply_protected_host_backoff_extends_wait_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_base_ms = pacing.crawler_runtime_settings.acquire_host_min_interval_ms
    original_protected_ms = pacing.crawler_runtime_settings.protected_host_additional_interval_ms
    pacing.crawler_runtime_settings.acquire_host_min_interval_ms = 250
    pacing.crawler_runtime_settings.protected_host_additional_interval_ms = 2000
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(pacing.asyncio, "sleep", _fake_sleep)
    await pacing.reset_pacing_state()
    try:
        await pacing.wait_for_host_slot("https://example.com/products/widget")
        await pacing.apply_protected_host_backoff("https://example.com/products/widget")
        await pacing.wait_for_host_slot("https://example.com/products/widget")
    finally:
        await pacing.reset_pacing_state()
        pacing.crawler_runtime_settings.acquire_host_min_interval_ms = original_base_ms
        pacing.crawler_runtime_settings.protected_host_additional_interval_ms = original_protected_ms

    assert sleeps
    assert sleeps[-1] >= 1.5


@pytest.mark.asyncio
async def test_mark_browser_first_host_prefers_browser_until_reset() -> None:
    await pacing.reset_pacing_state()
    try:
        assert await pacing.should_prefer_browser_for_host("https://example.com/path") is False
        await pacing.mark_browser_first_host("https://example.com/path")
        assert await pacing.should_prefer_browser_for_host("https://example.com/other") is True
    finally:
        await pacing.reset_pacing_state()
