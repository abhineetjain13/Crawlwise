from __future__ import annotations

import httpx
import pytest

from app.services.acquisition.acquirer import AcquisitionRequest, acquire
from app.services.acquisition_plan import AcquisitionPlan


@pytest.mark.asyncio
async def test_acquire_returns_public_headers_as_plain_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_fetch_page(*args, **kwargs):
        del args, kwargs
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
        )
    )

    assert result.headers == {"content-type": "text/html"}
    assert isinstance(result.headers, dict)
