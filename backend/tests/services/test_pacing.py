from __future__ import annotations

import pytest

from app.services.acquisition import pacing
@pytest.mark.asyncio
async def test_apply_protected_host_backoff_extends_wait_window(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(
        pacing.crawler_runtime_settings,
        acquire_host_min_interval_ms=250,
        protected_host_additional_interval_ms=2000,
    )
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(pacing.asyncio, "sleep", _fake_sleep)
    await pacing.reset_pacing_state()
    url = "https://example.com/products/widget"
    try:
        await pacing.wait_for_host_slot(url)
        await pacing.record_fetch_outcome(url, status_code=429, blocked=False)
        await pacing.wait_for_host_slot(url)
    finally:
        await pacing.reset_pacing_state()

    assert sleeps
    assert sleeps[-1] >= 1.5

