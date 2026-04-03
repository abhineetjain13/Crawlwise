# Acquisition waterfall service with optional proxy rotation.
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from app.core.config import settings
from app.services.acquisition.browser_client import BrowserResult, fetch_rendered_html
from app.services.acquisition.http_client import fetch_html


class ProxyRotator:
    """Simple round-robin proxy rotator.

    Users provide a list of proxy URLs in crawl settings.  If empty,
    no proxy is used.
    """

    def __init__(self, proxies: list[str] | None = None):
        self._proxies = [p.strip() for p in (proxies or []) if p.strip()]

    def next(self) -> str | None:
        if not self._proxies:
            return None
        return random.choice(self._proxies)


async def acquire_html(
    run_id: int,
    url: str,
    proxy_list: list[str] | None = None,
    advanced_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = 10,
) -> tuple[str, str, str, list[dict]]:
    """Acquire HTML for a URL using the waterfall strategy.

    Returns:
        (html, method, artifact_path, network_payloads)
    """
    rotator = ProxyRotator(proxy_list)
    proxy = rotator.next()
    network_payloads: list[dict] = []

    # If advanced mode is requested, go straight to Playwright
    if advanced_mode:
        browser_result = await fetch_rendered_html(
            url,
            proxy=proxy,
            advanced_mode=advanced_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
        )
        html = browser_result.html
        network_payloads = browser_result.network_payloads
        method = "playwright"
    else:
        # Waterfall: curl_cffi first, Playwright fallback
        try:
            html = await fetch_html(url, proxy=proxy)
        except Exception:
            html = ""
        method = "curl_cffi"

        visible = " ".join(html.lower().split())
        needs_browser = (
            len(visible) < 500
            or "enable javascript" in visible
            or "<noscript>" in visible.lower()
        )
        if needs_browser:
            proxy = rotator.next()  # get a fresh proxy for retry
            browser_result = await fetch_rendered_html(url, proxy=proxy)
            html = browser_result.html
            network_payloads = browser_result.network_payloads
            method = "playwright"

    path = _artifact_path(run_id, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    _write_network_payloads(run_id, url, network_payloads)

    return html, method, str(path), network_payloads


def _artifact_path(run_id: int, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return settings.artifacts_dir / "html" / str(run_id) / f"{digest}.html"


def _network_payload_path(run_id: int, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return settings.artifacts_dir / "network" / str(run_id) / f"{digest}.json"


def _write_network_payloads(run_id: int, url: str, payloads: list[dict]) -> None:
    if not payloads:
        return
    path = _network_payload_path(run_id, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payloads, indent=2), encoding="utf-8")
