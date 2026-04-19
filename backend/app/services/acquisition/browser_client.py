from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.crawl_engine import fetch_page
from app.services.crawl_fetch_runtime import (
    expand_all_interactive_elements,
    reset_fetch_runtime_state,
)
from app.services.acquisition.browser_identity import (
    BrowserIdentity,
    build_playwright_context_options,
    create_browser_identity,
)


@dataclass(slots=True)
class BrowserResult:
    html: str
    final_url: str
    network_urls: list[str] = field(default_factory=list)


async def fetch_rendered_html(
    url: str,
    *,
    proxy_list: list[str] | None = None,
    prefer_browser: bool = True,
    timeout_seconds: float | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
    sleep_ms: int = 0,
) -> BrowserResult:
    result = await fetch_page(
        url,
        proxy_list=proxy_list,
        prefer_browser=prefer_browser,
        timeout_seconds=timeout_seconds,
        surface=surface,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        sleep_ms=sleep_ms,
    )
    return BrowserResult(
        html=result.html,
        final_url=result.final_url,
        network_urls=_extract_network_urls(result),
    )


async def reset_browser_pool_state() -> None:
    await reset_fetch_runtime_state()


def _extract_network_urls(result: Any) -> list[str]:
    urls: list[str] = []
    payloads = getattr(result, "network_payloads", None)
    if isinstance(payloads, list):
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            candidate = str(payload.get("url") or "").strip()
            if candidate and candidate not in urls:
                urls.append(candidate)
    raw_urls = getattr(result, "network_urls", None)
    if isinstance(raw_urls, list):
        for candidate in raw_urls:
            value = str(candidate or "").strip()
            if value and value not in urls:
                urls.append(value)
    return urls


__all__ = [
    "BrowserIdentity",
    "BrowserResult",
    "build_playwright_context_options",
    "create_browser_identity",
    "expand_all_interactive_elements",
    "fetch_rendered_html",
    "reset_browser_pool_state",
]
