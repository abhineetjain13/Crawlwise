from __future__ import annotations

import httpx
import pytest

from app.services.acquisition.acquirer import AcquisitionRequest, acquire
from app.services.acquisition_plan import AcquisitionPlan


@pytest.mark.asyncio
async def test_acquire_returns_public_headers_as_plain_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str]] = []

    async def _on_event(level: str, message: str) -> None:
        events.append((level, message))

    async def _fake_fetch_page(*args, **kwargs):
        del args
        on_event = kwargs.get("on_event")
        if on_event is not None:
            await on_event("info", "Launched headless browser (chromium, proxy: direct)")
        return type(
            "FetchResult",
            (),
            {
                "final_url": "https://example.com/final",
                "html": "<html></html>",
                "method": "httpx",
                "status_code": 200,
                "content_type": "text/html",
                "blocked": False,
                "headers": httpx.Headers({"content-type": "text/html"}),
                "network_payloads": [],
                "browser_diagnostics": {},
                "artifacts": {},
            },
        )()

    monkeypatch.setattr(
        "app.services.acquisition.acquirer.fetch_page",
        _fake_fetch_page,
    )

    result = await acquire(
        AcquisitionRequest(
            run_id=1,
            url="https://example.com",
            plan=AcquisitionPlan(surface="ecommerce_detail"),
            on_event=_on_event,
        )
    )

    assert result.headers == {"content-type": "text/html"}
    assert isinstance(result.headers, dict)
    assert events == [
        ("info", "Acquiring https://example.com"),
        ("info", "Launched headless browser (chromium, proxy: direct)"),
    ]
