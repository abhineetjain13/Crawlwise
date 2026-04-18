from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.crawl_engine import fetch_page
from app.services.crawl_fetch_runtime import reset_fetch_runtime_state
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


EXPAND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ecommerce": (
        "about",
        "compatibility",
        "description",
        "details",
        "dimensions",
        "more",
        "product",
        "read more",
        "show more",
        "spec",
        "view more",
    ),
    "job": (
        "benefits",
        "compensation",
        "description",
        "more",
        "qualifications",
        "requirements",
        "responsibilities",
        "salary",
        "see more",
        "show all",
    ),
}


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


async def expand_all_interactive_elements(
    page: Any,
    *,
    surface: str = "",
    checkpoint: Any = None,
) -> dict[str, object]:
    del checkpoint
    selectors = (
        "button, summary, details summary, "
        "[role='button'], [aria-expanded='false'], "
        "[data-testid*='expand'], [data-testid*='accordion']"
    )
    diagnostics: dict[str, object] = {
        "buttons_found": 0,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
    }
    try:
        candidates = await page.locator(selectors).element_handles()
    except Exception as exc:
        diagnostics["interaction_failures"] = [f"locator_failed:{exc}"]
        return diagnostics

    keywords = _expansion_keywords(surface)
    expanded_elements: list[str] = []
    interaction_failures: list[str] = []
    diagnostics["buttons_found"] = len(candidates)
    for handle in candidates:
        try:
            label = await _interactive_label(handle)
            if keywords and label and not any(keyword in label for keyword in keywords):
                continue
            await handle.scroll_into_view_if_needed()
            try:
                await handle.click(timeout=1_000)
            except Exception:
                await handle.evaluate(
                    "(node) => node instanceof HTMLElement && node.click()"
                )
            if label:
                expanded_elements.append(label)
            diagnostics["clicked_count"] = int(diagnostics["clicked_count"]) + 1
        except Exception as exc:
            interaction_failures.append(str(exc))
    diagnostics["expanded_elements"] = expanded_elements
    diagnostics["interaction_failures"] = interaction_failures
    return diagnostics


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


def _expansion_keywords(surface: str) -> tuple[str, ...]:
    lowered = str(surface or "").strip().lower()
    if "ecommerce" in lowered:
        return EXPAND_KEYWORDS["ecommerce"]
    if "job" in lowered:
        return EXPAND_KEYWORDS["job"]
    return ()


async def _interactive_label(handle: Any) -> str:
    value = await handle.evaluate(
        """(node) => {
            const pieces = [
                node.innerText,
                node.textContent,
                node.getAttribute('aria-label'),
                node.getAttribute('title'),
                node.getAttribute('data-testid'),
            ];
            return pieces.find((item) => item && item.trim()) || '';
        }"""
    )
    return " ".join(str(value or "").split()).strip().lower()


__all__ = [
    "BrowserIdentity",
    "BrowserResult",
    "build_playwright_context_options",
    "create_browser_identity",
    "expand_all_interactive_elements",
    "fetch_rendered_html",
    "reset_browser_pool_state",
]
