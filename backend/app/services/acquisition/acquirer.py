# Acquisition waterfall service with optional proxy rotation.
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlparse
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_client import fetch_rendered_html
from app.services.acquisition.host_memory import host_prefers_stealth, remember_stealth_host
from app.services.acquisition.http_client import HttpFetchResult, fetch_html_result
from app.services.pipeline_config import BROWSER_FALLBACK_VISIBLE_TEXT_MIN, JS_GATE_PHRASES


class ProxyPoolExhausted(RuntimeError):
    pass


class ProxyRotator:
    """Round-robin proxy rotator."""

    def __init__(self, proxies: list[str] | None = None):
        self._proxies = [proxy.strip() for proxy in (proxies or []) if proxy and proxy.strip()]
        self._index = 0

    def next(self) -> str | None:
        if not self._proxies:
            return None
        proxy = self._proxies[self._index % len(self._proxies)]
        self._index += 1
        return proxy

    def cycle_once(self) -> list[str]:
        if not self._proxies:
            return []
        return [self.next() for _ in range(len(self._proxies))]


@dataclass
class AcquisitionResult:
    """Typed acquisition result with content-type routing."""

    html: str = ""
    json_data: dict | list | None = None
    content_type: str = "html"  # "html" | "json" | "binary"
    method: str = "curl_cffi"
    artifact_path: str = ""
    network_payloads: list[dict] = field(default_factory=list)


async def acquire_html(
    run_id: int,
    url: str,
    proxy_list: list[str] | None = None,
    advanced_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = 10,
    sleep_ms: int = 0,
) -> tuple[str, str, str, list[dict]]:
    """Acquire HTML for a URL using the waterfall strategy."""
    result = await acquire(
        run_id=run_id,
        url=url,
        proxy_list=proxy_list,
        advanced_mode=advanced_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        sleep_ms=sleep_ms,
    )
    return result.html, result.method, result.artifact_path, result.network_payloads


async def acquire(
    run_id: int,
    url: str,
    proxy_list: list[str] | None = None,
    advanced_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = 10,
    sleep_ms: int = 0,
) -> AcquisitionResult:
    """Acquire content for a URL using the waterfall strategy."""
    prefer_stealth = host_prefers_stealth(url)
    rotator = ProxyRotator(proxy_list)
    proxy_candidates = rotator.cycle_once()
    if proxy_list and not proxy_candidates:
        raise ProxyPoolExhausted(f"No valid proxies configured for {url}")
    if not proxy_candidates:
        proxy_candidates = [None]

    result: AcquisitionResult | None = None
    for proxy in proxy_candidates:
        result = await _acquire_once(
            run_id=run_id,
            url=url,
            proxy=proxy,
            advanced_mode=advanced_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            prefer_stealth=prefer_stealth,
            sleep_ms=sleep_ms,
        )
        if result is not None:
            break

    if result is None:
        if proxy_list:
            raise ProxyPoolExhausted(f"All configured proxies failed for {url}")
        raise RuntimeError(f"Unable to acquire content for {url}")

    path = _artifact_path(run_id, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    if result.content_type == "json" and result.json_data is not None:
        path = path.with_suffix(".json")
        path.write_text(json.dumps(result.json_data, indent=2, default=str), encoding="utf-8")
    else:
        path.write_text(result.html, encoding="utf-8")
    _write_network_payloads(run_id, url, result.network_payloads)

    result.artifact_path = str(path)
    return result


async def _acquire_once(
    *,
    run_id: int,
    url: str,
    proxy: str | None,
    advanced_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    prefer_stealth: bool,
    sleep_ms: int,
) -> AcquisitionResult | None:
    if advanced_mode:
        if sleep_ms > 0:
            await asyncio.sleep(sleep_ms / 1000)
        browser_result = await fetch_rendered_html(
            url,
            proxy=proxy,
            advanced_mode=advanced_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            prefer_stealth=prefer_stealth,
            request_delay_ms=sleep_ms,
        )
        if not browser_result.html or detect_blocked_page(browser_result.html).is_blocked:
            return None
        return AcquisitionResult(
            html=browser_result.html,
            content_type="html",
            method="playwright",
            artifact_path=str(_artifact_path(run_id, url)),
            network_payloads=browser_result.network_payloads,
        )

    if sleep_ms > 0:
        await asyncio.sleep(sleep_ms / 1000)
    fetch_result = await _fetch_with_content_type(url, proxy)
    normalized = _normalize_fetch_result(fetch_result)
    html = normalized.text
    if normalized.content_type == "json":
        return AcquisitionResult(
            html=html,
            json_data=normalized.json_data,
            content_type="json",
            method="curl_cffi",
            artifact_path=str(_artifact_path(run_id, url)),
        )

    blocked = detect_blocked_page(html)
    visible_text = " ".join(BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower().split())
    gate_phrases = any(phrase in visible_text for phrase in JS_GATE_PHRASES)
    needs_browser = bool(
        blocked.is_blocked
        or normalized.status_code in {403, 429, 503}
        or len(visible_text) < BROWSER_FALLBACK_VISIBLE_TEXT_MIN
        or gate_phrases
        or normalized.error
    )
    if blocked.is_blocked:
        remember_stealth_host(url)
        prefer_stealth = True
    if not needs_browser:
        return AcquisitionResult(
            html=html,
            json_data=normalized.json_data,
            content_type=normalized.content_type,
            method="curl_cffi",
            artifact_path=str(_artifact_path(run_id, url)),
        )

    if sleep_ms > 0:
        await asyncio.sleep(sleep_ms / 1000)
    browser_result = await fetch_rendered_html(
        url,
        proxy=proxy,
        prefer_stealth=prefer_stealth,
        advanced_mode=advanced_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        request_delay_ms=sleep_ms,
    )
    if not browser_result.html or detect_blocked_page(browser_result.html).is_blocked:
        return None
    return AcquisitionResult(
        html=browser_result.html,
        content_type="html",
        method="playwright",
        artifact_path=str(_artifact_path(run_id, url)),
        network_payloads=browser_result.network_payloads,
    )


async def _fetch_with_content_type(url: str, proxy: str | None) -> HttpFetchResult:
    """Fetch URL and detect content type from response headers."""
    return await fetch_html_result(url, proxy=proxy)


def _normalize_fetch_result(result: HttpFetchResult | tuple[str, str, dict | list | None]) -> HttpFetchResult:
    if isinstance(result, HttpFetchResult):
        return result
    text, content_type, json_data = result
    return HttpFetchResult(
        text=text,
        content_type=content_type,
        json_data=json_data,
        status_code=200 if content_type in {"html", "json"} else 0,
        error="",
    )


def _artifact_path(run_id: int, url: str) -> Path:
    return settings.artifacts_dir / "html" / str(run_id) / f"{_artifact_basename(run_id, url)}.html"


def _network_payload_path(run_id: int, url: str) -> Path:
    return settings.artifacts_dir / "network" / str(run_id) / f"{_artifact_basename(run_id, url)}.json"


def _write_network_payloads(run_id: int, url: str, payloads: list[dict]) -> None:
    if not payloads:
        return
    path = _network_payload_path(run_id, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payloads, indent=2), encoding="utf-8")


def _artifact_basename(run_id: int, url: str) -> str:
    parsed = urlparse(url)
    host = _slugify(parsed.netloc or "unknown-host")
    path_slug = _slugify(_artifact_path_hint(parsed)) or "root"
    short_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{host}__run-{run_id}__{path_slug}__{short_hash}"


def _artifact_path_hint(parsed) -> str:
    pieces = [segment for segment in parsed.path.split("/") if segment]
    query_bits = [f"{key}-{value}" if value else key for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
    hint = "-".join([*pieces[:4], *query_bits[:3]])
    return hint or "root"


def _slugify(value: str) -> str:
    safe = []
    previous_dash = False
    for ch in value.lower():
        if ch.isalnum():
            safe.append(ch)
            previous_dash = False
            continue
        if previous_dash:
            continue
        safe.append("-")
        previous_dash = True
    return "".join(safe).strip("-")[:80] or "item"
