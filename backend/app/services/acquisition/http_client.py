# Deterministic HTTP acquisition client with retry and stealth fallback.
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC
from email.utils import parsedate_to_datetime
from json import loads as parse_json
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.cookie_store import (
    load_cookies_for_http,
    load_session_cookies_for_http,
)
from app.services.config.crawl_runtime import (
    HTTP_IMPERSONATION_PROFILES,
    HTTP_MAX_RETRIES,
    HTTP_RETRY_BACKOFF_BASE_MS,
    HTTP_RETRY_BACKOFF_MAX_MS,
    HTTP_RETRY_STATUS_CODES,
    HTTP_STEALTH_IMPERSONATION_PROFILE,
    HTTP_TIMEOUT_SECONDS,
    IMPERSONATION_TARGET,
)
from app.services.url_safety import ValidatedTarget, validate_public_target
from curl_cffi import requests
from curl_cffi.const import CurlOpt
from curl_cffi.requests.errors import RequestsError as CurlRequestsError

if TYPE_CHECKING:
    from app.services.acquisition.session_context import SessionContext

_MAX_REDIRECTS = 5
_ALLOWED_REDIRECT_SCHEMES = {"http", "https"}


def _validate_retry_backoff_config() -> None:
    if HTTP_RETRY_BACKOFF_BASE_MS < 0:
        raise ValueError("HTTP_RETRY_BACKOFF_BASE_MS must be >= 0")
    if HTTP_RETRY_BACKOFF_MAX_MS < HTTP_RETRY_BACKOFF_BASE_MS:
        raise ValueError(
            "HTTP_RETRY_BACKOFF_MAX_MS must be >= HTTP_RETRY_BACKOFF_BASE_MS"
        )


@dataclass
class HttpFetchResult:
    text: str = ""
    status_code: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    final_url: str = ""
    content_type: str = "html"
    json_data: dict | list | None = None
    stealth_used: bool = False
    impersonate_profile: str = ""
    attempts: int = 0
    error: str = ""
    attempt_log: list[dict[str, object]] = field(default_factory=list)
    retry_after_seconds: float | None = None


async def fetch_html(url: str, proxy: str | None = None) -> str:
    """Fetch HTML via the shared HTTP provider and return the text payload."""
    result = await fetch_html_result(url, proxy=proxy)
    return result.text


async def fetch_html_result(
    url: str,
    proxy: str | None = None,
    *,
    allow_stealth_retry: bool = True,
    force_stealth: bool = False,
    session_context: SessionContext | None = None,
) -> HttpFetchResult:
    return await request_result(
        url,
        proxy=proxy,
        method="GET",
        allow_stealth_retry=allow_stealth_retry,
        force_stealth=force_stealth,
        session_context=session_context,
    )


async def request_result(
    url: str,
    proxy: str | None = None,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    data: Any | None = None,
    timeout_seconds: float | None = None,
    allow_stealth_retry: bool = True,
    force_stealth: bool = False,
    session_context: SessionContext | None = None,
) -> HttpFetchResult:
    """Fetch a URL and retry with stealth impersonation when needed.

    Args:
        url: Target URL.
        proxy: Optional proxy URL with embedded credentials if required
            (e.g. "http://<user>:<password>@host:port").
        method: HTTP method to use.
        headers: Optional request headers.
        json_body: Optional JSON payload.
        data: Optional non-JSON payload.
        timeout_seconds: Optional request timeout override.
        session_context: Optional SessionContext for proxy-fingerprint affinity.
            When provided, the bound impersonation profile and isolated cookies
            are used instead of the global defaults.
    """
    normalized_method = str(method or "GET").strip().upper() or "GET"
    if session_context is not None:
        # Session-affinity path: use the bound profile exclusively.
        result = await _fetch_with_retry(
            url,
            session_context.proxy,
            impersonate=session_context.impersonate_profile,
            method=normalized_method,
            headers=headers,
            json_body=json_body,
            data=data,
            timeout_seconds=timeout_seconds,
            session_context=session_context,
        )
        return result

    attempt_order = _build_attempt_order(
        url=url,
        allow_stealth_retry=allow_stealth_retry,
        force_stealth=force_stealth,
    )
    last_result = HttpFetchResult(error="request_not_attempted")

    for impersonate in attempt_order:
        result = await _fetch_with_retry(
            url,
            proxy,
            impersonate=impersonate,
            method=normalized_method,
            headers=headers,
            json_body=json_body,
            data=data,
            timeout_seconds=timeout_seconds,
        )
        last_result = result
        if _is_successful(result):
            return result
        if not _should_retry_with_stealth(result):
            break

    return last_result


def _build_attempt_order(
    *, url: str, allow_stealth_retry: bool, force_stealth: bool
) -> list[str]:
    profiles = [profile for profile in HTTP_IMPERSONATION_PROFILES if profile]
    if not profiles:
        fallback_profile = str(IMPERSONATION_TARGET or "").strip()
        if fallback_profile:
            profiles = [fallback_profile]
    if not profiles:
        raise ValueError("No valid HTTP impersonation profile is configured")
    stealth_profile = (
        str(HTTP_STEALTH_IMPERSONATION_PROFILE or "").strip() or profiles[-1]
    )
    if stealth_profile not in profiles:
        profiles.append(stealth_profile)
    if force_stealth:
        return [stealth_profile]
    primary = profiles[0]
    ordered = [primary, *[profile for profile in profiles if profile != primary]]
    return ordered[:1] if not allow_stealth_retry else ordered


async def _fetch_with_retry(
    url: str,
    proxy: str | None,
    *,
    impersonate: str,
    method: str,
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    data: Any | None = None,
    timeout_seconds: float | None = None,
    session_context: SessionContext | None = None,
) -> HttpFetchResult:
    attempts = max(1, HTTP_MAX_RETRIES + 1)
    last_result = HttpFetchResult(
        stealth_used=impersonate == HTTP_STEALTH_IMPERSONATION_PROFILE,
        impersonate_profile=impersonate,
    )
    attempt_log: list[dict[str, object]] = []

    for attempt in range(1, attempts + 1):
        result = await _fetch_once(
            url,
            proxy,
            impersonate=impersonate,
            method=method,
            headers=headers,
            json_body=json_body,
            data=data,
            timeout_seconds=timeout_seconds,
            session_context=session_context,
        )
        result.attempts = attempt
        attempt_log.append(
            _build_attempt_entry(result, attempt=attempt, impersonate=impersonate)
        )
        result.attempt_log = list(attempt_log)
        last_result = result
        if (
            result.text
            and result.content_type == "html"
            and detect_blocked_page(result.text).is_blocked
        ):
            return result
        if result.error and not result.status_code:
            if attempt < attempts:
                await asyncio.sleep(_retry_backoff_seconds(attempt))
                continue
            return result
        if result.status_code in HTTP_RETRY_STATUS_CODES and attempt < attempts:
            delay_seconds = max(
                _retry_backoff_seconds(attempt),
                float(result.retry_after_seconds or 0.0),
            )
            await asyncio.sleep(delay_seconds)
            continue
        return result

    return last_result


def _retry_backoff_seconds(attempt: int) -> float:
    _validate_retry_backoff_config()
    delay_ms = HTTP_RETRY_BACKOFF_BASE_MS * max(1, 2 ** (attempt - 1))
    bounded_ms = min(delay_ms, HTTP_RETRY_BACKOFF_MAX_MS)
    return bounded_ms / 1000


def _build_attempt_entry(
    result: HttpFetchResult, *, attempt: int, impersonate: str
) -> dict[str, object]:
    entry: dict[str, object] = {
        "attempt": attempt,
        "impersonate": impersonate,
    }
    if result.status_code:
        entry["status_code"] = result.status_code
    if result.content_type:
        entry["content_type"] = result.content_type
    if result.error:
        entry["error"] = result.error
    if result.retry_after_seconds is not None:
        entry["retry_after_seconds"] = result.retry_after_seconds
    if result.text and result.content_type == "html":
        entry["blocked"] = detect_blocked_page(result.text).is_blocked
    return entry


async def _fetch_once(
    url: str,
    proxy: str | None,
    *,
    impersonate: str,
    method: str,
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    data: Any | None = None,
    timeout_seconds: float | None = None,
    session_context: SessionContext | None = None,
) -> HttpFetchResult:
    request_url = str(url or "").strip()
    request_method = str(method or "GET").strip().upper() or "GET"
    redirect_count = 0

    # Seed session cookies once before the redirect loop.  Re-merging on
    # every iteration would pollute the session jar with domain-global
    # cookies from redirect targets.
    _cookies_seeded = False

    while True:
        target = await validate_public_target(request_url)
        session_kwargs: dict[str, Any] = {}
        session_kwargs["trust_env"] = False
        kwargs: dict[str, Any] = {
            "impersonate": impersonate,
            "timeout": float(timeout_seconds or HTTP_TIMEOUT_SECONDS),
            "allow_redirects": False,
        }
        if headers:
            kwargs["headers"] = dict(headers)
        if json_body is not None:
            kwargs["json"] = json_body
        if data is not None:
            kwargs["data"] = data
        if target.resolved_ips:
            session_kwargs["curl_options"] = _resolve_options(target)
        # Session-affinity: use SessionContext's proxy and isolated cookies
        # when available, falling back to legacy domain-scoped cookie store.
        effective_proxy = (
            session_context.proxy if session_context is not None else proxy
        )
        if effective_proxy:
            kwargs["proxies"] = {"http": effective_proxy, "https": effective_proxy}
        if session_context is not None:
            if not _cookies_seeded:
                # Seed once: load session-scoped cookies first, then fall
                # back to domain-scoped store for the initial request only.
                session_cookies = load_session_cookies_for_http(
                    target.hostname, session_context.identity_key
                )
                if session_cookies:
                    session_context.merge_http_cookies(session_cookies)
                else:
                    domain_cookies = load_cookies_for_http(target.hostname)
                    if domain_cookies:
                        session_context.merge_http_cookies(domain_cookies)
                _cookies_seeded = True
            if session_context.cookies:
                kwargs["cookies"] = dict(session_context.cookies)
        else:
            cookies = load_cookies_for_http(target.hostname)
            if cookies:
                kwargs["cookies"] = cookies
        try:
            async with requests.AsyncSession(**session_kwargs) as session:
                request_fn = getattr(session, request_method.lower(), None)
                if request_fn is None:
                    response = await session.request(
                        request_method,
                        request_url,
                        **kwargs,
                    )
                else:
                    response = await request_fn(request_url, **kwargs)
        except (OSError, RuntimeError, ValueError, TypeError, CurlRequestsError) as exc:
            return HttpFetchResult(
                error=str(exc),
                stealth_used=impersonate == HTTP_STEALTH_IMPERSONATION_PROFILE,
                impersonate_profile=impersonate,
                final_url=request_url,
            )

        headers = {
            str(key).lower(): str(value)
            for key, value in getattr(response, "headers", {}).items()
        }
        status_code = int(getattr(response, "status_code", 0) or 0)
        location = str(headers.get("location") or "").strip()
        if status_code in {301, 302, 303, 307, 308} and location:
            redirect_count += 1
            if redirect_count > _MAX_REDIRECTS:
                return HttpFetchResult(
                    status_code=status_code,
                    headers=headers,
                    final_url=str(getattr(response, "url", request_url)),
                    content_type="html",
                    stealth_used=impersonate == HTTP_STEALTH_IMPERSONATION_PROFILE,
                    impersonate_profile=impersonate,
                    attempts=1,
                    error="too_many_redirects",
                )
            next_url = _resolve_redirect_url(request_url, location)
            if next_url is None:
                return HttpFetchResult(
                    status_code=status_code,
                    headers=headers,
                    final_url=str(getattr(response, "url", request_url)),
                    content_type="html",
                    stealth_used=impersonate == HTTP_STEALTH_IMPERSONATION_PROFILE,
                    impersonate_profile=impersonate,
                    attempts=1,
                    error="invalid_redirect_target",
                )
            request_url = next_url
            continue

        text = getattr(response, "text", "") or ""
        content_type, json_data = _parse_content(text, headers)
        error = ""
        if status_code >= 400:
            error = f"HTTP {status_code}"
        return HttpFetchResult(
            text=text,
            status_code=status_code,
            headers=headers,
            final_url=str(getattr(response, "url", request_url)),
            content_type=content_type,
            json_data=json_data,
            stealth_used=impersonate == HTTP_STEALTH_IMPERSONATION_PROFILE,
            impersonate_profile=impersonate,
            attempts=1,
            error=error,
            retry_after_seconds=_parse_retry_after(headers),
        )


def _resolve_options(target: ValidatedTarget) -> dict[int, list[str]]:
    return {
        CurlOpt.RESOLVE: [
            f"{target.hostname}:{target.port}:{ip}" for ip in target.resolved_ips
        ],
    }


def _parse_content(
    text: str, headers: dict[str, str]
) -> tuple[str, dict | list | None]:
    ct = (headers.get("content-type") or "").lower()
    if "application/json" in ct or "text/json" in ct:
        try:
            return "json", parse_json(text) if text else None
        except json.JSONDecodeError:
            return "html", None
    stripped = text.lstrip()
    if stripped[:1] in {"{", "["}:
        try:
            return "json", parse_json(text)
        except json.JSONDecodeError:
            return "html", None
    return "html", None


def _resolve_redirect_url(current_url: str, location: str) -> str | None:
    candidate = urljoin(current_url, str(location or "").strip())
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in _ALLOWED_REDIRECT_SCHEMES:
        return None
    if parsed.username or parsed.password:
        return None
    return candidate


def _is_successful(result: HttpFetchResult) -> bool:
    return result.status_code >= 200 and result.status_code < 400 and not result.error


def _should_retry_with_stealth(result: HttpFetchResult) -> bool:
    if result.status_code in HTTP_RETRY_STATUS_CODES:
        return True
    if result.error and not result.status_code:
        return True
    if result.content_type != "json" and detect_blocked_page(result.text).is_blocked:
        return True
    return False


def _parse_retry_after(headers: dict[str, str]) -> float | None:
    raw_value = str((headers or {}).get("retry-after") or "").strip()
    if not raw_value:
        return None
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    else:
        retry_at = retry_at.astimezone(UTC)
    return max(0.0, retry_at.timestamp() - time.time())


_validate_retry_backoff_config()
