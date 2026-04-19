from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
from typing import Any
import json
import re

import httpx

from app.core.config import settings
from app.services.crawl_engine import (
    close_shared_http_client as close_shared_http_client,
    fetch_page,
)
from app.services.network_resolution import (
    build_async_http_client,
    should_retry_with_forced_ipv4,
)

requests = httpx


@dataclass(slots=True)
class HttpFetchResult:
    url: str
    final_url: str
    text: str
    status_code: int
    headers: httpx.Headers = field(default_factory=httpx.Headers)
    json_data: dict[str, object] | list[object] | None = None
    error: str = ""


async def request_result(
    url: str,
    *,
    prefer_browser: bool = False,
    expect_json: bool = False,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    data: Any | None = None,
    proxy: str | None = None,
    timeout_seconds: float | None = None,
) -> HttpFetchResult:
    if prefer_browser or (
        not expect_json
        and
        method.upper() == "GET"
        and not headers
        and json_body is None
        and data is None
        and proxy is None
    ):
        result = await fetch_page(
            url,
            prefer_browser=prefer_browser,
            timeout_seconds=timeout_seconds,
        )
        return HttpFetchResult(
            url=url,
            final_url=result.final_url,
            text=result.html,
            status_code=result.status_code,
            headers=_copy_headers(result.headers),
            json_data=_parse_json_payload(
                result.html,
                content_type=result.headers.get("content-type"),
            ),
        )

    timeout = timeout_seconds or settings.http_timeout_seconds
    try:
        response = await _request_with_httpx(
            url,
            method=method,
            headers=headers,
            json_body=json_body,
            data=data,
            proxy=proxy,
            timeout=timeout,
        )
    except Exception as exc:
        if not should_retry_with_forced_ipv4(exc):
            raise
        response = await _request_with_httpx(
            url,
            method=method,
            headers=headers,
            json_body=json_body,
            data=data,
            proxy=proxy,
            timeout=timeout,
            force_ipv4=True,
        )
    text = response.text or ""
    return HttpFetchResult(
        url=url,
        final_url=str(response.url),
        text=text,
        status_code=response.status_code,
        headers=_copy_headers(response.headers),
        json_data=_parse_json_payload(
            text,
            content_type=response.headers.get("content-type"),
        ),
    )


async def _request_with_httpx(
    url: str,
    *,
    method: str,
    headers: dict[str, str] | None,
    json_body: Any | None,
    data: Any | None,
    proxy: str | None,
    timeout: float,
    force_ipv4: bool = False,
) -> httpx.Response:
    async with build_async_http_client(
        follow_redirects=True,
        timeout=timeout,
        proxy=proxy,
        force_ipv4=force_ipv4,
    ) as client:
        return await client.request(
            method.upper(),
            url,
            headers=headers,
            json=json_body,
            data=data,
        )


def _copy_headers(headers: Any) -> httpx.Headers:
    if isinstance(headers, httpx.Headers):
        return httpx.Headers(list(headers.multi_items()))
    if hasattr(headers, "multi_items"):
        return httpx.Headers(list(headers.multi_items()))
    if isinstance(headers, dict):
        return httpx.Headers(headers)
    return httpx.Headers(list(getattr(headers, "items", lambda: [])()))


def _parse_json_payload(
    text: str,
    *,
    content_type: object = None,
) -> dict[str, object] | list[object] | None:
    lowered_content_type = str(content_type or "").lower()
    payload_text = str(text or "").strip()
    if not payload_text or "json" not in lowered_content_type:
        return None
    try:
        payload = json.loads(payload_text)
    except ValueError:
        pre_match = re.search(
            r"<pre[^>]*>(?P<body>.*)</pre>",
            payload_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if pre_match is None:
            return None
        try:
            payload = json.loads(unescape(pre_match.group("body")).strip())
        except ValueError:
            return None
    return payload if isinstance(payload, (dict, list)) else None
