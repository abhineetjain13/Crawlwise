# Acquisition waterfall service with optional proxy rotation.
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import re as _re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from app.core.config import settings  # noqa: F401 - imported for module-level patching in tests
from app.core.metrics import observe_acquisition_duration
from app.services.acquisition.artifact_store import (
    artifact_paths,
    persist_acquisition_artifacts,
    persist_failure_artifacts,
)
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.acquisition.browser_client import BrowserResult, fetch_rendered_html
from app.services.acquisition.proxy_manager import (
    ProxyRotator,
    mark_proxy_failed,
    mark_proxy_succeeded,
)
from app.services.acquisition.browser_readiness import _cooperative_sleep_ms
from app.services.acquisition.policy import (
    AcquisitionPlan,
    browser_failure_log_message,
    classify_acquisition_outcome,
    decide_acquisition_execution,
    normalize_traversal_summary,
    has_requested_traversal_mode,
    is_invalid_surface_page,
    plan_acquisition,
    should_force_browser_for_traversal,
    surface_selection_warnings,
    surface_warning_summary,
)
from app.services.acquisition.recovery import recover_blocked_listing_acquisition
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
from app.services.config.crawl_runtime import (
    ACQUIRE_HOST_MIN_INTERVAL_MS,
    ACQUISITION_ATTEMPT_TIMEOUT_SECONDS,
    BROWSER_FALLBACK_VISIBLE_TEXT_MIN,
    BROWSER_PREFERENCE_MIN_SUCCESSES,
    BROWSER_RENDER_TIMEOUT_SECONDS,
    DEFAULT_MAX_SCROLLS,
    HTTP_TIMEOUT_SECONDS,
    IFRAME_PROMOTION_MAX_CANDIDATES,
    JS_SHELL_MIN_CONTENT_LEN,
    JS_SHELL_MIN_SCRIPT_COUNT,
    JS_SHELL_VISIBLE_RATIO_MAX,
)
from app.services.platform_policy import detect_platform_family as detect_platform_family_from_registry
from app.services.discover.signal_inventory import (
    analyze_html_signals,
    assess_extractable_html,
    html_has_min_listing_link_signals,
)
from app.services.exceptions import (
    AcquisitionFailureError,
    ProxyPoolExhaustedError,
)
from app.services.runtime_metrics import incr
from app.services.url_safety import validate_proxy_endpoint, validate_public_target
from playwright.async_api import Error as PlaywrightError

logger = logging.getLogger(__name__)
_REDACTED = "[REDACTED]"
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

class ProxyPoolExhausted(ProxyPoolExhaustedError):  # noqa: N818 - compatibility alias kept for existing imports.
    pass


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
    adapter_records: list[dict] = field(default_factory=list)
    adapter_name: str = ""
    adapter_source_type: str = ""
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
    plan: AcquisitionPlan
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
    def plan(self) -> AcquisitionPlan:
        return self.request.plan

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

def _content_html_length(html: str) -> int:
    """Return HTML length with non-content tag bodies removed for shell detection."""
    stripped = _re.sub(
        r"<(script|style|svg)\b[^>]*>.*?</\1\s*>",
        "",
        html,
        flags=_re.IGNORECASE | _re.DOTALL,
    )
    return max(len(stripped), 1)


async def acquire(request: AcquisitionRequest) -> AcquisitionResult:
    """Acquire content for a URL using the waterfall strategy."""
    acquisition_request = request
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
    acquisition_plan = plan_acquisition(
        acquisition_request,
        platform_family=platform_family,
    )

    browser_first = (
        _memory_prefers_browser(profile)
        or acquisition_plan.require_browser_first
    )
    runtime_options = resolve_browser_runtime_options(
        profile,
        browser_first=browser_first,
    )
    prefer_stealth = runtime_options.warm_origin

    rotator = ProxyRotator(proxy_list)
    if rotator._proxies:
        await asyncio.gather(
            *(validate_proxy_endpoint(proxy) for proxy in rotator._proxies)
        )
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
    target_domain = urlparse(url).netloc.lower()
    for proxy in proxy_candidates:
        # Create a fresh SessionContext per proxy attempt.  When a proxy
        # dies, the entire context (cookies + fingerprint) is discarded.
        session_ctx = create_session_context(proxy=proxy)
        session_ctx.remember_domain(target_domain)
        try:
            result = await _acquire_once(
                _AcquireExecutionRequest(
                    run_id=run_id,
                    url=url,
                    plan=acquisition_plan,
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
            )
        except TimeoutError:
            logger.warning(
                "Acquisition attempt timed out after %.1fs for %s (proxy=%s)",
                float(ACQUISITION_ATTEMPT_TIMEOUT_SECONDS),
                url,
                "yes" if proxy else "no",
            )
            session_ctx.invalidate()
            for domain in set(session_ctx.persisted_domains) or {target_domain}:
                discard_session_cookies(domain, session_ctx.identity_key)
            if proxy:
                await mark_proxy_failed(proxy)
            result = None
        else:
            if result is None:
                session_ctx.invalidate()
                for domain in set(session_ctx.persisted_domains) or {target_domain}:
                    discard_session_cookies(domain, session_ctx.identity_key)
            if proxy:
                if result is None:
                    await mark_proxy_failed(proxy)
                else:
                    await mark_proxy_succeeded(proxy)
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
        raise AcquisitionFailureError(f"Unable to acquire content for {url}")

    artifact_path, diagnostics_path = await persist_acquisition_artifacts(
        run_id,
        url,
        result,
        scrub_payload=lambda value: value,
        scrub_html=lambda html: str(html or ""),
        scrub_text=lambda text: str(text or ""),
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
    result.outcome = classify_acquisition_outcome(result)
    if isinstance(result.diagnostics, dict):
        result.diagnostics["acquisition_outcome"] = result.outcome
    return result


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
    browser_first_surface_warnings = surface_selection_warnings(
        requested_url=ctx.request.url,
        final_url=str(first_data.get("final_url") or ctx.request.url),
        html=first_html,
        surface=ctx.surface,
    )
    browser_first_warning_summary = surface_warning_summary(
        browser_first_surface_warnings
    )
    first_extractability = assess_extractable_html(
        first_html,
        url=ctx.request.url,
        surface=ctx.surface,
        adapter_hint=None,
    )
    browser_first_is_usable = bool(
        first_extractability.get("has_extractable_data", False)
    ) or not ctx.plan.is_listing_surface
    if (
        first_data.get("blocked")
        or is_invalid_surface_page(
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
                    "browser_runtime_hardened": ctx.runtime_options.hardened_mode,
                    "browser_runtime_reason": ctx.runtime_options.hardened_mode_reason,
                    "proxy_used": bool(ctx.request.proxy),
                    "surface_selection_warnings": browser_first_surface_warnings
                    or None,
                    "soft_404_page": browser_first_warning_summary["soft_404_page"],
                    "transactional_page": browser_first_warning_summary["transactional_page"],
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
    execution_decision = analysis.get("execution_decision")
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
    browser_redirect_shell = is_invalid_surface_page(
        requested_url=ctx.request.url,
        final_url=browser_final_url,
        html=browser_html,
        surface=ctx.surface,
    )
    browser_surface_warnings = surface_selection_warnings(
        requested_url=ctx.request.url,
        final_url=browser_final_url,
        html=browser_html,
        surface=ctx.surface,
    )
    browser_warning_summary = surface_warning_summary(browser_surface_warnings)
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
                "soft_404_page": browser_warning_summary["soft_404_page"],
                "transactional_page": browser_warning_summary["transactional_page"],
                "timings_ms": merged_timings,
                **execution_decision.to_diagnostics(),
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
            soft_404_page=browser_warning_summary["soft_404_page"],
            transactional_page=browser_warning_summary["transactional_page"],
            timings_ms=merged_timings,
            browser_fallback_used=True,
            browser_fallback_reason="browser_result_not_usable",
            traversal_fallback_used=(
                True if has_requested_traversal_mode(ctx.request.traversal_mode) else None
            ),
            traversal_fallback_reason=(
                "browser_result_not_usable"
                if has_requested_traversal_mode(ctx.request.traversal_mode)
                else None
            ),
            **execution_decision.to_diagnostics(),
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
                "soft_404_page": browser_warning_summary["soft_404_page"],
                "transactional_page": browser_warning_summary["transactional_page"],
                "timings_ms": merged_timings,
                **execution_decision.to_diagnostics(),
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
            request.plan,
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

    if should_force_browser_for_traversal(request.traversal_mode):
        http_result = None
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
    analysis = http_result.acquirer_analysis or {} if http_result is not None else {}
    execution_decision = decide_acquisition_execution(
        http_result,
        plan=request.plan,
        traversal_mode=request.traversal_mode,
        requested_fields=request.requested_fields,
    )
    analysis["execution_decision"] = execution_decision
    blocked_recovery = await recover_blocked_listing_acquisition(
        url=request.url,
        proxy=request.proxy,
        plan=request.plan,
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
        session_context=request.session_context,
        browser_first=request.browser_first,
        analysis=analysis,
        try_browser=_try_browser,
    )
    if blocked_recovery is not None:
        if blocked_recovery.browser_result is not None:
            return await _finalize_browser_result(
                ctx,
                browser_result=blocked_recovery.browser_result,
                http_result=http_result,
                analysis=analysis,
                curl_result=None,
                curl_diagnostics={},
            )
        diagnostics = dict(analysis.get("curl_diagnostics", {}))
        diagnostics.update(
            {
                "blocked_adapter_recovery": True,
                "adapter_name": blocked_recovery.adapter_name,
                "adapter_record_count": len(blocked_recovery.adapter_records),
            }
        )
        return AcquisitionResult(
            html=http_result.text if http_result is not None else "",
            content_type="html",
            method="adapter_recovery",
            artifact_path=ctx.artifact_path,
            network_payloads=[],
            adapter_records=list(blocked_recovery.adapter_records),
            adapter_name=blocked_recovery.adapter_name,
            adapter_source_type=blocked_recovery.adapter_source_type,
            diagnostics=ctx.finalize_diagnostics_payload(diagnostics),
        )
    promoted_source_result = await _try_promoted_source_acquire(
        ctx=ctx,
        url=request.url,
        proxy=request.proxy,
        surface=request.surface,
        run_id=request.run_id,
        analysis=analysis,
        prefer_stealth=request.prefer_stealth,
        runtime_options=request.runtime_options,
        host_wait_seconds=host_wait,
        checkpoint=request.checkpoint,
        session_context=request.session_context,
    )
    if promoted_source_result is not None:
        return promoted_source_result

    curl_result, curl_diagnostics = _extract_curl_analysis(analysis)
    browser_failure_diagnostics = (
        curl_result.diagnostics
        if curl_result is not None and isinstance(curl_result.diagnostics, dict)
        else {}
    )
    if (
        http_result is not None
        and execution_decision.runtime == "curl"
    ):
        curl_diagnostics["timings_ms"] = _merge_timing_maps(
            curl_diagnostics.get("timings_ms"),
            {"acquisition_total_ms": _elapsed_ms(started)},
        )
        curl_diagnostics.update(execution_decision.to_diagnostics())
        if curl_result is not None:
            return ctx.update_result_diagnostics(
                curl_result,
                timings_ms=curl_diagnostics.get("timings_ms"),
                **execution_decision.to_diagnostics(),
            )
        return _build_curl_result(
            ctx,
            http_result=http_result,
            analysis=analysis,
            curl_diagnostics=curl_diagnostics,
        )
    browser_result = await _try_browser(
        request.url,
        request.plan,
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
        diagnostics_sink=browser_failure_diagnostics,
        session_context=request.session_context,
    )
    if browser_result is None:
        browser_fallback_updates = {
            "browser_attempted": True,
            "browser_fallback_used": True,
        }
        if has_requested_traversal_mode(request.traversal_mode):
            browser_fallback_updates.update(
                {
                    "traversal_fallback_used": True,
                    "traversal_fallback_reason": (
                        f"browser_failure:{browser_failure_diagnostics.get('browser_failure_class')}"
                        if browser_failure_diagnostics.get("browser_failure_class")
                        else "browser_failure:attempt_required"
                    ),
                }
            )
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
            analysis = http_result.acquirer_analysis or {}
            execution_decision = decide_acquisition_execution(
                http_result,
                plan=request.plan,
                traversal_mode=request.traversal_mode,
                requested_fields=request.requested_fields,
            )
            analysis["execution_decision"] = execution_decision
            curl_result, curl_diagnostics = _extract_curl_analysis(analysis)
            curl_diagnostics.update(browser_failure_diagnostics)
        curl_diagnostics.update(browser_fallback_updates)
        if curl_result is not None:
            fallback_updates = dict(browser_failure_diagnostics)
            fallback_updates.update(browser_fallback_updates)
            fallback_updates.update(execution_decision.to_diagnostics())
            return ctx.update_result_diagnostics(
                curl_result,
                **fallback_updates,
            )
        curl_diagnostics.update(execution_decision.to_diagnostics())
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
    ctx: _AcquireAttemptContext,
    url: str,
    proxy: str | None,
    surface: str | None,
    run_id: int,
    analysis: dict[str, object],
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
        promoted_extractability = assess_extractable_html(
            promoted_html,
            url=promoted_url,
            surface=surface,
            adapter_hint=promoted_adapter_hint,
        )
        promoted_has_data = bool(promoted_extractability.get("has_extractable_data"))
        if not promoted_has_data and html_has_min_listing_link_signals(
            promoted_html,
            surface=surface,
            url=promoted_url,
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
        promoted_visible_text = analyze_html_signals(
            promoted_html,
            url=promoted_url,
            surface=surface,
        ).visible_text
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
                plan_acquisition(
                    SimpleNamespace(url=promoted_url, surface=surface),
                    platform_family=_detect_platform_family(promoted_url),
                ),
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
            browser_runtime_hardened=runtime_options.hardened_mode,
            browser_runtime_reason=runtime_options.hardened_mode_reason,
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
                    {"acquisition_total_ms": _elapsed_ms(ctx.started_at)},
                ),
            }
        )
        if promoted_browser_used:
            diagnostics["browser_attempted"] = True
            diagnostics["browser_diagnostics"] = browser_data.get("diagnostics")
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
            diagnostics=ctx.finalize_diagnostics_payload(diagnostics),
        )
    return None


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
        browser_runtime_hardened=runtime_options.hardened_mode,
        browser_runtime_reason=runtime_options.hardened_mode_reason,
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
        normalized.acquirer_analysis = analysis
        return normalized
    decision_started_at = time.perf_counter()

    # FIX: Offload CPU-bound HTML parsing to prevent Event Loop Starvation
    blocked = normalized.blocked_result()
    html_signal_analysis = await asyncio.to_thread(
        analyze_html_signals,
        html,
        url=url,
        surface=surface,
    )
    soup = html_signal_analysis.soup
    visible_text = html_signal_analysis.visible_text
    gate_phrases = html_signal_analysis.gate_phrases
    listing_signals = html_signal_analysis.listing_signals
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
        assess_extractable_html,
        html,
        url=url,
        surface=surface,
        adapter_hint=adapter_hint,
        soup=soup,
        listing_signals=listing_signals,
    )

    invalid_surface_page = is_invalid_surface_page(
        requested_url=url,
        final_url=str(normalized.final_url or url).strip() or url,
        html=html,
        surface=surface,
        soup=soup,
    )
    page_surface_warnings = surface_selection_warnings(
        requested_url=url,
        final_url=str(normalized.final_url or url).strip() or url,
        html=html,
        surface=surface,
        soup=soup,
    )
    warnings_summary = surface_warning_summary(page_surface_warnings)
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
            "surface_selection_warnings": page_surface_warnings or None,
            "soft_404_page": warnings_summary["soft_404_page"],
            "transactional_page": warnings_summary["transactional_page"],
            "extractability": extractability,
            "promoted_sources": extractability.get("promoted_sources"),
            "listing_signals": listing_signals.as_dict(),
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
            "listing_signals": listing_signals,
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
    normalized.acquirer_analysis = analysis
    return normalized


async def _try_browser(
    url: str,
    plan: AcquisitionPlan,
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
    render_task: asyncio.Task[BrowserResult] | None = None
    try:
        await _cooperative_sleep_ms(sleep_ms, checkpoint=checkpoint)
        render_task = asyncio.create_task(
            fetch_rendered_html(
                url,
                plan=plan,
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
        )
        result = await asyncio.wait_for(
            render_task,
            timeout=float(BROWSER_RENDER_TIMEOUT_SECONDS),
        )
    except (
        TimeoutError,
        PlaywrightError,
        OSError,
        RuntimeError,
        ValueError,
        TypeError,
        NotImplementedError,
    ) as exc:
        if render_task is not None and not render_task.done():
            render_task.cancel()
            with suppress(asyncio.CancelledError):
                await render_task
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
    failure_class, failure_origin = _classify_browser_failure(exc)
    logger.warning(
        "[browser] FAILED class=%s origin=%s type=%s msg=%s",
        failure_class,
        failure_origin,
        type(exc).__name__,
        exc,
    )
    incr("browser_launch_failures_total")
    await _append_browser_failure_log(
        run_id,
        traversal_mode=traversal_mode,
        exc=exc,
        url=url,
        failure_class=failure_class,
        failure_origin=failure_origin,
    )
    if diagnostics_sink is not None:
        diagnostics_sink["browser_exception"] = f"{type(exc).__name__}: {exc}"
        diagnostics_sink["browser_attempted"] = True
        diagnostics_sink["failure_stage"] = "browser_render"
        diagnostics_sink["browser_failure_class"] = failure_class
        diagnostics_sink["browser_failure_origin"] = failure_origin
        diagnostics_sink["browser_fallback_used"] = True
        diagnostics_sink["browser_fallback_reason"] = (
            f"{failure_class}:{failure_origin}"
        )
        diagnostics_sink["retry_count"] = int(diagnostics_sink.get("retry_count", 0) or 0) + 1
        if has_requested_traversal_mode(traversal_mode):
            existing_summary = (
                dict(diagnostics_sink.get("traversal_summary") or {})
                if isinstance(diagnostics_sink.get("traversal_summary"), dict)
                else {}
            )
            existing_summary.update(
                {
                    "attempted": True,
                    "fallback_used": True,
                    "failure_stage": "browser_render",
                    "stop_reason": existing_summary.get("stop_reason")
                    or f"browser_failure:{failure_class}",
                }
            )
            diagnostics_sink["traversal_summary"] = normalize_traversal_summary(
                existing_summary,
                traversal_mode=traversal_mode,
                combined_html=None,
            )
            diagnostics_sink["traversal_fallback_used"] = True
            diagnostics_sink["traversal_fallback_reason"] = (
                f"browser_failure:{failure_class}"
            )
        if isinstance(exc, TimeoutError):
            diagnostics_sink["budget_exhausted"] = "browser_render"


async def _append_browser_failure_log(
    run_id: int | None,
    *,
    traversal_mode: str | None,
    exc: Exception,
    url: str,
    failure_class: str,
    failure_origin: str,
) -> None:
    if run_id is None:
        return
    from app.services.crawl_events import append_log_event

    try:
        await append_log_event(
            run_id=run_id,
            level="warning",
            message=browser_failure_log_message(
                traversal_mode,
                exc,
                failure_class=failure_class,
                failure_origin=failure_origin,
            ),
        )
    except Exception:
        incr("acquisition_log_event_failures_total")
        logger.debug(
            "Failed to append browser acquisition fallback event for %s",
            url,
            exc_info=True,
        )


def _classify_browser_failure(exc: Exception) -> tuple[str, str]:
    text = str(exc or "").strip().lower()
    if isinstance(exc, NotImplementedError):
        return "system_chrome_unsupported", "context"
    if isinstance(exc, TimeoutError) or "timeout" in text:
        return "timeout", "navigation"
    if "target page, context or browser has been closed" in text:
        return "closed_target", "page"
    if "browser_navigation_error" in text:
        return "navigation_failure", "navigation"
    if isinstance(exc, OSError):
        return "launch_failure", "launch"
    if isinstance(exc, (RuntimeError, ValueError, TypeError)):
        return "context_failure", "context"
    return "generic_browser_failure", "launch"


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


def _looks_sensitive_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


def scrub_network_payloads_for_storage(payloads: list[dict]) -> list[dict]:
    if isinstance(payloads, list):
        return [row for row in payloads if isinstance(row, dict)]
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
    browser_runtime_hardened: bool,
    browser_runtime_reason: str | None,
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
        "browser_runtime_hardened": browser_runtime_hardened,
        "browser_runtime_reason": browser_runtime_reason,
        "curl_impersonate_profile": normalized.impersonate_profile or None,
        "curl_attempts": normalized.attempts or None,
        "curl_attempt_log": normalized.attempt_log or None,
        "curl_response_headers": _select_response_headers(response_headers) or None,
        "budget_http_seconds": float(HTTP_TIMEOUT_SECONDS),
        "budget_browser_seconds": float(BROWSER_RENDER_TIMEOUT_SECONDS),
        "budget_acquisition_seconds": float(ACQUISITION_ATTEMPT_TIMEOUT_SECONDS),
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

# DEBT-06: Dead code removed - _artifact_basename and _slugify were never
# called; all artifact path resolution uses artifact_store.artifact_paths().


def _detect_platform_family(url: str, html: str = "") -> str | None:
    return detect_platform_family_from_registry(url, html)
