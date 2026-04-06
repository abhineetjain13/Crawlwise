# Acquisition waterfall service with optional proxy rotation.
from __future__ import annotations

import asyncio
import hashlib
import json
import re as _re
import time
from json import loads as parse_json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.adapters.registry import resolve_adapter
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_client import fetch_rendered_html
from app.services.acquisition.browser_runtime import resolve_browser_runtime_options
from app.services.acquisition.pacing import wait_for_host_slot
from app.services.acquisition.http_client import HttpFetchResult, fetch_html_result
from app.services.pipeline_config import (
    ACQUIRE_HOST_MIN_INTERVAL_MS,
    BROWSER_FALLBACK_VISIBLE_TEXT_MIN,
    BROWSER_FIRST_DOMAINS,
    DEFAULT_MAX_SCROLLS,
    JOB_ERROR_PAGE_HEADINGS,
    JOB_ERROR_PAGE_TITLES,
    JS_GATE_PHRASES,
    JOB_REDIRECT_SHELL_CANONICAL_URLS,
    JOB_REDIRECT_SHELL_HEADINGS,
    JOB_REDIRECT_SHELL_TITLES,
)
from app.services.platform_resolver import resolve_platform_family

_COMMERCE_REDIRECT_TITLE_FRAGMENTS: frozenset[str] = frozenset({
    "sign in",
    "log in",
    "login",
    "access denied",
    "403 forbidden",
    "404 not found",
    "page not found",
    "session expired",
    "account required",
})
_JS_SHELL_MIN_CONTENT_LEN = 100_000
_JS_SHELL_VISIBLE_RATIO_MAX = 0.15


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


def _content_html_length(html: str) -> int:
    """Return HTML length with non-content tag bodies removed for shell detection."""
    stripped = _re.sub(
        r"<(script|style|svg)\b[^>]*>.*?</\1\s*>",
        "",
        html,
        flags=_re.IGNORECASE | _re.DOTALL,
    )
    return max(len(stripped), 1)


async def acquire_html(
    run_id: int,
    url: str,
    proxy_list: list[str] | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    sleep_ms: int = 0,
    requested_fields: list[str] | None = None,
    requested_field_selectors: dict[str, list[dict]] | None = None,
    acquisition_profile: dict[str, object] | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> tuple[str, str, str, list[dict]]:
    """Acquire HTML for a URL using the waterfall strategy."""
    result = await acquire(
        run_id=run_id,
        url=url,
        proxy_list=proxy_list,
        surface=surface,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        sleep_ms=sleep_ms,
        requested_fields=requested_fields,
        requested_field_selectors=requested_field_selectors,
        acquisition_profile=acquisition_profile,
        checkpoint=checkpoint,
    )
    return result.html, result.method, result.artifact_path, result.network_payloads


async def acquire(
    run_id: int,
    url: str,
    proxy_list: list[str] | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    sleep_ms: int = 0,
    requested_fields: list[str] | None = None,
    requested_field_selectors: dict[str, list[dict]] | None = None,
    acquisition_profile: dict[str, object] | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> AcquisitionResult:
    """Acquire content for a URL using the waterfall strategy."""
    diagnostics_path = _diagnostics_path(run_id, url)
    profile = dict(acquisition_profile or {})

    # Domain-based fast track: known problematic domains should use the
    # hardened browser runtime, not the minimal default browser settings.
    domain = urlparse(url).netloc.lower().replace("www.", "")
    browser_first = any(df in domain for df in BROWSER_FIRST_DOMAINS) or _memory_prefers_browser(profile)
    if browser_first and "anti_bot_enabled" not in profile:
        profile["anti_bot_enabled"] = True
    runtime_options = resolve_browser_runtime_options(profile)
    prefer_stealth = runtime_options.warm_origin

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
            surface=surface,
            traversal_mode=traversal_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            prefer_stealth=prefer_stealth,
            sleep_ms=sleep_ms,
            requested_fields=requested_fields,
            requested_field_selectors=requested_field_selectors,
            browser_first=browser_first,
            acquisition_profile=profile,
            runtime_options=runtime_options,
            checkpoint=checkpoint,
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
    surface: str | None,
    traversal_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    prefer_stealth: bool,
    sleep_ms: int,
    requested_fields: list[str] | None,
    requested_field_selectors: dict[str, list[dict]] | None,
    browser_first: bool,
    acquisition_profile: dict[str, object] | None,
    runtime_options,
    checkpoint: Callable[[], Awaitable[None]] | None,
) -> AcquisitionResult | None:
    import logging as _logging
    _log = _logging.getLogger(__name__)
    acquisition_started_at = time.perf_counter()
    host_wait_seconds = await wait_for_host_slot(
        urlparse(url).netloc.lower(),
        ACQUIRE_HOST_MIN_INTERVAL_MS,
        checkpoint=checkpoint,
    )

    if browser_first:
        await _cooperative_sleep_ms(sleep_ms, checkpoint=checkpoint)
        browser_started_at = time.perf_counter()
        try:
            browser_result = await fetch_rendered_html(
                url,
                proxy=proxy,
                surface=surface,
                prefer_stealth=prefer_stealth,
                traversal_mode=traversal_mode,
                max_pages=max_pages,
                max_scrolls=max_scrolls,
                request_delay_ms=sleep_ms,
                runtime_options=runtime_options,
                requested_fields=requested_fields,
                requested_field_selectors=requested_field_selectors,
                checkpoint=checkpoint,
            )
        except Exception as exc:
            _log.warning("Memory-led browser-first acquisition failed for %s: %s — falling back to curl_cffi", url, exc)
        else:
            browser_html = browser_result.html if isinstance(browser_result.html, str) else ""
            browser_diagnostics = browser_result.diagnostics if isinstance(browser_result.diagnostics, dict) else {}
            browser_network_payloads = browser_result.network_payloads if isinstance(browser_result.network_payloads, list) else []
            browser_final_url = str(browser_diagnostics.get("final_url") or url).strip() or url
            if (
                browser_html
                and not detect_blocked_page(browser_html).is_blocked
                and not _is_invalid_surface_page(
                    requested_url=url,
                    final_url=browser_final_url,
                    html=browser_html,
                    surface=surface,
                )
            ):
                return AcquisitionResult(
                    html=browser_html,
                    content_type="html",
                    method="playwright",
                    artifact_path=str(_artifact_path(run_id, url)),
                    network_payloads=browser_network_payloads,
                    diagnostics={
                        "browser_attempted": True,
                        "browser_challenge_state": browser_result.challenge_state,
                        "browser_origin_warmed": browser_result.origin_warmed,
                        "browser_network_payloads": len(browser_network_payloads),
                        "browser_diagnostics": browser_diagnostics,
                        "timings_ms": _merge_timing_maps(
                            {"browser_total_ms": _elapsed_ms(browser_started_at)},
                            browser_diagnostics.get("timings_ms"),
                            {"acquisition_total_ms": _elapsed_ms(acquisition_started_at)},
                        ),
                        "memory_prefer_stealth": bool((acquisition_profile or {}).get("prefer_stealth")),
                        "memory_browser_first": True,
                        "host_wait_seconds": round(host_wait_seconds, 3) if host_wait_seconds > 0 else None,
                        "prefer_stealth": prefer_stealth,
                        "anti_bot_enabled": runtime_options.anti_bot_enabled,
                        "proxy_used": bool(proxy),
                    },
                )

    # Always try curl_cffi first — it's faster and more resilient to HTTP/2 issues.
    await _cooperative_sleep_ms(sleep_ms, checkpoint=checkpoint)
    curl_started_at = time.perf_counter()
    fetch_result = await _fetch_with_content_type(url, proxy)
    curl_fetch_ms = _elapsed_ms(curl_started_at)
    normalized = _normalize_fetch_result(fetch_result)
    html = normalized.text
    curl_result: AcquisitionResult | None = None

    if normalized.content_type == "json":
        platform_family = resolve_platform_family(url, "")
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
                content_len=None,
                    gate_phrases=False,
                    needs_browser=False,
                    adapter_hint=None,
                    platform_family=platform_family,
                    proxy=proxy,
                    prefer_stealth=prefer_stealth,
                    traversal_mode=traversal_mode,
                host_wait_seconds=host_wait_seconds,
                memory_prefer_stealth=bool((acquisition_profile or {}).get("prefer_stealth")),
                anti_bot_enabled=runtime_options.anti_bot_enabled,
                memory_browser_first=browser_first,
            ),
        )

    decision_started_at = time.perf_counter()
    blocked = detect_blocked_page(html)
    soup = BeautifulSoup(html, "html.parser")
    visible_text = " ".join(soup.get_text(" ", strip=True).lower().split())
    gate_phrases = any(phrase in visible_text for phrase in JS_GATE_PHRASES)
    
    # Detect JS-shell pages: large HTML with very little visible text indicates
    # a SPA/Next.js shell where all real content is JS-rendered.
    content_len = _content_html_length(html)
    visible_len = len(visible_text)
    js_shell_detected = (
        content_len >= _JS_SHELL_MIN_CONTENT_LEN
        and visible_len > 0
        and (visible_len / content_len) < _JS_SHELL_VISIBLE_RATIO_MAX
    )
    adapter_hint = await _resolve_adapter_hint(url, html)
    platform_family = resolve_platform_family(url, html)
    
    # Determine if we really need a browser.
    needs_browser = bool(
        blocked.is_blocked
        or normalized.status_code in {403, 429, 503}
        or (len(visible_text) < BROWSER_FALLBACK_VISIBLE_TEXT_MIN and content_len < _JS_SHELL_MIN_CONTENT_LEN)
        or gate_phrases
        or (js_shell_detected and adapter_hint is None and platform_family is None and len(visible_text) < 1000)
        or normalized.error
    )
    structured_listing_override = (
        needs_browser
        and not blocked.is_blocked
        and not str(surface or "").strip().lower().endswith("detail")
        and _html_has_extractable_listings_from_soup(soup)
    )
    invalid_surface_page = _is_invalid_surface_page(
        requested_url=url,
        final_url=str(normalized.final_url or url).strip() or url,
        html=html,
        surface=surface,
    )
    if structured_listing_override:
        needs_browser = False
    if invalid_surface_page:
        needs_browser = True
    decision_ms = _elapsed_ms(decision_started_at)

    curl_diagnostics = _build_curl_diagnostics(
        normalized=normalized,
        blocked=blocked,
        visible_text=visible_text,
        content_len=content_len,
        gate_phrases=gate_phrases,
        needs_browser=needs_browser,
        adapter_hint=adapter_hint,
        platform_family=platform_family,
        proxy=proxy,
        prefer_stealth=prefer_stealth,
        traversal_mode=traversal_mode,
        host_wait_seconds=host_wait_seconds,
        memory_prefer_stealth=bool((acquisition_profile or {}).get("prefer_stealth")),
        anti_bot_enabled=runtime_options.anti_bot_enabled,
        memory_browser_first=browser_first,
    )
    curl_diagnostics["curl_final_url"] = normalized.final_url or url
    curl_diagnostics["invalid_surface_page"] = invalid_surface_page or None
    if structured_listing_override:
        curl_diagnostics["js_shell_overridden"] = "structured_data_found"
    curl_diagnostics["timings_ms"] = _merge_timing_maps(
        curl_diagnostics.get("timings_ms"),
        {
            "curl_fetch_ms": curl_fetch_ms,
            "browser_decision_ms": decision_ms,
        },
    )

    # Keep the curl_cffi result as a fallback even if we escalate to browser,
    # but only when the content is substantive enough to be useful for extraction.
    has_useful_content = (
        html
        and not blocked.is_blocked
        and len(visible_text) >= BROWSER_FALLBACK_VISIBLE_TEXT_MIN
        and normalized.status_code not in {403, 429, 503}
        and not invalid_surface_page
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

    force_browser_for_traversal = _should_force_browser_for_traversal(traversal_mode)

    if not needs_browser and not force_browser_for_traversal:
        curl_diagnostics["timings_ms"] = _merge_timing_maps(
            curl_diagnostics.get("timings_ms"),
            {"acquisition_total_ms": _elapsed_ms(acquisition_started_at)},
        )
        return curl_result or AcquisitionResult(
            html=html,
            json_data=normalized.json_data,
            content_type=normalized.content_type,
            method="curl_cffi",
            artifact_path=str(_artifact_path(run_id, url)),
            diagnostics=curl_diagnostics,
        )

    # Escalate to Playwright only for real browser need or explicit traversal modes.
    await _cooperative_sleep_ms(sleep_ms, checkpoint=checkpoint)
    browser_started_at = time.perf_counter()
    try:
        browser_result = await fetch_rendered_html(
            url,
            proxy=proxy,
            surface=surface,
            prefer_stealth=prefer_stealth,
            traversal_mode=traversal_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            request_delay_ms=sleep_ms,
            runtime_options=runtime_options,
            requested_fields=requested_fields,
            requested_field_selectors=requested_field_selectors,
            checkpoint=checkpoint,
        )
    except Exception as exc:
        _log.warning("Playwright failed for %s: %s — falling back to curl_cffi result", url, exc)
        if curl_result is not None:
            curl_result.diagnostics["browser_exception"] = f"{type(exc).__name__}: {exc}"
            curl_result.diagnostics["browser_attempted"] = True
        return curl_result

    browser_html = browser_result.html if isinstance(browser_result.html, str) else ""
    browser_result_diagnostics = browser_result.diagnostics if isinstance(browser_result.diagnostics, dict) else {}
    browser_network_payloads = browser_result.network_payloads if isinstance(browser_result.network_payloads, list) else []
    browser_final_url = str(browser_result_diagnostics.get("final_url") or url).strip() or url
    browser_redirect_shell = _is_invalid_surface_page(
        requested_url=url,
        final_url=browser_final_url,
        html=browser_html,
        surface=surface,
    )
    if (
        browser_html
        and not detect_blocked_page(browser_html).is_blocked
        and not browser_redirect_shell
    ):
        merged_browser_diagnostics = dict(curl_diagnostics)
        merged_browser_diagnostics.update(
            {
                "browser_attempted": True,
                "browser_challenge_state": browser_result.challenge_state,
                "browser_origin_warmed": browser_result.origin_warmed,
                "browser_network_payloads": len(browser_network_payloads),
                "browser_diagnostics": browser_result_diagnostics,
                "timings_ms": _merge_timing_maps(
                    curl_diagnostics.get("timings_ms"),
                    {"browser_total_ms": _elapsed_ms(browser_started_at)},
                    browser_result_diagnostics.get("timings_ms"),
                    {"acquisition_total_ms": _elapsed_ms(acquisition_started_at)},
                ),
            }
        )
        return AcquisitionResult(
            html=browser_html,
            content_type="html",
            method="playwright",
            artifact_path=str(_artifact_path(run_id, url)),
            network_payloads=browser_network_payloads,
            diagnostics=merged_browser_diagnostics,
        )

    # Playwright returned empty or blocked — prefer curl_cffi result if available.
    if curl_result:
        curl_result.diagnostics["browser_attempted"] = True
        curl_result.diagnostics["browser_challenge_state"] = browser_result.challenge_state
        curl_result.diagnostics["browser_origin_warmed"] = browser_result.origin_warmed
        curl_result.diagnostics["browser_network_payloads"] = len(browser_network_payloads)
        curl_result.diagnostics["browser_diagnostics"] = browser_result_diagnostics
        curl_result.diagnostics["browser_blocked"] = bool(
            browser_html and detect_blocked_page(browser_html).is_blocked
        )
        curl_result.diagnostics["browser_redirect_shell"] = browser_redirect_shell or None
        curl_result.diagnostics["timings_ms"] = _merge_timing_maps(
            curl_result.diagnostics.get("timings_ms"),
            {"browser_total_ms": _elapsed_ms(browser_started_at)},
            browser_result_diagnostics.get("timings_ms"),
            {"acquisition_total_ms": _elapsed_ms(acquisition_started_at)},
        )
        _log.info("Playwright returned blocked/empty for %s — using curl_cffi fallback", url)
        if _is_invalid_surface_page(
            requested_url=url,
            final_url=str(normalized.final_url or url).strip() or url,
            html=curl_result.html,
            surface=surface,
        ):
            _log.warning("Discarding curl_cffi fallback for %s because it resolved to a job redirect shell", url)
            return None
        return curl_result

    browser_blocked = bool(browser_html and detect_blocked_page(browser_html).is_blocked)
    if browser_blocked and not browser_redirect_shell:
        blocked_diagnostics = dict(curl_diagnostics)
        blocked_diagnostics.update(
            {
                "browser_attempted": True,
                "browser_challenge_state": browser_result.challenge_state,
                "browser_origin_warmed": browser_result.origin_warmed,
                "browser_network_payloads": len(browser_network_payloads),
                "browser_diagnostics": browser_result_diagnostics,
                "browser_blocked": True,
                "browser_redirect_shell": browser_redirect_shell or None,
                "timings_ms": _merge_timing_maps(
                    curl_diagnostics.get("timings_ms"),
                    {"browser_total_ms": _elapsed_ms(browser_started_at)},
                    browser_result_diagnostics.get("timings_ms"),
                    {"acquisition_total_ms": _elapsed_ms(acquisition_started_at)},
                ),
            }
        )
        return AcquisitionResult(
            html=browser_html,
            content_type="html",
            method="playwright",
            artifact_path=str(_artifact_path(run_id, url)),
            network_payloads=browser_network_payloads,
            diagnostics=blocked_diagnostics,
        )

    if blocked.is_blocked and not invalid_surface_page:
        curl_diagnostics["timings_ms"] = _merge_timing_maps(
            curl_diagnostics.get("timings_ms"),
            {"browser_total_ms": _elapsed_ms(browser_started_at)},
            browser_result_diagnostics.get("timings_ms"),
            {"acquisition_total_ms": _elapsed_ms(acquisition_started_at)},
        )
        return AcquisitionResult(
            html=html,
            json_data=normalized.json_data,
            content_type=normalized.content_type,
            method="curl_cffi",
            artifact_path=str(_artifact_path(run_id, url)),
            diagnostics=curl_diagnostics,
        )

    return None


def _should_force_browser_for_traversal(traversal_mode: str | None) -> bool:
    normalized_mode = str(traversal_mode or "").strip().lower()
    return normalized_mode in {"scroll", "load_more", "paginate"}


async def _cooperative_sleep_ms(
    delay_ms: int,
    *,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> None:
    remaining_ms = max(0, int(delay_ms or 0))
    if remaining_ms <= 0:
        if checkpoint is not None:
            await checkpoint()
        return
    poll_ms = 250
    while remaining_ms > 0:
        if checkpoint is not None:
            await checkpoint()
        current_ms = min(remaining_ms, poll_ms)
        await asyncio.sleep(current_ms / 1000)
        remaining_ms -= current_ms
    if checkpoint is not None:
        await checkpoint()


def _is_invalid_surface_page(
    *,
    requested_url: str,
    final_url: str,
    html: str,
    surface: str | None,
) -> bool:
    return _is_invalid_job_surface_page(
        requested_url=requested_url,
        final_url=final_url,
        html=html,
        surface=surface,
    ) or _is_invalid_commerce_surface_page(
        requested_url=requested_url,
        final_url=final_url,
        surface=surface,
        html=html,
    )


def _is_invalid_job_surface_page(
    *,
    requested_url: str,
    final_url: str,
    html: str,
    surface: str | None,
) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface not in {"job_listing", "job_detail"}:
        return False
    requested = urlparse(requested_url)
    final = urlparse(final_url or requested_url)
    redirected_to_root = (
        bool(final_url)
        and requested.netloc.lower() == final.netloc.lower()
        and requested.path.rstrip("/") != final.path.rstrip("/")
        and final.path.rstrip("/") == ""
    )
    if not html:
        return redirected_to_root
    soup = BeautifulSoup(html, "html.parser")
    title_text = " ".join((soup.title.get_text(" ", strip=True) if soup.title else "").split())
    canonical_url = str((soup.select_one("link[rel='canonical']") or {}).get("href", "")).strip()
    headings = {
        " ".join(node.get_text(" ", strip=True).split()).lower()
        for node in soup.select("h1, [role='heading']")
        if node.get_text(" ", strip=True)
    }
    title_match = title_text in JOB_REDIRECT_SHELL_TITLES
    canonical_match = canonical_url in JOB_REDIRECT_SHELL_CANONICAL_URLS
    heading_match = any(heading in JOB_REDIRECT_SHELL_HEADINGS for heading in headings)
    error_title_match = title_text in JOB_ERROR_PAGE_TITLES
    error_heading_match = any(heading in JOB_ERROR_PAGE_HEADINGS for heading in headings)
    return (redirected_to_root and (title_match or canonical_match or heading_match)) or error_title_match or error_heading_match


def _is_invalid_commerce_surface_page(
    *,
    requested_url: str,
    final_url: str,
    surface: str | None,
    html: str = "",
) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface not in {"ecommerce_detail", "ecommerce_listing"}:
        return False
    requested = urlparse(requested_url)
    final = urlparse(final_url or requested_url)
    redirected_to_root = bool(
        final_url
        and requested.netloc.lower() == final.netloc.lower()
        and requested.path.rstrip("/") != final.path.rstrip("/")
        and final.path.rstrip("/") == ""
    )
    if redirected_to_root:
        return True
    if html:
        soup = BeautifulSoup(html, "html.parser")
        title_text = " ".join(
            (soup.title.get_text(" ", strip=True) if soup.title else "").lower().split()
        )
        if any(fragment in title_text for fragment in _COMMERCE_REDIRECT_TITLE_FRAGMENTS):
            return True
    return False


async def _fetch_with_content_type(url: str, proxy: str | None) -> HttpFetchResult:
    """Fetch URL and detect content type from response headers."""
    return await fetch_html_result(url, proxy=proxy)


async def _resolve_adapter_hint(url: str, html: str) -> str | None:
    if not html:
        return None
    adapter = await resolve_adapter(url, html)
    return adapter.name if adapter is not None else None


_NEXT_DATA_PRODUCT_SIGNALS = (
    '"productId"', '"partNumber"', '"displayName"', '"sku"', '"skuId"', '"price"', '"salePrice"',
    '"listPrice"', '"imageUrl"', '"imageURL"', '"image_url"', '"availability"', '"inStock"',
    '"slug"', '"handle"', '"jobId"', '"jobTitle"', '"companyName"',
)


def _html_has_extractable_listings_from_soup(soup: BeautifulSoup) -> bool:
    product_count = 0
    for node in soup.select("script[type='application/ld+json']"):
        raw = node.string or node.get_text(" ", strip=True) or ""
        try:
            payload = parse_json(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        product_count += _json_ld_listing_count(payload)
        if product_count >= 2:
            return True

    next_data_node = soup.select_one("script#__NEXT_DATA__")
    if next_data_node is not None:
        raw_next_data = next_data_node.string or next_data_node.get_text(" ", strip=True) or ""
        signal_hits = sum(raw_next_data.count(key) for key in _NEXT_DATA_PRODUCT_SIGNALS)
        if signal_hits >= 4:
            return True

    return False


def _json_ld_listing_count(payload: object, *, _depth: int = 0, _max_depth: int = 3) -> int:
    if _depth > _max_depth:
        return 0
    if isinstance(payload, list):
        return sum(
            _json_ld_listing_count(item, _depth=_depth + 1, _max_depth=_max_depth)
            for item in payload
        )
    if not isinstance(payload, dict):
        return 0

    count = 0
    raw_ld_type = payload.get("@type", "")
    if isinstance(raw_ld_type, str):
        ld_types = {raw_ld_type.lower()}
    elif isinstance(raw_ld_type, (list, tuple, set)):
        ld_types = {
            str(item).lower()
            for item in raw_ld_type
            if isinstance(item, str) and item.strip()
        }
    else:
        ld_types = set()

    if ld_types & {"product", "jobposting"}:
        count += 1
    if "itemlist" in ld_types or "itemListElement" in payload:
        count += len(payload.get("itemListElement", []))

    graph = payload.get("@graph")
    if isinstance(graph, list):
        count += sum(
            _json_ld_listing_count(item, _depth=_depth + 1, _max_depth=_max_depth)
            for item in graph
        )

    main_entity = payload.get("mainEntity")
    if isinstance(main_entity, dict):
        count += _json_ld_listing_count(
            main_entity,
            _depth=_depth + 1,
            _max_depth=_max_depth,
        )

    offers = payload.get("offers")
    if isinstance(offers, dict):
        item_offered = offers.get("itemOffered")
        if isinstance(item_offered, list):
            count += sum(1 for item in item_offered if isinstance(item, dict))

    return count


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
    return settings.artifacts_dir / "html" / f"{_artifact_basename(run_id, url)}.html"


def _network_payload_path(run_id: int, url: str) -> Path:
    return settings.artifacts_dir / "network" / f"{_artifact_basename(run_id, url)}.json"


def _diagnostics_path(run_id: int, url: str) -> Path:
    return settings.artifacts_dir / "diagnostics" / f"{_artifact_basename(run_id, url)}.json"


def _write_network_payloads(run_id: int, url: str, payloads: list[dict]) -> None:
    if not payloads:
        return
    path = _network_payload_path(run_id, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payloads, indent=2), encoding="utf-8")


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
    content_len: int | None,
    gate_phrases: bool,
    needs_browser: bool,
    adapter_hint: str | None,
    platform_family: str | None,
    proxy: str | None,
    prefer_stealth: bool,
    traversal_mode: str | None,
    host_wait_seconds: float,
    memory_prefer_stealth: bool,
    anti_bot_enabled: bool,
    memory_browser_first: bool,
) -> dict[str, object]:
    response_headers = normalized.headers if isinstance(normalized.headers, dict) else {}
    payload = {
        "curl_status_code": normalized.status_code,
        "curl_content_type": normalized.content_type,
        "curl_error": normalized.error or None,
        "curl_retry_after_seconds": normalized.retry_after_seconds,
        "curl_visible_text_length": len(visible_text),
        "content_len": content_len,
        "curl_blocked": blocked.is_blocked if blocked is not None else False,
        "curl_block_provider": blocked.provider if blocked is not None else None,
        "curl_gate_phrases": gate_phrases,
        "curl_needs_browser": needs_browser,
        "curl_adapter_hint": adapter_hint,
        "curl_platform_family": platform_family,
        "traversal_mode": traversal_mode,
        "proxy_used": bool(proxy),
        "prefer_stealth": prefer_stealth,
        "anti_bot_enabled": anti_bot_enabled,
        "curl_impersonate_profile": normalized.impersonate_profile or None,
        "curl_attempts": normalized.attempts or None,
        "curl_attempt_log": normalized.attempt_log or None,
        "curl_response_headers": _select_response_headers(response_headers) or None,
        "host_wait_seconds": round(host_wait_seconds, 3) if host_wait_seconds > 0 else None,
        "memory_prefer_stealth": memory_prefer_stealth or None,
        "memory_browser_first": memory_browser_first or None,
        "timings_ms": {},
    }
    return {key: value for key, value in payload.items() if value is not None}


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((time.perf_counter() - started_at) * 1000)))


def _merge_timing_maps(*maps: object) -> dict[str, int]:
    merged: dict[str, int] = {}
    for item in maps:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            try:
                int_value = int(value)
            except (TypeError, ValueError):
                continue
            if int_value >= 0:
                merged[str(key)] = int_value
    return merged


def _select_response_headers(headers: dict[str, str]) -> dict[str, str]:
    keep = ("server", "cf-mitigated", "retry-after", "content-type", "accept-ch", "critical-ch")
    return {
        key: str(headers.get(key) or "")
        for key in keep
        if str(headers.get(key) or "").strip()
    }


def _memory_prefers_browser(acquisition_profile: dict[str, object] | None) -> bool:
    if not isinstance(acquisition_profile, dict):
        return False
    if bool(acquisition_profile.get("prefer_browser")):
        return True
    browser_successes = int(acquisition_profile.get("browser_success_count", 0) or 0)
    curl_successes = int(acquisition_profile.get("curl_success_count", 0) or 0)
    return browser_successes >= 2 and curl_successes == 0


def _artifact_basename(run_id: int, url: str) -> str:
    parsed = urlparse(url)
    host = _slugify(parsed.netloc or "unknown-host")
    short_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{host}-{short_hash}-run_{run_id}"


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
