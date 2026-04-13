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
from json import loads as parse_json
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings
from app.core.metrics import observe_acquisition_duration
from app.services.acquisition.artifact_store import (
    artifact_paths,
    persist_acquisition_artifacts,
    persist_failure_artifacts,
)
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_client import BrowserResult, fetch_rendered_html
from app.services.acquisition.browser_runtime import resolve_browser_runtime_options
from app.services.acquisition.cookie_store import (
    discard_session_cookies,
)
from app.services.acquisition.http_client import HttpFetchResult, fetch_html_result
from app.services.acquisition.pacing import wait_for_host_slot
from app.services.acquisition.session_context import (
    SessionContext,
    create_session_context,
)
from app.services.adapters.registry import resolve_adapter
from app.services.config.acquisition_guards import (
    JOB_ERROR_PAGE_HEADINGS,
    JOB_ERROR_PAGE_TITLES,
    JOB_REDIRECT_SHELL_CANONICAL_URLS,
    JOB_REDIRECT_SHELL_HEADINGS,
    JOB_REDIRECT_SHELL_TITLES,
)
from app.services.config.crawl_runtime import (
    ACQUIRE_HOST_MIN_INTERVAL_MS,
    ACQUISITION_ATTEMPT_TIMEOUT_SECONDS,
    BROWSER_FALLBACK_VISIBLE_TEXT_MIN,
    BROWSER_PREFERENCE_MIN_SUCCESSES,
    COOPERATIVE_SLEEP_POLL_MS,
    DEFAULT_MAX_SCROLLS,
    DETAIL_FIELD_SIGNAL_MIN_COUNT,
    EXTRACTABILITY_JSON_LD_MIN_TYPE_SIGNALS,
    EXTRACTABILITY_NEXT_DATA_SIGNAL_MIN,
    EXTRACTABILITY_NEXT_DATA_SIGNAL_TRIGGER,
    EXTRACTABILITY_NON_PRODUCT_TYPE_RATIO_MAX,
    IFRAME_PROMOTION_MAX_CANDIDATES,
    JS_GATE_PHRASES,
    JS_SHELL_MIN_CONTENT_LEN,
    JS_SHELL_MIN_SCRIPT_COUNT,
    JS_SHELL_VISIBLE_RATIO_MAX,
    LISTING_MIN_ITEMS,
    PROXY_FAILURE_BACKOFF_MAX_EXPONENT,
    PROXY_FAILURE_COOLDOWN_BASE_MS,
    PROXY_FAILURE_COOLDOWN_MAX_MS,
    PROXY_FAILURE_STATE_MAX_ENTRIES,
    PROXY_FAILURE_STATE_TTL_SECONDS,
)
from app.services.config.extraction_rules import SITE_POLICY_REGISTRY
from app.services.config.platform_registry import (
    acquisition_hint_tokens,
    job_platform_families,
    is_job_platform_signal,
    resolve_platform_runtime_policy,
)
from app.services.config.platform_registry import (
    detect_platform_family as detect_platform_family_from_registry,
)
from app.services.extractability import (
    NEXT_DATA_PRODUCT_SIGNALS,
    html_has_extractable_listings_from_soup,
    json_ld_listing_count,
)
from app.services.exceptions import (
    AcquisitionFailureError,
    AcquisitionTimeoutError,
    ProxyPoolExhaustedError,
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
HTML_PARSER = "html.parser"
logger = logging.getLogger(__name__)
_REDACTED = "[REDACTED]"
_PROXY_FAILURE_STATE: dict[str, tuple[int, float, float]] = {}
_PROXY_FAILURE_STATE_LOCK = asyncio.Lock()
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
_URL_CREDENTIALS_RE = _re.compile(
    r"(?i)\b([a-z][a-z0-9+\-.]*://)([^/\s:@]+)(?::([^/\s@]*))?@"
)
_SENSITIVE_HTML_FIELD_TOKENS = (
    "authenticity",
    "csrf",
    "email",
    "passwd",
    "password",
    "phone",
    "secret",
    "session",
    "token",
)
JOB_PLATFORM_FAMILIES = frozenset({*job_platform_families(), "generic_jobs"})
BROWSER_FIRST_DOMAINS = sorted(
    domain
    for domain, policy in SITE_POLICY_REGISTRY.items()
    if isinstance(policy, dict) and bool(policy.get("browser_first"))
)


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
    exponent = min(failure_count - 1, PROXY_FAILURE_BACKOFF_MAX_EXPONENT)
    delay_ms = PROXY_FAILURE_COOLDOWN_BASE_MS * (2**exponent)
    bounded_ms = min(delay_ms, PROXY_FAILURE_COOLDOWN_MAX_MS)
    return max(0.0, bounded_ms / 1000)


def _evict_stale_proxy_entries(now: float) -> None:
    stale_cutoff = now - PROXY_FAILURE_STATE_TTL_SECONDS
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

    if len(_PROXY_FAILURE_STATE) <= PROXY_FAILURE_STATE_MAX_ENTRIES:
        return
    overflow = len(_PROXY_FAILURE_STATE) - PROXY_FAILURE_STATE_MAX_ENTRIES
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
    outcome: str = ""  # AcquisitionOutcome value; empty means unclassified


@dataclass(slots=True)
class AcquisitionRequest:
    run_id: int
    url: str
    proxy_list: list[str] = field(default_factory=list)
    surface: str | None = None
    traversal_mode: str | None = None
    max_pages: int = 5
    max_scrolls: int = DEFAULT_MAX_SCROLLS
    sleep_ms: int = 0
    requested_fields: list[str] = field(default_factory=list)
    requested_field_selectors: dict[str, list[dict]] = field(default_factory=dict)
    acquisition_profile: dict[str, object] = field(default_factory=dict)
    checkpoint: Callable[[], Awaitable[None]] | None = None

    @classmethod
    def from_legacy(
        cls,
        *,
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
    ) -> "AcquisitionRequest":
        return cls(
            run_id=run_id,
            url=url,
            proxy_list=list(proxy_list or []),
            surface=surface,
            traversal_mode=traversal_mode,
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            sleep_ms=sleep_ms,
            requested_fields=list(requested_fields or []),
            requested_field_selectors=dict(requested_field_selectors or {}),
            acquisition_profile=dict(acquisition_profile or {}),
            checkpoint=checkpoint,
        )

    def with_profile_updates(self, **updates: object) -> "AcquisitionRequest":
        profile = dict(self.acquisition_profile)
        profile.update(updates)
        return AcquisitionRequest(
            run_id=self.run_id,
            url=self.url,
            proxy_list=list(self.proxy_list),
            surface=self.surface,
            traversal_mode=self.traversal_mode,
            max_pages=self.max_pages,
            max_scrolls=self.max_scrolls,
            sleep_ms=self.sleep_ms,
            requested_fields=list(self.requested_fields),
            requested_field_selectors=dict(self.requested_field_selectors),
            acquisition_profile=profile,
            checkpoint=self.checkpoint,
        )


@dataclass(slots=True)
class _AcquireExecutionRequest:
    run_id: int
    url: str
    proxy: str | None
    surface: str | None
    traversal_mode: str | None
    max_pages: int
    max_scrolls: int
    prefer_stealth: bool
    sleep_ms: int
    requested_fields: list[str] | None
    requested_field_selectors: dict[str, list[dict]] | None
    browser_first: bool
    acquisition_profile: dict[str, object] | None
    runtime_options: object
    checkpoint: Callable[[], Awaitable[None]] | None
    session_context: SessionContext | None = None


@dataclass(slots=True)
class _AcquireAttemptContext:
    request: _AcquireExecutionRequest
    started_at: float
    host_wait_seconds: float
    artifact_path: str

    @property
    def surface(self) -> str | None:
        return self.request.surface

    @property
    def runtime_options(self):
        return self.request.runtime_options

    def finalize_diagnostics_payload(
        self,
        diagnostics: dict[str, object] | None,
    ) -> dict[str, object]:
        payload = dict(diagnostics or {})
        timings = _merge_timing_maps(payload.get("timings_ms"))
        total_ms = max(0, _elapsed_ms(self.started_at))
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

    def result_diagnostics(self, result: AcquisitionResult) -> dict[str, object]:
        return dict(result.diagnostics or {})

    def update_result_diagnostics(
        self,
        result: AcquisitionResult,
        **updates: object,
    ) -> AcquisitionResult:
        diagnostics = self.result_diagnostics(result)
        diagnostics.update(updates)
        result.diagnostics = self.finalize_diagnostics_payload(diagnostics)
        return result


def _coerce_acquisition_request(
    *,
    request: AcquisitionRequest | None,
    run_id: int | None,
    url: str | None,
    proxy_list: list[str] | None,
    surface: str | None,
    traversal_mode: str | None,
    max_pages: int,
    max_scrolls: int,
    sleep_ms: int,
    requested_fields: list[str] | None,
    requested_field_selectors: dict[str, list[dict]] | None,
    acquisition_profile: dict[str, object] | None,
    checkpoint: Callable[[], Awaitable[None]] | None,
) -> AcquisitionRequest:
    if request is not None:
        return request
    if run_id is None or url is None:
        raise TypeError("run_id and url are required when request is not provided")
    return AcquisitionRequest.from_legacy(
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
    run_id: int | None = None,
    url: str | None = None,
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
    request: AcquisitionRequest | None = None,
) -> tuple[str, str, str, list[dict]]:
    """Acquire HTML for a URL using the waterfall strategy."""
    acquisition_request = _coerce_acquisition_request(
        request=request,
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
    result = await acquire(
        request=acquisition_request,
    )
    return result.html, result.method, result.artifact_path, result.network_payloads


async def acquire(
    run_id: int | None = None,
    url: str | None = None,
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
    request: AcquisitionRequest | None = None,
) -> AcquisitionResult:
    """Acquire content for a URL using the waterfall strategy."""
    acquisition_request = _coerce_acquisition_request(
        request=request,
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
    run_id = acquisition_request.run_id
    url = acquisition_request.url
    proxy_list = acquisition_request.proxy_list
    surface = acquisition_request.surface
    traversal_mode = acquisition_request.traversal_mode
    max_pages = acquisition_request.max_pages
    max_scrolls = acquisition_request.max_scrolls
    sleep_ms = acquisition_request.sleep_ms
    requested_fields = acquisition_request.requested_fields
    requested_field_selectors = acquisition_request.requested_field_selectors
    checkpoint = acquisition_request.checkpoint
    profile = dict(acquisition_request.acquisition_profile)
    platform_family = _detect_platform_family(url)

    # Domain-based fast track: known problematic domains should use the
    # hardened browser runtime, not the minimal default browser settings.
    domain = urlparse(url).netloc.lower().replace("www.", "")
    browser_first = (
        _matches_domain_policy(domain, BROWSER_FIRST_DOMAINS)
        or _memory_prefers_browser(profile)
        or _requires_browser_first(url, platform_family)
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
    target_domain = urlparse(url).netloc.lower()
    for proxy in proxy_candidates:
        # Create a fresh SessionContext per proxy attempt.  When a proxy
        # dies, the entire context (cookies + fingerprint) is discarded.
        session_ctx = create_session_context(proxy=proxy)
        session_ctx.remember_domain(target_domain)
        try:
            result = await asyncio.wait_for(
                _acquire_once(
                    _AcquireExecutionRequest(
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
                        session_context=session_ctx,
                    )
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
            session_ctx.invalidate()
            for domain in set(session_ctx.persisted_domains) or {target_domain}:
                discard_session_cookies(domain, session_ctx.identity_key)
            if proxy:
                await _mark_proxy_failed(proxy)
            result = None
        else:
            if result is None:
                session_ctx.invalidate()
                for domain in set(session_ctx.persisted_domains) or {target_domain}:
                    discard_session_cookies(domain, session_ctx.identity_key)
            if proxy:
                if result is None:
                    await _mark_proxy_failed(proxy)
                else:
                    await _mark_proxy_succeeded(proxy)
        if result is not None:
            # Stamp session diagnostics into the acquisition result.
            if isinstance(result.diagnostics, dict):
                result.diagnostics["session_context"] = session_ctx.to_diagnostics()
            break

    if result is None:
        await persist_failure_artifacts(
            run_id,
            url,
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

    artifact_path, diagnostics_path = await persist_acquisition_artifacts(
        run_id,
        url,
        result,
        scrub_payload=_scrub_payload_for_artifact,
        scrub_html=_scrub_html_for_artifact,
        scrub_text=_scrub_sensitive_text,
    )

    result.artifact_path = artifact_path
    result.diagnostics_path = diagnostics_path
    diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
    if bool(diagnostics.get("browser_blocked")) or bool(
        diagnostics.get("curl_blocked")
    ):
        incr("blocked_page_result_total")
    timings_ms = (
        diagnostics.get("timings_ms") if isinstance(diagnostics, dict) else None
    )
    acquisition_total_ms = 0
    if isinstance(timings_ms, dict):
        acquisition_total_ms = int(timings_ms.get("acquisition_total_ms", 0) or 0)
    if acquisition_total_ms > 0:
        observe_acquisition_duration(acquisition_total_ms / 1000)
    # Classify the acquisition outcome from diagnostics.
    result.outcome = _classify_outcome(result)
    if isinstance(result.diagnostics, dict):
        result.diagnostics["acquisition_outcome"] = result.outcome
    return result


def _classify_outcome(result: AcquisitionResult) -> str:
    """Derive a typed :class:`AcquisitionOutcome` value from the result."""
    from app.services.pipeline.types import AcquisitionOutcome

    diag = result.diagnostics if isinstance(result.diagnostics, dict) else {}
    if result.content_type == "json":
        return AcquisitionOutcome.json_response
    if not result.html and result.json_data is None:
        return AcquisitionOutcome.empty
    blocked = diag.get("blocked")
    if isinstance(blocked, dict) and blocked.get("is_blocked"):
        return AcquisitionOutcome.blocked
    if getattr(blocked, "is_blocked", False):
        return AcquisitionOutcome.blocked
    if diag.get("promoted_browser_used"):
        return AcquisitionOutcome.promoted_source_browser
    if diag.get("promoted_source_used"):
        return AcquisitionOutcome.promoted_source
    if result.method == "playwright":
        return AcquisitionOutcome.browser_rendered
    if result.method == "curl_cffi":
        return AcquisitionOutcome.direct_html
    return AcquisitionOutcome.direct_html


def _extract_curl_analysis(
    analysis: dict[str, object],
) -> tuple[AcquisitionResult | None, dict[str, object]]:
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
    return curl_result, curl_diagnostics


def _build_curl_result(
    ctx: _AcquireAttemptContext,
    *,
    http_result,
    analysis: dict[str, object],
    curl_diagnostics: dict[str, object],
) -> AcquisitionResult:
    return AcquisitionResult(
        html=http_result.text,
        json_data=http_result.json_data,
        content_type=http_result.content_type,
        method="curl_cffi",
        artifact_path=ctx.artifact_path,
        promoted_sources=list(
            (analysis.get("extractability") or {}).get("promoted_sources") or []
        ),
        diagnostics=ctx.finalize_diagnostics_payload(curl_diagnostics),
    )


def _try_browser_first_success_result(
    ctx: _AcquireAttemptContext,
    *,
    browser_result,
) -> AcquisitionResult | None:
    first_data = (
        getattr(browser_result, "_acquirer_browser", {})
        if browser_result is not None
        else {}
    )
    first_html = str(first_data.get("html") or "")
    if not first_html:
        return None
    browser_first_surface_warnings = _surface_selection_warnings(
        requested_url=ctx.request.url,
        final_url=str(first_data.get("final_url") or ctx.request.url),
        html=first_html,
        surface=ctx.surface,
    )
    first_extractability = _assess_extractable_html(
        first_html,
        url=ctx.request.url,
        surface=ctx.surface,
        adapter_hint=None,
    )
    browser_first_is_usable = bool(
        first_extractability.get("has_extractable_data", False)
    ) or not str(ctx.surface or "").strip().lower().endswith("listing")
    if (
        first_data.get("blocked")
        or _is_invalid_surface_page(
            requested_url=ctx.request.url,
            final_url=str(first_data.get("final_url") or ctx.request.url),
            html=first_html,
            surface=ctx.surface,
        )
        or not browser_first_is_usable
    ):
        return None
    return AcquisitionResult(
        html=first_html,
        content_type="html",
        method="playwright",
        artifact_path=ctx.artifact_path,
        network_payloads=list(first_data.get("network_payloads") or []),
        frame_sources=getattr(browser_result, "frame_sources", []),
        promoted_sources=getattr(browser_result, "promoted_sources", []),
        diagnostics=ctx.finalize_diagnostics_payload(
            {
                k: v
                for k, v in {
                    "browser_attempted": True,
                    "browser_challenge_state": browser_result.challenge_state,
                    "browser_origin_warmed": browser_result.origin_warmed,
                    "browser_network_payloads": len(
                        list(first_data.get("network_payloads") or [])
                    ),
                    "browser_diagnostics": first_data.get("diagnostics"),
                    "timings_ms": _merge_timing_maps(
                        {"browser_total_ms": first_data.get("browser_total_ms")},
                        first_data.get("diagnostics", {}).get("timings_ms")
                        if isinstance(first_data.get("diagnostics"), dict)
                        else None,
                        {"acquisition_total_ms": _elapsed_ms(ctx.started_at)},
                    ),
                    "memory_prefer_stealth": bool(
                        (ctx.request.acquisition_profile or {}).get("prefer_stealth")
                    ),
                    "memory_browser_first": True,
                    "host_wait_seconds": round(ctx.host_wait_seconds, 3)
                    if ctx.host_wait_seconds > 0
                    else None,
                    "prefer_stealth": ctx.request.prefer_stealth,
                    "anti_bot_enabled": ctx.runtime_options.anti_bot_enabled,
                    "proxy_used": bool(ctx.request.proxy),
                    "surface_selection_warnings": browser_first_surface_warnings
                    or None,
                }.items()
                if v is not None
            }
        ),
    )


async def _finalize_browser_result(
    ctx: _AcquireAttemptContext,
    *,
    browser_result,
    http_result,
    analysis: dict[str, object],
    curl_result: AcquisitionResult | None,
    curl_diagnostics: dict[str, object],
) -> AcquisitionResult | None:
    browser_data = getattr(browser_result, "_acquirer_browser", {})
    browser_html = str(browser_data.get("html") or "")
    browser_final_url = (
        str(browser_data.get("final_url") or ctx.request.url).strip() or ctx.request.url
    )
    browser_public_target = True
    try:
        await validate_public_target(browser_final_url)
    except ValueError:
        browser_public_target = False
        logger.warning(
            "Playwright final URL is non-public and was rejected for %s -> %s",
            ctx.request.url,
            browser_final_url,
        )
    browser_diag = (
        browser_data.get("diagnostics")
        if isinstance(browser_data.get("diagnostics"), dict)
        else {}
    )
    browser_payloads = list(browser_data.get("network_payloads") or [])
    browser_redirect_shell = _is_invalid_surface_page(
        requested_url=ctx.request.url,
        final_url=browser_final_url,
        html=browser_html,
        surface=ctx.surface,
    )
    browser_surface_warnings = _surface_selection_warnings(
        requested_url=ctx.request.url,
        final_url=browser_final_url,
        html=browser_html,
        surface=ctx.surface,
    )
    merged_timings = _merge_timing_maps(
        curl_diagnostics.get("timings_ms"),
        {"browser_total_ms": browser_data.get("browser_total_ms")},
        browser_diag.get("timings_ms"),
        {"acquisition_total_ms": _elapsed_ms(ctx.started_at)},
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
                "timings_ms": merged_timings,
            }
        )
        for key in (
            "traversal_mode",
            "traversal_summary",
            "traversal_fallback_used",
            "traversal_fallback_reason",
        ):
            if key in browser_diag:
                merged[key] = browser_diag[key]
        return AcquisitionResult(
            html=browser_html,
            content_type="html",
            method="playwright",
            artifact_path=ctx.artifact_path,
            network_payloads=browser_payloads,
            frame_sources=getattr(browser_result, "frame_sources", []),
            promoted_sources=getattr(browser_result, "promoted_sources", []),
            diagnostics=ctx.finalize_diagnostics_payload(merged),
        )
    if curl_result is not None:
        curl_result = ctx.update_result_diagnostics(
            curl_result,
            browser_attempted=True,
            browser_challenge_state=browser_result.challenge_state,
            browser_origin_warmed=browser_result.origin_warmed,
            browser_network_payloads=len(browser_payloads),
            browser_diagnostics=browser_diag,
            browser_blocked=browser_data.get("blocked") or None,
            browser_redirect_shell=browser_redirect_shell or None,
            browser_non_public_target=(not browser_public_target) or None,
            surface_selection_warnings=browser_surface_warnings or None,
            timings_ms=merged_timings,
        )
        logger.info(
            "Playwright returned blocked/empty for %s — using curl_cffi fallback",
            ctx.request.url,
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
                "timings_ms": merged_timings,
            }
        )
        return AcquisitionResult(
            html=browser_html,
            content_type="html",
            method="playwright",
            artifact_path=ctx.artifact_path,
            network_payloads=browser_payloads,
            frame_sources=getattr(browser_result, "frame_sources", []),
            promoted_sources=getattr(browser_result, "promoted_sources", []),
            diagnostics=ctx.finalize_diagnostics_payload(blocked),
        )
    if (
        http_result is not None
        and getattr(analysis.get("blocked"), "is_blocked", False)
        and not bool(analysis.get("invalid_surface_page"))
    ):
        curl_diagnostics["timings_ms"] = merged_timings
        return _build_curl_result(
            ctx,
            http_result=http_result,
            analysis=analysis,
            curl_diagnostics=curl_diagnostics,
        )
    if curl_result is not None:
        return ctx.update_result_diagnostics(curl_result, browser_failed=True)
    return None


async def _acquire_once(
    request: _AcquireExecutionRequest,
) -> AcquisitionResult | None:
    started = time.perf_counter()
    host_wait = await wait_for_host_slot(
        urlparse(request.url).netloc.lower(),
        ACQUIRE_HOST_MIN_INTERVAL_MS,
        checkpoint=request.checkpoint,
    )
    ctx = _AcquireAttemptContext(
        request=request,
        started_at=started,
        host_wait_seconds=host_wait,
        artifact_path=str(_artifact_path(request.run_id, request.url)),
    )
    browser_first_result = (
        await _try_browser(
            request.url,
            request.proxy,
            request.surface,
            traversal_mode=request.traversal_mode,
            max_pages=request.max_pages,
            max_scrolls=request.max_scrolls,
            prefer_stealth=request.prefer_stealth,
            sleep_ms=request.sleep_ms,
            runtime_options=request.runtime_options,
            requested_fields=request.requested_fields,
            requested_field_selectors=request.requested_field_selectors,
            checkpoint=request.checkpoint,
            run_id=request.run_id,
            failure_log_message="Memory-led browser-first acquisition failed for %s: %s — falling back to curl_cffi",
            session_context=request.session_context,
        )
        if request.browser_first
        else None
    )
    browser_first_success = _try_browser_first_success_result(
        ctx,
        browser_result=browser_first_result,
    )
    if browser_first_success is not None:
        return browser_first_success

    if _should_force_browser_for_traversal(request.traversal_mode):
        http_result = None
        analysis = {}
    else:
        http_result = await _try_http(
            request.url,
            request.proxy,
            request.surface,
            run_id=request.run_id,
            traversal_mode=request.traversal_mode,
            prefer_stealth=request.prefer_stealth,
            sleep_ms=request.sleep_ms,
            browser_first=request.browser_first,
            acquisition_profile=request.acquisition_profile,
            runtime_options=request.runtime_options,
            host_wait_seconds=host_wait,
            checkpoint=request.checkpoint,
            session_context=request.session_context,
        )
    analysis = (
        getattr(http_result, "_acquirer_analysis", {})
        if http_result is not None
        else {}
    )
    promoted_source_result = await _try_promoted_source_acquire(
        url=request.url,
        proxy=request.proxy,
        surface=request.surface,
        run_id=request.run_id,
        analysis=analysis,
        started=started,
        prefer_stealth=request.prefer_stealth,
        runtime_options=request.runtime_options,
        host_wait_seconds=host_wait,
        checkpoint=request.checkpoint,
        session_context=request.session_context,
    )
    if promoted_source_result is not None:
        promoted_source_result.diagnostics = ctx.finalize_diagnostics_payload(
            promoted_source_result.diagnostics
        )
        return promoted_source_result

    should_escalate, _ = _needs_browser(
        http_result,
        request.url,
        request.surface,
        request.requested_fields,
        request.acquisition_profile,
    )
    curl_result, curl_diagnostics = _extract_curl_analysis(analysis)
    if (
        http_result is not None
        and not should_escalate
        and not _should_force_browser_for_traversal(request.traversal_mode)
    ):
        curl_diagnostics["timings_ms"] = _merge_timing_maps(
            curl_diagnostics.get("timings_ms"),
            {"acquisition_total_ms": _elapsed_ms(started)},
        )
        if curl_result is not None:
            return ctx.update_result_diagnostics(
                curl_result,
                timings_ms=curl_diagnostics.get("timings_ms"),
            )
        return _build_curl_result(
            ctx,
            http_result=http_result,
            analysis=analysis,
            curl_diagnostics=curl_diagnostics,
        )
    browser_result = await _try_browser(
        request.url,
        request.proxy,
        request.surface,
        traversal_mode=request.traversal_mode,
        max_pages=request.max_pages,
        max_scrolls=request.max_scrolls,
        prefer_stealth=request.prefer_stealth,
        sleep_ms=request.sleep_ms,
        runtime_options=request.runtime_options,
        requested_fields=request.requested_fields,
        requested_field_selectors=request.requested_field_selectors,
        checkpoint=request.checkpoint,
        run_id=request.run_id,
        diagnostics_sink=curl_result.diagnostics if curl_result is not None else None,
        session_context=request.session_context,
    )
    if browser_result is None:
        if http_result is None:
            http_result = await _try_http(
                request.url,
                request.proxy,
                request.surface,
                run_id=request.run_id,
                traversal_mode=request.traversal_mode,
                prefer_stealth=request.prefer_stealth,
                sleep_ms=request.sleep_ms,
                browser_first=request.browser_first,
                acquisition_profile=request.acquisition_profile,
                runtime_options=request.runtime_options,
                host_wait_seconds=host_wait,
                checkpoint=request.checkpoint,
                session_context=request.session_context,
            )
            if http_result is None:
                return None
            analysis = getattr(http_result, "_acquirer_analysis", {})
            curl_result, curl_diagnostics = _extract_curl_analysis(analysis)
        if curl_result is not None:
            return ctx.update_result_diagnostics(curl_result)
        return _build_curl_result(
            ctx,
            http_result=http_result,
            analysis=analysis,
            curl_diagnostics=curl_diagnostics,
        )
    return await _finalize_browser_result(
        ctx,
        browser_result=browser_result,
        http_result=http_result,
        analysis=analysis,
        curl_result=curl_result,
        curl_diagnostics=curl_diagnostics,
    )


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
    session_context: SessionContext | None,
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

    for source in promoted_sources[:IFRAME_PROMOTION_MAX_CANDIDATES]:
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
                await _fetch_with_content_type(
                    promoted_url,
                    proxy,
                    session_context=session_context,
                )
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

        # ── Promoted source shell detection ──
        # If the promoted HTML is a JS shell (very low visible text despite
        # an adapter hint claiming extractability), the curl fetch returned a
        # wrapper that needs browser rendering.  Escalate to Playwright for
        # the promoted URL so the real content gets hydrated.
        promoted_visible_text = " ".join(
            BeautifulSoup(promoted_html, HTML_PARSER)
            .get_text(" ", strip=True)
            .split()
        )
        promoted_is_shell = (
            len(promoted_visible_text) < BROWSER_FALLBACK_VISIBLE_TEXT_MIN
            and str(promoted_extractability.get("reason") or "") == "adapter_hint"
        )
        browser_data: dict = {}
        if promoted_is_shell:
            logger.info(
                "[promoted] curl returned shell for %s (visible=%d), "
                "escalating to browser",
                promoted_url,
                len(promoted_visible_text),
            )
            browser_result = await _try_browser(
                promoted_url,
                proxy,
                surface,
                traversal_mode=None,
                max_pages=1,
                max_scrolls=0,
                prefer_stealth=prefer_stealth,
                sleep_ms=0,
                runtime_options=runtime_options,
                requested_fields=None,
                requested_field_selectors=None,
                checkpoint=checkpoint,
                run_id=run_id,
                session_context=session_context,
            )
            browser_data = (
                getattr(browser_result, "_acquirer_browser", {})
                if browser_result is not None
                else {}
            )
            browser_html = str(browser_data.get("html") or "")
            if browser_html and not browser_data.get("blocked"):
                promoted_html = browser_html
                promoted_extractability = {
                    **promoted_extractability,
                    "promoted_browser_rendered": True,
                }

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
        promoted_browser_used = bool(
            promoted_extractability.get("promoted_browser_rendered")
        )
        browser_timing_map = (
            browser_data.get("diagnostics", {}).get("timings_ms")
            if promoted_browser_used
            and isinstance(browser_data.get("diagnostics"), dict)
            else None
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
                "promoted_browser_used": promoted_browser_used,
                "timings_ms": _merge_timing_maps(
                    diagnostics.get("timings_ms"),
                    promoted_timings,
                    browser_timing_map,
                    {"acquisition_total_ms": _elapsed_ms(started)},
                ),
            }
        )
        if promoted_browser_used:
            diagnostics["browser_attempted"] = True
            diagnostics["browser_diagnostics"] = browser_data.get("diagnostics")
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
        acquisition_method = "playwright" if promoted_browser_used else "curl_cffi"
        network_payloads = (
            list(browser_data.get("network_payloads") or [])
            if promoted_browser_used
            else []
        )
        return AcquisitionResult(
            html=promoted_html,
            content_type="html",
            method=acquisition_method,
            artifact_path=str(_artifact_path(run_id, url)),
            promoted_sources=promoted_sources,
            network_payloads=network_payloads,
            diagnostics=diagnostics,
        )
    return None


def _html_has_min_listing_link_signals(html: str, *, surface: str | None) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_surface.endswith("listing"):
        return False
    soup = BeautifulSoup(html, HTML_PARSER)
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
    soup = BeautifulSoup(html, HTML_PARSER)
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
    session_context: SessionContext | None = None,
) -> HttpFetchResult | None:
    try:
        await _cooperative_sleep_ms(sleep_ms, checkpoint=checkpoint)
        curl_started_at = time.perf_counter()
        normalized = _normalize_fetch_result(
            await _fetch_with_content_type(url, proxy, session_context=session_context)
        )
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
    # Large page with low visible-text ratio (classic SPA shell).
    js_shell_detected = (
        content_len >= JS_SHELL_MIN_CONTENT_LEN
        and visible_len > 0
        and (visible_len / content_len) < JS_SHELL_VISIBLE_RATIO_MAX
    )
    # Small page with near-zero visible text and deferred script bundles
    # (server-rendered wrapper shells like SaaSHR, ATS embed pages).
    if (
        not js_shell_detected
        and visible_len < BROWSER_FALLBACK_VISIBLE_TEXT_MIN
        and content_len < JS_SHELL_MIN_CONTENT_LEN
        and html.count("<script") >= JS_SHELL_MIN_SCRIPT_COUNT
        and ("defer" in html or "async" in html)
    ):
        js_shell_detected = True
    adapter_hint = await _resolve_adapter_hint(url, html)
    platform_family = _detect_platform_family(url, html)

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
        and len(visible_text) < BROWSER_FALLBACK_VISIBLE_TEXT_MIN
    ):
        needs_browser, reason = True, "requested_fields_require_browser"
    elif (
        len(visible_text) < BROWSER_FALLBACK_VISIBLE_TEXT_MIN
        and content_len < JS_SHELL_MIN_CONTENT_LEN
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
    session_context: SessionContext | None = None,
) -> BrowserResult | None:
    logger.info("[browser] attempting url=%s traversal_mode=%s", url, traversal_mode)
    browser_started_at = time.perf_counter()
    try:
        await _cooperative_sleep_ms(sleep_ms, checkpoint=checkpoint)
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
            session_context=session_context,
        )
    except (PlaywrightError, OSError, RuntimeError, ValueError, TypeError) as exc:
        await _record_browser_failure(
            exc,
            url=url,
            traversal_mode=traversal_mode,
            run_id=run_id,
            diagnostics_sink=diagnostics_sink,
        )
        return None
    result._acquirer_browser = _build_browser_attempt_metadata(
        result,
        url=url,
        browser_started_at=browser_started_at,
    )
    return result


async def _record_browser_failure(
    exc: Exception,
    *,
    url: str,
    traversal_mode: str | None,
    run_id: int | None,
    diagnostics_sink: dict[str, object] | None,
) -> None:
    logger.warning("[browser] FAILED type=%s msg=%s", type(exc).__name__, exc)
    incr("browser_launch_failures_total")
    await _append_browser_failure_log(run_id, traversal_mode=traversal_mode, exc=exc, url=url)
    if diagnostics_sink is not None:
        diagnostics_sink["browser_exception"] = f"{type(exc).__name__}: {exc}"
        diagnostics_sink["browser_attempted"] = True


async def _append_browser_failure_log(
    run_id: int | None,
    *,
    traversal_mode: str | None,
    exc: Exception,
    url: str,
) -> None:
    if run_id is None:
        return
    from app.services.crawl_events import append_log_event

    try:
        await append_log_event(
            run_id=run_id,
            level="warning",
            message=_browser_failure_log_message(traversal_mode, exc),
        )
    except Exception:
        incr("acquisition_log_event_failures_total")
        logger.debug(
            "Failed to append browser acquisition fallback event for %s",
            url,
            exc_info=True,
        )


def _browser_failure_log_message(
    traversal_mode: str | None,
    exc: Exception,
) -> str:
    prefix = (
        "[traversal] Browser acquisition failed, falling back to curl"
        if _should_force_browser_for_traversal(traversal_mode)
        else "Browser acquisition failed"
    )
    return f"{prefix}: {type(exc).__name__}: {exc}"


def _build_browser_attempt_metadata(
    result: BrowserResult,
    *,
    url: str,
    browser_started_at: float,
) -> dict[str, object]:
    browser_html = result.html if isinstance(result.html, str) else ""
    browser_diagnostics = (
        result.diagnostics if isinstance(result.diagnostics, dict) else {}
    )
    browser_network_payloads = (
        result.network_payloads if isinstance(result.network_payloads, list) else []
    )
    return {
        "html": browser_html,
        "diagnostics": browser_diagnostics,
        "network_payloads": browser_network_payloads,
        "final_url": str(browser_diagnostics.get("final_url") or url).strip() or url,
        "blocked": bool(browser_html and detect_blocked_page(browser_html).is_blocked),
        "browser_total_ms": _elapsed_ms(browser_started_at),
    }


def _should_force_browser_for_traversal(traversal_mode: str | None) -> bool:
    normalized_mode = str(traversal_mode or "").strip().lower()
    return normalized_mode in {"auto", "scroll", "load_more", "paginate"}


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
    poll_ms = COOPERATIVE_SLEEP_POLL_MS
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
    soup = BeautifulSoup(html, HTML_PARSER)
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
        soup = BeautifulSoup(html, HTML_PARSER)
        title_text = " ".join(
            (soup.title.get_text(" ", strip=True) if soup.title else "").lower().split()
        )
        if any(
            fragment in title_text for fragment in _COMMERCE_REDIRECT_TITLE_FRAGMENTS
        ):
            return True
    return False


async def _fetch_with_content_type(
    url: str,
    proxy: str | None,
    *,
    session_context: SessionContext | None = None,
) -> HttpFetchResult:
    """Fetch URL and detect content type from response headers."""
    return await fetch_html_result(url, proxy=proxy, session_context=session_context)


async def _resolve_adapter_hint(url: str, html: str) -> str | None:
    if not html:
        return None
    adapter = await resolve_adapter(url, html)
    return adapter.name if adapter is not None else None


def _html_has_extractable_listings_from_soup(soup: BeautifulSoup) -> bool:
    return html_has_extractable_listings_from_soup(soup, json_loader=parse_json)


def _find_promotable_iframe_sources(html: str, *, surface: str | None) -> list[dict]:
    normalized_surface = str(surface or "").strip().lower()
    if "job" not in normalized_surface:
        return []
    soup = BeautifulSoup(html, HTML_PARSER)
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
        token
        for token in (base_tokens | set(acquisition_hint_tokens()))
        if len(token) >= 3
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

    soup_probe = BeautifulSoup(html, HTML_PARSER)
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
            total_types > 0
            and (non_product_types / total_types)
            > EXTRACTABILITY_NON_PRODUCT_TYPE_RATIO_MAX
        )
        if (
            json_ld_count >= EXTRACTABILITY_JSON_LD_MIN_TYPE_SIGNALS
            and not is_mostly_non_product
        ):
            return {
                "has_extractable_data": True,
                "reason": "structured_listing_markup",
                "json_ld_count": json_ld_count,
                "promoted_sources": promoted_iframes or None,
            }

        # (b) __NEXT_DATA__ signal density OR general product signals in HTML
        signal_hits = sum(html.count(sig) for sig in NEXT_DATA_PRODUCT_SIGNALS)
        has_next_data = "__NEXT_DATA__" in html
        if (
            has_next_data
            or signal_hits >= EXTRACTABILITY_NEXT_DATA_SIGNAL_TRIGGER
        ) and signal_hits >= EXTRACTABILITY_NEXT_DATA_SIGNAL_MIN:
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
        soup = BeautifulSoup(html, HTML_PARSER)
        visible_text = soup.get_text(" ", strip=True).lower()
        detail_tokens = ("title", "price", "brand", "description", "sku")
        field_hits = sum(1 for tok in detail_tokens if tok in visible_text)
        if field_hits >= DETAIL_FIELD_SIGNAL_MIN_COUNT:
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
    return json_ld_listing_count(payload, _depth=_depth, max_depth=_max_depth)


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
    return artifact_paths(run_id, url).artifact_path


def _network_payload_path(run_id: int, url: str) -> Path:
    return artifact_paths(run_id, url).network_payload_path


def _diagnostics_path(run_id: int, url: str) -> Path:
    return artifact_paths(run_id, url).diagnostics_path


def _scrub_payload_for_artifact(value: object) -> object:
    if isinstance(value, dict):
        scrubbed: dict[object, object] = {}
        for key, nested_value in value.items():
            if _looks_sensitive_key(str(key)):
                scrubbed[key] = _REDACTED
            else:
                scrubbed[key] = _scrub_payload_for_artifact(nested_value)
        return scrubbed
    if isinstance(value, list):
        return [_scrub_payload_for_artifact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_payload_for_artifact(item) for item in value)
    if isinstance(value, str):
        return _scrub_sensitive_text(value)
    return value


def _scrub_html_for_artifact(html: str) -> str:
    scrubbed = _scrub_sensitive_text(html)
    for token in _SENSITIVE_HTML_FIELD_TOKENS:
        scrubbed = _re.sub(
            rf'(?is)(<input\b[^>]*?\b(?:name|id)=["\'][^"\']*{_re.escape(token)}[^"\']*["\'][^>]*?\bvalue=)(["\']).*?\2',
            rf"\1\2{_REDACTED}\2",
            scrubbed,
        )
        scrubbed = _re.sub(
            rf'(?is)(<meta\b[^>]*?\b(?:name|property)=["\'][^"\']*{_re.escape(token)}[^"\']*["\'][^>]*?\bcontent=)(["\']).*?\2',
            rf"\1\2{_REDACTED}\2",
            scrubbed,
        )
    return scrubbed


def _looks_sensitive_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


def _scrub_sensitive_text(text: str) -> str:
    scrubbed = str(text or "")
    scrubbed = _BEARER_TOKEN_RE.sub(f"Bearer {_REDACTED}", scrubbed)
    scrubbed = _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", scrubbed)
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
    return (
        browser_successes >= BROWSER_PREFERENCE_MIN_SUCCESSES
        and curl_successes == 0
    )


def _requires_browser_first(url: str, platform_family: str | None) -> bool:
    domain = urlparse(url).netloc.lower().replace("www.", "")
    configured_domain_match = _matches_domain_policy(domain, BROWSER_FIRST_DOMAINS)
    if configured_domain_match:
        return True
    normalized_platform = str(platform_family or "").strip().lower()
    if normalized_platform in JOB_PLATFORM_FAMILIES:
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
