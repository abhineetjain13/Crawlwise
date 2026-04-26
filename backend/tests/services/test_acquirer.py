from __future__ import annotations

import httpx
import pytest

from app.services.acquisition import acquirer
from app.services.acquisition.acquirer import AcquisitionRequest, acquire
from app.services.acquisition_plan import AcquisitionPlan
from app.services.crawl_utils import normalize_target_url


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


@pytest.mark.asyncio
async def test_acquire_normalizes_url_via_adapter_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_urls: list[str] = []

    async def _fake_normalize(url: str | None) -> str | None:
        return f"{url}&normalized=1"

    async def _fake_fetch_page(url: str, *args, **kwargs):
        del args, kwargs
        observed_urls.append(url)
        return type(
            "FetchResult",
            (),
            {
                "final_url": url,
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
        "app.services.acquisition.acquirer.normalize_adapter_acquisition_url",
        _fake_normalize,
    )
    monkeypatch.setattr(
        "app.services.acquisition.acquirer.fetch_page",
        _fake_fetch_page,
    )

    result = await acquire(
        AcquisitionRequest(
            run_id=1,
            url="https://example.com/jobs/123",
            plan=AcquisitionPlan(surface="job_detail"),
        )
    )

    assert observed_urls == ["https://example.com/jobs/123&normalized=1"]
    assert result.final_url == "https://example.com/jobs/123&normalized=1"


def test_normalize_target_url_strips_signed_detail_context_query_params() -> None:
    normalized = normalize_target_url(
        "https://www.mouser.in/ProductDetail/Phoenix-Contact/1509524"
        "?qs=sGAEpiMZZMuGSqhhLqSWxfOEVG9XfT7wFuevx9ZKoIs05o6zFXlrHA%3D%3D"
    )

    assert normalized == "https://www.mouser.in/ProductDetail/Phoenix-Contact/1509524"


def test_resolve_fetch_mode_honors_explicit_empty_profile() -> None:
    request = AcquisitionRequest(
        run_id=1,
        url="https://example.com",
        plan=AcquisitionPlan(surface="ecommerce_detail"),
        acquisition_profile={"prefer_browser": True, "fetch_mode": "browser_only"},
    )

    assert acquirer._resolve_fetch_mode(request, acquisition_profile={}) == "auto"
    assert acquirer._resolve_browser_reason(
        request=request,
        acquisition_profile={},
        requires_browser=False,
    ) is None
    assert acquirer._resolve_listing_recovery_mode(
        request,
        acquisition_profile={},
    ) is None
