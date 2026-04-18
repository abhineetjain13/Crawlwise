from __future__ import annotations

from dataclasses import dataclass, field

from app.services.crawl_engine import fetch_page
from app.services.crawl_fetch_runtime import reset_fetch_runtime_state


@dataclass(slots=True)
class BrowserResult:
    html: str
    final_url: str
    network_urls: list[str] = field(default_factory=list)


async def fetch_rendered_html(url: str) -> BrowserResult:
    result = await fetch_page(url, prefer_browser=True)
    return BrowserResult(html=result.html, final_url=result.final_url)


async def expand_all_interactive_elements(_page) -> None:
    return None


async def reset_browser_pool_state() -> None:
    await reset_fetch_runtime_state()
