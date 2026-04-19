from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services.acquisition.browser_identity import build_playwright_context_options
from app.services.acquisition.browser_runtime import (
    SharedBrowserRuntime as _SharedBrowserRuntime,
    _BROWSER_PREFERRED_HOSTS,
    _BROWSER_PREFERRED_HOST_SUCCESSES,
    _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES,
    build_failed_browser_diagnostics,
    browser_fetch,
    browser_runtime_snapshot,
    classify_network_endpoint,
    expand_all_interactive_elements,
    get_browser_runtime,
    host_prefers_browser,
    prune_browser_preferred_hosts,
    read_network_payload_body,
    remember_browser_host_if_good,
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
    classify_block_from_headers,
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
    runtime_policy: dict[str, object] | None = None,
) -> bool:
    return should_escalate_to_browser(
        result,
        surface=surface,
        runtime_policy=runtime_policy,
    )


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
    browser_reason: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
) -> PageFetchResult:
    return await browser_fetch(
        url,
        timeout_seconds,
        proxy=proxy,
        browser_reason=browser_reason,
        surface=surface,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        runtime_provider=get_browser_runtime,
        proxied_page_factory=temporary_browser_page,
        blocked_html_checker=_is_blocked_html_async,
    )


async def _is_blocked_html_async(html: str, status_code: int) -> bool:
    return await is_blocked_html_async(html, status_code)


async def _should_escalate_to_browser_async(
    result: PageFetchResult,
    *,
    surface: str | None = None,
    runtime_policy: dict[str, object] | None = None,
) -> bool:
    return await asyncio.to_thread(
        _should_escalate_to_browser,
        result,
        surface=surface,
        runtime_policy=runtime_policy,
    )


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


def _host_prefers_browser(url: str) -> bool:
    return host_prefers_browser(url)


def _vendor_confirmed_block(result: PageFetchResult) -> str | None:
    if not result.blocked:
        return None
    return classify_block_from_headers(result.headers)


def _remember_browser_host_if_good(result: PageFetchResult) -> bool:
    diagnostics = (
        dict(result.browser_diagnostics or {})
        if isinstance(result.browser_diagnostics, dict)
        else {}
    )
    return remember_browser_host_if_good(
        result.final_url,
        browser_outcome=str(diagnostics.get("browser_outcome") or "").strip().lower()
        or None,
        blocked=bool(result.blocked),
    )


async def reset_fetch_runtime_state() -> None:
    _BROWSER_PREFERRED_HOSTS.clear()
    _BROWSER_PREFERRED_HOST_SUCCESSES.clear()
    await shutdown_browser_runtime()
    await close_shared_http_client()
    await close_adapter_shared_http_client()


async def fetch_page(
    url: str,
    *,
    timeout_seconds: float | None = None,
    proxy_list: list[str] | None = None,
    prefer_browser: bool = False,
    browser_reason: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
) -> PageFetchResult:
    resolved_timeout = float(timeout_seconds or settings.http_timeout_seconds)
    runtime_policy = resolve_platform_runtime_policy(url, surface=surface)
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
    host_preference_enabled = _host_prefers_browser(url)
    traversal_required = should_run_traversal(surface, traversal_mode)
    browser_first = (
        prefer_browser
        or host_preference_enabled
        or bool(runtime_policy.get("requires_browser"))
        or traversal_required
    )
    last_browser_attempt_diagnostics: dict[str, object] = {}
    if browser_first:
        resolved_browser_reason = _resolve_browser_reason(
            browser_reason=browser_reason,
            requires_browser=bool(runtime_policy.get("requires_browser")),
            traversal_required=traversal_required,
            host_preference_enabled=host_preference_enabled,
        )
        proxy_attempts = proxies or [None]
        last_browser_error: Exception | None = None
        for proxy in proxy_attempts:
            try:
                browser_result = await _browser_fetch(
                    url,
                    resolved_timeout,
                    proxy=proxy,
                    browser_reason=resolved_browser_reason,
                    surface=surface,
                    traversal_mode=traversal_mode,
                    max_pages=max_pages,
                    max_scrolls=max_scrolls,
                )
                _remember_browser_host_if_good(browser_result)
                return browser_result
            except Exception as exc:
                last_browser_error = exc
                last_browser_attempt_diagnostics = build_failed_browser_diagnostics(
                    browser_reason=resolved_browser_reason,
                    exc=exc,
                )
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
    vendor_block_confirmed = False
    for proxy in proxy_attempts:
        if vendor_block_confirmed:
            break
        for fetcher in (_curl_fetch, _http_fetch):
            resolved_browser_reason: str | None = None
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
                vendor = _vendor_confirmed_block(result)
                if vendor:
                    vendor_block_confirmed = True
                result_runtime_policy = resolve_platform_runtime_policy(
                    result.final_url or result.url,
                    result.html,
                    surface=surface,
                )

                if vendor or await _should_escalate_to_browser_async(
                    result,
                    surface=surface,
                    runtime_policy=result_runtime_policy,
                ):
                    resolved_browser_reason = (
                        browser_reason
                        or (f"vendor-block:{vendor}" if vendor else "http-escalation")
                    )
                    browser_result = await _browser_fetch(
                        url,
                        resolved_timeout,
                        proxy=proxy,
                        browser_reason=resolved_browser_reason,
                        surface=surface,
                        traversal_mode=traversal_mode,
                        max_pages=max_pages,
                        max_scrolls=max_scrolls,
                    )
                    _remember_browser_host_if_good(browser_result)
                    return browser_result
                _attach_browser_attempt_diagnostics(
                    result,
                    diagnostics=last_browser_attempt_diagnostics,
                )
                return result
            except Exception as exc:
                last_error = exc
                if resolved_browser_reason is not None:
                    last_browser_attempt_diagnostics = build_failed_browser_diagnostics(
                        browser_reason=resolved_browser_reason,
                        exc=exc,
                    )
                logger.debug(
                    "Fetch failed for %s via %s (%s)",
                    url,
                    fetcher.__name__,
                    proxy or "direct",
                    exc_info=True,
                )
                if vendor_block_confirmed:
                    break
    if vendor_block_confirmed and last_error is not None:
        raise last_error
    if last_error is not None:
        logger.info(
            "HTTP fetchers exhausted for %s (%s); attempting browser fallback",
            url,
            type(last_error).__name__,
        )
        last_browser_error: Exception | None = None
        for proxy in proxy_attempts:
            try:
                resolved_browser_reason = browser_reason or "http-escalation"
                browser_result = await _browser_fetch(
                    url,
                    resolved_timeout,
                    proxy=proxy,
                    browser_reason=resolved_browser_reason,
                    surface=surface,
                    traversal_mode=traversal_mode,
                    max_pages=max_pages,
                    max_scrolls=max_scrolls,
                )
                _remember_browser_host_if_good(browser_result)
                return browser_result
            except Exception as exc:
                last_browser_error = exc
                last_browser_attempt_diagnostics = build_failed_browser_diagnostics(
                    browser_reason=resolved_browser_reason,
                    exc=exc,
                )
                logger.debug(
                    "Browser fallback failed for %s via %s after HTTP transport errors",
                    url,
                    proxy or "direct",
                    exc_info=True,
                )
        if last_browser_error is not None:
            raise last_error from last_browser_error
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def _attach_browser_attempt_diagnostics(
    result: PageFetchResult,
    *,
    diagnostics: dict[str, object] | None,
) -> None:
    if not diagnostics:
        return
    merged = dict(result.browser_diagnostics or {})
    merged.update(dict(diagnostics))
    result.browser_diagnostics = merged


def _resolve_browser_reason(
    *,
    browser_reason: str | None,
    requires_browser: bool,
    traversal_required: bool,
    host_preference_enabled: bool,
) -> str:
    if str(browser_reason or "").strip():
        return str(browser_reason).strip().lower()
    if requires_browser:
        return "platform-required"
    if traversal_required:
        return "traversal-required"
    if host_preference_enabled:
        return "host-preference"
    return "http-escalation"


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
