from __future__ import annotations

import pytest

from app.services import crawl_fetch_runtime
from app.services.acquisition.browser_runtime import (
    classify_network_endpoint,
    read_network_payload_body,
    should_capture_network_payload,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.acquisition.runtime import PageFetchResult, should_escalate_to_browser_async


class _FakeResponse:
    def __init__(self, body: bytes | None = None, *, error: Exception | None = None) -> None:
        self._body = body
        self._error = error
        self.body_calls = 0

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


def test_classify_network_endpoint_uses_platform_config_family_signatures() -> None:
    assert classify_network_endpoint(
        response_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs/1234",
        surface="job_detail",
    ) == {"type": "job_api", "family": "greenhouse"}
    assert classify_network_endpoint(
        response_url="https://shop.example.com/products/widget/product.js",
        surface="ecommerce_detail",
    ) == {"type": "product_api", "family": "shopify"}
    assert classify_network_endpoint(
        response_url="https://store.example.com/_next/data/build-id/widget.json",
        surface="ecommerce_detail",
    ) == {"type": "generic_json", "family": "nextjs"}


@pytest.mark.asyncio
async def test_read_network_payload_body_rejects_oversized_body_before_decode() -> None:
    response = _FakeResponse(b"x" * 600_000)

    body = await read_network_payload_body(response)

    assert body.outcome == "too_large"
    assert body.body is None
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
async def test_fetch_page_falls_back_to_browser_after_http_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from app.services import crawl_fetch_runtime

    async def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del proxy
        raise httpx.TooManyRedirects("redirect loop")

    async def _failing_http(url: str, timeout: float, *, proxy: str | None = None):
        del proxy
        raise OSError(11001, "getaddrinfo failed")

    browser_calls: list[str] = []

    async def _fake_browser(url, timeout, **kwargs):
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
        "https://ar.puma.com/pd/widget.html",
        surface="ecommerce_detail",
    )

    assert result.method == "browser"
    assert browser_calls == ["https://ar.puma.com/pd/widget.html"]


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
async def test_http_fetch_retries_with_forced_ipv4_after_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import crawl_fetch_runtime

    class _FakeResponse:
        status_code = 200
        url = "https://example.com/jobs"
        headers = {"content-type": "text/html"}
        text = "<html><body>ok</body></html>"

    class _SharedClient:
        async def get(self, url: str, timeout: float):
            del url, timeout
            raise OSError(11001, "getaddrinfo failed")

    class _RetryClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, timeout: float):
            del url, timeout
            return _FakeResponse()

    retry_builds: list[bool] = []

    def _fake_build_async_http_client(**kwargs):
        retry_builds.append(bool(kwargs.get("force_ipv4")))
        return _RetryClient()

    async def _fake_is_blocked_html_async(html: str, status_code: int) -> bool:
        del html, status_code
        return False

    async def _fake_get_shared_http_client(*, proxy: str | None = None):
        del proxy
        return _SharedClient()

    monkeypatch.setattr(crawl_fetch_runtime, "_get_shared_http_client", _fake_get_shared_http_client)
    monkeypatch.setattr(crawl_fetch_runtime, "build_async_http_client", _fake_build_async_http_client)
    monkeypatch.setattr(crawl_fetch_runtime, "_is_blocked_html_async", _fake_is_blocked_html_async)

    result = await crawl_fetch_runtime._http_fetch("https://example.com/jobs", 10.0)

    assert retry_builds == [True]
    assert result.method == "httpx"
    assert result.final_url == "https://example.com/jobs"


@pytest.mark.asyncio
async def test_fetch_page_reraises_original_transport_error_when_browser_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from app.services import crawl_fetch_runtime

    original_error = httpx.ConnectError("getaddrinfo failed")

    async def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del proxy
        raise original_error

    async def _failing_http(url: str, timeout: float, *, proxy: str | None = None):
        del proxy
        raise original_error

    async def _failing_browser(url, timeout, **kwargs):
        raise RuntimeError("browser launch failed")

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _failing_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _failing_browser)

    with pytest.raises(httpx.ConnectError):
        await crawl_fetch_runtime.fetch_page("https://paycomonline.net/career-page")


@pytest.mark.asyncio
async def test_fetch_page_host_preference_requires_repeated_good_browser_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    original_threshold = crawler_runtime_settings.browser_preference_min_successes
    crawler_runtime_settings.browser_preference_min_successes = 2
    try:
        curl_calls: list[str] = []
        browser_calls: list[str] = []
        should_escalate_values = iter([True, True, False])

        async def _fake_curl(url: str, timeout: float, *, proxy: str | None = None):
            del timeout, proxy
            curl_calls.append(url)
            return PageFetchResult(
                url=url,
                final_url=url,
                html="<html><body>http</body></html>",
                status_code=200,
                method="curl_cffi",
                blocked=False,
            )

        async def _unexpected_http(url: str, timeout: float, *, proxy: str | None = None):
            raise AssertionError(f"http fallback should not run for {url} {timeout} {proxy}")

        async def _fake_should_escalate(result: PageFetchResult, *, surface: str | None = None) -> bool:
            del result, surface
            return next(should_escalate_values)

        async def _fake_browser(url, timeout, **kwargs):
            del timeout, kwargs
            browser_calls.append(url)
            return PageFetchResult(
                url=url,
                final_url=url,
                html="<html><body>browser</body></html>",
                status_code=200,
                method="browser",
                blocked=False,
                browser_diagnostics={"browser_outcome": "usable_content"},
            )

        monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
        monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _unexpected_http)
        monkeypatch.setattr(
            crawl_fetch_runtime,
            "_should_escalate_to_browser_async",
            _fake_should_escalate,
        )
        monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

        first = await crawl_fetch_runtime.fetch_page("https://example.com/products/1")
        second = await crawl_fetch_runtime.fetch_page("https://example.com/products/2")
        third = await crawl_fetch_runtime.fetch_page("https://example.com/products/3")

        assert first.method == "browser"
        assert second.method == "browser"
        assert third.method == "browser"
        assert curl_calls == [
            "https://example.com/products/1",
            "https://example.com/products/2",
        ]
        assert browser_calls == [
            "https://example.com/products/1",
            "https://example.com/products/2",
            "https://example.com/products/3",
        ]
    finally:
        crawler_runtime_settings.browser_preference_min_successes = original_threshold
        await crawl_fetch_runtime.reset_fetch_runtime_state()


@pytest.mark.asyncio
async def test_fetch_page_does_not_prefer_host_after_bad_browser_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    curl_calls: list[str] = []
    browser_calls: list[str] = []
    should_escalate_values = iter([True, False])

    async def _fake_curl(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        curl_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>http</body></html>",
            status_code=200,
            method="curl_cffi",
            blocked=False,
        )

    async def _unexpected_http(url: str, timeout: float, *, proxy: str | None = None):
        raise AssertionError(f"http fallback should not run for {url} {timeout} {proxy}")

    async def _fake_should_escalate(result: PageFetchResult, *, surface: str | None = None) -> bool:
        del result, surface
        return next(should_escalate_values)

    async def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        browser_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>challenge</body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={"browser_outcome": "challenge_page"},
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _unexpected_http)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_should_escalate_to_browser_async",
        _fake_should_escalate,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    first = await crawl_fetch_runtime.fetch_page("https://example.com/products/1")
    second = await crawl_fetch_runtime.fetch_page("https://example.com/products/2")

    assert first.method == "browser"
    assert second.method == "curl_cffi"
    assert curl_calls == [
        "https://example.com/products/1",
        "https://example.com/products/2",
    ]
    assert browser_calls == ["https://example.com/products/1"]


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

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "shutdown_browser_runtime",
        _fake_shutdown_browser_runtime,
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

    assert calls == ["browser", "runtime_http", "adapter_http"]
