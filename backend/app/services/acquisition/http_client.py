from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.services.crawl_engine import close_shared_http_client, fetch_page

requests = httpx


@dataclass(slots=True)
class HttpFetchResult:
    url: str
    final_url: str
    text: str
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    error: str = ""


async def request_result(url: str, *, prefer_browser: bool = False) -> HttpFetchResult:
    result = await fetch_page(url, prefer_browser=prefer_browser)
    return HttpFetchResult(
        url=url,
        final_url=result.final_url,
        text=result.html,
        status_code=result.status_code,
        headers=result.headers,
    )
