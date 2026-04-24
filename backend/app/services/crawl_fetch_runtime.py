from __future__ import annotations

import asyncio
import inspect
import logging
import secrets
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlparse, urlunparse

import httpx

from app.services.acquisition.browser_identity import (
    PlaywrightContextSpec,
    build_playwright_context_options,
    build_playwright_context_spec,
)
from app.services.acquisition.browser_runtime import (
    SharedBrowserRuntime as _SharedBrowserRuntime,
    _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES,
    _display_proxy,
    _proxy_scheme,
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
from app.services.acquisition.host_protection_memory import (
    HostProtectionPolicy,
    load_host_protection_policy,
    note_host_hard_block,
    note_host_usable_fetch,
)
from app.services.acquisition.cookie_store import clear_cookie_store_cache
from app.services.acquisition.http_client import (
    close_shared_http_client as close_adapter_shared_http_client,
)
from app.services.acquisition.pacing import (
    apply_protected_host_backoff,
    mark_browser_first_host,
    note_browser_block_for_host,
    note_usable_fetch_for_host,
    reset_pacing_state,
    should_prefer_browser_for_host,
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
    proxy_profile: dict[str, object]
    traversal_required: bool
    fetch_mode: str
    runtime_policy: dict[str, object]
    locality_profile: dict[str, object] = field(default_factory=dict)
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
    def _build_context_spec(
        self,
        *,
        run_id: int | None = None,
        locality_profile: dict[str, object] | None = None,
        inject_init_script: bool = False,
    ) -> PlaywrightContextSpec:
        spec = build_playwright_context_spec(
            run_id=run_id,
            locality_profile=locality_profile,
        )
        if inject_init_script:
            return spec
        return PlaywrightContextSpec(
            context_options=dict(spec.context_options),
            init_script=None,
        )

    def _build_context_options(
        self,
        *,
        run_id: int | None = None,
        locality_profile: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return build_playwright_context_options(
            run_id=run_id,
            locality_profile=locality_profile,
        )


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
    browser_engine: str = "chromium",
    browser_reason: str | None = None,
    escalation_lane: str | None = None,
    host_policy_snapshot: dict[str, object] | None = None,
    proxy_profile: dict[str, object] | None = None,
    locality_profile: dict[str, object] | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    requested_fields: list[str] | None = None,
    listing_recovery_mode: str | None = None,
    capture_page_markdown: bool = False,
    max_pages: int = 1,
    max_scrolls: int = 1,
    on_event=None,
) -> PageFetchResult:
    return await browser_fetch(
        url,
        timeout_seconds,
        run_id=run_id,
        proxy=proxy,
        browser_engine=browser_engine,
        browser_reason=browser_reason,
        escalation_lane=escalation_lane,
        host_policy_snapshot=host_policy_snapshot,
        proxy_profile=proxy_profile,
        locality_profile=locality_profile,
        surface=surface,
        traversal_mode=traversal_mode,
        requested_fields=requested_fields,
        listing_recovery_mode=listing_recovery_mode,
        capture_page_markdown=capture_page_markdown,
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
    await clear_cookie_store_cache()
    await reset_pacing_state()
    await close_shared_http_client()
    await close_adapter_shared_http_client()


async def fetch_page(
    url: str,
    *,
    run_id: int | None = None,
    timeout_seconds: float | None = None,
    proxy_list: list[str] | None = None,
    proxy_profile: dict[str, object] | None = None,
    locality_profile: dict[str, object] | None = None,
    fetch_mode: str = "auto",
    prefer_browser: bool = False,
    browser_reason: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    requested_fields: list[str] | None = None,
    listing_recovery_mode: str | None = None,
    capture_page_markdown: bool = False,
    max_pages: int = 1,
    max_scrolls: int = 1,
    on_event=None,
) -> PageFetchResult:
    url = _ensure_scheme(url)
    resolved_timeout_source = timeout_seconds
    if resolved_timeout_source is None:
        resolved_timeout_source = (
            crawler_runtime_settings.acquisition_attempt_timeout_seconds
        )
    if resolved_timeout_source is None:
        raise ValueError(
            "fetch_page requires timeout_seconds or "
            "crawler_runtime_settings.acquisition_attempt_timeout_seconds"
        )
    context = _FetchRuntimeContext(
        url=url,
        resolved_timeout=float(resolved_timeout_source),
        run_id=run_id,
        surface=surface,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        on_event=on_event,
        browser_reason=browser_reason,
        requested_fields=list(requested_fields or []),
        listing_recovery_mode=str(listing_recovery_mode or "").strip() or None,
        proxies=_resolve_proxy_attempts(
            proxy_list,
            run_id=run_id,
            proxy_profile=proxy_profile,
        ),
        proxy_profile=_normalize_proxy_profile(proxy_profile),
        locality_profile=dict(locality_profile or {})
        if isinstance(locality_profile, dict)
        else {},
        traversal_required=should_run_traversal(surface, traversal_mode),
        fetch_mode=_normalize_fetch_mode(fetch_mode),
        runtime_policy=resolve_platform_runtime_policy(url, surface=surface),
    )
    learned_host_policy = await load_host_protection_policy(url)
    host_preference_enabled = bool(
        await should_prefer_browser_for_host(url) or learned_host_policy.prefer_browser
    )
    browser_first = _browser_first_decision(
        context=context,
        prefer_browser=prefer_browser,
        host_preference_enabled=host_preference_enabled,
    )
    if browser_first:
        resolved_browser_reason = _resolve_browser_reason(
            browser_reason=browser_reason,
            requires_browser=bool(context.runtime_policy.get("requires_browser")),
            traversal_required=context.traversal_required,
            host_preference_enabled=host_preference_enabled,
        )
        browser_result = await _invoke_run_browser_attempts(
            context,
            reason=resolved_browser_reason,
            requested_fields=context.requested_fields,
            listing_recovery_mode=context.listing_recovery_mode,
            capture_page_markdown=bool(capture_page_markdown),
            proxies=context.proxies,
            host_policy=learned_host_policy,
        )
        await _update_host_result_memory(
            context,
            result=browser_result,
        )
        return browser_result

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
            return await _invoke_run_browser_attempts(
                context,
                reason=browser_reason or "http-escalation",
                requested_fields=context.requested_fields,
                listing_recovery_mode=context.listing_recovery_mode,
                capture_page_markdown=bool(capture_page_markdown),
                proxies=context.proxies,
                host_policy=learned_host_policy,
            )
        except (httpx.HTTPError, OSError, TimeoutError, RuntimeError) as exc:
            _attach_exception_browser_diagnostics(
                context.last_error,
                context.last_browser_attempt_diagnostics,
            )
            raise context.last_error from exc
    raise RuntimeError(f"Failed to fetch {url}")


def _resolve_proxy_attempts(
    proxy_list: list[str] | None,
    run_id: int | None = None,
    proxy_profile: dict[str, object] | None = None,
) -> list[str | None]:
    seen: set[str] = set()
    proxies: list[str] = []
    session_rewrite_enabled = _proxy_session_rewrite_enabled(proxy_profile)
    for proxy in list(proxy_list or []):
        value = str(proxy or "").strip()
        if not value:
            continue
        if session_rewrite_enabled:
            value = _attach_proxy_run_session(value, run_id=run_id)
        if value in seen:
            continue
        seen.add(value)
        proxies.append(value)
    return [*proxies] if proxies else [None]


def _attach_proxy_run_session(proxy_url: str, *, run_id: int | None) -> str:
    if run_id is None:
        return proxy_url
    raw_proxy = str(proxy_url or "").strip()
    if not raw_proxy:
        return raw_proxy
    parsed = urlparse(raw_proxy)
    username = str(parsed.username or "").strip()
    if not username:
        return raw_proxy
    decoded_username = unquote(username)
    if "-session-" in decoded_username:
        import re

        session_username = re.sub(
            r"-session-[^:]+",
            f"-session-r{run_id}",
            decoded_username,
        )
    else:
        session_username = f"{decoded_username}-session-r{run_id}"
    auth = quote(session_username, safe="")
    if parsed.password is not None:
        auth = f"{auth}:{quote(unquote(str(parsed.password)), safe='')}"
    host = str(parsed.hostname or "").strip()
    if not host:
        return raw_proxy
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = auth + "@"
    netloc += f"{host}:{parsed.port}" if parsed.port is not None else host
    return urlunparse(parsed._replace(netloc=netloc))


def _normalize_proxy_profile(value: dict[str, object] | None) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _proxy_session_rewrite_enabled(proxy_profile: dict[str, object] | None) -> bool:
    if not isinstance(proxy_profile, dict):
        return False
    for key in tuple(crawler_runtime_settings.proxy_session_rewrite_enabled_keys or ()):
        if bool(proxy_profile.get(str(key))):
            return True
    return False


def _proxy_rotation_mode(proxy_profile: dict[str, object] | None) -> str | None:
    if not isinstance(proxy_profile, dict):
        return None
    normalized = str(proxy_profile.get("rotation") or "").strip().lower()
    if not normalized:
        return None
    if normalized in set(crawler_runtime_settings.proxy_rotation_sticky_tokens or ()):
        return "sticky"
    if normalized in set(crawler_runtime_settings.proxy_rotation_rotating_tokens or ()):
        return "rotating"
    return normalized


def _normalize_fetch_mode(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"auto", "http_only", "browser_only", "http_then_browser"}:
        return normalized
    return "auto"


def _hard_browser_requirement(
    *,
    context: _FetchRuntimeContext,
    runtime_policy: dict[str, object] | None = None,
) -> bool:
    active_policy = runtime_policy or context.runtime_policy
    return bool(active_policy.get("requires_browser")) or context.traversal_required


def _browser_first_decision(
    *,
    context: _FetchRuntimeContext,
    prefer_browser: bool,
    host_preference_enabled: bool,
) -> bool:
    if context.fetch_mode == "browser_only":
        return True
    if context.fetch_mode == "http_then_browser":
        return False
    if context.fetch_mode == "http_only":
        return _hard_browser_requirement(context=context)
    return (
        prefer_browser
        or host_preference_enabled
        or _hard_browser_requirement(context=context)
    )


def _browser_escalation_allowed(
    *,
    context: _FetchRuntimeContext,
    runtime_policy: dict[str, object] | None = None,
) -> bool:
    if context.fetch_mode in {"browser_only", "http_then_browser"}:
        return True
    if context.fetch_mode == "http_only":
        return _hard_browser_requirement(context=context, runtime_policy=runtime_policy)
    return True


async def _run_browser_attempts(
    context: _FetchRuntimeContext,
    *,
    reason: str,
    requested_fields: list[str] | None = None,
    listing_recovery_mode: str | None = None,
    capture_page_markdown: bool = False,
    proxies: list[str | None] | None = None,
    host_policy: HostProtectionPolicy | None = None,
) -> PageFetchResult:
    last_browser_error: Exception | None = None
    last_blocked_result: PageFetchResult | None = None
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
    active_host_policy = host_policy or await load_host_protection_policy(context.url)
    browser_proxies = list(proxies or context.proxies)
    for proxy_attempt_index, proxy in enumerate(browser_proxies, start=1):
        engine_attempts = _browser_engine_attempts(
            context=context,
            host_policy=active_host_policy,
        )
        escalation_lane = _browser_escalation_lane(
            context=context,
            reason=reason,
            host_policy=active_host_policy,
            proxy=proxy,
        )
        for engine_index, browser_engine in enumerate(engine_attempts, start=1):
            host_policy_snapshot = _host_policy_snapshot(active_host_policy)
            try:
                await wait_for_host_slot(context.url)
                result = await _browser_fetch(
                    context.url,
                    context.resolved_timeout,
                    run_id=context.run_id,
                    proxy=proxy,
                    browser_engine=browser_engine,
                    browser_reason=reason,
                    escalation_lane=escalation_lane,
                    host_policy_snapshot=host_policy_snapshot,
                    proxy_profile=context.proxy_profile,
                    locality_profile=context.locality_profile,
                    surface=context.surface,
                    traversal_mode=context.traversal_mode,
                    requested_fields=browser_requested_fields,
                    listing_recovery_mode=recovery_mode,
                    capture_page_markdown=capture_page_markdown,
                    max_pages=context.max_pages,
                    max_scrolls=context.max_scrolls,
                    on_event=context.on_event,
                )
                result.browser_diagnostics = {
                    **dict(result.browser_diagnostics or {}),
                    "proxy_url_redacted": _display_proxy(proxy),
                    "proxy_scheme": _proxy_scheme(proxy),
                    "browser_proxy_mode": "launch" if proxy else "direct",
                    "proxy_attempt_index": proxy_attempt_index,
                    "engine_attempt_index": engine_index,
                    "proxy_rotation_mode": _proxy_rotation_mode(context.proxy_profile),
                }
                if bool(result.blocked):
                    last_blocked_result = result
                    await _update_host_result_memory(
                        context,
                        result=result,
                    )
                    active_host_policy = await load_host_protection_policy(
                        result.final_url or result.url or context.url
                    )
                    if engine_index < len(engine_attempts):
                        cooldown_ms = max(
                            0,
                            int(
                                crawler_runtime_settings.browser_post_block_cooldown_ms
                                or 0
                            ),
                        )
                        if cooldown_ms > 0:
                            await asyncio.sleep(cooldown_ms / 1000)
                        continue
                    break
                return result
            except (httpx.HTTPError, OSError, TimeoutError, RuntimeError) as exc:
                last_browser_error = exc
                context.last_browser_attempt_diagnostics = build_failed_browser_diagnostics(
                    browser_reason=reason,
                    exc=exc,
                    proxy=proxy,
                    proxy_attempt_index=proxy_attempt_index,
                    browser_engine=browser_engine,
                    browser_binary=browser_engine,
                    bridge_used=_proxy_scheme(proxy) in {"socks5", "socks5h"},
                    escalation_lane=escalation_lane,
                    host_policy_snapshot=host_policy_snapshot,
                )
                _attach_exception_browser_diagnostics(
                    exc,
                    context.last_browser_attempt_diagnostics,
                )
                logger.debug(
                    "Browser fetch failed for %s via %s engine=%s",
                    context.url,
                    proxy or "direct",
                    browser_engine,
                    exc_info=True,
                )
    if last_blocked_result is not None:
        return last_blocked_result
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
    primary_fetcher = _select_http_fetcher(context)
    result, vendor_block_confirmed = await _run_http_fetch_chain_with_fetcher(
        context,
        fetcher=primary_fetcher,
    )
    if result is not None or vendor_block_confirmed:
        return result, vendor_block_confirmed
    if (
        primary_fetcher is _curl_fetch
        and not crawler_runtime_settings.force_httpx
        and context.last_error is not None
    ):
        logger.info(
            "curl_cffi transport failed for %s (%s); retrying via httpx",
            context.url,
            type(context.last_error).__name__,
        )
        return await _run_http_fetch_chain_with_fetcher(
            context,
            fetcher=_http_fetch,
        )
    return None, vendor_block_confirmed


async def _run_http_fetch_chain_with_fetcher(
    context: _FetchRuntimeContext,
    *,
    fetcher,
) -> tuple[PageFetchResult | None, bool]:
    vendor_block_confirmed = False
    for proxy in context.proxies:
        result, proxy_vendor_block_confirmed = await _run_http_fetcher_attempts(
            context,
            fetcher=fetcher,
            proxy=proxy,
        )
        vendor_block_confirmed = vendor_block_confirmed or proxy_vendor_block_confirmed
        if result is not None:
            return result, vendor_block_confirmed
    return None, vendor_block_confirmed


def _select_http_fetcher(context: _FetchRuntimeContext):
    del context
    if crawler_runtime_settings.force_httpx:
        return _http_fetch
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
        if not isinstance(result, PageFetchResult):
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
        if isinstance(handled_result, PageFetchResult):
            return handled_result, vendor_block_confirmed
        return None, vendor_block_confirmed
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
    if vendor:
        await note_browser_block_for_host(result.final_url or result.url or context.url)
        await mark_browser_first_host(result.final_url or result.url or context.url)
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
    if should_browser_escalate and (vendor or bool(result.blocked)):
        await note_host_hard_block(
            result.final_url or result.url or context.url,
            method=result.method,
            vendor=vendor,
            status_code=result.status_code,
            proxy_used=proxy is not None,
        )
    if (
        _retryable_status_for_http_fetch(result.status_code)
        and not vendor
        and not should_browser_escalate
        and attempt < max_attempts
    ):
        await _sleep_before_retry(attempt)
        return _RETRY_SENTINEL, False
    if should_browser_escalate and _browser_escalation_allowed(
        context=context,
        runtime_policy=result_runtime_policy,
    ):
        browser_reason = (
            context.browser_reason
            or (f"vendor-block:{vendor}" if vendor else "http-escalation")
        )
        browser_proxies = _browser_escalation_proxies(
            context=context,
            current_proxy=proxy,
            vendor_blocked=bool(vendor),
        )
        browser_result = await _invoke_run_browser_attempts(
            context,
            reason=browser_reason,
            requested_fields=context.requested_fields,
            listing_recovery_mode=context.listing_recovery_mode,
            capture_page_markdown=False,
            proxies=browser_proxies,
            host_policy=await load_host_protection_policy(
                result.final_url or result.url or context.url
            ),
        )
        await _update_host_result_memory(
            context,
            result=browser_result,
        )
        return browser_result, bool(vendor)
    if is_non_retryable_http_status(result.status_code):
        logger.info(
            "Returning non-retryable HTTP status %s for %s without browser fallback",
            result.status_code,
            context.url,
        )
        await _update_host_result_memory(
            context,
            result=result,
        )
        return result, bool(vendor)
    _attach_browser_attempt_diagnostics(
        result,
        diagnostics=context.last_browser_attempt_diagnostics,
    )
    await _update_host_result_memory(
        context,
        result=result,
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


def _host_policy_snapshot(policy: HostProtectionPolicy) -> dict[str, object]:
    return {
        "prefer_browser": bool(policy.prefer_browser),
        "last_block_vendor": policy.last_block_vendor,
        "hard_block_count": int(policy.hard_block_count),
        "request_blocked": bool(policy.request_blocked),
        "chromium_blocked": bool(policy.chromium_blocked),
        "real_chrome_blocked": bool(policy.real_chrome_blocked),
        "real_chrome_success": bool(policy.real_chrome_success),
        "last_block_method": policy.last_block_method,
    }


def _browser_escalation_lane(
    *,
    context: _FetchRuntimeContext,
    reason: str,
    host_policy: HostProtectionPolicy,
    proxy: str | None,
) -> str:
    if context.fetch_mode == "browser_only":
        base = "browser_only"
    elif context.fetch_mode == "http_then_browser":
        base = "http_then_browser"
    elif reason.startswith("vendor-block:"):
        base = "vendor_block"
    elif host_policy.prefer_browser:
        base = "host_memory"
    else:
        base = "http_escalation"
    if proxy:
        return f"{base}_proxy"
    return base


def _browser_engine_attempts(
    *,
    context: _FetchRuntimeContext,
    host_policy: HostProtectionPolicy,
) -> list[str]:
    engines = ["chromium"]
    if not str(context.surface or "").startswith("ecommerce_"):
        return engines
    if not bool(crawler_runtime_settings.browser_real_chrome_enabled):
        return engines
    if host_policy.chromium_blocked and not host_policy.real_chrome_success:
        return ["real_chrome", "chromium"]
    if host_policy.real_chrome_blocked and not host_policy.chromium_blocked:
        return ["chromium", "real_chrome"]
    if host_policy.request_blocked or host_policy.prefer_browser or host_policy.last_block_vendor:
        return ["chromium", "real_chrome"]
    return engines


def _browser_escalation_proxies(
    *,
    context: _FetchRuntimeContext,
    current_proxy: str | None,
    vendor_blocked: bool,
) -> list[str | None]:
    attempts = list(context.proxies)
    if not vendor_blocked:
        return attempts
    remaining = [
        candidate
        for candidate in attempts
        if candidate != current_proxy
    ]
    return remaining or attempts


async def _invoke_run_browser_attempts(
    context: _FetchRuntimeContext,
    *,
    reason: str,
    requested_fields: list[str] | None,
    listing_recovery_mode: str | None,
    capture_page_markdown: bool,
    proxies: list[str | None] | None,
    host_policy: HostProtectionPolicy | None,
) -> PageFetchResult:
    browser_attempt_kwargs = {
        "reason": reason,
        "requested_fields": requested_fields,
        "listing_recovery_mode": listing_recovery_mode,
        "capture_page_markdown": capture_page_markdown,
        "proxies": proxies,
    }
    if "host_policy" in inspect.signature(_run_browser_attempts).parameters:
        browser_attempt_kwargs["host_policy"] = host_policy
    return await _run_browser_attempts(
        context,
        **browser_attempt_kwargs,
    )


async def _update_host_result_memory(
    context: _FetchRuntimeContext,
    *,
    result: PageFetchResult,
) -> None:
    target_url = result.final_url or result.url or context.url
    browser_diagnostics = dict(result.browser_diagnostics or {})
    browser_engine = str(browser_diagnostics.get("browser_engine") or "").strip().lower()
    method_label = str(result.method or "").strip().lower()
    if method_label == "browser" and browser_engine:
        method_label = f"browser:{browser_engine}"
    proxy_used = bool(browser_diagnostics.get("proxy_scheme"))
    if bool(result.blocked):
        await apply_protected_host_backoff(target_url)
        await note_browser_block_for_host(target_url)
        await note_host_hard_block(
            target_url,
            method=method_label or result.method,
            vendor=_vendor_confirmed_block(result),
            status_code=result.status_code,
            proxy_used=proxy_used,
        )
        return
    await note_usable_fetch_for_host(target_url)
    await note_host_usable_fetch(
        target_url,
        method=method_label or result.method,
        proxy_used=proxy_used,
    )


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
