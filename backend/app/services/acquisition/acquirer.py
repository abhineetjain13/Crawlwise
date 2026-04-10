# Acquisition waterfall service with optional proxy rotation.
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re as _re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from json import loads as parse_json
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings
from app.core.metrics import observe_acquisition_duration
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_client import BrowserResult, fetch_rendered_html
from app.services.acquisition.browser_runtime import resolve_browser_runtime_options
from app.services.acquisition.http_client import HttpFetchResult, fetch_html_result
from app.services.acquisition.pacing import wait_for_host_slot
from app.services.adapters.registry import resolve_adapter
from app.services.config.platform_registry import (
    acquisition_hint_tokens,
    is_job_platform_signal,
    resolve_platform_runtime_policy,
)
from app.services.config.platform_registry import (
    detect_platform_family as detect_platform_family_from_registry,
)
from app.services.exceptions import (
    AcquisitionFailureError,
    AcquisitionTimeoutError,
    ProxyPoolExhaustedError,
)
from app.services.pipeline_config import (
    ACQUIRE_HOST_MIN_INTERVAL_MS,
    ACQUISITION_ATTEMPT_TIMEOUT_SECONDS,
    BROWSER_FALLBACK_VISIBLE_TEXT_MIN,
    BROWSER_FIRST_DOMAINS,
    DEFAULT_MAX_SCROLLS,
    JOB_ERROR_PAGE_HEADINGS,
    JOB_ERROR_PAGE_TITLES,
    JOB_PLATFORM_FAMILIES,
    JOB_REDIRECT_SHELL_CANONICAL_URLS,
    JOB_REDIRECT_SHELL_HEADINGS,
    JOB_REDIRECT_SHELL_TITLES,
    JS_GATE_PHRASES,
    LISTING_MIN_ITEMS,
    PROXY_FAILURE_COOLDOWN_BASE_MS,
    PROXY_FAILURE_COOLDOWN_MAX_MS,
)
from app.services.runtime_metrics import incr
from app.services.url_safety import validate_proxy_endpoint, validate_public_target
from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError

_COMMERCE_REDIRECT_TITLE_FRAGMENTS: frozenset[str] = frozenset(
    {
        "sign in",
        "log in",
        "login",
        "access denied",
        "403 forbidden",
        "404 not found",
        "page not found",
        "session expired",
        "account required",
    }
)
_JS_SHELL_MIN_CONTENT_LEN = 100_000
_JS_SHELL_VISIBLE_RATIO_MAX = 0.15
_MIN_DETAIL_FIELD_SIGNAL_COUNT = 2
logger = logging.getLogger(__name__)
_REDACTED = "[REDACTED]"
_MAX_PROXY_BACKOFF_EXPONENT = 8
_PROXY_FAILURE_STATE: dict[str, tuple[int, float, float]] = {}
_PROXY_FAILURE_STATE_LOCK = asyncio.Lock()
_PROXY_FAILURE_STATE_TTL_SECONDS = 60 * 60
_PROXY_FAILURE_STATE_MAX_ENTRIES = 1024
_SENSITIVE_KEY_TOKENS = (
    "authorization",
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "cookie",
    "set-cookie",
    "session_id",
    "session",
    "jwt",
    "ssn",
    "email",
    "phone",
)
_BEARER_TOKEN_RE = _re.compile(r"(?i)\bbearer\s+[a-z0-9\-\._~\+/]+=*")
_LONG_TOKEN_RE = _re.compile(
    r"(?<![a-z0-9])[a-z0-9_\-]{32,}(?![a-z0-9])", _re.IGNORECASE
)
_EMAIL_RE = _re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b")


class ProxyPoolExhausted(ProxyPoolExhaustedError):  # noqa: N818 - compatibility alias kept for existing imports.
    pass


class ProxyRotator:
    """Round-robin proxy rotator."""

    def __init__(self, proxies: list[str] | None = None):
        self._proxies = [
            proxy.strip() for proxy in (proxies or []) if proxy and proxy.strip()
        ]
        self._index = 0

    def next(self) -> str | None:
        if not self._proxies:
            return None
        proxy = self._proxies[self._index % len(self._proxies)]
        self._index += 1
        return proxy

    async def cycle_once(self, *, use_cooldown: bool = True) -> list[str]:
        if not self._proxies:
            return []
        candidates = list(self._proxies)
        if not use_cooldown:
            return [proxy for proxy in candidates if proxy]
        available: list[str] = []
        for proxy in candidates:
            if proxy and await _is_proxy_available(proxy):
                available.append(proxy)
        return available


def _proxy_backoff_seconds(failure_count: int) -> float:
    if failure_count <= 0:
        return 0.0
    exponent = min(failure_count - 1, _MAX_PROXY_BACKOFF_EXPONENT)
    delay_ms = PROXY_FAILURE_COOLDOWN_BASE_MS * (2**exponent)
    bounded_ms = min(delay_ms, PROXY_FAILURE_COOLDOWN_MAX_MS)
    return max(0.0, bounded_ms / 1000)


def _evict_stale_proxy_entries(now: float) -> None:
    stale_cutoff = now - _PROXY_FAILURE_STATE_TTL_SECONDS
    stale_keys = [
        key
        for key, (
            _failures,
            last_failure_time,
            _cooldown_until,
        ) in _PROXY_FAILURE_STATE.items()
        if last_failure_time <= stale_cutoff
    ]
    for key in stale_keys:
        _PROXY_FAILURE_STATE.pop(key, None)

    if len(_PROXY_FAILURE_STATE) <= _PROXY_FAILURE_STATE_MAX_ENTRIES:
        return
    overflow = len(_PROXY_FAILURE_STATE) - _PROXY_FAILURE_STATE_MAX_ENTRIES
    for key, _state in sorted(
        _PROXY_FAILURE_STATE.items(), key=lambda item: item[1][1]
    )[:overflow]:
        _PROXY_FAILURE_STATE.pop(key, None)


async def _is_proxy_available(proxy: str) -> bool:
    key = str(proxy or "").strip()
    if not key:
        return True
    async with _PROXY_FAILURE_STATE_LOCK:
        now = time.monotonic()
        _evict_stale_proxy_entries(now)
        state = _PROXY_FAILURE_STATE.get(key)
        if state is None:
            return True
        _, _, cooldown_until = state
        return now >= cooldown_until


async def _mark_proxy_failed(proxy: str) -> None:
    key = str(proxy or "").strip()
    if not key:
        return
    async with _PROXY_FAILURE_STATE_LOCK:
        now = time.monotonic()
        _evict_stale_proxy_entries(now)
        previous_failures = int((_PROXY_FAILURE_STATE.get(key) or (0, 0.0, 0.0))[0])
        failures = max(1, previous_failures + 1)
        cooldown_until = now + _proxy_backoff_seconds(failures)
        _PROXY_FAILURE_STATE[key] = (failures, now, cooldown_until)
        _evict_stale_proxy_entries(now)


async def _mark_proxy_succeeded(proxy: str) -> None:
    key = str(proxy or "").strip()
    if not key:
        return
    async with _PROXY_FAILURE_STATE_LOCK:
        now = time.monotonic()
        _PROXY_FAILURE_STATE.pop(key, None)
        _evict_stale_proxy_entries(now)


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
    frame_sources: list[dict] = field(default_factory=list)
    promoted_sources: list[dict] = field(default_factory=list)
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
    platform_family = _detect_platform_family(url)
    effective_surface = _resolve_effective_surface(
        surface,
        platform_family=platform_family,
        adapter_hint=None,
    )
    suggested_surface = _suggest_surface_from_hints(
        surface,
        platform_family=platform_family,
        adapter_hint=None,
    )

    # Domain-based fast track: known problematic domains should use the
    # hardened browser runtime, not the minimal default browser settings.
    domain = urlparse(url).netloc.lower().replace("www.", "")
    browser_first = (
        _matches_domain_policy(domain, BROWSER_FIRST_DOMAINS)
        or _memory_prefers_browser(profile)
        or _requires_browser_first(url, effective_surface)
    )
    if browser_first:
        # Browser-first targets require hardened challenge/runtime handling.
        # Force anti-bot runtime options even if a default false flag was sent.
        profile["anti_bot_enabled"] = True
    runtime_options = resolve_browser_runtime_options(profile)
    prefer_stealth = runtime_options.warm_origin

    rotator = ProxyRotator(proxy_list)
    for proxy in rotator._proxies:
        await validate_proxy_endpoint(proxy)
    proxy_candidates = await rotator.cycle_once(use_cooldown=True)
    if proxy_list and not proxy_candidates:
        # All proxies are currently cooling down; probe one to avoid deadlock.
        fallback_candidates = await rotator.cycle_once(use_cooldown=False)
        proxy_candidates = fallback_candidates[:1]
    if proxy_list and not proxy_candidates:
        incr("proxy_exhaustion_total")
        raise ProxyPoolExhausted(f"No valid proxies configured for {url}")
    if not proxy_candidates:
        proxy_candidates = [None]

    result: AcquisitionResult | None = None
    last_timeout_error: asyncio.TimeoutError | None = None
    for proxy in proxy_candidates:
        try:
            result = await asyncio.wait_for(
                _acquire_once(
                    run_id=run_id,
                    url=url,
                    proxy=proxy,
                    requested_surface=surface,
                    surface=effective_surface,
                    suggested_surface=suggested_surface,
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
                ),
                timeout=float(ACQUISITION_ATTEMPT_TIMEOUT_SECONDS),
            )
        except TimeoutError as exc:
            logger.warning(
                "Acquisition attempt timed out after %.1fs for %s (proxy=%s)",
                float(ACQUISITION_ATTEMPT_TIMEOUT_SECONDS),
                url,
                "yes" if proxy else "no",
            )
            last_timeout_error = exc
            if proxy:
                await _mark_proxy_failed(proxy)
            result = None
        else:
            if proxy:
                if result is None:
                    await _mark_proxy_failed(proxy)
                else:
                    await _mark_proxy_succeeded(proxy)
        if result is not None:
            break

    if result is None:
        # FIX: Offload disk I/O
        await asyncio.to_thread(
            _write_failed_diagnostics,
            run_id,
            url,
            diagnostics_path,
            error_detail="All acquisition attempts failed",
        )
        if proxy_list:
            incr("proxy_exhaustion_total")
            raise ProxyPoolExhausted(f"All configured proxies failed for {url}")
        if last_timeout_error is not None:
            raise AcquisitionTimeoutError(
                f"Timed out acquiring content for {url}"
            ) from last_timeout_error
        raise AcquisitionFailureError(f"Unable to acquire content for {url}")

    path = _artifact_path(run_id, url)
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)

    if result.content_type == "json" and result.json_data is not None:
        path = path.with_suffix(".json")
        await asyncio.to_thread(
            path.write_text,
            json.dumps(result.json_data, indent=2, default=str),
            encoding="utf-8",
        )
    else:
        await asyncio.to_thread(path.write_text, result.html, encoding="utf-8")

    # FIX: Offload network payload and diagnostics disk I/O
    await asyncio.to_thread(
        _write_network_payloads, run_id, url, result.network_payloads
    )
    await asyncio.to_thread(
        _write_diagnostics, run_id, url, result, path, diagnostics_path
    )

    result.artifact_path = str(path)
    result.diagnostics_path = str(diagnostics_path)
    diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
    if bool(diagnostics.get("browser_blocked")) or bool(diagnostics.get("curl_blocked")):
        incr("blocked_page_result_total")
    timings_ms = diagnostics.get("timings_ms") if isinstance(diagnostics, dict) else None
    acquisition_total_ms = 0
    if isinstance(timings_ms, dict):
        acquisition_total_ms = int(timings_ms.get("acquisition_total_ms", 0) or 0)
    if acquisition_total_ms > 0:
        observe_acquisition_duration(acquisition_total_ms / 1000)
    return result


async def _acquire_once(
    *,
    run_id: int,
    url: str,
    proxy: str | None,
    requested_surface: str | None,
    surface: str | None,
    suggested_surface: str | None,
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
    started = time.perf_counter()
    requested_surface = str(requested_surface or "").strip().lower() or None
    suggested_surface = str(suggested_surface or "").strip().lower() or None

    def _finalize_diagnostics_payload(
        diagnostics: dict[str, object] | None,
    ) -> dict[str, object]:
        payload = dict(diagnostics or {})
        payload["surface_requested"] = requested_surface
        payload["surface_effective"] = surface or requested_surface
        payload["suggested_surface"] = (
            suggested_surface
            if requested_surface and suggested_surface and requested_surface != suggested_surface
            else None
        )
        payload["surface_mismatch_detected"] = bool(
            requested_surface
            and suggested_surface
            and requested_surface != suggested_surface
        )
        payload["surface_remapped"] = bool(
            requested_surface and surface and requested_surface != surface
        )
        timings = _merge_timing_maps(payload.get("timings_ms"))
        total_ms = max(0, _elapsed_ms(started))
        if not timings.get("acquisition_total_ms"):
            timings["acquisition_total_ms"] = total_ms
        phase_sum_ms = sum(
            int(value)
            for key, value in timings.items()
            if key != "acquisition_total_ms" and isinstance(value, int)
        )
        timings["phases_total_ms"] = phase_sum_ms
        timings["unattributed_ms"] = max(
            0, int(timings.get("acquisition_total_ms", total_ms)) - phase_sum_ms
        )
        payload["timings_ms"] = timings
        return payload

    host_wait = await wait_for_host_slot(
        urlparse(url).netloc.lower(),
        ACQUIRE_HOST_MIN_INTERVAL_MS,
        checkpoint=checkpoint,
    )
    path = str(_artifact_path(run_id, url))
    browser_first_result = (
        await _try_browser(
            url,
            proxy,
            surface,
            traversal_mode=traversal_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            prefer_stealth=prefer_stealth,
            sleep_ms=sleep_ms,
            runtime_options=runtime_options,
            requested_fields=requested_fields,
            requested_field_selectors=requested_field_selectors,
            checkpoint=checkpoint,
            run_id=run_id,
            failure_log_message="Memory-led browser-first acquisition failed for %s: %s — falling back to curl_cffi",
        )
        if browser_first
        else None
    )
    first_data = (
        getattr(browser_first_result, "_acquirer_browser", {})
        if browser_first_result is not None
        else {}
    )
    first_html = str(first_data.get("html") or "")
    first_extractability = (
        _assess_extractable_html(
            first_html, url=url, surface=surface, adapter_hint=None
        )
        if first_html
        else {}
    )
    browser_first_is_usable = (
        first_extractability.get("has_extractable_data", False)
        if first_extractability
        else False
    )
    browser_first_surface_warnings = _surface_selection_warnings(
        requested_url=url,
        final_url=str(first_data.get("final_url") or url),
        html=first_html,
        surface=surface,
    )
    if (
        browser_first_result is not None
        and first_data.get("html")
        and not first_data.get("blocked")
        and not _is_invalid_surface_page(
            requested_url=url,
            final_url=str(first_data.get("final_url") or url),
            html=first_html,
            surface=surface,
        )
        and browser_first_is_usable
    ):
        return AcquisitionResult(
            html=str(first_data["html"]),
            content_type="html",
            method="playwright",
            artifact_path=path,
            network_payloads=list(first_data.get("network_payloads") or []),
            frame_sources=getattr(browser_first_result, "frame_sources", []),
            promoted_sources=getattr(browser_first_result, "promoted_sources", []),
            diagnostics=_finalize_diagnostics_payload(
                {
                    k: v
                    for k, v in {
                        "browser_attempted": True,
                        "browser_challenge_state": browser_first_result.challenge_state,
                        "browser_origin_warmed": browser_first_result.origin_warmed,
                        "browser_network_payloads": len(
                            list(first_data.get("network_payloads") or [])
                        ),
                        "browser_diagnostics": first_data.get("diagnostics"),
                        "timings_ms": _merge_timing_maps(
                            {"browser_total_ms": first_data.get("browser_total_ms")},
                            first_data.get("diagnostics", {}).get("timings_ms")
                            if isinstance(first_data.get("diagnostics"), dict)
                            else None,
                            {"acquisition_total_ms": _elapsed_ms(started)},
                        ),
                        "memory_prefer_stealth": bool(
                            (acquisition_profile or {}).get("prefer_stealth")
                        ),
                        "memory_browser_first": True,
                        "host_wait_seconds": round(host_wait, 3)
                        if host_wait > 0
                        else None,
                        "prefer_stealth": prefer_stealth,
                        "anti_bot_enabled": runtime_options.anti_bot_enabled,
                        "proxy_used": bool(proxy),
                        "surface_selection_warnings": browser_first_surface_warnings or None,
                    }.items()
                    if v is not None
                }
            ),
        )
    if _should_force_browser_for_traversal(traversal_mode):
        http_result = None
        analysis = {}
    else:
        http_result = await _try_http(
            url,
            proxy,
            surface,
            run_id=run_id,
            traversal_mode=traversal_mode,
            prefer_stealth=prefer_stealth,
            sleep_ms=sleep_ms,
            browser_first=browser_first,
            acquisition_profile=acquisition_profile,
            runtime_options=runtime_options,
            host_wait_seconds=host_wait,
            checkpoint=checkpoint,
        )
    analysis = (
        getattr(http_result, "_acquirer_analysis", {})
        if http_result is not None
        else {}
    )

    promoted_source_result = await _try_promoted_source_acquire(
        url=url,
        proxy=proxy,
        surface=surface,
        run_id=run_id,
        analysis=analysis,
        started=started,
        prefer_stealth=prefer_stealth,
        runtime_options=runtime_options,
        host_wait_seconds=host_wait,
        checkpoint=checkpoint,
    )
    if promoted_source_result is not None:
        return promoted_source_result

    should_escalate, _ = _needs_browser(
        http_result, url, surface, requested_fields, acquisition_profile
    )
    curl_result = (
        analysis.get("curl_result")
        if isinstance(analysis.get("curl_result"), AcquisitionResult)
        else None
    )
    curl_diagnostics = (
        analysis.get("curl_diagnostics")
        if isinstance(analysis.get("curl_diagnostics"), dict)
        else {}
    )
    if (
        http_result is not None
        and not should_escalate
        and not _should_force_browser_for_traversal(traversal_mode)
    ):
        curl_diagnostics["timings_ms"] = _merge_timing_maps(
            curl_diagnostics.get("timings_ms"),
            {"acquisition_total_ms": _elapsed_ms(started)},
        )
        if curl_result is not None:
            if curl_result.diagnostics is None:
                curl_result.diagnostics = {}
            else:
                curl_result.diagnostics = dict(curl_result.diagnostics)
            curl_result.diagnostics["timings_ms"] = curl_diagnostics.get("timings_ms")
            curl_result.diagnostics = _finalize_diagnostics_payload(
                curl_result.diagnostics
            )
            return curl_result
        return AcquisitionResult(
            html=http_result.text,
            json_data=http_result.json_data,
            content_type=http_result.content_type,
            method="curl_cffi",
            artifact_path=path,
            promoted_sources=list(
                (analysis.get("extractability") or {}).get("promoted_sources") or []
            ),
            diagnostics=_finalize_diagnostics_payload(curl_diagnostics),
        )
    browser_result = await _try_browser(
        url,
        proxy,
        surface,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        prefer_stealth=prefer_stealth,
        sleep_ms=sleep_ms,
        runtime_options=runtime_options,
        requested_fields=requested_fields,
        requested_field_selectors=requested_field_selectors,
        checkpoint=checkpoint,
        run_id=run_id,
        diagnostics_sink=curl_result.diagnostics if curl_result is not None else None,
    )
    if browser_result is None:
        if http_result is None:
            http_result = await _try_http(
                url,
                proxy,
                surface,
                run_id=run_id,
                traversal_mode=traversal_mode,
                prefer_stealth=prefer_stealth,
                sleep_ms=sleep_ms,
                browser_first=browser_first,
                acquisition_profile=acquisition_profile,
                runtime_options=runtime_options,
                host_wait_seconds=host_wait,
                checkpoint=checkpoint,
            )
            if http_result is None:
                return None
            analysis = getattr(http_result, "_acquirer_analysis", {})
            curl_result = (
                analysis.get("curl_result")
                if isinstance(analysis.get("curl_result"), AcquisitionResult)
                else None
            )
            curl_diagnostics = (
                analysis.get("curl_diagnostics")
                if isinstance(analysis.get("curl_diagnostics"), dict)
                else {}
            )
        if curl_result is not None:
            if curl_result.diagnostics is None:
                curl_result.diagnostics = {}
            else:
                curl_result.diagnostics = dict(curl_result.diagnostics)
            curl_result.diagnostics = _finalize_diagnostics_payload(
                curl_result.diagnostics
            )
            return curl_result
        return AcquisitionResult(
            html=http_result.text,
            json_data=http_result.json_data,
            content_type=http_result.content_type,
            method="curl_cffi",
            artifact_path=path,
            promoted_sources=list(
                (analysis.get("extractability") or {}).get("promoted_sources") or []
            ),
            diagnostics=_finalize_diagnostics_payload(curl_diagnostics),
        )
    browser_data = getattr(browser_result, "_acquirer_browser", {})
    browser_html = str(browser_data.get("html") or "")
    browser_final_url = str(browser_data.get("final_url") or url).strip() or url
    browser_public_target = True
    try:
        await validate_public_target(browser_final_url)
    except ValueError:
        browser_public_target = False
        logger.warning(
            "Playwright final URL is non-public and was rejected for %s -> %s",
            url,
            browser_final_url,
        )
    browser_diag = (
        browser_data.get("diagnostics")
        if isinstance(browser_data.get("diagnostics"), dict)
        else {}
    )
    browser_payloads = list(browser_data.get("network_payloads") or [])
    browser_redirect_shell = _is_invalid_surface_page(
        requested_url=url,
        final_url=browser_final_url,
        html=browser_html,
        surface=surface,
    )
    browser_surface_warnings = _surface_selection_warnings(
        requested_url=url,
        final_url=browser_final_url,
        html=browser_html,
        surface=surface,
    )
    if (
        browser_html
        and not browser_data.get("blocked")
        and not browser_redirect_shell
        and browser_public_target
    ):
        merged = dict(curl_diagnostics)
        merged.update(
            {
                "browser_attempted": True,
                "browser_challenge_state": browser_result.challenge_state,
                "browser_origin_warmed": browser_result.origin_warmed,
                "browser_network_payloads": len(browser_payloads),
                "browser_diagnostics": browser_diag,
                "surface_selection_warnings": browser_surface_warnings or None,
                "timings_ms": _merge_timing_maps(
                    curl_diagnostics.get("timings_ms"),
                    {"browser_total_ms": browser_data.get("browser_total_ms")},
                    browser_diag.get("timings_ms"),
                    {"acquisition_total_ms": _elapsed_ms(started)},
                ),
            }
        )
        # Surface traversal diagnostics at top level for pipeline/frontend consumers
        for _tkey in ("traversal_mode", "traversal_summary", "traversal_fallback_used", "traversal_fallback_reason"):
            if _tkey in browser_diag:
                merged[_tkey] = browser_diag[_tkey]
        return AcquisitionResult(
            html=browser_html,
            content_type="html",
            method="playwright",
            artifact_path=path,
            network_payloads=browser_payloads,
            frame_sources=getattr(browser_result, "frame_sources", []),
            promoted_sources=getattr(browser_result, "promoted_sources", []),
            diagnostics=_finalize_diagnostics_payload(merged),
        )
    if curl_result is not None:
        curl_result.diagnostics.update(
            {
                "browser_attempted": True,
                "browser_challenge_state": browser_result.challenge_state,
                "browser_origin_warmed": browser_result.origin_warmed,
                "browser_network_payloads": len(browser_payloads),
                "browser_diagnostics": browser_diag,
                "browser_blocked": browser_data.get("blocked") or None,
                "browser_redirect_shell": browser_redirect_shell or None,
                "browser_non_public_target": (not browser_public_target) or None,
                "surface_selection_warnings": browser_surface_warnings or None,
                "timings_ms": _merge_timing_maps(
                    curl_result.diagnostics.get("timings_ms"),
                    {"browser_total_ms": browser_data.get("browser_total_ms")},
                    browser_diag.get("timings_ms"),
                    {"acquisition_total_ms": _elapsed_ms(started)},
                ),
            }
        )
        curl_result.diagnostics = _finalize_diagnostics_payload(curl_result.diagnostics)
        logger.info(
            "Playwright returned blocked/empty for %s — using curl_cffi fallback", url
        )
        return None if bool(analysis.get("invalid_surface_page")) else curl_result
    if (
        browser_data.get("blocked")
        and not browser_redirect_shell
        and browser_public_target
    ):
        blocked = dict(curl_diagnostics)
        blocked.update(
            {
                "browser_attempted": True,
                "browser_challenge_state": browser_result.challenge_state,
                "browser_origin_warmed": browser_result.origin_warmed,
                "browser_network_payloads": len(browser_payloads),
                "browser_diagnostics": browser_diag,
                "browser_blocked": True,
                "browser_redirect_shell": browser_redirect_shell or None,
                "timings_ms": _merge_timing_maps(
                    curl_diagnostics.get("timings_ms"),
                    {"browser_total_ms": browser_data.get("browser_total_ms")},
                    browser_diag.get("timings_ms"),
                    {"acquisition_total_ms": _elapsed_ms(started)},
                ),
            }
        )
        return AcquisitionResult(
            html=browser_html,
            content_type="html",
            method="playwright",
            artifact_path=path,
            network_payloads=browser_payloads,
            frame_sources=getattr(browser_result, "frame_sources", []),
            promoted_sources=getattr(browser_result, "promoted_sources", []),
            diagnostics=_finalize_diagnostics_payload(blocked),
        )
    if (
        http_result is not None
        and getattr(analysis.get("blocked"), "is_blocked", False)
        and not bool(analysis.get("invalid_surface_page"))
    ):
        curl_diagnostics["timings_ms"] = _merge_timing_maps(
            curl_diagnostics.get("timings_ms"),
            {"browser_total_ms": browser_data.get("browser_total_ms")},
            browser_diag.get("timings_ms"),
            {"acquisition_total_ms": _elapsed_ms(started)},
        )
        return AcquisitionResult(
            html=http_result.text,
            json_data=http_result.json_data,
            content_type=http_result.content_type,
            method="curl_cffi",
            artifact_path=path,
            promoted_sources=list(
                (analysis.get("extractability") or {}).get("promoted_sources") or []
            ),
            diagnostics=_finalize_diagnostics_payload(curl_diagnostics),
        )
    # FINAL FALLBACK: If we have a curl result and browser failed or was rejected, return curl.
    if curl_result is not None:
        if curl_result.diagnostics is None:
            curl_result.diagnostics = {}
        else:
            curl_result.diagnostics = dict(curl_result.diagnostics)
        curl_result.diagnostics["browser_failed"] = True
        curl_result.diagnostics = _finalize_diagnostics_payload(curl_result.diagnostics)
        return curl_result

    return None


async def _try_promoted_source_acquire(
    *,
    url: str,
    proxy: str | None,
    surface: str | None,
    run_id: int,
    analysis: dict[str, object],
    started: float,
    prefer_stealth: bool,
    runtime_options,
    host_wait_seconds: float,
    checkpoint: Callable[[], Awaitable[None]] | None,
) -> AcquisitionResult | None:
    extractability = (
        analysis.get("extractability")
        if isinstance(analysis.get("extractability"), dict)
        else {}
    )
    promoted_sources = list(extractability.get("promoted_sources") or [])
    if not promoted_sources:
        return None
    if str(extractability.get("reason") or "") != "iframe_shell":
        return None

    max_candidates = 2
    for source in promoted_sources[:max_candidates]:
        if checkpoint is not None:
            await checkpoint()
        if not isinstance(source, dict):
            continue
        promoted_url = str(source.get("url") or "").strip()
        if not promoted_url:
            continue
        try:
            await validate_public_target(promoted_url)
        except ValueError:
            logger.debug("Skipping non-public promoted source %s", promoted_url)
            continue
        try:
            fetch_started = time.perf_counter()
            promoted_fetch = _normalize_fetch_result(
                await _fetch_with_content_type(promoted_url, proxy)
            )
            promoted_timings = {"promoted_source_fetch_ms": _elapsed_ms(fetch_started)}
        except (OSError, RuntimeError, ValueError, TypeError):
            continue
        if promoted_fetch.content_type != "html":
            continue
        promoted_html = str(promoted_fetch.text or "")
        if not promoted_html:
            continue
        promoted_adapter_hint = await _resolve_adapter_hint(promoted_url, promoted_html)
        promoted_extractability = _assess_extractable_html(
            promoted_html,
            url=promoted_url,
            surface=surface,
            adapter_hint=promoted_adapter_hint,
        )
        promoted_has_data = bool(promoted_extractability.get("has_extractable_data"))
        if not promoted_has_data and _html_has_min_listing_link_signals(
            promoted_html, surface=surface
        ):
            promoted_has_data = True
            promoted_extractability = {
                **promoted_extractability,
                "has_extractable_data": True,
                "reason": "listing_link_signals",
            }
        if not promoted_has_data:
            continue
        blocked = detect_blocked_page(promoted_html)
        if blocked.is_blocked:
            continue

        diagnostics = _build_curl_diagnostics(
            normalized=promoted_fetch,
            blocked=blocked,
            visible_text="",
            content_len=_content_html_length(promoted_html),
            gate_phrases=False,
            needs_browser=False,
            adapter_hint=promoted_adapter_hint,
            platform_family=_detect_platform_family(promoted_url, promoted_html),
            proxy=proxy,
            prefer_stealth=prefer_stealth,
            traversal_mode=None,
            host_wait_seconds=host_wait_seconds,
            memory_prefer_stealth=False,
            anti_bot_enabled=runtime_options.anti_bot_enabled,
            memory_browser_first=False,
        )
        diagnostics.update(
            {
                "curl_final_url": promoted_fetch.final_url or promoted_url,
                "extractability": promoted_extractability,
                "promoted_source_used": {
                    "kind": str(source.get("kind") or "iframe"),
                    "url": promoted_url,
                },
                "promoted_source_candidates": promoted_sources,
                "timings_ms": _merge_timing_maps(
                    diagnostics.get("timings_ms"),
                    promoted_timings,
                    {"acquisition_total_ms": _elapsed_ms(started)},
                ),
            }
        )
        timings = _merge_timing_maps(diagnostics.get("timings_ms"))
        phase_sum_ms = sum(
            int(value)
            for key, value in timings.items()
            if key != "acquisition_total_ms" and isinstance(value, int)
        )
        timings["phases_total_ms"] = phase_sum_ms
        timings["unattributed_ms"] = max(
            0, int(timings.get("acquisition_total_ms", 0)) - phase_sum_ms
        )
        diagnostics["timings_ms"] = timings
        return AcquisitionResult(
            html=promoted_html,
            content_type="html",
            method="curl_cffi",
            artifact_path=str(_artifact_path(run_id, url)),
            promoted_sources=promoted_sources,
            diagnostics=diagnostics,
        )
    return None


def _html_has_min_listing_link_signals(html: str, *, surface: str | None) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_surface.endswith("listing"):
        return False
    soup = BeautifulSoup(html, "html.parser")
    count = 0
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        text = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not text:
            continue
        if len(text) < 3:
            continue
        count += 1
        if count >= max(2, int(LISTING_MIN_ITEMS)):
            return True
    return False


def _analyze_html_sync(html: str) -> tuple[str, bool]:
    """Runs heavy CPU-bound HTML analysis synchronously."""
    soup = BeautifulSoup(html, "html.parser")
    visible_text = " ".join(soup.get_text(" ", strip=True).lower().split())
    gate_phrases = any(phrase in visible_text for phrase in JS_GATE_PHRASES)
    return visible_text, gate_phrases


async def _try_http(
    url: str,
    proxy: str | None,
    surface: str | None,
    *,
    run_id: int,
    traversal_mode: str | None,
    prefer_stealth: bool,
    sleep_ms: int,
    browser_first: bool,
    acquisition_profile: dict[str, object] | None,
    runtime_options,
    host_wait_seconds: float,
    checkpoint: Callable[[], Awaitable[None]] | None,
) -> HttpFetchResult | None:
    try:
        await _cooperative_sleep_ms(sleep_ms, checkpoint=checkpoint)
        curl_started_at = time.perf_counter()
        normalized = _normalize_fetch_result(await _fetch_with_content_type(url, proxy))
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        logger.warning("curl_cffi acquisition failed for %s: %s", url, exc)
        return None
    html = normalized.text
    platform_family = _detect_platform_family(
        url, "" if normalized.content_type == "json" else html
    )
    diagnostics = _build_curl_diagnostics(
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
    )
    diagnostics["curl_final_url"] = normalized.final_url or url
    diagnostics["timings_ms"] = _merge_timing_maps(
        diagnostics.get("timings_ms"), {"curl_fetch_ms": _elapsed_ms(curl_started_at)}
    )
    analysis: dict[str, object] = {
        "curl_diagnostics": diagnostics,
        "curl_result": None,
        "extractability": {
            "has_extractable_data": False,
            "reason": "non_html_response",
        },
        "blocked": None,
        "invalid_surface_page": False,
    }
    if normalized.content_type == "json":
        analysis["curl_result"] = AcquisitionResult(
            html=html,
            json_data=normalized.json_data,
            content_type="json",
            method="curl_cffi",
            artifact_path=str(_artifact_path(run_id, url)),
            promoted_sources=[],
            diagnostics=diagnostics,
        )
        normalized._acquirer_analysis = analysis
        return normalized
    decision_started_at = time.perf_counter()

    # FIX: Offload CPU-bound HTML parsing to prevent Event Loop Starvation
    blocked = await asyncio.to_thread(detect_blocked_page, html)
    visible_text, gate_phrases = await asyncio.to_thread(_analyze_html_sync, html)
    content_len = _content_html_length(html)

    visible_len = len(visible_text)
    js_shell_detected = (
        content_len >= _JS_SHELL_MIN_CONTENT_LEN
        and visible_len > 0
        and (visible_len / content_len) < _JS_SHELL_VISIBLE_RATIO_MAX
    )
    adapter_hint = await _resolve_adapter_hint(url, html)
    platform_family = _detect_platform_family(url, html)
    effective_surface = _resolve_effective_surface(
        surface,
        platform_family=platform_family,
        adapter_hint=adapter_hint,
    )
    suggested_surface = _suggest_surface_from_hints(
        surface,
        platform_family=platform_family,
        adapter_hint=adapter_hint,
    )

    # FIX: Offload extractability check
    extractability = await asyncio.to_thread(
        _assess_extractable_html,
        html,
        url=url,
        surface=surface,
        adapter_hint=adapter_hint,
    )

    invalid_surface_page = _is_invalid_surface_page(
        requested_url=url,
        final_url=str(normalized.final_url or url).strip() or url,
        html=html,
        surface=surface,
    )
    surface_selection_warnings = _surface_selection_warnings(
        requested_url=url,
        final_url=str(normalized.final_url or url).strip() or url,
        html=html,
        surface=surface,
    )
    diagnostics.update(
        {
            "curl_visible_text_length": len(visible_text),
            "content_len": content_len,
            "curl_blocked": blocked.is_blocked,
            "curl_block_provider": blocked.provider or None,
            "curl_gate_phrases": gate_phrases,
            "curl_adapter_hint": adapter_hint,
            "curl_platform_family": platform_family,
            "surface_requested": str(surface or "").strip().lower() or None,
            "surface_effective": effective_surface,
            "suggested_surface": (
                suggested_surface
                if str(surface or "").strip().lower()
                and suggested_surface
                and str(surface or "").strip().lower() != suggested_surface
                else None
            ),
            "surface_mismatch_detected": bool(
                str(surface or "").strip()
                and suggested_surface
                and str(surface or "").strip().lower() != suggested_surface
            ),
            "surface_remapped": bool(
                str(surface or "").strip().lower()
                and effective_surface
                and str(surface or "").strip().lower() != effective_surface
            ),
            "invalid_surface_page": invalid_surface_page or None,
            "surface_selection_warnings": surface_selection_warnings or None,
            "extractability": extractability,
            "promoted_sources": extractability.get("promoted_sources"),
        }
    )
    diagnostics["timings_ms"] = _merge_timing_maps(
        diagnostics.get("timings_ms"),
        {"browser_decision_ms": _elapsed_ms(decision_started_at)},
    )
    useful = bool(
        html
        and not blocked.is_blocked
        and extractability["has_extractable_data"]
        and normalized.status_code not in {403, 429, 503}
        and not invalid_surface_page
    )
    # Keep a curl fallback artifact even when extractability is weak so
    # browser failures can still return usable HTML instead of hard-failing.
    fallback_eligible = bool(
        html
        and normalized.status_code not in {403, 429, 503}
        and not invalid_surface_page
    )
    analysis.update(
        {
            "blocked": blocked,
            "visible_text": visible_text,
            "content_len": content_len,
            "gate_phrases": gate_phrases,
            "js_shell_detected": js_shell_detected,
            "adapter_hint": adapter_hint,
            "platform_family": platform_family,
            "extractability": extractability,
            "invalid_surface_page": invalid_surface_page,
            "curl_result": AcquisitionResult(
                html=html,
                json_data=normalized.json_data,
                content_type=normalized.content_type,
                method="curl_cffi",
                artifact_path=str(_artifact_path(run_id, url)),
                promoted_sources=list(extractability.get("promoted_sources") or []),
                diagnostics=diagnostics,
            )
            if useful or fallback_eligible
            else None,
        }
    )
    normalized._acquirer_analysis = analysis
    return normalized


def _needs_browser(
    http_result: HttpFetchResult | None,
    url: str,
    surface: str | None,
    requested_fields: list[str] | None,
    acquisition_profile: dict[str, object] | None,
) -> tuple[bool, str]:
    del url, acquisition_profile
    if http_result is None:
        return True, "http_failed"
    analysis = getattr(http_result, "_acquirer_analysis", {})
    if http_result.content_type == "json":
        return False, "json_response"
    blocked = analysis.get("blocked")
    visible_text = str(analysis.get("visible_text") or "")
    content_len = int(analysis.get("content_len") or 0)
    gate_phrases = bool(analysis.get("gate_phrases"))
    extractability = (
        analysis.get("extractability")
        if isinstance(analysis.get("extractability"), dict)
        else {}
    )
    invalid_surface_page = bool(analysis.get("invalid_surface_page"))
    js_shell_detected = bool(analysis.get("js_shell_detected"))
    normalized_surface = str(surface or "").strip().lower()
    supported_surfaces = {
        "ecommerce_listing",
        "job_listing",
        "ecommerce_detail",
        "job_detail",
    }
    supported_surface = normalized_surface in supported_surfaces
    requested_field_names = [
        str(field or "").strip()
        for field in (requested_fields or [])
        if str(field or "").strip()
    ]
    missing_data_requires_browser = (
        supported_surface
        and not extractability.get("has_extractable_data")
        and str(extractability.get("reason") or "")
        in {
            "listing_search_shell_without_records",
            "iframe_shell",
            "frameset_shell",
            "insufficient_detail_signals",
            "no_listing_signals",
            "empty_html",
        }
    )
    needs_browser, reason = False, "extractable_data_found"
    if getattr(blocked, "is_blocked", False):
        needs_browser, reason = True, "blocked_page"
    elif http_result.status_code in {403, 429, 503}:
        needs_browser, reason = True, f"http_status_{http_result.status_code}"
    elif missing_data_requires_browser:
        needs_browser, reason = (
            True,
            str(extractability.get("reason") or "missing_extractable_data"),
        )
    elif (
        normalized_surface.endswith("detail")
        and requested_field_names
        and js_shell_detected
        and len(visible_text) < 1000
    ):
        needs_browser, reason = True, "requested_fields_require_browser"
    elif (
        len(visible_text) < BROWSER_FALLBACK_VISIBLE_TEXT_MIN
        and content_len < _JS_SHELL_MIN_CONTENT_LEN
    ):
        needs_browser, reason = True, "low_visible_text"
    elif gate_phrases:
        needs_browser, reason = True, "js_gate_phrases"
    elif js_shell_detected and len(visible_text) < 1000:
        needs_browser, reason = True, "js_shell"
    elif http_result.error:
        needs_browser, reason = True, "http_error"
    extractability_reason = str(extractability.get("reason") or "")
    # Do NOT cancel browser escalation for JS shells when the only evidence
    # of extractable data is an adapter hint — the adapter needs rendered HTML.
    structured_override = (
        needs_browser
        and reason != "js_shell"
        and not getattr(blocked, "is_blocked", False)
        and not str(surface or "").strip().lower().endswith("detail")
        and bool(extractability.get("has_extractable_data"))
        and extractability_reason not in {"surface_unspecified", "adapter_hint"}
    )
    if structured_override:
        needs_browser, reason = False, "structured_data_found"
    if invalid_surface_page:
        needs_browser, reason = True, "invalid_surface_page"
    diagnostics = (
        analysis.get("curl_diagnostics")
        if isinstance(analysis.get("curl_diagnostics"), dict)
        else {}
    )
    diagnostics["curl_needs_browser"] = needs_browser
    diagnostics["browser_retry_reason"] = (
        str(extractability.get("reason") or reason) if needs_browser else None
    )
    if structured_override:
        override_reason = str(extractability.get("reason") or "extractable_data_found")
        diagnostics["js_shell_overridden"] = (
            "structured_data_found"
            if override_reason in {"structured_listing_markup", "next_data_signals"}
            else override_reason
        )
    return needs_browser, reason


async def _try_browser(
    url: str,
    proxy: str | None,
    surface: str | None,
    *,
    traversal_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    prefer_stealth: bool,
    sleep_ms: int,
    runtime_options,
    requested_fields: list[str] | None,
    requested_field_selectors: dict[str, list[dict]] | None,
    checkpoint: Callable[[], Awaitable[None]] | None,
    run_id: int | None = None,
    diagnostics_sink: dict[str, object] | None = None,
    failure_log_message: str = "Playwright failed for %s: %s — falling back to curl_cffi result",
) -> BrowserResult | None:
    logger.info("[browser] attempting url=%s traversal_mode=%s", url, traversal_mode)
    try:
        await _cooperative_sleep_ms(sleep_ms, checkpoint=checkpoint)
        browser_started_at = time.perf_counter()
        result = await fetch_rendered_html(
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
            run_id=run_id,
        )
    except (PlaywrightError, OSError, RuntimeError, ValueError, TypeError) as exc:
        logger.warning("[browser] FAILED type=%s msg=%s", type(exc).__name__, exc)
        incr("browser_launch_failures_total")
        # Surface to crawl log so users can see traversal was abandoned
        if run_id is not None:
            from app.services.crawl_events import append_log_event

            try:
                traversal_failure = _should_force_browser_for_traversal(traversal_mode)
                log_message = (
                    f"[traversal] Browser acquisition failed, falling back to curl: {type(exc).__name__}: {exc}"
                    if traversal_failure
                    else f"Browser acquisition failed: {type(exc).__name__}: {exc}"
                )
                await append_log_event(
                    run_id=run_id,
                    level="warning",
                    message=log_message,
                )
            except Exception:
                incr("acquisition_log_event_failures_total")
                logger.debug(
                    "Failed to append browser acquisition fallback event for %s",
                    url,
                    exc_info=True,
                )
        if diagnostics_sink is not None:
            diagnostics_sink["browser_exception"] = f"{type(exc).__name__}: {exc}"
            diagnostics_sink["browser_attempted"] = True
        return None
    browser_html = result.html if isinstance(result.html, str) else ""
    browser_diagnostics = (
        result.diagnostics if isinstance(result.diagnostics, dict) else {}
    )
    browser_network_payloads = (
        result.network_payloads if isinstance(result.network_payloads, list) else []
    )
    result._acquirer_browser = {"html": browser_html, "diagnostics": browser_diagnostics, "network_payloads": browser_network_payloads, "final_url": str(browser_diagnostics.get("final_url") or url).strip() or url, "blocked": bool(browser_html and detect_blocked_page(browser_html).is_blocked), "browser_total_ms": _elapsed_ms(browser_started_at)}
    return result


def _should_force_browser_for_traversal(traversal_mode: str | None) -> bool:
    normalized_mode = str(traversal_mode or "").strip().lower()
    return normalized_mode in {"auto", "scroll", "load_more", "paginate"}


def _resolve_effective_surface(
    surface: str | None,
    *,
    platform_family: str | None,
    adapter_hint: str | None,
) -> str | None:
    requested_surface = str(surface or "").strip().lower()
    if not requested_surface:
        return None
    suggested_surface = _suggest_surface_from_hints(
        requested_surface,
        platform_family=platform_family,
        adapter_hint=adapter_hint,
    )
    return suggested_surface or requested_surface


def _suggest_surface_from_hints(
    surface: str | None,
    *,
    platform_family: str | None,
    adapter_hint: str | None,
) -> str | None:
    requested_surface = str(surface or "").strip().lower()
    if not requested_surface:
        return None
    if requested_surface not in {
        "ecommerce_listing",
        "ecommerce_detail",
        "job_listing",
        "job_detail",
    }:
        return requested_surface

    normalized_platform = str(platform_family or "").strip().lower()
    normalized_hint = str(adapter_hint or "").strip().lower()
    is_job_like = is_job_platform_signal(
        platform_family=normalized_platform,
        adapter_hint=normalized_hint,
    ) or normalized_platform in JOB_PLATFORM_FAMILIES
    if not is_job_like:
        return requested_surface
    if requested_surface.endswith("listing"):
        return "job_listing"
    if requested_surface.endswith("detail"):
        return "job_detail"
    return requested_surface


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
    return _is_invalid_commerce_surface_page(
        requested_url=requested_url,
        final_url=final_url,
        surface=surface,
        html=html,
    )


def _surface_selection_warnings(
    *,
    requested_url: str,
    final_url: str,
    html: str,
    surface: str | None,
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    job_warning = _diagnose_job_surface_page(
        requested_url=requested_url,
        final_url=final_url,
        html=html,
        surface=surface,
    )
    if job_warning is not None:
        warnings.append(job_warning)
    return warnings


def _diagnose_job_surface_page(
    *,
    requested_url: str,
    final_url: str,
    html: str,
    surface: str | None,
) -> dict[str, object] | None:
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface not in {"job_listing", "job_detail"}:
        return None
    requested = urlparse(requested_url)
    final = urlparse(final_url or requested_url)
    redirected_to_root = (
        bool(final_url)
        and requested.netloc.lower() == final.netloc.lower()
        and requested.path.rstrip("/") != final.path.rstrip("/")
        and final.path.rstrip("/") == ""
    )
    if not html and not redirected_to_root:
        return None
    warning_signals: list[str] = []
    if redirected_to_root:
        warning_signals.append("redirected_to_root")
    if not html:
        return {
            "surface_requested": normalized_surface,
            "warning": "surface_selection_may_be_low_confidence",
            "signals": warning_signals,
            "requested_url": requested_url,
            "final_url": final_url or requested_url,
        }
    soup = BeautifulSoup(html, "html.parser")
    title_text = " ".join(
        (soup.title.get_text(" ", strip=True) if soup.title else "").split()
    )
    canonical_url = str(
        (soup.select_one("link[rel='canonical']") or {}).get("href", "")
    ).strip()
    headings = {
        " ".join(node.get_text(" ", strip=True).split()).lower()
        for node in soup.select("h1, [role='heading']")
        if node.get_text(" ", strip=True)
    }
    title_match = title_text in JOB_REDIRECT_SHELL_TITLES
    canonical_match = canonical_url in JOB_REDIRECT_SHELL_CANONICAL_URLS
    heading_match = any(heading in JOB_REDIRECT_SHELL_HEADINGS for heading in headings)
    error_title_match = title_text in JOB_ERROR_PAGE_TITLES
    error_heading_match = any(
        heading in JOB_ERROR_PAGE_HEADINGS for heading in headings
    )
    if title_match:
        warning_signals.append("redirect_shell_title")
    if canonical_match:
        warning_signals.append("redirect_shell_canonical")
    if heading_match:
        warning_signals.append("auth_wall_heading")
    if error_title_match:
        warning_signals.append("soft_404_title")
    if error_heading_match:
        warning_signals.append("soft_404_heading")
    if not warning_signals:
        return None
    return {
        "surface_requested": normalized_surface,
        "warning": "surface_selection_may_be_low_confidence",
        "signals": warning_signals,
        "requested_url": requested_url,
        "final_url": final_url or requested_url,
        "title": title_text or None,
        "canonical_url": canonical_url or None,
    }


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
        if any(
            fragment in title_text for fragment in _COMMERCE_REDIRECT_TITLE_FRAGMENTS
        ):
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
    '"productId"',
    '"partNumber"',
    '"displayName"',
    '"sku"',
    '"skuId"',
    '"price"',
    '"salePrice"',
    '"listPrice"',
    '"imageUrl"',
    '"imageURL"',
    '"image_url"',
    '"availability"',
    '"inStock"',
    '"slug"',
    '"handle"',
    '"jobId"',
    '"jobTitle"',
    '"companyName"',
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
        raw_next_data = (
            next_data_node.string or next_data_node.get_text(" ", strip=True) or ""
        )
        signal_hits = sum(
            raw_next_data.count(key) for key in _NEXT_DATA_PRODUCT_SIGNALS
        )
        if signal_hits >= 4:
            return True

    return False


def _find_promotable_iframe_sources(html: str, *, surface: str | None) -> list[dict]:
    normalized_surface = str(surface or "").strip().lower()
    if "job" not in normalized_surface:
        return []
    soup = BeautifulSoup(html, "html.parser")
    promoted: list[dict] = []
    promotable_tokens = _promotable_job_iframe_tokens()
    for tag in soup.select("iframe[src], frame[src]"):
        src = str(tag.get("src") or "").strip()
        if not src:
            continue
        lowered = src.lower()
        if any(token in lowered for token in promotable_tokens):
            kind = "frame" if tag.name and tag.name.lower() == "frame" else "iframe"
            promoted.append({"kind": kind, "url": src, "same_origin": False})
    return promoted


def _promotable_job_iframe_tokens() -> tuple[str, ...]:
    base_tokens = {"job", "jobs", "career", "careers"}
    merged = {
        token for token in (base_tokens | set(acquisition_hint_tokens())) if len(token) >= 3
    }
    return tuple(sorted(merged))


def _count_json_ld_type_signals(html: str) -> int:
    """Count Product/JobPosting @type occurrences via raw string matching."""
    count = 0
    search_start = 0
    html_lower = html.lower()
    while True:
        pos = html_lower.find('"@type"', search_start)
        if pos == -1:
            break
        window = html_lower[pos : pos + 200]
        if '"product"' in window or '"jobposting"' in window:
            count += 1
        search_start = pos + 7
    return count


def _count_json_ld_non_product_types(html: str) -> int:
    """Count non-product @type occurrences to filter shell pages."""
    count = 0
    search_start = 0
    html_lower = html.lower()
    while True:
        pos = html_lower.find('"@type"', search_start)
        if pos == -1:
            break
        window = html_lower[pos : pos + 200]
        if '"product"' not in window and '"jobposting"' not in window:
            count += 1
        search_start = pos + 7
    return count


def _assess_extractable_html(
    html: str,
    *,
    url: str,
    surface: str | None,
    adapter_hint: str | None,
) -> dict[str, object]:
    """Lightweight signal check — no extraction-layer imports."""
    normalized_surface = str(surface or "").strip().lower()
    if not html:
        return {"has_extractable_data": False, "reason": "empty_html"}

    soup_probe = BeautifulSoup(html, "html.parser")
    if soup_probe.find("frameset") is not None or "<frameset" in html.lower():
        promoted_iframes = _find_promotable_iframe_sources(html, surface=surface)
        return {
            "has_extractable_data": False,
            "reason": "frameset_shell",
            "promoted_sources": promoted_iframes or None,
        }

    if normalized_surface.endswith("listing") or not normalized_surface:
        promoted_iframes = _find_promotable_iframe_sources(html, surface=surface)

        # (a) JSON-LD: count "@type" paired with Product/JobPosting
        json_ld_count = _count_json_ld_type_signals(html)
        non_product_types = _count_json_ld_non_product_types(html)
        total_types = json_ld_count + non_product_types
        is_mostly_non_product = (
            total_types > 0 and (non_product_types / total_types) > 0.8
        )
        if json_ld_count >= 2 and not is_mostly_non_product:
            return {
                "has_extractable_data": True,
                "reason": "structured_listing_markup",
                "json_ld_count": json_ld_count,
                "promoted_sources": promoted_iframes or None,
            }

        # (b) __NEXT_DATA__ signal density OR general product signals in HTML
        signal_hits = sum(html.count(sig) for sig in _NEXT_DATA_PRODUCT_SIGNALS)
        has_next_data = "__NEXT_DATA__" in html
        if (has_next_data or signal_hits >= 15) and signal_hits >= 4:
            return {
                "has_extractable_data": True,
                "reason": "next_data_signals"
                if has_next_data
                else "product_signals_in_html",
                "signal_hits": signal_hits,
                "promoted_sources": promoted_iframes or None,
            }

        # (c) Iframe shell detection (BeautifulSoup only, no extractor imports)
        if promoted_iframes:
            return {
                "has_extractable_data": False,
                "reason": "iframe_shell",
                "promoted_sources": promoted_iframes,
            }

        if adapter_hint:
            return {
                "has_extractable_data": True,
                "reason": "adapter_hint",
                "adapter_hint": adapter_hint,
            }

        # (d) Search shell detection
        html_lower = html.lower()
        if (
            "window.searchconfig" in html_lower
            or "data-jibe-search-version" in html_lower
            or "window._jibe" in html_lower
        ):
            return {
                "has_extractable_data": False,
                "reason": "listing_search_shell_without_records",
            }

        return {"has_extractable_data": False, "reason": "no_listing_signals"}

    if normalized_surface.endswith("detail"):
        if adapter_hint:
            return {
                "has_extractable_data": True,
                "reason": "adapter_hint",
                "adapter_hint": adapter_hint,
            }
        # (a) JSON-LD presence for detail types
        html_lower = html.lower()
        has_json_ld = '"@type"' in html and any(
            t in html_lower
            for t in ('"product"', '"jobposting"', '"offer"', '"service"')
        )
        if has_json_ld:
            return {"has_extractable_data": True, "reason": "detail_json_ld"}

        # (b) Count canonical field tokens in visible text
        soup = BeautifulSoup(html, "html.parser")
        visible_text = soup.get_text(" ", strip=True).lower()
        detail_tokens = ("title", "price", "brand", "description", "sku")
        field_hits = sum(1 for tok in detail_tokens if tok in visible_text)
        if field_hits >= _MIN_DETAIL_FIELD_SIGNAL_COUNT:
            return {
                "has_extractable_data": True,
                "reason": "detail_field_signals",
                "field_signal_count": field_hits,
            }

        return {
            "has_extractable_data": False,
            "reason": "insufficient_detail_signals",
            "field_signal_count": field_hits,
        }

    return {"has_extractable_data": True, "reason": "surface_unspecified"}


def _json_ld_listing_count(
    payload: object, *, _depth: int = 0, _max_depth: int = 3
) -> int:
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


def _normalize_fetch_result(
    result: HttpFetchResult | tuple[str, str, dict | list | None],
) -> HttpFetchResult:
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
    return (
        settings.artifacts_dir / "network" / f"{_artifact_basename(run_id, url)}.json"
    )


def _diagnostics_path(run_id: int, url: str) -> Path:
    return (
        settings.artifacts_dir
        / "diagnostics"
        / f"{_artifact_basename(run_id, url)}.json"
    )


def _write_network_payloads(run_id: int, url: str, payloads: list[dict]) -> None:
    if not payloads:
        return
    path = _network_payload_path(run_id, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    scrubbed_payloads = scrub_network_payloads_for_storage(payloads)
    path.write_text(json.dumps(scrubbed_payloads, indent=2), encoding="utf-8")


def _write_failed_diagnostics(
    run_id: int,
    url: str,
    diagnostics_path: Path,
    *,
    error_detail: str,
) -> None:
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
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
    diagnostics_path.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )


def _write_diagnostics(
    run_id: int,
    url: str,
    result: AcquisitionResult,
    artifact_path: Path,
    diagnostics_path: Path,
) -> None:
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    blocked = (
        detect_blocked_page(result.html).as_dict()
        if result.content_type == "html"
        else None
    )
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "url": url,
        "status": "completed",
        "method": result.method,
        "content_type": result.content_type,
        "artifact_path": str(artifact_path),
        "network_payload_path": str(_network_payload_path(run_id, url))
        if result.network_payloads
        else None,
        "html_length": len(result.html or ""),
        "json_kind": type(result.json_data).__name__
        if result.json_data is not None
        else None,
        "network_payloads": len(result.network_payloads or []),
        "blocked": blocked,
        "diagnostics": result.diagnostics,
    }
    diagnostics_path.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )


def _scrub_payload_for_artifact(value: object) -> object:
    if isinstance(value, dict):
        output: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if _looks_sensitive_key(key_text):
                output[key_text] = _REDACTED
                continue
            output[key_text] = _scrub_payload_for_artifact(item)
        return output
    if isinstance(value, list):
        return [_scrub_payload_for_artifact(item) for item in value]
    if isinstance(value, str):
        return _scrub_sensitive_text(value)
    return value


def _looks_sensitive_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


def _scrub_sensitive_text(text: str) -> str:
    scrubbed = str(text or "")
    scrubbed = _BEARER_TOKEN_RE.sub(_REDACTED, scrubbed)
    scrubbed = _EMAIL_RE.sub(_REDACTED, scrubbed)
    scrubbed = _LONG_TOKEN_RE.sub(_REDACTED, scrubbed)
    return scrubbed


def scrub_network_payloads_for_storage(payloads: list[dict]) -> list[dict]:
    scrubbed = _scrub_payload_for_artifact(payloads)
    if isinstance(scrubbed, list):
        return [row for row in scrubbed if isinstance(row, dict)]
    return []


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
    response_headers = (
        normalized.headers if isinstance(normalized.headers, dict) else {}
    )
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
        "host_wait_seconds": round(host_wait_seconds, 3)
        if host_wait_seconds > 0
        else None,
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
    keep = (
        "server",
        "cf-mitigated",
        "retry-after",
        "content-type",
        "accept-ch",
        "critical-ch",
    )
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


def _requires_browser_first(url: str, surface: str | None) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface not in {"job_listing", "job_detail"}:
        return False
    domain = urlparse(url).netloc.lower().replace("www.", "")
    configured_domain_match = _matches_domain_policy(domain, BROWSER_FIRST_DOMAINS)
    if configured_domain_match:
        return True
    policy = resolve_platform_runtime_policy(url)
    return bool(policy.get("requires_browser"))


def _matches_domain_policy(domain: str, candidates: list[str]) -> bool:
    normalized_domain = str(domain or "").strip().lower()
    for candidate in (
        str(candidate or "").strip().lower() for candidate in candidates if candidate
    ):
        if normalized_domain == candidate or normalized_domain.endswith(
            f".{candidate}"
        ):
            return True
    return False


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


def _normalize_patterns(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [
        str(value or "").strip().lower() for value in values if str(value or "").strip()
    ]


def _detect_platform_family(url: str, html: str = "") -> str | None:
    return detect_platform_family_from_registry(url, html)
