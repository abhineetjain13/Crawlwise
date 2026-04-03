# Deterministic HTTP acquisition client with retry and stealth fallback.
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from curl_cffi import requests

from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.host_memory import host_prefers_stealth, remember_stealth_host
from app.services.pipeline_config import HTTP_MAX_RETRIES, HTTP_RETRY_STATUS_CODES, HTTP_TIMEOUT_SECONDS, IMPERSONATION_TARGET

STEALTH_IMPERSONATE = "chrome131"


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
    prefer_stealth = force_stealth or host_prefers_stealth(url)
    if force_stealth:
        attempt_order = [STEALTH_IMPERSONATE]
    elif prefer_stealth:
        attempt_order = [STEALTH_IMPERSONATE] if not allow_stealth_retry else [STEALTH_IMPERSONATE, IMPERSONATION_TARGET]
    else:
        attempt_order = [IMPERSONATION_TARGET] if not allow_stealth_retry else [IMPERSONATION_TARGET, STEALTH_IMPERSONATE]
    seen: set[str] = set()
    last_result = HttpFetchResult(error="request_not_attempted")

    for impersonate in attempt_order:
        if impersonate in seen:
            continue
        seen.add(impersonate)
        result = await _fetch_with_retry(url, proxy, impersonate=impersonate)
        last_result = result
        if _is_successful(result):
            if result.stealth_used:
                remember_stealth_host(url)
            return result
        if not _should_retry_with_stealth(result):
            break

    return last_result


async def _fetch_with_retry(url: str, proxy: str | None, *, impersonate: str) -> HttpFetchResult:
    attempts = max(1, HTTP_MAX_RETRIES + 1)
    last_result = HttpFetchResult(stealth_used=impersonate == STEALTH_IMPERSONATE)

    for attempt in range(1, attempts + 1):
        result = await _fetch_once(url, proxy, impersonate=impersonate)
        result.attempts = attempt
        last_result = result
        if result.error and not result.status_code:
            if attempt < attempts:
                continue
            return result
        if result.status_code in HTTP_RETRY_STATUS_CODES:
            if attempt < attempts:
                continue
        return result

    return last_result


async def _fetch_once(url: str, proxy: str | None, *, impersonate: str) -> HttpFetchResult:
    kwargs: dict[str, Any] = {
        "impersonate": impersonate,
        "timeout": HTTP_TIMEOUT_SECONDS,
    }
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    try:
        async with requests.AsyncSession() as session:
            response = await session.get(url, **kwargs)
    except Exception as exc:
        return HttpFetchResult(
            error=str(exc),
            stealth_used=impersonate == STEALTH_IMPERSONATE,
        )

    headers = {str(key).lower(): str(value) for key, value in getattr(response, "headers", {}).items()}
    text = getattr(response, "text", "") or ""
    status_code = int(getattr(response, "status_code", 0) or 0)
    content_type, json_data = _parse_content(text, headers)
    error = "" if status_code and status_code < 400 else f"HTTP {status_code}" if status_code else ""
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
