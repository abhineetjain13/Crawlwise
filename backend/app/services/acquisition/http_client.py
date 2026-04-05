# Deterministic HTTP acquisition client with retry and stealth fallback.
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from curl_cffi.const import CurlOpt
from curl_cffi import requests

from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.host_memory import host_prefers_stealth, remember_stealth_host
from app.services.pipeline_config import (
    HTTP_MAX_RETRIES,
    HTTP_RETRY_BACKOFF_BASE_MS,
    HTTP_RETRY_BACKOFF_MAX_MS,
    HTTP_RETRY_STATUS_CODES,
    HTTP_TIMEOUT_SECONDS,
    IMPERSONATION_TARGET,
)
from app.services.url_safety import ValidatedTarget, validate_public_target

STEALTH_IMPERSONATE = "chrome131"


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
    attempts: int = 0
    error: str = ""
    attempt_log: list[dict[str, object]] = field(default_factory=list)

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
) -> HttpFetchResult:
    """Fetch a URL and retry with stealth impersonation when needed.

    Args:
        url: Target URL.
        proxy: Optional proxy URL (e.g. "http://user:pass@host:port").
    """
    attempt_order = _build_attempt_order(
        url=url,
        allow_stealth_retry=allow_stealth_retry,
        force_stealth=force_stealth,
    )
    last_result = HttpFetchResult(error="request_not_attempted")

    for impersonate in attempt_order:
        result = await _fetch_with_retry(url, proxy, impersonate=impersonate)
        last_result = result
        if _is_successful(result):
            _remember_successful_fetch(url, result)
            return result
        if not _should_retry_with_stealth(result):
            break

    return last_result


def _build_attempt_order(*, url: str, allow_stealth_retry: bool, force_stealth: bool) -> list[str]:
    prefer_stealth = force_stealth or host_prefers_stealth(url)
    if force_stealth:
        return [STEALTH_IMPERSONATE]
    if prefer_stealth:
        return [STEALTH_IMPERSONATE] if not allow_stealth_retry else [STEALTH_IMPERSONATE, IMPERSONATION_TARGET]
    return [IMPERSONATION_TARGET] if not allow_stealth_retry else [IMPERSONATION_TARGET, STEALTH_IMPERSONATE]


def _remember_successful_fetch(url: str, result: HttpFetchResult) -> None:
    if result.stealth_used:
        remember_stealth_host(url)


async def _fetch_with_retry(url: str, proxy: str | None, *, impersonate: str) -> HttpFetchResult:
    attempts = max(1, HTTP_MAX_RETRIES + 1)
    last_result = HttpFetchResult(stealth_used=impersonate == STEALTH_IMPERSONATE)
    attempt_log: list[dict[str, object]] = []

    for attempt in range(1, attempts + 1):
        result = await _fetch_once(url, proxy, impersonate=impersonate)
        result.attempts = attempt
        attempt_log.append(_build_attempt_entry(result, attempt=attempt, impersonate=impersonate))
        result.attempt_log = list(attempt_log)
        last_result = result
        if result.text and result.content_type == "html" and detect_blocked_page(result.text).is_blocked:
            return result
        if result.error and not result.status_code:
            if attempt < attempts:
                await asyncio.sleep(_retry_backoff_seconds(attempt))
                continue
            return result
        if result.status_code in HTTP_RETRY_STATUS_CODES and attempt < attempts:
            await asyncio.sleep(_retry_backoff_seconds(attempt))
            continue
        return result

    return last_result


def _retry_backoff_seconds(attempt: int) -> float:
    _validate_retry_backoff_config()
    delay_ms = HTTP_RETRY_BACKOFF_BASE_MS * max(1, 2 ** (attempt - 1))
    bounded_ms = min(delay_ms, HTTP_RETRY_BACKOFF_MAX_MS)
    return bounded_ms / 1000


def _build_attempt_entry(result: HttpFetchResult, *, attempt: int, impersonate: str) -> dict[str, object]:
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
    if result.text and result.content_type == "html":
        entry["blocked"] = detect_blocked_page(result.text).is_blocked
    return entry


async def _fetch_once(url: str, proxy: str | None, *, impersonate: str) -> HttpFetchResult:
    target = await validate_public_target(url)
    session_kwargs: dict[str, Any] = {}
    kwargs: dict[str, Any] = {
        "impersonate": impersonate,
        "timeout": HTTP_TIMEOUT_SECONDS,
    }
    request_url = url
    if target.resolved_ips:
        session_kwargs["curl_options"] = _resolve_options(target)
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    try:
        async with requests.AsyncSession(**session_kwargs) as session:
            response = await session.get(request_url, **kwargs)
    except Exception as exc:
        return HttpFetchResult(
            error=str(exc),
            stealth_used=impersonate == STEALTH_IMPERSONATE,
        )

    headers = {str(key).lower(): str(value) for key, value in getattr(response, "headers", {}).items()}
    text = getattr(response, "text", "") or ""
    status_code = int(getattr(response, "status_code", 0) or 0)
    content_type, json_data = _parse_content(text, headers)
    error = ""
    if status_code >= 400:
        error = f"HTTP {status_code}"
    return HttpFetchResult(
        text=text,
        status_code=status_code,
        headers=headers,
        final_url=str(getattr(response, "url", url)),
        content_type=content_type,
        json_data=json_data,
        stealth_used=impersonate == STEALTH_IMPERSONATE,
        attempts=1,
        error=error,
    )


def _resolve_options(target: ValidatedTarget) -> dict[int, list[str]]:
    return {
        CurlOpt.RESOLVE: [f"{target.hostname}:{target.port}:{ip}" for ip in target.resolved_ips],
    }


def _parse_content(text: str, headers: dict[str, str]) -> tuple[str, dict | list | None]:
    ct = (headers.get("content-type") or "").lower()
    if "application/json" in ct or "text/json" in ct:
        try:
            return "json", json.loads(text) if text else None
        except json.JSONDecodeError:
            return "html", None
    stripped = text.lstrip()
    if stripped[:1] in {"{", "["}:
        try:
            return "json", json.loads(text)
        except json.JSONDecodeError:
            return "html", None
    return "html", None


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


_validate_retry_backoff_config()
