from __future__ import annotations

import asyncio
import concurrent.futures
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from app.services import crawl_fetch_runtime
from app.services.acquisition import (
    browser_capture,
    browser_identity,
    runtime as acquisition_runtime,
)
from app.services.acquisition.host_protection_memory import HostProtectionPolicy
from app.services.acquisition.browser_runtime import (
    classify_network_endpoint,
    read_network_payload_body,
    should_capture_network_payload,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.acquisition.runtime import (
    PageFetchResult,
    http_fetch,
    should_escalate_to_browser_async,
)


class _FakeResponse:
    def __init__(
        self,
        body: bytes | None = None,
        *,
        error: Exception | None = None,
        url: str = "https://example.com/api/data.json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self._error = error
        self.url = url
        self.body_calls = 0
        self.headers = headers or {}

    async def body(self) -> bytes:
        self.body_calls += 1
        if self._error is not None:
            raise self._error
        return self._body


def test_should_capture_network_payload_skips_noise_and_large_declared_payloads() -> None:
    assert not should_capture_network_payload(
        url="https://example.com/telemetry/events",
        content_type="application/json",
        headers={},
        captured_count=0,
    )
    assert not should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={"content-length": "9999999"},
        captured_count=0,
    )
    assert should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={"content-length": "512"},
        captured_count=0,
    )
    assert should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={"content-length": "600000"},
        captured_count=0,
    )
    assert should_capture_network_payload(
        url="https://example.com/products/widget/product.js",
        content_type="application/json",
        headers={"content-length": "6000000"},
        captured_count=0,
        surface="ecommerce_detail",
    )


def test_should_capture_network_payload_accepts_chunked_json_without_content_length() -> None:
    assert should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={"transfer-encoding": "chunked"},
        captured_count=0,
    )


def test_select_http_fetcher_uses_httpx_when_forced() -> None:
    original_force_httpx = crawler_runtime_settings.force_httpx
    crawler_runtime_settings.force_httpx = True
    try:
        fetcher = crawl_fetch_runtime._select_http_fetcher(object())
    finally:
        crawler_runtime_settings.force_httpx = original_force_httpx

    assert fetcher is crawl_fetch_runtime._http_fetch


def test_should_capture_network_payload_ignores_misleading_content_length_when_chunked() -> None:
    assert should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={
            "transfer-encoding": "chunked",
            "content-length": "9999999",
        },
        captured_count=0,
    )


def test_should_capture_network_payload_accepts_react_server_component_streams() -> None:
    assert should_capture_network_payload(
        url="https://example.com/products/widget",
        content_type="text/x-component",
        headers={},
        captured_count=0,
    )


def test_should_capture_network_payload_accepts_trpc_and_rsc_url_hints() -> None:
    assert should_capture_network_payload(
        url="https://example.com/api/trpc/product.get",
        content_type="application/trpc+json",
        headers={},
        captured_count=0,
    )
    assert should_capture_network_payload(
        url="https://example.com/products/widget?_rsc=abc123",
        content_type="text/plain",
        headers={},
        captured_count=0,
    )


def test_classify_network_endpoint_uses_platform_config_family_signatures() -> None:
    assert classify_network_endpoint(
        response_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs/1234",
        surface="job_detail",
    ) == {"type": "job_api", "family": "greenhouse"}
    assert classify_network_endpoint(
        response_url="https://jobs.example.com/api/positions/1234",
        surface="job_detail",
    ) == {"type": "job_api", "family": "generic"}
    assert classify_network_endpoint(
        response_url="https://shop.example.com/products/widget/product.js",
        surface="ecommerce_detail",
    ) == {"type": "product_api", "family": "shopify"}
    assert classify_network_endpoint(
        response_url="https://shop.example.com/api/variants/123",
        surface="ecommerce_detail",
    ) == {"type": "product_api", "family": "generic"}
    assert classify_network_endpoint(
        response_url="https://store.example.com/_next/data/build-id/widget.json",
        surface="ecommerce_detail",
    ) == {"type": "generic_json", "family": "nextjs"}


@pytest.mark.asyncio
async def test_curl_fetch_uses_runtime_owned_default_request_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: dict[str, str] = {}
    original_user_agent = crawler_runtime_settings.http_user_agent
    crawler_runtime_settings.http_user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    def _fake_get(url: str, **kwargs):
        del url
        captured_headers.update(dict(kwargs.get("headers") or {}))
        return SimpleNamespace(
            text="<html><body>ok</body></html>",
            headers={"content-type": "text/html"},
            status_code=200,
            url="https://example.com/products/widget",
        )

    monkeypatch.setitem(
        sys.modules,
        "curl_cffi",
        SimpleNamespace(requests=SimpleNamespace(get=_fake_get)),
    )
    try:
        result = await acquisition_runtime.curl_fetch(
            "https://example.com/products/widget",
            5.0,
        )
    finally:
        crawler_runtime_settings.http_user_agent = original_user_agent

    assert result.method == "curl_cffi"
    assert captured_headers["User-Agent"].endswith("Chrome/131.0.0.0 Safari/537.36")
    assert "Accept" in captured_headers
    assert "Accept-Language" in captured_headers
    assert captured_headers["Upgrade-Insecure-Requests"] == "1"
    assert "sec-ch-ua" in captured_headers


@pytest.mark.asyncio
async def test_curl_fetch_coerces_blank_impersonate_target_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_impersonate: list[object] = []
    original_impersonate_target = crawler_runtime_settings.curl_impersonate_target

    def _fake_get(url: str, **kwargs):
        del url
        captured_impersonate.append(kwargs.get("impersonate"))
        return SimpleNamespace(
            text="<html><body>ok</body></html>",
            headers={"content-type": "text/html"},
            status_code=200,
            url="https://example.com/products/widget",
        )

    monkeypatch.setitem(
        sys.modules,
        "curl_cffi",
        SimpleNamespace(requests=SimpleNamespace(get=_fake_get)),
    )
    crawler_runtime_settings.curl_impersonate_target = "   "
    try:
        await acquisition_runtime.curl_fetch(
            "https://example.com/products/widget",
            5.0,
        )
    finally:
        crawler_runtime_settings.curl_impersonate_target = original_impersonate_target

    assert captured_impersonate == [None]


@pytest.mark.asyncio
async def test_fetch_page_waits_for_host_slot_before_http_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wait_calls: list[str] = []

    async def _fake_wait_for_host_slot(url: str) -> None:
        wait_calls.append(url)

    async def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del timeout_seconds, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html=(
                "<html><body><article class='product-card'>"
                "<a href='/products/widget'>Widget</a><span>$19.99</span>"
                "</article></body></html>"
            ),
            status_code=200,
            method="curl_cffi",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", _fake_wait_for_host_slot)
    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/collections/widgets",
        surface="ecommerce_listing",
    )

    assert result.method == "curl_cffi"
    assert wait_calls == ["https://example.com/collections/widgets"]


@pytest.mark.asyncio
async def test_fetch_page_preserves_requested_fields_on_http_to_browser_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requested_fields: list[str] | None = None

    async def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del timeout_seconds, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>challenge</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=False,
        )

    async def _fake_should_escalate(*args, **kwargs):
        del args, kwargs
        return True

    async def _fake_run_browser_attempts(
        context,
        *,
        reason: str,
        requested_fields: list[str] | None = None,
        listing_recovery_mode: str | None = None,
        proxies: list[str | None] | None = None,
    ):
        del context, reason, listing_recovery_mode, proxies
        nonlocal captured_requested_fields
        captured_requested_fields = list(requested_fields or [])
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_should_escalate_to_browser_async",
        _fake_should_escalate,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_run_browser_attempts",
        _fake_run_browser_attempts,
    )

    await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        requested_fields=["product measurements"],
    )

    assert captured_requested_fields == ["product measurements"]


@pytest.mark.asyncio
async def test_fetch_page_preserves_requested_fields_on_browser_first_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requested_fields: list[str] | None = None

    async def _fake_run_browser_attempts(
        context,
        *,
        reason: str,
        requested_fields: list[str] | None = None,
        listing_recovery_mode: str | None = None,
        proxies: list[str | None] | None = None,
    ):
        del context, reason, listing_recovery_mode, proxies
        nonlocal captured_requested_fields
        captured_requested_fields = list(requested_fields or [])
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_run_browser_attempts",
        _fake_run_browser_attempts,
    )

    await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        prefer_browser=True,
        requested_fields=["product measurements"],
    )

    assert captured_requested_fields == ["product measurements"]


@pytest.mark.asyncio
async def test_fetch_page_browser_only_skips_http_fetchers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        raise AssertionError(f"curl should not run for browser_only: {url} {timeout_seconds} {proxy}")

    async def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>browser</body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _unexpected_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="browser_only",
    )

    assert result.method == "browser"


@pytest.mark.asyncio
async def test_fetch_page_http_only_disables_browser_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del timeout_seconds, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>challenge</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=False,
        )

    async def _fake_should_escalate(*args, **kwargs):
        del args, kwargs
        return True

    async def _unexpected_browser(url, timeout, **kwargs):
        raise AssertionError(f"browser should not run for http_only: {url} {timeout} {kwargs}")

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_should_escalate_to_browser_async", _fake_should_escalate)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _unexpected_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="http_only",
    )

    assert result.method == "curl_cffi"
    assert result.status_code == 403


@pytest.mark.asyncio
async def test_fetch_page_http_then_browser_escalates_after_http_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del timeout_seconds, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>challenge</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=False,
        )

    async def _fake_should_escalate(*args, **kwargs):
        del args, kwargs
        return True

    async def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>browser</body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_should_escalate_to_browser_async", _fake_should_escalate)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="http_then_browser",
    )

    assert result.method == "browser"


@pytest.mark.asyncio
async def test_fetch_page_prefers_browser_from_learned_host_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        raise AssertionError(f"http should be skipped for learned browser-first host: {url} {timeout_seconds} {proxy}")

    async def _fake_load_policy(url: str, *, session=None):
        del session
        return HostProtectionPolicy(host="example.com", prefer_browser=True)

    async def _fake_should_prefer_browser_for_host(url: str) -> bool:
        del url
        return False

    async def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>browser</body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _unexpected_curl)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        _fake_load_policy,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "should_prefer_browser_for_host",
        _fake_should_prefer_browser_for_host,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    assert result.method == "browser"


@pytest.mark.asyncio
async def test_fetch_page_preserves_proxy_list_on_browser_first_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_proxies: list[str | None] | None = None

    async def _fake_run_browser_attempts(
        context,
        *,
        reason: str,
        requested_fields: list[str] | None = None,
        listing_recovery_mode: str | None = None,
        capture_page_markdown: bool = False,
        proxies: list[str | None] | None = None,
    ):
        del context, reason, requested_fields, listing_recovery_mode, capture_page_markdown
        nonlocal captured_proxies
        captured_proxies = list(proxies or [])
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_run_browser_attempts",
        _fake_run_browser_attempts,
    )

    await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        prefer_browser=True,
        proxy_list=["http://proxy-one", "http://proxy-two"],
    )

    assert sorted(captured_proxies or []) == ["http://proxy-one", "http://proxy-two"]


@pytest.mark.asyncio
async def test_read_network_payload_body_rejects_oversized_body_before_decode() -> None:
    response = _FakeResponse(b"x" * 3_500_000)

    body = await read_network_payload_body(response)

    assert body.outcome == "too_large"
    assert body.body is None
    assert response.body_calls == 1


@pytest.mark.asyncio
async def test_read_network_payload_body_rejects_oversized_declared_content_length_before_body_read() -> None:
    response = _FakeResponse(
        b"x",
        headers={"content-length": "3500000"},
    )

    body = await read_network_payload_body(response)

    assert body.outcome == "read"
    assert body.body == b"x"
    assert response.body_calls == 1


@pytest.mark.asyncio
async def test_read_network_payload_body_accepts_large_but_in_budget_body() -> None:
    response = _FakeResponse(b"x" * 600_000)

    body = await read_network_payload_body(response)

    assert body.outcome == "read"
    assert body.body == b"x" * 600_000
    assert response.body_calls == 1


@pytest.mark.asyncio
async def test_read_network_payload_body_accepts_high_value_large_body_with_scaled_budget() -> None:
    response = _FakeResponse(
        b"x" * 3_500_000,
        url="https://example.com/products/widget/product.js",
    )

    body = await read_network_payload_body(response, surface="ecommerce_detail")

    assert body.outcome == "read"
    assert body.body == b"x" * 3_500_000
    assert response.body_calls == 1


@pytest.mark.asyncio
async def test_read_network_payload_body_marks_closed_page_failures_explicitly() -> None:
    response = _FakeResponse(error=RuntimeError("Target closed"))

    result = await read_network_payload_body(response)

    assert result.outcome == "response_closed"
    assert result.body is None
    assert "RuntimeError" in str(result.error)


@pytest.mark.asyncio
async def test_read_network_payload_body_marks_generic_read_failures_explicitly() -> None:
    response = _FakeResponse(error=RuntimeError("socket reset"))

    result = await read_network_payload_body(response)

    assert result.outcome == "read_error"
    assert result.body is None
    assert "socket reset" in str(result.error)


@pytest.mark.asyncio
async def test_read_network_payload_body_maps_read_timeouts_to_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeResponse(b"x")

    async def _fake_wait_for(awaitable, timeout: float):
        awaitable.close()
        del timeout
        raise asyncio.TimeoutError

    monkeypatch.setattr(browser_capture.asyncio, "wait_for", _fake_wait_for)

    result = await read_network_payload_body(response)

    assert result.outcome == "timeout"
    assert result.body is None
    assert response.body_calls == 0


@pytest.mark.asyncio
async def test_should_escalate_to_browser_async_uses_thread_offload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr("app.services.acquisition.runtime.asyncio.to_thread", _fake_to_thread)

    result = await should_escalate_to_browser_async(
        PageFetchResult(
            url="https://example.com",
            final_url="https://example.com",
            html="<html><body><div id='__next'></div><script></script><script></script><script></script></body></html>",
            status_code=200,
            method="httpx",
            blocked=False,
        )
    )

    assert result is True
    assert calls == ["should_escalate_to_browser"]


@pytest.mark.asyncio
async def test_http_fetch_populates_platform_family_from_response_url() -> None:
    class _FakeClient:
        async def get(self, url: str, timeout: float) -> SimpleNamespace:
            del url, timeout
            return SimpleNamespace(
                text="<html><body>Jobs</body></html>",
                headers={"content-type": "text/html"},
                status_code=200,
                url="https://boards.greenhouse.io/acme",
            )

    async def _fake_get_client(*, proxy: str | None = None):
        del proxy
        return _FakeClient()

    async def _not_blocked(*_args, **_kwargs) -> bool:
        return False

    result = await http_fetch(
        "https://example.com/jobs",
        5,
        get_client=_fake_get_client,
        blocked_html_checker=_not_blocked,
    )

    assert result.platform_family == "greenhouse"


@pytest.mark.asyncio
async def test_http_fetch_accepts_legacy_client_builder_keyword() -> None:
    class _FakeClient:
        async def get(self, url: str, timeout: float) -> SimpleNamespace:
            del url, timeout
            return SimpleNamespace(
                text="<html><body>ok</body></html>",
                headers={"content-type": "text/html"},
                status_code=200,
                url="https://example.com/products/widget",
            )

    async def _legacy_client_builder(*, proxy: str | None = None):
        assert proxy is None
        return _FakeClient()

    async def _not_blocked(*_args, **_kwargs) -> bool:
        return False

    result = await http_fetch(
        "https://example.com/products/widget",
        5,
        client_builder=_legacy_client_builder,
        blocked_html_checker=_not_blocked,
    )

    assert result.final_url == "https://example.com/products/widget"


@pytest.mark.asyncio
async def test_detail_surface_without_signals_escalates_even_when_html_is_not_a_js_shell() -> None:
    listing_shell_html = (
        "<html><body><h1>Careers</h1>"
        + "<ul>"
        + "".join(
            f"<li><a href='#'>Job {index}</a></li>" for index in range(20)
        )
        + "</ul>"
        + "<p>" + ("Lots of visible non-detail copy. " * 30) + "</p>"
        + "</body></html>"
    )
    result = PageFetchResult(
        url="https://ats.example.com/careers?ShowJob=123",
        final_url="https://ats.example.com/careers?ShowJob=123",
        html=listing_shell_html,
        status_code=200,
        method="httpx",
        blocked=False,
    )

    assert await should_escalate_to_browser_async(result, surface="job_detail") is True
    assert await should_escalate_to_browser_async(result, surface="job_listing") is False


@pytest.mark.asyncio
async def test_should_escalate_to_browser_async_uses_runtime_policy_for_missing_detail_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.acquisition.runtime.resolve_platform_runtime_policy",
        lambda url, html="", *, surface=None: {
            "family": None,
            "requires_browser": False,
            "proxy_policy": None,
            "http_browser_escalation": {
                "js_shell_without_detail_signals": False,
                "missing_detail_signals": False,
                "listing_shell_without_listing_signals": False,
            },
        },
    )
    result = PageFetchResult(
        url="https://ats.example.com/careers?ShowJob=123",
        final_url="https://ats.example.com/careers?ShowJob=123",
        html=(
            "<html><body><h1>Careers</h1>"
            + "<ul>"
            + "".join(f"<li><a href='#'>Job {index}</a></li>" for index in range(20))
            + "</ul>"
            + "<p>" + ("Lots of visible non-detail copy. " * 30) + "</p>"
            + "</body></html>"
        ),
        status_code=200,
        method="httpx",
        blocked=False,
    )

    assert await should_escalate_to_browser_async(result, surface="job_detail") is False


@pytest.mark.asyncio
async def test_listing_hash_router_shell_escalates_to_browser() -> None:
    result = PageFetchResult(
        url="https://practicesoftwaretesting.com/#/",
        final_url="https://practicesoftwaretesting.com/#/",
        html=(
            "<html><body><div id='root'></div>"
            "<script></script><script></script><script></script>"
            "</body></html>"
        ),
        status_code=200,
        method="httpx",
        blocked=False,
    )

    assert await should_escalate_to_browser_async(result, surface="ecommerce_listing") is True


@pytest.mark.asyncio
async def test_listing_202_shell_escalates_to_browser() -> None:
    result = PageFetchResult(
        url="https://www.govplanet.com/for-sale/equipment",
        final_url="https://www.govplanet.com/for-sale/equipment",
        html=(
            "<html><body><div id='app'></div>"
            "<script type='application/json'>{\"pending\":true}</script>"
            "<script></script><script></script>"
            "</body></html>"
        ),
        status_code=202,
        method="httpx",
        blocked=False,
    )

    assert await should_escalate_to_browser_async(result, surface="ecommerce_listing") is True


@pytest.mark.asyncio
async def test_js_disabled_placeholder_shell_escalates_to_browser() -> None:
    result = PageFetchResult(
        url="https://example.com/for-sale/mixer-truck",
        final_url="https://example.com/for-sale/mixer-truck",
        html=(
            "<html><head><title>JavaScript is disabled</title></head>"
            "<body><noscript>Please enable JavaScript to continue.</noscript>"
            "<main><h1>JavaScript is disabled</h1></main></body></html>"
        ),
        status_code=200,
        method="httpx",
        blocked=False,
    )

    assert await should_escalate_to_browser_async(result, surface="ecommerce_detail") is True


@pytest.mark.asyncio
async def test_fetch_page_uses_browser_for_js_disabled_placeholder_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import crawl_fetch_runtime

    async def _fake_curl(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html=(
                "<html><head><title>JavaScript is disabled</title></head>"
                "<body><noscript>Please enable JavaScript to continue.</noscript>"
                "<main><h1>JavaScript is disabled</h1></main></body></html>"
            ),
            status_code=200,
            method="curl_cffi",
            blocked=False,
        )

    async def _unexpected_http(url: str, timeout: float, *, proxy: str | None = None):
        raise AssertionError(
            f"http fallback should not run when curl already returned a JS-disabled shell: {url} {timeout} {proxy}"
        )

    browser_calls: list[str] = []

    async def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        browser_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body><h1>Rendered listing</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _unexpected_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/for-sale/mixer-truck",
        surface="ecommerce_detail",
    )

    assert result.method == "browser"
    assert browser_calls == ["https://example.com/for-sale/mixer-truck"]


@pytest.mark.asyncio
async def test_fetch_page_falls_back_to_httpx_after_curl_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from app.services import crawl_fetch_runtime

    async def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del proxy
        raise httpx.TooManyRedirects("redirect loop")

    http_calls: list[str] = []

    async def _http_success(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        http_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>http-fallback</body></html>",
            status_code=200,
            method="httpx",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _http_success)
    async def _no_browser_escalation(*args, **kwargs):
        del args, kwargs
        return False

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_should_escalate_to_browser_async",
        _no_browser_escalation,
    )

    result = await crawl_fetch_runtime.fetch_page(
        "https://ar.puma.com/pd/widget.html",
        surface="ecommerce_detail",
    )

    assert result.method == "httpx"
    assert http_calls == ["https://ar.puma.com/pd/widget.html"]


@pytest.mark.asyncio
async def test_fetch_page_retries_curl_before_httpx_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    await crawl_fetch_runtime.reset_fetch_runtime_state()
    original_retries = crawler_runtime_settings.http_max_retries
    original_base = crawler_runtime_settings.http_retry_backoff_base_ms
    original_max = crawler_runtime_settings.http_retry_backoff_max_ms
    crawler_runtime_settings.http_max_retries = 2
    crawler_runtime_settings.http_retry_backoff_base_ms = 0
    crawler_runtime_settings.http_retry_backoff_max_ms = 0
    curl_calls: list[int] = []
    http_calls: list[str] = []

    async def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        curl_calls.append(1)
        raise httpx.ConnectTimeout("timed out")

    async def _http_success(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        http_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>http-fallback</body></html>",
            status_code=200,
            method="httpx",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _http_success)
    async def _no_browser_escalation(*args, **kwargs):
        del args, kwargs
        return False

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_should_escalate_to_browser_async",
        _no_browser_escalation,
    )
    try:
        result = await crawl_fetch_runtime.fetch_page(
            "https://example.com/products/widget",
            surface="ecommerce_detail",
        )
    finally:
        crawler_runtime_settings.http_max_retries = original_retries
        crawler_runtime_settings.http_retry_backoff_base_ms = original_base
        crawler_runtime_settings.http_retry_backoff_max_ms = original_max

    assert result.method == "httpx"
    assert len(curl_calls) == 3
    assert http_calls == ["https://example.com/products/widget"]


@pytest.mark.asyncio
async def test_fetch_page_falls_back_to_browser_after_curl_and_httpx_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    async def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        raise httpx.TooManyRedirects("redirect loop")

    async def _failing_http(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        raise httpx.ConnectError("httpx failed")

    browser_calls: list[str] = []

    async def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        browser_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>browser-rendered</body></html>",
            status_code=200,
            method="browser",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _failing_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    assert result.method == "browser"
    assert browser_calls == ["https://example.com/products/widget"]


@pytest.mark.asyncio
async def test_fetch_page_returns_non_retryable_404_without_browser_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import crawl_fetch_runtime

    async def _fake_curl(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>not found</body></html>",
            status_code=404,
            method="curl_cffi",
            blocked=False,
        )

    async def _unexpected_browser(url, timeout, **kwargs):
        raise AssertionError(f"browser fallback should not run for non-retryable status {url} {timeout} {kwargs}")

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _unexpected_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/missing-job",
        surface="job_detail",
    )

    assert result.status_code == 404
    assert result.method == "curl_cffi"


@pytest.mark.asyncio
async def test_fetch_page_escalates_404_shell_to_browser_before_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import crawl_fetch_runtime

    async def _fake_curl(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html=(
                "<html><body><div id='root'></div>"
                "<script></script><script></script><script></script>"
                "</body></html>"
            ),
            status_code=404,
            method="curl_cffi",
            blocked=False,
        )

    browser_calls: list[str] = []

    async def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        browser_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body><h1>Rendered page</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/missing-spa-route",
        surface="ecommerce_detail",
    )

    assert result.method == "browser"
    assert browser_calls == ["https://example.com/missing-spa-route"]


@pytest.mark.asyncio
async def test_fetch_page_stops_http_waterfall_after_vendor_confirmed_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import crawl_fetch_runtime

    curl_proxies: list[str | None] = []
    browser_proxies: list[str | None] = []

    async def _vendor_blocked_curl(url: str, timeout: float, *, proxy: str | None = None):
        del timeout
        curl_proxies.append(proxy)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>blocked</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=True,
            headers={"x-datadome": "blocked"},
        )

    async def _unexpected_http(url: str, timeout: float, *, proxy: str | None = None):
        raise AssertionError(f"http fallback should not run after vendor-confirmed block: {url} {timeout} {proxy}")

    async def _failing_browser(url, timeout, **kwargs):
        del timeout
        browser_proxies.append(kwargs.get("proxy"))
        raise RuntimeError(f"browser failed for {url}")

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _vendor_blocked_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _unexpected_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _failing_browser)

    with pytest.raises(RuntimeError, match="browser failed"):
        await crawl_fetch_runtime.fetch_page(
            "https://example.com/products/widget",
            proxy_list=["http://proxy-a", "http://proxy-b"],
            surface="ecommerce_detail",
        )

    assert len(curl_proxies) == 1
    assert browser_proxies == curl_proxies


@pytest.mark.asyncio
async def test_fetch_page_requires_a_timeout_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "acquisition_attempt_timeout_seconds",
        None,
    )

    with pytest.raises(ValueError, match="fetch_page requires timeout_seconds"):
        await crawl_fetch_runtime.fetch_page("https://example.com/products/widget")


@pytest.mark.asyncio
async def test_fetch_page_learns_browser_first_after_vendor_blocked_http_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://wellfound.com/location/united-states"
    curl_calls: list[str] = []
    browser_reasons: list[str | None] = []

    async def _vendor_blocked_curl(
        request_url: str,
        timeout: float,
        *,
        proxy: str | None = None,
    ):
        del timeout, proxy
        curl_calls.append(request_url)
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>blocked</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=True,
            headers={"x-datadome": "blocked"},
        )

    async def _browser_ok(request_url, timeout, **kwargs):
        del timeout
        browser_reasons.append(kwargs.get("browser_reason"))
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _vendor_blocked_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_ok)
    try:
        first = await crawl_fetch_runtime.fetch_page(url, surface="job_listing")
        second = await crawl_fetch_runtime.fetch_page(url, surface="job_listing")
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert first.method == "browser"
    assert second.method == "browser"
    assert curl_calls == [url]
    assert browser_reasons == ["vendor-block:datadome", "host-preference"]


@pytest.mark.asyncio
async def test_fetch_page_prefers_browser_after_hard_blocked_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://wellfound.com/location/united-states"
    curl_calls: list[str] = []
    browser_reasons: list[str | None] = []

    async def _vendor_blocked_curl(
        request_url: str,
        timeout: float,
        *,
        proxy: str | None = None,
    ):
        del timeout, proxy
        curl_calls.append(request_url)
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>blocked</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=True,
            headers={"x-datadome": "blocked"},
        )

    async def _browser_blocked(request_url, timeout, **kwargs):
        del timeout
        browser_reasons.append(kwargs.get("browser_reason"))
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>still blocked</body></html>",
            status_code=403,
            method="browser",
            blocked=True,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _vendor_blocked_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_blocked)
    try:
        first = await crawl_fetch_runtime.fetch_page(url, surface="job_listing")
        second = await crawl_fetch_runtime.fetch_page(url, surface="job_listing")
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert first.method == "browser"
    assert second.method == "browser"
    assert first.blocked is True
    assert second.blocked is True
    assert curl_calls == [url]
    assert browser_reasons == ["vendor-block:datadome", "host-preference"]


@pytest.mark.asyncio
async def test_http_fetch_surfaces_dns_failure_without_hidden_ipv4_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import crawl_fetch_runtime

    class _SharedClient:
        async def get(self, url: str, timeout: float):
            del url, timeout
            raise OSError(11001, "getaddrinfo failed")

    async def _fake_get_shared_http_client(*, proxy: str | None = None):
        del proxy
        return _SharedClient()

    monkeypatch.setattr(crawl_fetch_runtime, "_get_shared_http_client", _fake_get_shared_http_client)

    with pytest.raises(OSError, match="getaddrinfo failed"):
        await crawl_fetch_runtime._http_fetch("https://example.com/jobs", 10.0)


@pytest.mark.asyncio
async def test_fetch_page_reraises_latest_transport_error_when_browser_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from app.services import crawl_fetch_runtime

    curl_error = httpx.ConnectError("getaddrinfo failed")
    httpx_error = httpx.ReadTimeout("httpx fallback timed out")

    async def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del proxy
        raise curl_error

    async def _failing_http(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        raise httpx_error

    async def _failing_browser(url, timeout, **kwargs):
        raise RuntimeError("browser launch failed")

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _failing_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _failing_browser)

    with pytest.raises(httpx.ReadTimeout) as excinfo:
        await crawl_fetch_runtime.fetch_page("https://paycomonline.net/career-page")

    assert excinfo.value.browser_diagnostics["browser_attempted"] is True
    assert excinfo.value.browser_diagnostics["browser_outcome"] == "navigation_failed"
    assert excinfo.value.browser_diagnostics["failure_kind"] == "navigation_error"




@pytest.mark.asyncio
async def test_reset_fetch_runtime_state_closes_adapter_and_runtime_http_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import crawl_fetch_runtime

    calls: list[str] = []

    async def _fake_shutdown_browser_runtime() -> None:
        calls.append("browser")

    async def _fake_close_runtime_http_client() -> None:
        calls.append("runtime_http")

    async def _fake_close_adapter_http_client() -> None:
        calls.append("adapter_http")

    async def _fake_reset_pacing_state() -> None:
        calls.append("pacing")

    async def _fake_clear_cookie_store_cache() -> None:
        calls.append("cookie_store")

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "shutdown_browser_runtime",
        _fake_shutdown_browser_runtime,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "clear_cookie_store_cache",
        _fake_clear_cookie_store_cache,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "reset_pacing_state",
        _fake_reset_pacing_state,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "close_shared_http_client",
        _fake_close_runtime_http_client,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "close_adapter_shared_http_client",
        _fake_close_adapter_http_client,
    )

    await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert calls == ["browser", "cookie_store", "pacing", "runtime_http", "adapter_http"]


def test_build_playwright_context_options_reuses_identity_within_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_identity.clear_browser_identity_cache()
    created = iter(
        [
            browser_identity.BrowserIdentity(
                user_agent="ua-1",
                viewport={"width": 100, "height": 200},
                extra_http_headers={"x-test": "1"},
                locale="en-US",
                device_scale_factor=1.0,
                has_touch=False,
                is_mobile=False,
            ),
            browser_identity.BrowserIdentity(
                user_agent="ua-2",
                viewport={"width": 101, "height": 201},
                extra_http_headers={"x-test": "2"},
                locale="en-US",
                device_scale_factor=1.0,
                has_touch=False,
                is_mobile=False,
            ),
        ]
    )
    monkeypatch.setattr(
        browser_identity,
        "create_browser_identity",
        lambda: next(created),
    )

    first = browser_identity.build_playwright_context_options(run_id=101)
    second = browser_identity.build_playwright_context_options(run_id=101)
    third = browser_identity.build_playwright_context_options(run_id=202)

    assert first["user_agent"] == "ua-1"
    assert second["user_agent"] == "ua-1"
    assert third["user_agent"] == "ua-2"
    browser_identity.clear_browser_identity_cache()


def test_browser_identity_for_run_uses_single_creation_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_identity.clear_browser_identity_cache()
    created_count = 0
    creation_lock = threading.Lock()

    def _fake_create() -> browser_identity.BrowserIdentity:
        nonlocal created_count
        time.sleep(0.05)
        with creation_lock:
            created_count += 1
            sequence = created_count
        return browser_identity.BrowserIdentity(
            user_agent=f"ua-{sequence}",
            viewport={"width": 100, "height": 200},
            extra_http_headers={"x-test": str(sequence)},
            locale="en-US",
            device_scale_factor=1.0,
            has_touch=False,
            is_mobile=False,
        )

    monkeypatch.setattr(browser_identity, "create_browser_identity", _fake_create)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        identities = list(executor.map(lambda _: browser_identity.browser_identity_for_run(303), range(4)))

    assert created_count == 1
    assert {identity.user_agent for identity in identities} == {"ua-1"}
    browser_identity.clear_browser_identity_cache()


def test_create_browser_identity_builds_generator_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_identity.clear_browser_identity_cache()
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR", None)
    captured: dict[str, object] = {}

    class _FakeGenerator:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def generate(self):
            return SimpleNamespace(
                screen=SimpleNamespace(width=1280, height=720, devicePixelRatio=1.0),
                navigator=SimpleNamespace(
                    userAgent="Mozilla/5.0 Chrome/131.0.0.0",
                    language="en-US",
                    maxTouchPoints=0,
                    userAgentData={"mobile": False, "brands": []},
                ),
                headers={"accept-language": "en-US"},
            )

    monkeypatch.setattr(browser_identity, "FingerprintGenerator", _FakeGenerator)
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_locale",
        "fr-FR",
    )

    identity = browser_identity.create_browser_identity()

    assert identity.locale == "en-US"
    assert captured["locale"] == ["fr-FR"]
