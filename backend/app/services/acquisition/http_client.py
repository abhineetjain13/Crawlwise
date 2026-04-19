from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import json

import httpx

from app.core.config import settings
from app.services.crawl_engine import (
    close_shared_http_client as close_shared_http_client,
    fetch_page,
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
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    data: Any | None = None,
    proxy: str | None = None,
    timeout_seconds: float | None = None,
) -> HttpFetchResult:
    if prefer_browser or (
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
        parsed_json: dict[str, object] | list[object] | None = None
        content_type = str(result.headers.get("content-type", "") or "").lower()
        if "json" in content_type:
            try:
                payload = json.loads(result.html or "")
            except ValueError:
                parsed_json = None
            else:
                if isinstance(payload, (dict, list)):
                    parsed_json = payload
        return HttpFetchResult(
            url=url,
            final_url=result.final_url,
            text=result.html,
            status_code=result.status_code,
            headers=_copy_headers(result.headers),
            json_data=parsed_json,
        )

    timeout = timeout_seconds or settings.http_timeout_seconds
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        proxy=proxy,
    ) as client:
        response = await client.request(
            method.upper(),
            url,
            headers=headers,
            json=json_body,
            data=data,
        )
        text = response.text or ""
        parsed_json: dict[str, object] | list[object] | None = None
        content_type = str(response.headers.get("content-type", "") or "").lower()
        if "json" in content_type:
            try:
                payload = response.json()
            except ValueError:
                parsed_json = None
            else:
                if isinstance(payload, (dict, list)):
                    parsed_json = payload
        return HttpFetchResult(
            url=url,
            final_url=str(response.url),
            text=text,
            status_code=response.status_code,
            headers=_copy_headers(response.headers),
            json_data=parsed_json,
        )


def _copy_headers(headers: Any) -> httpx.Headers:
    if isinstance(headers, httpx.Headers):
        return httpx.Headers(list(headers.multi_items()))
    if hasattr(headers, "multi_items"):
        return httpx.Headers(list(headers.multi_items()))
    if isinstance(headers, dict):
        return httpx.Headers(headers)
    return httpx.Headers(list(getattr(headers, "items", lambda: [])()))
