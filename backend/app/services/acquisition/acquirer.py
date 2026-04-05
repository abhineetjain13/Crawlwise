# Acquisition waterfall service with optional proxy rotation.
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlparse
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_client import fetch_rendered_html
from app.services.acquisition.host_memory import host_prefers_stealth, remember_stealth_host
from app.services.acquisition.pacing import wait_for_host_slot
from app.services.acquisition.http_client import HttpFetchResult, fetch_html_result
from app.services.pipeline_config import (
    ACQUIRE_HOST_MIN_INTERVAL_MS,
    BROWSER_FALLBACK_HTML_SIZE_THRESHOLD,
    BROWSER_FALLBACK_VISIBLE_TEXT_MIN,
    BROWSER_FALLBACK_VISIBLE_TEXT_RATIO_MAX,
    DEFAULT_MAX_SCROLLS,
    JS_GATE_PHRASES,
)
from app.services.requested_field_policy import requested_field_terms


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
    diagnostics_path: str = ""
    network_payloads: list[dict] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)


async def acquire_html(
    run_id: int,
    url: str,
    proxy_list: list[str] | None = None,
    advanced_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    sleep_ms: int = 0,
    requested_fields: list[str] | None = None,
    requested_field_selectors: dict[str, list[dict]] | None = None,
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
        requested_fields=requested_fields,
        requested_field_selectors=requested_field_selectors,
    )
    return result.html, result.method, result.artifact_path, result.network_payloads


async def acquire(
    run_id: int,
    url: str,
    proxy_list: list[str] | None = None,
    advanced_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    sleep_ms: int = 0,
    requested_fields: list[str] | None = None,
    requested_field_selectors: dict[str, list[dict]] | None = None,
) -> AcquisitionResult:
    """Acquire content for a URL using the waterfall strategy."""
    diagnostics_path = _diagnostics_path(run_id, url)
    _write_diagnostics_stub(run_id, url, diagnostics_path)
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
            requested_fields=requested_fields,
            requested_field_selectors=requested_field_selectors,
        )
        if result is None and not prefer_stealth and host_prefers_stealth(url):
            result = await _acquire_once(
                run_id=run_id,
                url=url,
                proxy=proxy,
                advanced_mode=advanced_mode,
                max_pages=max_pages,
                max_scrolls=max_scrolls,
                prefer_stealth=True,
                sleep_ms=sleep_ms,
                requested_fields=requested_fields,
                requested_field_selectors=requested_field_selectors,
            )
        if result is not None:
            break

    if result is None:
        _write_failed_diagnostics(
            run_id,
            url,
            diagnostics_path,
            error_detail="All acquisition attempts failed",
        )
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
    _write_diagnostics(run_id, url, result, path, diagnostics_path)

    result.artifact_path = str(path)
    result.diagnostics_path = str(diagnostics_path)
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
    requested_fields: list[str] | None,
    requested_field_selectors: dict[str, list[dict]] | None,
) -> AcquisitionResult | None:
    import logging as _logging
    _log = _logging.getLogger(__name__)
    host_wait_seconds = await wait_for_host_slot(urlparse(url).netloc.lower(), ACQUIRE_HOST_MIN_INTERVAL_MS)

    # Always try curl_cffi first — it's faster and more resilient to HTTP/2 issues.
    if sleep_ms > 0:
        await asyncio.sleep(sleep_ms / 1000)
    fetch_result = await _fetch_with_content_type(url, proxy)
    normalized = _normalize_fetch_result(fetch_result)
    html = normalized.text
    curl_result: AcquisitionResult | None = None

    if normalized.content_type == "json":
        return AcquisitionResult(
            html=html,
            json_data=normalized.json_data,
            content_type="json",
            method="curl_cffi",
            artifact_path=str(_artifact_path(run_id, url)),
            diagnostics=_build_curl_diagnostics(
                normalized=normalized,
                blocked=None,
                visible_text="",
                gate_phrases=False,
                needs_browser=False,
                proxy=proxy,
                prefer_stealth=prefer_stealth,
                advanced_mode=advanced_mode,
                host_wait_seconds=host_wait_seconds,
            ),
        )

    blocked = detect_blocked_page(html)
    visible_text = " ".join(BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower().split())
    gate_phrases = any(phrase in visible_text for phrase in JS_GATE_PHRASES)
    # Detect JS-shell pages: large HTML with very little visible text indicates
    # a SPA/Next.js shell where all real content is JS-rendered.
    html_len = len(html or "")
    visible_len = len(visible_text)
    js_shell_detected = (
        html_len >= BROWSER_FALLBACK_HTML_SIZE_THRESHOLD
        and visible_len > 0
        and (visible_len / html_len) < BROWSER_FALLBACK_VISIBLE_TEXT_RATIO_MAX
    )
    needs_browser = bool(
        blocked.is_blocked
        or normalized.status_code in {403, 429, 503}
        or len(visible_text) < BROWSER_FALLBACK_VISIBLE_TEXT_MIN
        or gate_phrases
        or js_shell_detected
        or _requested_fields_need_browser(
            html,
            visible_text,
            requested_fields or [],
            requested_field_selectors or {},
        )
        or normalized.error
    )
    if blocked.is_blocked:
        remember_stealth_host(url)
        prefer_stealth = True

    curl_diagnostics = _build_curl_diagnostics(
        normalized=normalized,
        blocked=blocked,
        visible_text=visible_text,
        gate_phrases=gate_phrases,
        needs_browser=needs_browser,
        proxy=proxy,
        prefer_stealth=prefer_stealth,
        advanced_mode=advanced_mode,
        host_wait_seconds=host_wait_seconds,
    )

    # Keep the curl_cffi result as a fallback even if we escalate to browser,
    # but only when the content is substantive enough to be useful for extraction.
    has_useful_content = (
        html
        and not blocked.is_blocked
        and len(visible_text) >= BROWSER_FALLBACK_VISIBLE_TEXT_MIN
        and normalized.status_code not in {403, 429, 503}
    )
    if has_useful_content:
        curl_result = AcquisitionResult(
            html=html,
            json_data=normalized.json_data,
            content_type=normalized.content_type,
            method="curl_cffi",
            artifact_path=str(_artifact_path(run_id, url)),
            diagnostics=curl_diagnostics,
        )

    if not needs_browser and not advanced_mode:
        return curl_result or AcquisitionResult(
            html=html,
            json_data=normalized.json_data,
            content_type=normalized.content_type,
            method="curl_cffi",
            artifact_path=str(_artifact_path(run_id, url)),
            diagnostics=curl_diagnostics,
        )

    # Escalate to Playwright for JS rendering or advanced crawl modes.
    if sleep_ms > 0:
        await asyncio.sleep(sleep_ms / 1000)
    try:
        browser_result = await fetch_rendered_html(
            url,
            proxy=proxy,
            prefer_stealth=prefer_stealth,
            advanced_mode=advanced_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            request_delay_ms=sleep_ms,
            requested_fields=requested_fields,
            requested_field_selectors=requested_field_selectors,
        )
    except Exception as exc:
        _log.warning("Playwright failed for %s: %s — falling back to curl_cffi result", url, exc)
        if curl_result is not None:
            curl_result.diagnostics["browser_exception"] = f"{type(exc).__name__}: {exc}"
            curl_result.diagnostics["browser_attempted"] = True
        return curl_result

    if browser_result.html and not detect_blocked_page(browser_result.html).is_blocked:
        browser_diagnostics = dict(curl_diagnostics)
        browser_diagnostics.update(
            {
                "browser_attempted": True,
                "browser_challenge_state": browser_result.challenge_state,
                "browser_origin_warmed": browser_result.origin_warmed,
                "browser_network_payloads": len(browser_result.network_payloads or []),
                "browser_diagnostics": browser_result.diagnostics,
            }
        )
        return AcquisitionResult(
            html=browser_result.html,
            content_type="html",
            method="playwright",
            artifact_path=str(_artifact_path(run_id, url)),
            network_payloads=browser_result.network_payloads,
            diagnostics=browser_diagnostics,
        )

    # Playwright returned empty or blocked — prefer curl_cffi result if available.
    if curl_result:
        curl_result.diagnostics["browser_attempted"] = True
        curl_result.diagnostics["browser_challenge_state"] = browser_result.challenge_state
        curl_result.diagnostics["browser_origin_warmed"] = browser_result.origin_warmed
        curl_result.diagnostics["browser_network_payloads"] = len(browser_result.network_payloads or [])
        curl_result.diagnostics["browser_diagnostics"] = browser_result.diagnostics
        curl_result.diagnostics["browser_blocked"] = bool(
            browser_result.html and detect_blocked_page(browser_result.html).is_blocked
        )
        _log.info("Playwright returned blocked/empty for %s — using curl_cffi fallback", url)
        return curl_result

    return None


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


def _requested_fields_need_browser(
    html: str,
    visible_text: str,
    requested_fields: list[str],
    requested_field_selectors: dict[str, list[dict]],
) -> bool:
    if not requested_fields:
        return False
    if any(requested_field_selectors.get(str(field_name or "").strip().lower()) for field_name in requested_fields):
        return True
    normalized_html = " ".join(str(html or "").lower().replace("&", " and ").split())
    normalized_visible = " ".join(str(visible_text or "").lower().replace("&", " and ").split())
    for field_name in requested_fields:
        terms = requested_field_terms(field_name)
        if not terms:
            continue
        if any(term in normalized_visible or term in normalized_html for term in terms):
            continue
        return True
    return False


def _artifact_path(run_id: int, url: str) -> Path:
    return settings.artifacts_dir / "html" / str(run_id) / f"{_artifact_basename(run_id, url)}.html"


def _network_payload_path(run_id: int, url: str) -> Path:
    return settings.artifacts_dir / "network" / str(run_id) / f"{_artifact_basename(run_id, url)}.json"


def _diagnostics_path(run_id: int, url: str) -> Path:
    return settings.artifacts_dir / "diagnostics" / str(run_id) / f"{_artifact_basename(run_id, url)}.json"


def _write_network_payloads(run_id: int, url: str, payloads: list[dict]) -> None:
    if not payloads:
        return
    path = _network_payload_path(run_id, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payloads, indent=2), encoding="utf-8")


def _write_diagnostics_stub(run_id: int, url: str, diagnostics_path: Path) -> None:
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "url": url,
        "status": "started",
        "artifact_path": None,
        "network_payload_path": None,
        "html_length": 0,
        "json_kind": None,
        "network_payloads": 0,
        "blocked": None,
        "diagnostics": {},
    }
    diagnostics_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _write_failed_diagnostics(
    run_id: int,
    url: str,
    diagnostics_path: Path,
    *,
    error_detail: str,
) -> None:
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "url": url,
        "status": "failed",
        "artifact_path": None,
        "network_payload_path": None,
        "html_length": 0,
        "json_kind": None,
        "network_payloads": 0,
        "blocked": None,
        "diagnostics": {
            "error_code": "acquisition_failed",
            "error_detail": error_detail,
        },
    }
    diagnostics_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _write_diagnostics(
    run_id: int,
    url: str,
    result: AcquisitionResult,
    artifact_path: Path,
    diagnostics_path: Path,
) -> None:
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    blocked = detect_blocked_page(result.html).as_dict() if result.content_type == "html" else None
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "url": url,
        "status": "completed",
        "method": result.method,
        "content_type": result.content_type,
        "artifact_path": str(artifact_path),
        "network_payload_path": str(_network_payload_path(run_id, url)) if result.network_payloads else None,
        "html_length": len(result.html or ""),
        "json_kind": type(result.json_data).__name__ if result.json_data is not None else None,
        "network_payloads": len(result.network_payloads or []),
        "blocked": blocked,
        "diagnostics": result.diagnostics,
    }
    diagnostics_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _build_curl_diagnostics(
    *,
    normalized: HttpFetchResult,
    blocked,
    visible_text: str,
    gate_phrases: bool,
    needs_browser: bool,
    proxy: str | None,
    prefer_stealth: bool,
    advanced_mode: str | None,
    host_wait_seconds: float,
) -> dict[str, object]:
    payload = {
        "curl_status_code": normalized.status_code,
        "curl_content_type": normalized.content_type,
        "curl_error": normalized.error or None,
        "curl_visible_text_length": len(visible_text),
        "curl_blocked": blocked.is_blocked if blocked is not None else False,
        "curl_block_provider": blocked.provider if blocked is not None else None,
        "curl_gate_phrases": gate_phrases,
        "curl_needs_browser": needs_browser,
        "advanced_mode": advanced_mode,
        "proxy_used": bool(proxy),
        "prefer_stealth": prefer_stealth,
        "curl_attempts": normalized.attempts or None,
        "curl_attempt_log": normalized.attempt_log or None,
        "host_wait_seconds": round(host_wait_seconds, 3) if host_wait_seconds > 0 else None,
    }
    return {key: value for key, value in payload.items() if value is not None}


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
