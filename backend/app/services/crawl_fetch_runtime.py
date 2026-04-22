from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.acquisition.browser_identity import build_playwright_context_options
from app.services.acquisition.browser_runtime import (
    SharedBrowserRuntime as _SharedBrowserRuntime,
    _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES,
    build_failed_browser_diagnostics,
    browser_fetch,
    browser_runtime_snapshot,
    classify_network_endpoint,
    expand_all_interactive_elements,
    get_browser_runtime,
    read_network_payload_body,
    should_capture_network_payload,
    shutdown_browser_runtime,
    temporary_browser_page,
)
from app.services.acquisition.http_client import (
    close_shared_http_client as close_adapter_shared_http_client,
)
from app.services.acquisition.pacing import (
    apply_protected_host_backoff,
    wait_for_host_slot,
)
from app.services.acquisition.runtime import (
    NetworkPayloadReadResult,
    PageFetchResult,
    classify_block_from_headers,
    close_shared_http_client,
    curl_fetch,
    get_shared_http_client,
    http_fetch,
    is_blocked_html,
    is_blocked_html_async,
    is_non_retryable_http_status,
    should_escalate_to_browser,
)
from app.services.acquisition.traversal import should_run_traversal
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.platform_policy import resolve_platform_runtime_policy

logger = logging.getLogger(__name__)


def _attach_exception_browser_diagnostics(
    exc: Exception | None,
    diagnostics: dict[str, object] | None,
) -> None:
    if exc is None or not diagnostics:
        return
    setattr(exc, "browser_diagnostics", dict(diagnostics))


@dataclass(slots=True)
class _FetchRuntimeContext:
    url: str
    resolved_timeout: float
    run_id: int | None
    surface: str | None
    traversal_mode: str | None
    max_pages: int
    max_scrolls: int
    on_event: object | None
    browser_reason: str | None
    requested_fields: list[str]
    listing_recovery_mode: str | None
    proxies: list[str | None]
    traversal_required: bool
    runtime_policy: dict[str, object]
    last_browser_attempt_diagnostics: dict[str, object] = field(default_factory=dict)
    last_error: Exception | None = None


def _ensure_scheme(url: str) -> str:
    """Prepend ``https://`` when *url* has no scheme.

    Inputs that already include a scheme are returned unchanged. Inputs that
    start with ``/``, ``#``, or ``javascript:`` are also returned unchanged;
    callers must validate or reject those values separately because this helper
    does not guarantee an absolute URL.
    """
    stripped = str(url or "").strip()
    if not stripped:
        return stripped
    parsed = urlparse(stripped)
    if parsed.scheme:
        return stripped
    if stripped.startswith(("/", "#", "javascript:")):
        return stripped
    return f"https://{stripped}"


class SharedBrowserRuntime(_SharedBrowserRuntime):
    def _build_context_options(self, *, run_id: int | None = None) -> dict[str, object]:
        return build_playwright_context_options(run_id=run_id)


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
    run_id: int | None = None,
    proxy: str | None = None,
    browser_reason: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    requested_fields: list[str] | None = None,
    listing_recovery_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
    on_event=None,
) -> PageFetchResult:
    return await browser_fetch(
        url,
        timeout_seconds,
        run_id=run_id,
        proxy=proxy,
        browser_reason=browser_reason,
        surface=surface,
        traversal_mode=traversal_mode,
        requested_fields=requested_fields,
        listing_recovery_mode=listing_recovery_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        on_event=on_event,
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


def _vendor_confirmed_block(result: PageFetchResult) -> str | None:
    if not result.blocked:
        return None
    return classify_block_from_headers(result.headers)


async def reset_fetch_runtime_state() -> None:
    await shutdown_browser_runtime()
    await close_shared_http_client()
    await close_adapter_shared_http_client()


async def fetch_page(
    url: str,
    *,
    run_id: int | None = None,
    timeout_seconds: float | None = None,
    proxy_list: list[str] | None = None,
    prefer_browser: bool = False,
    browser_reason: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    requested_fields: list[str] | None = None,
    listing_recovery_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
    on_event=None,
) -> PageFetchResult:
    url = _ensure_scheme(url)
    context = _FetchRuntimeContext(
        url=url,
        resolved_timeout=float(timeout_seconds or settings.http_timeout_seconds),
        run_id=run_id,
        surface=surface,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        on_event=on_event,
        browser_reason=browser_reason,
        requested_fields=list(requested_fields or []),
        listing_recovery_mode=str(listing_recovery_mode or "").strip() or None,
        proxies=_resolve_proxy_attempts(proxy_list),
        traversal_required=should_run_traversal(surface, traversal_mode),
        runtime_policy=resolve_platform_runtime_policy(url, surface=surface),
    )
    browser_first = (
        prefer_browser
        or bool(context.runtime_policy.get("requires_browser"))
        or context.traversal_required
    )
    if browser_first:
        return await _run_browser_attempts(
            context,
            reason=_resolve_browser_reason(
                browser_reason=browser_reason,
                requires_browser=bool(context.runtime_policy.get("requires_browser")),
                traversal_required=context.traversal_required,
                host_preference_enabled=False,
            ),
            requested_fields=context.requested_fields,
            listing_recovery_mode=context.listing_recovery_mode,
        )

    http_result, vendor_block_confirmed = await _run_http_fetch_chain(context)
    if http_result is not None:
        return http_result
    if vendor_block_confirmed and context.last_error is not None:
        raise context.last_error
    if context.last_error is not None:
        logger.info(
            "HTTP fetchers exhausted for %s (%s); attempting browser fallback",
            context.url,
            type(context.last_error).__name__,
        )
        try:
            return await _run_browser_attempts(
                context,
                reason=browser_reason or "http-escalation",
                requested_fields=context.requested_fields,
                listing_recovery_mode=context.listing_recovery_mode,
            )
        except (httpx.HTTPError, OSError, TimeoutError, RuntimeError) as exc:
            _attach_exception_browser_diagnostics(
                context.last_error,
                context.last_browser_attempt_diagnostics,
            )
            raise context.last_error from exc
    raise RuntimeError(f"Failed to fetch {url}")


def _resolve_proxy_attempts(proxy_list: list[str] | None) -> list[str | None]:
    proxies = [
        value
        for value in {
            str(proxy or "").strip()
            for proxy in list(proxy_list or [])
            if str(proxy or "").strip()
        }
        if value
    ]
    return proxies or [None]


async def _run_browser_attempts(
    context: _FetchRuntimeContext,
    *,
    reason: str,
    requested_fields: list[str] | None = None,
    listing_recovery_mode: str | None = None,
    proxies: list[str | None] | None = None,
) -> PageFetchResult:
    last_browser_error: Exception | None = None
    browser_requested_fields = (
        list(context.requested_fields)
        if requested_fields is None
        else list(requested_fields)
    )
    recovery_mode = (
        str(context.listing_recovery_mode or "").strip() or None
        if listing_recovery_mode is None
        else str(listing_recovery_mode or "").strip() or None
    )
    for proxy in list(proxies or context.proxies):
        try:
            await wait_for_host_slot(context.url)
            return await _browser_fetch(
                context.url,
                context.resolved_timeout,
                run_id=context.run_id,
                proxy=proxy,
                browser_reason=reason,
                surface=context.surface,
                traversal_mode=context.traversal_mode,
                requested_fields=browser_requested_fields,
                listing_recovery_mode=recovery_mode,
                max_pages=context.max_pages,
                max_scrolls=context.max_scrolls,
                on_event=context.on_event,
            )
        except (httpx.HTTPError, OSError, TimeoutError, RuntimeError) as exc:
            last_browser_error = exc
            context.last_browser_attempt_diagnostics = build_failed_browser_diagnostics(
                browser_reason=reason,
                exc=exc,
            )
            _attach_exception_browser_diagnostics(
                exc,
                context.last_browser_attempt_diagnostics,
            )
            logger.debug(
                "Browser fetch failed for %s via %s",
                context.url,
                proxy or "direct",
                exc_info=True,
            )
    if last_browser_error is not None:
        _attach_exception_browser_diagnostics(
            last_browser_error,
            context.last_browser_attempt_diagnostics,
        )
        raise last_browser_error
    raise RuntimeError(f"Failed to fetch {context.url} in browser")


async def _run_http_fetch_chain(
    context: _FetchRuntimeContext,
) -> tuple[PageFetchResult | None, bool]:
    vendor_block_confirmed = False
    fetcher = _select_http_fetcher(context)
    for proxy in context.proxies:
        if vendor_block_confirmed:
            break
        result, vendor_block_confirmed = await _run_http_fetcher_attempts(
            context,
            fetcher=fetcher,
            proxy=proxy,
        )
        if result is not None:
            return result, vendor_block_confirmed
    return None, vendor_block_confirmed


def _select_http_fetcher(context: _FetchRuntimeContext):
    del context
    return _curl_fetch


async def _run_http_fetcher_attempts(
    context: _FetchRuntimeContext,
    *,
    fetcher,
    proxy: str | None,
) -> tuple[PageFetchResult | None, bool]:
    max_attempts = max(1, int(crawler_runtime_settings.http_max_retries) + 1)
    for attempt in range(1, max_attempts + 1):
        result = await _attempt_http_fetch(context, fetcher=fetcher, proxy=proxy, attempt=attempt, max_attempts=max_attempts)
        if result is _HTTP_ATTEMPT_FAILED:
            if attempt < max_attempts:
                continue
            break
        handled_result, vendor_block_confirmed = await _handle_http_result(
            context,
            result=result,
            proxy=proxy,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        if handled_result is _RETRY_SENTINEL:
            continue
        return handled_result, vendor_block_confirmed
    return None, False


_RETRY_SENTINEL = object()
_HTTP_ATTEMPT_FAILED = object()


async def _attempt_http_fetch(
    context: _FetchRuntimeContext,
    *,
    fetcher,
    proxy: str | None,
    attempt: int,
    max_attempts: int,
) -> PageFetchResult | object:
    try:
        await wait_for_host_slot(context.url)
        if proxy is not None:
            return await fetcher(context.url, context.resolved_timeout, proxy=proxy)
        return await fetcher(context.url, context.resolved_timeout)
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        context.last_error = exc
        logger.debug(
            "Retryable fetch failure for %s via %s (%s attempt=%s/%s)",
            context.url,
            fetcher.__name__,
            proxy or "direct",
            attempt,
            max_attempts,
            exc_info=True,
        )
        if attempt < max_attempts:
            await _sleep_before_retry(attempt)
        return _HTTP_ATTEMPT_FAILED
    except RuntimeError as exc:
        context.last_error = exc
        logger.debug(
            "Fetch failed for %s via %s (%s)",
            context.url,
            fetcher.__name__,
            proxy or "direct",
            exc_info=True,
        )
        return _HTTP_ATTEMPT_FAILED


async def _handle_http_result(
    context: _FetchRuntimeContext,
    *,
    result: PageFetchResult,
    proxy: str | None,
    attempt: int,
    max_attempts: int,
) -> tuple[PageFetchResult | object | None, bool]:
    vendor = _vendor_confirmed_block(result)
    if vendor or bool(result.blocked):
        await apply_protected_host_backoff(result.final_url or result.url or context.url)
    result_runtime_policy = resolve_platform_runtime_policy(
        result.final_url or result.url,
        result.html,
        surface=context.surface,
    )
    should_browser_escalate = bool(vendor) or await _should_escalate_to_browser_async(
        result,
        surface=context.surface,
        runtime_policy=result_runtime_policy,
    )
    if (
        _retryable_status_for_http_fetch(result.status_code)
        and not vendor
        and not should_browser_escalate
        and attempt < max_attempts
    ):
        await _sleep_before_retry(attempt)
        return _RETRY_SENTINEL, False
    if should_browser_escalate:
        browser_reason = (
            context.browser_reason
            or (f"vendor-block:{vendor}" if vendor else "http-escalation")
        )
        browser_result = await _run_browser_attempts(
            context,
            reason=browser_reason,
            requested_fields=context.requested_fields,
            listing_recovery_mode=context.listing_recovery_mode,
            proxies=[proxy],
        )
        if bool(browser_result.blocked):
            await apply_protected_host_backoff(
                browser_result.final_url or browser_result.url or context.url
            )
        return browser_result, bool(vendor)
    if is_non_retryable_http_status(result.status_code):
        logger.info(
            "Returning non-retryable HTTP status %s for %s without browser fallback",
            result.status_code,
            context.url,
        )
        return result, bool(vendor)
    _attach_browser_attempt_diagnostics(
        result,
        diagnostics=context.last_browser_attempt_diagnostics,
    )
    return result, bool(vendor)


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


def _retryable_status_for_http_fetch(status_code: int) -> bool:
    code = int(status_code or 0)
    return code in {int(value) for value in list(crawler_runtime_settings.http_retry_status_codes or [])}


async def _sleep_before_retry(attempt: int) -> None:
    base_ms = max(0, int(crawler_runtime_settings.http_retry_backoff_base_ms))
    max_ms = max(base_ms, int(crawler_runtime_settings.http_retry_backoff_max_ms))
    delay_ms = min(max_ms, base_ms * (2 ** max(0, attempt - 1)))
    if delay_ms <= 0:
        return
    jitter_ms = secrets.randbelow(max(1, delay_ms // 4) + 1)
    await asyncio.sleep((delay_ms + jitter_ms) / 1000)


__all__ = [
    "PageFetchResult",
    "SharedBrowserRuntime",
    "_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES",
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
