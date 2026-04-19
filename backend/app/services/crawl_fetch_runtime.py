from __future__ import annotations

import asyncio
import logging
import traceback

from app.core.config import settings
from app.services.acquisition.browser_identity import build_playwright_context_options
from app.services.acquisition.browser_runtime import (
    SharedBrowserRuntime as _SharedBrowserRuntime,
    _BROWSER_PREFERRED_HOSTS,
    _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES,
    browser_fetch,
    browser_runtime_snapshot,
    classify_network_endpoint,
    expand_all_interactive_elements,
    get_browser_runtime,
    host_prefers_browser,
    prune_browser_preferred_hosts,
    read_network_payload_body,
    remember_browser_host,
    should_capture_network_payload,
    shutdown_browser_runtime,
    temporary_browser_page,
)
from app.services.acquisition.http_client import (
    close_shared_http_client as close_adapter_shared_http_client,
)
from app.services.acquisition.runtime import (
    NetworkPayloadReadResult,
    PageFetchResult,
    close_shared_http_client,
    copy_headers,
    curl_fetch,
    get_shared_http_client,
    http_fetch,
    is_blocked_html,
    is_blocked_html_async,
    is_non_retryable_http_status,
    should_escalate_to_browser,
    should_escalate_to_browser_async,
)
from app.services.acquisition.traversal import should_run_traversal
from app.services.network_resolution import build_async_http_client
from app.services.platform_policy import resolve_platform_runtime_policy

logger = logging.getLogger(__name__)


class SharedBrowserRuntime(_SharedBrowserRuntime):
    def _build_context_options(self) -> dict[str, object]:
        return build_playwright_context_options()


def _copy_headers(headers):
    return copy_headers(headers)


def _should_escalate_to_browser(
    result: PageFetchResult,
    *,
    surface: str | None = None,
) -> bool:
    return should_escalate_to_browser(result, surface=surface)


async def _get_shared_http_client(*, proxy: str | None = None):
    return await get_shared_http_client(proxy=proxy)


async def _http_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
) -> PageFetchResult:
    return await http_fetch(
        url,
        timeout_seconds,
        proxy=proxy,
        get_client=_get_shared_http_client,
        client_builder=build_async_http_client,
        blocked_html_checker=_is_blocked_html_async,
    )


async def _curl_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
) -> PageFetchResult:
    return await curl_fetch(url, timeout_seconds, proxy=proxy)


async def _browser_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
) -> PageFetchResult:
    return await browser_fetch(
        url,
        timeout_seconds,
        proxy=proxy,
        surface=surface,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        runtime_provider=get_browser_runtime,
        proxied_page_factory=temporary_browser_page,
        blocked_html_checker=_is_blocked_html_async,
    )


async def _call_browser_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
) -> PageFetchResult:
    browser_kwargs = {
        "surface": surface,
        "traversal_mode": traversal_mode,
        "max_pages": max_pages,
        "max_scrolls": max_scrolls,
    }
    if proxy is not None:
        browser_kwargs["proxy"] = proxy
    try:
        return await _browser_fetch(url, timeout_seconds, **browser_kwargs)
    except TypeError as exc:
        message = str(exc)
        if "unexpected keyword argument" not in message or not _is_browser_fetch_signature_error(exc):
            raise
        logger.info(
            "Falling back to legacy _browser_fetch signature without traversal parameters for %s; dropped proxy=%r surface=%r traversal_mode=%r max_pages=%r max_scrolls=%r; error=%s",
            url,
            proxy,
            surface,
            traversal_mode,
            max_pages,
            max_scrolls,
            message,
        )
        if proxy is not None:
            return await _browser_fetch(url, timeout_seconds, proxy=proxy)
        return await _browser_fetch(url, timeout_seconds)


def _is_browser_fetch_signature_error(exc: TypeError) -> bool:
    frames = traceback.extract_tb(exc.__traceback__)
    return any(frame.name in {"_call_browser_fetch", "_browser_fetch"} for frame in frames)


async def _is_blocked_html_async(html: str, status_code: int) -> bool:
    return await is_blocked_html_async(html, status_code)


async def _should_escalate_to_browser_async(
    result: PageFetchResult,
    *,
    surface: str | None = None,
) -> bool:
    return await asyncio.to_thread(_should_escalate_to_browser, result, surface=surface)


def _should_capture_network_payload(*, url: str, content_type: str, headers, captured_count: int) -> bool:
    return should_capture_network_payload(
        url=url,
        content_type=content_type,
        headers=headers,
        captured_count=captured_count,
    )


def _classify_network_endpoint(*, response_url: str, surface: str) -> dict[str, str]:
    return classify_network_endpoint(response_url=response_url, surface=surface)


async def _read_network_payload_body(response) -> NetworkPayloadReadResult:
    return await read_network_payload_body(response)


def _remember_browser_host(url: str) -> None:
    remember_browser_host(url)


def _host_prefers_browser(url: str) -> bool:
    return host_prefers_browser(url)


async def reset_fetch_runtime_state() -> None:
    _BROWSER_PREFERRED_HOSTS.clear()
    await shutdown_browser_runtime()
    await close_shared_http_client()
    await close_adapter_shared_http_client()


async def fetch_page(
    url: str,
    *,
    timeout_seconds: float | None = None,
    proxy_list: list[str] | None = None,
    prefer_browser: bool = False,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
) -> PageFetchResult:
    resolved_timeout = float(timeout_seconds or settings.http_timeout_seconds)
    runtime_policy = resolve_platform_runtime_policy(url)
    proxies = [
        value
        for value in {
            str(proxy or "").strip()
            for proxy in list(proxy_list or [])
            if str(proxy or "").strip()
        }
        if value
    ]
    prune_browser_preferred_hosts()
    browser_first = (
        prefer_browser
        or _host_prefers_browser(url)
        or bool(runtime_policy.get("requires_browser"))
        or should_run_traversal(surface, traversal_mode)
    )
    if browser_first:
        proxy_attempts = proxies or [None]
        last_browser_error: Exception | None = None
        for proxy in proxy_attempts:
            try:
                browser_result = await _call_browser_fetch(
                    url,
                    resolved_timeout,
                    proxy=proxy,
                    surface=surface,
                    traversal_mode=traversal_mode,
                    max_pages=max_pages,
                    max_scrolls=max_scrolls,
                )
                _remember_browser_host(browser_result.final_url)
                return browser_result
            except Exception as exc:
                last_browser_error = exc
                logger.debug(
                    "Browser fetch failed for %s via %s",
                    url,
                    proxy or "direct",
                    exc_info=True,
                )
        if last_browser_error is not None:
            raise last_browser_error

    last_error: Exception | None = None
    proxy_attempts = proxies or [None]
    for proxy in proxy_attempts:
        for fetcher in (_curl_fetch, _http_fetch):
            try:
                if proxy is not None:
                    result = await fetcher(url, resolved_timeout, proxy=proxy)
                else:
                    result = await fetcher(url, resolved_timeout)
                if is_non_retryable_http_status(result.status_code):
                    logger.info(
                        "Returning non-retryable HTTP status %s for %s without browser fallback",
                        result.status_code,
                        url,
                    )
                    return result
                if await _should_escalate_to_browser_async(result, surface=surface):
                    browser_result = await _call_browser_fetch(
                        url,
                        resolved_timeout,
                        proxy=proxy,
                        surface=surface,
                        traversal_mode=traversal_mode,
                        max_pages=max_pages,
                        max_scrolls=max_scrolls,
                    )
                    _remember_browser_host(browser_result.final_url)
                    return browser_result
                return result
            except Exception as exc:
                last_error = exc
                logger.debug(
                    "Fetch failed for %s via %s (%s)",
                    url,
                    fetcher.__name__,
                    proxy or "direct",
                    exc_info=True,
                )
    if last_error is not None:
        logger.info(
            "HTTP fetchers exhausted for %s (%s); attempting browser fallback",
            url,
            type(last_error).__name__,
        )
        last_browser_error: Exception | None = None
        for proxy in proxy_attempts:
            try:
                browser_result = await _call_browser_fetch(
                    url,
                    resolved_timeout,
                    proxy=proxy,
                    surface=surface,
                    traversal_mode=traversal_mode,
                    max_pages=max_pages,
                    max_scrolls=max_scrolls,
                )
                _remember_browser_host(browser_result.final_url)
                return browser_result
            except Exception as exc:
                last_browser_error = exc
                logger.debug(
                    "Browser fallback failed for %s via %s after HTTP transport errors",
                    url,
                    proxy or "direct",
                    exc_info=True,
                )
        if last_browser_error is not None:
            raise type(last_error)(
                f"{last_error} (browser fallback failed: {last_browser_error})"
            ) from last_browser_error
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


__all__ = [
    "PageFetchResult",
    "SharedBrowserRuntime",
    "_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES",
    "_BROWSER_PREFERRED_HOSTS",
    "_classify_network_endpoint",
    "_curl_fetch",
    "_http_fetch",
    "_read_network_payload_body",
    "_should_capture_network_payload",
    "_should_escalate_to_browser_async",
    "browser_runtime_snapshot",
    "close_shared_http_client",
    "expand_all_interactive_elements",
    "fetch_page",
    "is_blocked_html",
    "reset_fetch_runtime_state",
    "shutdown_browser_runtime",
]
