from __future__ import annotations
import asyncio
from dataclasses import dataclass, replace
import inspect
import logging
import re
import time
from typing import Any, cast
from urllib.parse import urlsplit
import httpx
from bs4 import BeautifulSoup, Tag
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services.acquisition.browser_capture import is_response_closed_error
from app.services.acquisition.browser_readiness import HtmlAnalysis, analyze_html
from app.services.acquisition.dom_runtime import get_page_html
from app.services.acquisition.browser_recovery import (
    capture_rendered_listing_fragments,
    recover_browser_challenge,
)
from app.services.acquisition.runtime import (
    BlockPageClassification,
    classify_blocked_page_async,
    copy_headers,
)
from app.services.config.extraction_rules import (
    ECOMMERCE_DETAIL_SURFACE,
    HTML_PARSER,
    LISTING_VISUAL_PRICE_REGEX_PATTERN,
    LISTING_BRAND_SELECTORS,
    LISTING_UTILITY_URL_TOKENS,
)
from app.services.config.field_mappings import (
    DOM_HIGH_VALUE_FIELDS,
    DOM_OPTIONAL_CUE_FIELDS,
)
from app.services.config.selectors import (
    ANCHOR_SELECTOR,
    LOCATION_INTERSTITIAL_CONTAINER_SELECTORS,
    LOCATION_INTERSTITIAL_DISMISS_SELECTORS,
    LOCATION_INTERSTITIAL_DISMISS_TEXT_TOKENS,
    LOCATION_INTERSTITIAL_TEXT_TOKENS,
    LISTING_CAPTURE_STRUCTURAL_ANCESTOR_SELECTORS,
    LISTING_VISUAL_CANDIDATE_CONTAINER_SELECTORS,
    LISTING_VISUAL_CAPTURE_SELECTORS,
)
from app.services.config.surface_hints import detail_path_hints
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_value_dom import requested_content_extractability
from app.services.platform_policy import (
    resolve_browser_readiness_policy,
    resolve_platform_runtime_policy,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BrowserFinalizeInput:
    page: Any
    url: str
    surface: str | None
    browser_reason: str | None
    on_event: Any
    response: Any
    navigation_strategy: str
    readiness_probes: list[dict[str, object]]
    networkidle_timed_out: bool
    networkidle_skip_reason: str | None
    readiness_policy: dict[str, object]
    readiness_diagnostics: dict[str, object]
    expansion_diagnostics: dict[str, object]
    listing_recovery_diagnostics: dict[str, object]
    payload_capture: Any
    html: str
    traversal_result: Any
    rendered_html: str
    phase_timings_ms: dict[str, int]
    started_at: float
    interstitial_diagnostics: dict[str, object] | None = None
    capture_screenshot: bool = False
    html_analysis: HtmlAnalysis | None = None


class BrowserAcquisitionResultBuilder:
    def __init__(
        self,
        payload: BrowserFinalizeInput,
        *,
        blocked_html_checker,
        classify_blocked_page_async,
        classify_low_content_reason,
        classify_browser_outcome,
        capture_browser_screenshot,
        emit_browser_event,
        elapsed_ms,
    ) -> None:
        self.payload = payload
        self.blocked_html_checker = blocked_html_checker
        self.classify_blocked_page_async = classify_blocked_page_async
        self.classify_low_content_reason = classify_low_content_reason
        self.classify_browser_outcome = classify_browser_outcome
        self.capture_browser_screenshot = capture_browser_screenshot
        self.emit_browser_event = emit_browser_event
        self.elapsed_ms = elapsed_ms

    async def build(self) -> dict[str, object]:
        payload = self.payload
        response_missing = payload.response is None
        status_code = (
            int(
                getattr(
                    payload.response,
                    "browser_recovered_status",
                    getattr(payload.response, "status", 0),
                )
                or 0
            )
            if payload.response is not None
            else 0
        )
        payload_capture_started_at = time.perf_counter()
        capture_summary = await payload.payload_capture.close(payload.page)
        payload.phase_timings_ms["payload_capture"] = self.elapsed_ms(
            payload_capture_started_at
        )
        html_bytes = len(payload.html.encode("utf-8"))
        fast_finalize = _ready_probe_supports_fast_finalize(
            payload.readiness_probes,
            surface=payload.surface,
            status_code=status_code,
            expansion_diagnostics=payload.expansion_diagnostics,
        )
        if fast_finalize:
            blocked_classification = BlockPageClassification(
                blocked=False,
                outcome="ok",
            )
            blocked = False
            challenge_evidence: list[str] = []
            low_content_reason = None
            location_interstitial_present = False
        else:
            blocked_classification = await self.classify_blocked_page_async(
                payload.html, status_code
            )
            blocked_result = self.blocked_html_checker(payload.html, status_code)
            if inspect.isawaitable(blocked_result):
                blocked_result = await blocked_result
            blocked = bool(blocked_classification.blocked) or bool(blocked_result)
            if blocked and not blocked_classification.blocked:
                blocked_classification = BlockPageClassification(
                    blocked=True,
                    outcome="challenge_page",
                    evidence=["blocked_html_checker"],
                )
            challenge_evidence = list(blocked_classification.evidence or [])
            low_content_reason = self.classify_low_content_reason(
                payload.html,
                html_bytes=html_bytes,
            )
            location_interstitial_present = location_interstitial_detected(
                payload.html, analysis=payload.html_analysis
            )
        browser_outcome = self.classify_browser_outcome(
            html=payload.html,
            html_bytes=html_bytes,
            blocked=blocked,
            block_classification=blocked_classification,
            traversal_result=payload.traversal_result,
        )
        if location_interstitial_present:
            blocked = True
            browser_outcome = "location_required"
            low_content_reason = "location_required"
            blocked_classification = replace(
                blocked_classification,
                blocked=True,
                outcome="location_required",
                evidence=list(
                    dict.fromkeys([*challenge_evidence, "location_interstitial"])
                ),
            )
            challenge_evidence = list(blocked_classification.evidence)
        await self._emit_events(browser_outcome=browser_outcome, blocked=blocked)
        screenshot_path = await self._capture_screenshot(
            browser_outcome=browser_outcome
        )
        (
            rendered_listing_fragments,
            listing_visual_elements,
            listing_artifact_diagnostics,
        ) = await self._capture_listing_artifacts()
        payload.phase_timings_ms["total"] = self.elapsed_ms(payload.started_at)
        listing_evidence_counts = {
            "rendered_listing_fragments": len(rendered_listing_fragments),
            "listing_visual_elements": len(listing_visual_elements),
        }
        diagnostics = build_browser_diagnostics(
            browser_reason=payload.browser_reason,
            browser_outcome=browser_outcome,
            navigation_strategy=payload.navigation_strategy,
            response_missing=response_missing,
            networkidle_timed_out=payload.networkidle_timed_out,
            networkidle_skip_reason=payload.networkidle_skip_reason,
            readiness_policy=payload.readiness_policy,
            phase_timings_ms=payload.phase_timings_ms,
            html_bytes=html_bytes,
            challenge_evidence=challenge_evidence,
            blocked_classification=blocked_classification,
            low_content_reason=low_content_reason,
            readiness_probes=payload.readiness_probes,
            capture_summary=capture_summary,
            readiness_diagnostics=payload.readiness_diagnostics,
            expansion_diagnostics=payload.expansion_diagnostics,
            listing_recovery_diagnostics=payload.listing_recovery_diagnostics,
            listing_artifact_diagnostics=listing_artifact_diagnostics,
            interstitial_diagnostics={
                **dict(payload.interstitial_diagnostics or {}),
                "location_required": location_interstitial_present,
            },
            traversal_result=payload.traversal_result,
        )
        diagnostics["rendered_listing_fragment_count"] = listing_evidence_counts[
            "rendered_listing_fragments"
        ]
        diagnostics["listing_visual_element_count"] = listing_evidence_counts[
            "listing_visual_elements"
        ]
        diagnostics["extractable_listing_evidence"] = listing_evidence_counts
        artifacts = build_browser_artifacts(
            screenshot_path=screenshot_path,
            traversal_result=payload.traversal_result,
            html=payload.html,
            rendered_html=payload.rendered_html,
            rendered_listing_fragments=(
                rendered_listing_fragments
                if _capture_status_ok(
                    listing_artifact_diagnostics,
                    "rendered_listing_fragment_capture",
                )
                else None
            ),
            listing_visual_elements=(
                listing_visual_elements
                if _capture_status_ok(
                    listing_artifact_diagnostics,
                    "listing_visual_capture",
                )
                else None
            ),
        )
        return {
            "response_missing": response_missing,
            "status_code": status_code,
            "blocked": blocked,
            "diagnostics": diagnostics,
            "artifacts": artifacts,
            "network_payloads": capture_summary.payloads,
            "page_headers": (
                copy_headers(payload.response.headers)
                if payload.response is not None
                else httpx.Headers()
            ),
            "content_type": (
                payload.response.headers.get("content-type", "text/html")
                if payload.response is not None
                else "text/html"
            ),
            "platform_family": resolve_platform_runtime_policy(
                payload.page.url,
                payload.html,
                surface=payload.surface,
            ).get("family"),
        }

    async def _emit_events(self, *, browser_outcome: str, blocked: bool) -> None:
        payload = self.payload
        if payload.traversal_result is not None and payload.traversal_result.activated:
            await self.emit_browser_event(
                payload.on_event,
                "info",
                (
                    "Traversal complete - "
                    f"mode={payload.traversal_result.selected_mode or payload.traversal_result.requested_mode}, "
                    f"last_page_cards={int(payload.traversal_result.card_count or 0)}, "
                    f"fragments={len(payload.traversal_result.html_fragments)}, "
                    f"progress_events={int(payload.traversal_result.progress_events or 0)}, "
                    f"stop_reason={payload.traversal_result.stop_reason}"
                ),
            )
        if blocked:
            await self.emit_browser_event(
                payload.on_event,
                "warning",
                f"Acquisition detected rate limiting or bot protection for {payload.url}",
            )
        if browser_outcome == "usable_content":
            payload.phase_timings_ms["screenshot_capture"] = 0

    async def _capture_screenshot(self, *, browser_outcome: str) -> str:
        payload = self.payload
        if browser_outcome == "usable_content":
            return ""
        if not payload.capture_screenshot:
            payload.phase_timings_ms["screenshot_capture"] = 0
            return ""
        probes_summary = [
            {
                "stage": probe.get("stage"),
                "is_ready": probe.get("is_ready"),
                "visible_text": probe.get("visible_text_length"),
                "cards": probe.get("listing_card_count"),
            }
            for probe in payload.readiness_probes
        ]
        html_bytes = len(payload.html.encode("utf-8"))
        low_content_reason = self.classify_low_content_reason(
            payload.html,
            html_bytes=html_bytes,
        )
        logger.warning(
            "Browser acquisition outcome=%s url=%s html_bytes=%s low_content_reason=%s probes=%s",
            browser_outcome,
            payload.url,
            html_bytes,
            low_content_reason,
            probes_summary,
        )
        screenshot_started_at = time.perf_counter()
        try:
            return await self.capture_browser_screenshot(payload.page)
        finally:
            payload.phase_timings_ms["screenshot_capture"] = self.elapsed_ms(
                screenshot_started_at
            )

    async def _capture_listing_artifacts(
        self,
    ) -> tuple[
        list[str],
        list[dict[str, object]],
        dict[str, object],
    ]:
        payload = self.payload
        is_listing = "listing" in str(payload.surface or "").lower()
        if is_listing:
            (
                rendered_listing_fragments,
                rendered_listing_fragment_capture,
            ) = await self._capture_timed_listing_artifact(
                capture_rendered_listing_fragments(
                    payload.page,
                    surface=payload.surface,
                    limit=int(crawler_runtime_settings.rendered_listing_card_capture_limit),
                ),
                stage="rendered_listing_fragment_capture",
                item_kind="text",
            )
        else:
            payload.phase_timings_ms["rendered_listing_fragment_capture"] = 0
            rendered_listing_fragments, rendered_listing_fragment_capture = [], {
                "status": "skipped",
                "reason": "non_listing_surface",
            }
        if is_listing:
            (
                listing_visual_elements,
                listing_visual_capture,
            ) = await self._capture_timed_listing_artifact(
                _capture_listing_visual_elements(
                    payload.page,
                    surface=payload.surface,
                ),
                stage="listing_visual_capture",
                item_kind="mapping",
            )
        else:
            payload.phase_timings_ms["listing_visual_capture"] = 0
            listing_visual_elements, listing_visual_capture = [], {
                "status": "skipped",
                "reason": "non_listing_surface",
            }
        return (
            cast(list[str], rendered_listing_fragments),
            cast(list[dict[str, object]], listing_visual_elements),
            {
                "rendered_listing_fragment_capture": rendered_listing_fragment_capture,
                "listing_visual_capture": listing_visual_capture,
            },
        )

    async def _capture_timed_listing_artifact(
        self,
        operation,
        *,
        stage: str,
        item_kind: str,
    ) -> tuple[list[object], dict[str, object]]:
        payload = self.payload
        started_at = time.perf_counter()
        artifacts, capture_diagnostics = await _capture_listing_artifact_with_timeout(
            operation,
            stage=stage,
            url=payload.url,
            item_kind=item_kind,
        )
        payload.phase_timings_ms[stage] = self.elapsed_ms(started_at)
        return artifacts, capture_diagnostics


async def _capture_listing_artifact_with_timeout(
    operation,
    *,
    stage: str,
    url: str,
    item_kind: str = "mapping",
) -> tuple[list[object], dict[str, object]]:
    timeout_seconds = max(
        0.1,
        float(crawler_runtime_settings.browser_artifact_capture_timeout_ms) / 1000,
    )
    try:
        result = await asyncio.wait_for(operation, timeout=timeout_seconds)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        logger.warning(
            "Timed out during %s for %s after %.1fs",
            stage,
            url,
            timeout_seconds,
        )
        return [], {"status": "timeout"}
    except PlaywrightTimeoutError:
        logger.warning("Playwright timed out during %s for %s", stage, url)
        return [], {"status": "playwright_timeout"}
    except PlaywrightError as exc:
        status = "closed" if is_response_closed_error(exc) else "playwright_error"
        logger.debug(
            "Listing artifact capture Playwright error stage=%s url=%s status=%s",
            stage,
            url,
            status,
            exc_info=True,
        )
        return [], {"status": status}
    except Exception:
        logger.exception(
            "Listing artifact capture unexpected error stage=%s url=%s",
            stage,
            url,
        )
        return [], {"status": "unexpected_error"}
    if not isinstance(result, list):
        return [], {"status": "invalid_result"}
    rows: list[object] = []
    for item in result:
        if item_kind == "mapping" and isinstance(item, dict):
            rows.append(dict(item))
            continue
        if item_kind == "text" and isinstance(item, str):
            text = item.strip()
            if text:
                rows.append(text)
    return (rows, {"status": "ok"})


def remaining_timeout_factory(deadline: float):
    def _remaining() -> float:
        return max(2.0, deadline - time.perf_counter())

    return _remaining


def _capture_status_ok(
    diagnostics: dict[str, object],
    key: str,
) -> bool:
    capture = diagnostics.get(key)
    if not isinstance(capture, dict):
        return False
    return str(capture.get("status") or "").strip().lower() == "ok"


def _is_navigation_interrupted_error(exc: Exception) -> bool:
    return "interrupted by another navigation" in str(exc or "").strip().lower()


def _urls_match_for_navigation(expected_url: str, current_url: str) -> bool:
    expected = urlsplit(str(expected_url or "").strip())
    current = urlsplit(str(current_url or "").strip())
    if not expected.scheme or not expected.netloc:
        return False
    return (
        expected.scheme.lower(),
        expected.netloc.lower(),
        expected.path.rstrip("/") or "/",
        expected.query,
    ) == (
        current.scheme.lower(),
        current.netloc.lower(),
        current.path.rstrip("/") or "/",
        current.query,
    )


async def _recover_interrupted_navigation(
    page: Any,
    *,
    url: str,
    wait_until: str,
    timeout_ms: int,
) -> bool:
    if timeout_ms <= 0:
        return False
    recovery_state = "domcontentloaded" if wait_until == "commit" else wait_until
    if recovery_state not in {"load", "domcontentloaded", "networkidle"}:
        recovery_state = "domcontentloaded"
    try:
        await page.wait_for_load_state(recovery_state, timeout=timeout_ms)
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, PlaywrightTimeoutError, PlaywrightError):
        return False
    return _urls_match_for_navigation(url, str(getattr(page, "url", "") or ""))


async def _goto_with_interrupted_navigation_recovery(
    page: Any,
    *,
    url: str,
    wait_until: str,
    timeout_ms: int,
):
    try:
        return await page.goto(
            url,
            wait_until=wait_until,
            timeout=timeout_ms,
        )
    except asyncio.CancelledError:
        raise
    except PlaywrightError as exc:
        if not _is_navigation_interrupted_error(exc):
            raise
        if not await _recover_interrupted_navigation(
            page,
            url=url,
            wait_until=wait_until,
            timeout_ms=timeout_ms,
        ):
            raise
        logger.debug(
            "Recovered interrupted navigation url=%s wait_until=%s current_url=%s",
            url,
            wait_until,
            getattr(page, "url", ""),
        )
        return None


async def navigate_browser_page_impl(
    page: Any,
    *,
    url: str,
    browser_engine: str | None = None,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
    readiness_policy: dict[str, object] | None,
    crawler_runtime_settings,
    elapsed_ms,
):
    navigation_wait_until = (
        str((readiness_policy or {}).get("navigation_wait_until") or "domcontentloaded")
        .strip()
        .lower()
    )
    total_timeout_ms = int(timeout_seconds * 1000)
    primary_timeout_cap_ms = int(
        crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms
    )
    if navigation_wait_until == "networkidle":
        primary_timeout_cap_ms = min(
            int(crawler_runtime_settings.browser_navigation_networkidle_timeout_ms),
            max(
                1,
                int(
                    total_timeout_ms
                    * float(
                        crawler_runtime_settings.browser_navigation_networkidle_primary_budget_ratio
                    )
                ),
            ),
        )
    goto_timeout_ms = min(total_timeout_ms, primary_timeout_cap_ms)
    fallback_timeout_ms = min(
        total_timeout_ms,
        int(crawler_runtime_settings.browser_navigation_min_final_commit_timeout_ms),
    )
    navigation_strategy = navigation_wait_until
    navigation_started_at = time.perf_counter()
    try:
        response = await _goto_with_interrupted_navigation_recovery(
            page,
            url=url,
            wait_until=navigation_wait_until,
            timeout_ms=goto_timeout_ms,
        )
    except asyncio.CancelledError:
        raise
    except (PlaywrightTimeoutError, PlaywrightError):
        fallback_strategy = (
            "domcontentloaded" if navigation_wait_until == "networkidle" else "commit"
        )
        navigation_strategy = fallback_strategy
        try:
            fallback_timeout = (
                min(
                    total_timeout_ms,
                    int(
                        crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms
                    ),
                )
                if fallback_strategy == "domcontentloaded"
                else fallback_timeout_ms
            )
            response = await _goto_with_interrupted_navigation_recovery(
                page,
                url=url,
                wait_until=fallback_strategy,
                timeout_ms=fallback_timeout,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if fallback_strategy != "commit":
                navigation_strategy = "commit"
                try:
                    response = await _goto_with_interrupted_navigation_recovery(
                        page,
                        url=url,
                        wait_until="commit",
                        timeout_ms=fallback_timeout_ms,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as final_exc:
                    phase_timings_ms["navigation"] = elapsed_ms(navigation_started_at)
                    setattr(
                        final_exc, "browser_phase_timings_ms", dict(phase_timings_ms)
                    )
                    setattr(
                        final_exc, "browser_navigation_strategy", navigation_strategy
                    )
                    raise
            else:
                phase_timings_ms["navigation"] = elapsed_ms(navigation_started_at)
                setattr(exc, "browser_phase_timings_ms", dict(phase_timings_ms))
                setattr(exc, "browser_navigation_strategy", navigation_strategy)
                raise
    finally:
        phase_timings_ms["navigation"] = elapsed_ms(navigation_started_at)
    response = await recover_browser_challenge(
        page,
        url=url,
        response=response,
        browser_engine=browser_engine,
        timeout_seconds=timeout_seconds,
        phase_timings_ms=phase_timings_ms,
        challenge_wait_max_seconds=float(
            crawler_runtime_settings.challenge_wait_max_seconds or 0
        ),
        challenge_poll_interval_ms=int(
            crawler_runtime_settings.challenge_poll_interval_ms
        ),
        navigation_timeout_ms=int(
            crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms
        ),
        elapsed_ms=elapsed_ms,
        classify_blocked_page=classify_blocked_page_async,
        get_page_html=get_page_html,
    )
    if response is not None:
        recovered_strategy = getattr(response, "browser_navigation_strategy", None)
        if recovered_strategy is not None:
            navigation_strategy = str(recovered_strategy) or navigation_strategy
    return response, navigation_strategy


async def settle_browser_page_impl(
    page: Any,
    *,
    url: str,
    surface: str,
    requested_fields: list[str] | None,
    timeout_seconds: float,
    readiness_override: dict[str, object] | None,
    readiness_policy: dict[str, object],
    phase_timings_ms: dict[str, int],
    crawler_runtime_settings,
    get_page_html_impl=get_page_html,
    probe_browser_readiness,
    wait_for_listing_readiness,
    expand_detail_content_if_needed,
    append_readiness_probe,
    elapsed_ms,
):
    readiness_probes: list[dict[str, object]] = []
    cached_html: str | None = None
    cached_analysis: HtmlAnalysis | None = None

    async def _cached_probe(*, refresh_html: bool = False) -> dict[str, object]:
        nonlocal cached_html, cached_analysis
        if refresh_html or cached_html is None:
            cached_html = await get_page_html_impl(page)
            cached_analysis = analyze_html(cached_html or "")
        elif cached_analysis is None:
            cached_analysis = analyze_html(cached_html or "")
        return await probe_browser_readiness(
            page,
            url=url,
            surface=surface,
            listing_override=readiness_override,
            html=cached_html,
        )

    current_probe = await _cached_probe(refresh_html=True)
    append_readiness_probe(
        readiness_probes, stage="after_navigation", probe=current_probe
    )
    wait_ms = min(
        int(timeout_seconds * 1000),
        int(crawler_runtime_settings.browser_navigation_optimistic_wait_ms),
    )
    if wait_ms > 0 and not current_probe["is_ready"]:
        optimistic_wait_started_at = time.perf_counter()
        try:
            await page.wait_for_function(
                "({visibleTextMin}) => String((document.body && (document.body.innerText || document.body.textContent)) || '').trim().length >= Number(visibleTextMin || 0)",
                arg={
                    "visibleTextMin": int(
                        crawler_runtime_settings.browser_readiness_visible_text_min
                    ),
                },
                timeout=wait_ms,
            )
        except PlaywrightTimeoutError:
            pass
        phase_timings_ms["optimistic_wait"] = elapsed_ms(optimistic_wait_started_at)
        current_probe = await _cached_probe(refresh_html=True)
        append_readiness_probe(
            readiness_probes, stage="after_optimistic_wait", probe=current_probe
        )
    else:
        phase_timings_ms["optimistic_wait"] = 0
    networkidle_timed_out = False
    networkidle_skip_reason = None
    explicit_require_networkidle = bool(readiness_policy.get("require_networkidle"))
    is_listing_surface = "listing" in str(surface or "").lower()
    is_detail_surface = "detail" in str(surface or "").lower()
    implicit_networkidle_attempt = bool(
        not current_probe["is_ready"]
        and not explicit_require_networkidle
        and not is_detail_surface
        and (is_listing_surface or not current_probe.get("structured_data_present"))
    )
    if not current_probe["is_ready"] and (
        explicit_require_networkidle or implicit_networkidle_attempt
    ):
        networkidle_wait_started_at = time.perf_counter()
        networkidle_timeout_cap_ms = (
            int(crawler_runtime_settings.browser_navigation_networkidle_timeout_ms)
            if explicit_require_networkidle
            else int(
                crawler_runtime_settings.browser_spa_implicit_networkidle_timeout_ms
            )
        )
        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=min(
                    int(timeout_seconds * 1000),
                    networkidle_timeout_cap_ms,
                ),
            )
        except PlaywrightTimeoutError:
            networkidle_timed_out = True
        phase_timings_ms["networkidle_wait"] = elapsed_ms(networkidle_wait_started_at)
        current_probe = await _cached_probe(refresh_html=True)
        append_readiness_probe(
            readiness_probes, stage="after_networkidle", probe=current_probe
        )
    else:
        phase_timings_ms["networkidle_wait"] = 0
        networkidle_skip_reason = (
            "fast_path_ready"
            if current_probe["is_ready"]
            else "structured_data_present"
            if current_probe.get("structured_data_present")
            else "not_required"
        )
    if not current_probe["is_ready"] and readiness_override is not None:
        readiness_started_at = time.perf_counter()
        readiness_diagnostics = await wait_for_listing_readiness(
            page,
            url,
            override=readiness_override,
        )
        phase_timings_ms["readiness_wait"] = elapsed_ms(readiness_started_at)
        current_probe = await _cached_probe(refresh_html=True)
        append_readiness_probe(
            readiness_probes, stage="after_platform_readiness", probe=current_probe
        )
    else:
        phase_timings_ms["readiness_wait"] = 0
        readiness_diagnostics = {
            "status": "skipped",
            "reason": (
                "fast_path_ready"
                if current_probe["is_ready"]
                else "no_platform_override"
            ),
        }
    if not is_detail_surface:
        expansion_diagnostics = {
            "status": "skipped",
            "reason": "non_detail_surface",
            "clicked_count": 0,
            "expanded_elements": [],
            "interaction_failures": [],
            "dom": {},
            "aom": {},
        }
        phase_timings_ms["expansion"] = 0
    else:
        initial_extractability = _detail_expansion_extractability(
            html=cached_html or "",
            soup=cached_analysis.soup if cached_analysis is not None else None,
            surface=surface or "",
            requested_fields=requested_fields,
        )
        skip_expansion, skip_reason = _detail_expansion_can_skip(
            initial_extractability,
            surface=surface,
            requested_fields=requested_fields,
            readiness_probe=current_probe,
        )
        if skip_expansion:
            expansion_diagnostics = {
                "status": "skipped",
                "reason": skip_reason,
                "clicked_count": 0,
                "expanded_elements": [],
                "interaction_failures": [],
                "dom": {},
                "aom": {},
                "extractability": initial_extractability,
            }
            phase_timings_ms["expansion"] = 0
        else:
            expansion_started_at = time.perf_counter()
            expansion_diagnostics = await expand_detail_content_if_needed(
                page,
                surface=surface,
                readiness_probe=current_probe,
                requested_fields=requested_fields,
            )
            phase_timings_ms["expansion"] = elapsed_ms(expansion_started_at)
        if expansion_diagnostics.get("clicked_count", 0):
            current_probe = await _cached_probe(refresh_html=True)
            append_readiness_probe(
                readiness_probes,
                stage="after_detail_expansion",
                probe=current_probe,
            )
            expansion_diagnostics["extractability"] = _detail_expansion_extractability(
                html=cached_html or "",
                soup=cached_analysis.soup if cached_analysis is not None else None,
                surface=surface or "",
                requested_fields=requested_fields,
            )
    return (
        current_probe,
        readiness_probes,
        networkidle_timed_out,
        networkidle_skip_reason,
        readiness_diagnostics,
        expansion_diagnostics,
        cached_html or "",
        cached_analysis,
    )


async def serialize_browser_page_content_impl(
    page: Any,
    *,
    surface: str | None,
    traversal_mode: str | None,
    listing_recovery_mode: str | None,
    traversal_active: bool,
    timeout_seconds: float,
    max_pages: int,
    max_scrolls: int,
    max_records: int | None = None,
    prefetched_html: str | None = None,
    prefetched_analysis: HtmlAnalysis | None = None,
    phase_timings_ms: dict[str, int],
    execute_listing_traversal,
    recover_listing_page_content,
    elapsed_ms,
    on_event=None,
):
    should_flatten_shadow = "listing" not in str(surface or "").strip().lower()
    traversal_result = None
    traversal_html = ""
    rendered_html = ""
    listing_recovery_diagnostics = {
        "status": "skipped",
        "reason": "not_requested",
        "clicked_count": 0,
        "actions_taken": [],
    }
    recovery_started_at = time.perf_counter()
    normalized_listing_recovery_mode = _normalize_listing_recovery_mode(
        listing_recovery_mode
    )
    if normalized_listing_recovery_mode is not None:
        listing_recovery_diagnostics["requested_mode"] = (
            normalized_listing_recovery_mode
        )
    if traversal_active and normalized_listing_recovery_mode == "thin_listing":
        listing_recovery_diagnostics = await recover_listing_page_content(
            page,
            on_event=on_event,
        )
        listing_recovery_diagnostics["requested_mode"] = (
            normalized_listing_recovery_mode
        )
    elif normalized_listing_recovery_mode is not None:
        listing_recovery_diagnostics["reason"] = (
            "traversal_inactive" if not traversal_active else "unsupported_mode"
        )
    phase_timings_ms["listing_recovery"] = elapsed_ms(recovery_started_at)
    traversal_started_at = time.perf_counter()
    if traversal_active:
        traversal_result = await execute_listing_traversal(
            page,
            surface=str(surface or ""),
            traversal_mode=str(traversal_mode or ""),
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            max_records=max_records,
            timeout_seconds=timeout_seconds,
            on_event=on_event,
        )
        traversal_html = traversal_result.compose_html()
        rendered_html = await get_page_html(
            page,
            flatten_shadow=should_flatten_shadow,
        )
        html = _select_primary_browser_html(
            surface=surface,
            traversal_result=traversal_result,
            traversal_html=traversal_html,
            rendered_html=rendered_html,
            listing_min_items=int(crawler_runtime_settings.listing_min_items),
        )
    else:
        html = ""
    phase_timings_ms["traversal"] = elapsed_ms(traversal_started_at)
    serialization_started_at = time.perf_counter()
    if traversal_result is None:
        html = str(prefetched_html or "")
        if not html.strip():
            html = await get_page_html(
                page,
                flatten_shadow=should_flatten_shadow,
            )
        rendered_html = html
    phase_timings_ms["content_serialization"] = elapsed_ms(serialization_started_at)
    return (
        html,
        traversal_result,
        rendered_html,
        listing_recovery_diagnostics,
    )


def resolve_browser_fetch_policy(
    *,
    url: str,
    surface: str,
    traversal_mode: str | None,
    should_run_traversal,
) -> tuple[bool, dict[str, object], dict[str, object] | None]:
    traversal_active = should_run_traversal(surface, traversal_mode)
    readiness_policy = resolve_browser_readiness_policy(
        url,
        surface=surface,
        traversal_active=traversal_active,
    )
    readiness_override = readiness_policy.get("listing_override")
    return traversal_active, readiness_policy, readiness_override


def build_browser_diagnostics(
    *,
    browser_reason: str | None,
    browser_outcome: str,
    navigation_strategy: str,
    response_missing: bool,
    networkidle_timed_out: bool,
    networkidle_skip_reason: str | None,
    readiness_policy: dict[str, object],
    phase_timings_ms: dict[str, int],
    html_bytes: int,
    challenge_evidence: list[str],
    blocked_classification,
    low_content_reason: str | None,
    readiness_probes: list[dict[str, object]],
    capture_summary,
    readiness_diagnostics: dict[str, object],
    expansion_diagnostics: dict[str, object],
    listing_recovery_diagnostics: dict[str, object],
    listing_artifact_diagnostics: dict[str, object],
    interstitial_diagnostics: dict[str, object],
    traversal_result,
) -> dict[str, object]:
    diagnostics = {
        "browser_attempted": True,
        "browser_reason": str(browser_reason or "").strip().lower() or None,
        "browser_outcome": browser_outcome,
        "navigation_strategy": navigation_strategy,
        "response_missing": response_missing,
        "networkidle_timed_out": networkidle_timed_out,
        "networkidle_wait_reason": readiness_policy.get("networkidle_reason"),
        "networkidle_skip_reason": networkidle_skip_reason,
        "html_bytes": html_bytes,
        "phase_timings_ms": phase_timings_ms,
        "challenge_evidence": challenge_evidence,
        "challenge_provider_hits": list(blocked_classification.provider_hits or []),
        "challenge_element_hits": list(
            blocked_classification.challenge_element_hits or []
        ),
        "low_content_reason": low_content_reason,
        "readiness_probes": readiness_probes,
        "network_payload_count": capture_summary.network_payload_count,
        "malformed_network_payloads": capture_summary.malformed_network_payloads,
        "network_payload_read_failures": capture_summary.network_payload_read_failures,
        "network_payload_read_timeouts": capture_summary.network_payload_read_timeouts,
        "closed_network_payloads": capture_summary.closed_network_payloads,
        "skipped_oversized_network_payloads": capture_summary.skipped_oversized_network_payloads,
        "dropped_network_payload_events": capture_summary.dropped_payload_events,
        "listing_readiness": readiness_diagnostics,
        "listing_recovery": listing_recovery_diagnostics,
        "listing_artifact_capture": listing_artifact_diagnostics,
        "interstitial": interstitial_diagnostics,
        "failure_reason": "location_required"
        if browser_outcome == "location_required"
        else None,
        "detail_expansion": expansion_diagnostics,
    }
    if traversal_result is not None:
        diagnostics.update(traversal_result.diagnostics())
    return diagnostics


def build_browser_artifacts(
    *,
    screenshot_path: str,
    traversal_result,
    html: str,
    rendered_html: str,
    rendered_listing_fragments: list[str] | None = None,
    listing_visual_elements: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    artifacts: dict[str, object] = {}
    if screenshot_path:
        artifacts["browser_screenshot_path"] = screenshot_path
    if rendered_listing_fragments is not None:
        artifacts["rendered_listing_fragments"] = rendered_listing_fragments
    if listing_visual_elements is not None:
        artifacts["listing_visual_elements"] = listing_visual_elements
    if traversal_result is not None and traversal_result.activated:
        artifacts["traversal_composed_html"] = traversal_result.compose_html()
        artifacts["full_rendered_html"] = rendered_html
    return artifacts


def _string_config_list(value: object) -> list[str]:
    if isinstance(value, (str, bytes)):
        return [str(value).strip()] if str(value).strip() else []
    if isinstance(value, dict):
        items: list[object] = list(value.keys())
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]


def location_interstitial_detected(
    html: str,
    *,
    analysis: HtmlAnalysis | None = None,
) -> bool:
    analysis = analysis or analyze_html(str(html or ""))
    soup = analysis.soup
    text = analysis.normalized_text.lower()
    tokens = _string_config_list(LOCATION_INTERSTITIAL_TEXT_TOKENS)
    matched_tokens = [
        token.lower() for token in tokens if token and token.lower() in text
    ]
    if not text or not matched_tokens:
        return False
    selectors = _string_config_list(LOCATION_INTERSTITIAL_CONTAINER_SELECTORS)
    for selector in selectors:
        try:
            if soup.select_one(selector) is not None:
                return True
        except Exception:
            logger.debug(
                "Invalid location interstitial selector=%s", selector, exc_info=True
            )
    for node in soup.select(
        "[aria-modal='true'], [role='dialog'], .modal, .popup, .overlay"
    ):
        node_text = " ".join(node.get_text(" ", strip=True).lower().split())
        if any(token in node_text for token in matched_tokens):
            return True
    return len(matched_tokens) >= 2


def _ready_probe_supports_fast_finalize(
    readiness_probes: list[dict[str, object]],
    *,
    surface: str | None,
    status_code: int,
    expansion_diagnostics: dict[str, object] | None = None,
) -> bool:
    if int(status_code or 0) in {401, 403, 429}:
        return False
    normalized_surface = str(surface or "").strip().lower()
    min_visible_text = int(crawler_runtime_settings.browser_readiness_visible_text_min)
    min_detail_hints = int(crawler_runtime_settings.detail_field_signal_min_count)
    min_listing_items = int(crawler_runtime_settings.listing_min_items)
    extractability = (
        cast(dict[str, object], expansion_diagnostics.get("extractability"))
        if isinstance(expansion_diagnostics, dict)
        and isinstance(expansion_diagnostics.get("extractability"), dict)
        else {}
    )
    matched_requested_fields = extractability.get("matched_requested_fields")
    extractable_fields = extractability.get("extractable_fields")
    if bool(extractability.get("verified")) and (
        bool(matched_requested_fields) or bool(extractable_fields)
    ):
        return True
    for probe in readiness_probes:
        if not isinstance(probe, dict) or not bool(probe.get("is_ready")):
            continue
        visible_text_length = _object_int(probe.get("visible_text_length"))
        if visible_text_length < min_visible_text:
            continue
        if "detail" in normalized_surface:
            if bool(probe.get("structured_data_present")):
                return True
            if _object_int(probe.get("detail_hint_count")) >= min_detail_hints:
                return True
            continue
        if "listing" in normalized_surface:
            if _object_int(probe.get("listing_card_count")) >= min_listing_items:
                return True
            if _object_int(probe.get("matched_listing_selectors")) > 0:
                return True
            continue
        return True
    return False


def _object_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value or default))
    except (TypeError, ValueError):
        return default


async def _page_might_have_location_interstitial(page: Any) -> bool:
    selectors = _string_config_list(LOCATION_INTERSTITIAL_CONTAINER_SELECTORS)
    tokens = _string_config_list(LOCATION_INTERSTITIAL_TEXT_TOKENS)
    if not tokens:
        return False
    try:
        result = await page.evaluate(
            """
            ({selectors, tokens}) => {
              const normalizedSelectors = Array.isArray(selectors) ? selectors : [];
              const normalizedTokens = (Array.isArray(tokens) ? tokens : [])
                .map((value) => String(value || '').trim().toLowerCase())
                .filter(Boolean);
              if (!normalizedTokens.length) {
                return false;
              }
              const hasToken = (text) => {
                const normalized = String(text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                return normalized && normalizedTokens.some((token) => normalized.includes(token));
              };
              if (normalizedSelectors.length) {
                for (const selector of normalizedSelectors) {
                  try {
                    const node = document.querySelector(selector);
                    if (node && hasToken(node.innerText || node.textContent || '')) {
                      return true;
                    }
                  } catch {}
                }
              }
              return hasToken(document.body ? document.body.innerText : '');
            }
            """,
            {"selectors": selectors, "tokens": tokens},
        )
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, PlaywrightTimeoutError, PlaywrightError):
        logger.debug(
            "Location interstitial precheck failed url=%s",
            getattr(page, "url", ""),
            exc_info=True,
        )
        return True
    return bool(result)


async def dismiss_safe_location_interstitial(page: Any) -> dict[str, object]:
    if not await _page_might_have_location_interstitial(page):
        return {"status": "not_found", "reason": "no_location_signal"}
    selectors = _string_config_list(LOCATION_INTERSTITIAL_DISMISS_SELECTORS)
    still_present_result: dict[str, object] | None = None
    visible_timeout_ms = int(
        crawler_runtime_settings.traversal_location_interstitial_visible_timeout_ms
        if crawler_runtime_settings.traversal_location_interstitial_visible_timeout_ms
        is not None
        else crawler_runtime_settings.traversal_cookie_consent_visible_timeout_ms
    )
    click_timeout_ms = int(
        crawler_runtime_settings.traversal_location_interstitial_click_timeout_ms
        if crawler_runtime_settings.traversal_location_interstitial_click_timeout_ms
        is not None
        else crawler_runtime_settings.traversal_cookie_consent_click_timeout_ms
    )
    postclick_wait_ms = int(
        crawler_runtime_settings.traversal_location_interstitial_postclick_wait_ms
        if crawler_runtime_settings.traversal_location_interstitial_postclick_wait_ms
        is not None
        else crawler_runtime_settings.cookie_consent_postclick_wait_ms
    )
    for selector in selectors:
        try:
            matches = page.locator(selector)
            if await matches.count() <= 0:
                continue
            locator = matches.first
            await locator.wait_for(
                state="visible",
                timeout=visible_timeout_ms,
            )
            await locator.click(
                timeout=click_timeout_ms,
                force=True,
            )
            await page.wait_for_timeout(postclick_wait_ms)
            if not await _page_might_have_location_interstitial(page):
                return {"status": "dismissed", "selector": selector}
            still_present_result = {"status": "still_present", "selector": selector}
        except asyncio.CancelledError:
            raise
        except (asyncio.TimeoutError, PlaywrightTimeoutError, PlaywrightError):
            logger.debug(
                "Location interstitial dismissal probe failed selector=%s url=%s",
                selector,
                getattr(page, "url", ""),
                exc_info=True,
            )
    text_result = await _dismiss_location_interstitial_by_text(page)
    if text_result.get("status") == "dismissed":
        return text_result
    if text_result.get("status") == "still_present":
        return text_result
    if still_present_result is not None:
        return still_present_result
    return {"status": "not_found"}


async def _dismiss_location_interstitial_by_text(page: Any) -> dict[str, object]:
    tokens = _string_config_list(LOCATION_INTERSTITIAL_DISMISS_TEXT_TOKENS)
    location_tokens = _string_config_list(LOCATION_INTERSTITIAL_TEXT_TOKENS)
    if not tokens:
        return {"status": "skipped", "reason": "no_text_tokens"}
    try:
        result = await page.evaluate(
            """
            ({tokens, locationTokens}) => {
              const normalizedTokens = tokens
                .map((value) => String(value || '').trim().toLowerCase())
                .filter(Boolean);
              const normalizedLocationTokens = locationTokens
                .map((value) => String(value || '').trim().toLowerCase())
                .filter(Boolean);
              const hasLocationText = (node) => {
                const root = node.closest('[aria-modal="true"],[role="dialog"],.modal,.popup,.overlay')
                  || node.parentElement;
                const text = String((root && (root.innerText || root.textContent)) || document.body.textContent || '')
                  .replace(/\\s+/g, ' ')
                  .trim()
                  .toLowerCase();
                return normalizedLocationTokens.some((token) => text.includes(token));
              };
              const elements = Array.from(document.querySelectorAll(
                'button,[role="button"],a,input[type="button"],input[type="submit"]'
              ));
              const visible = (node) => {
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.visibility !== 'hidden'
                  && style.display !== 'none'
                  && rect.width > 0
                  && rect.height > 0;
              };
              for (const node of elements) {
                if (!visible(node)) continue;
                if (!hasLocationText(node)) continue;
                const rawText = node.innerText || node.textContent || node.value
                  || node.getAttribute('aria-label') || '';
                const text = String(rawText).replace(/\\s+/g, ' ').trim();
                const lowered = text.toLowerCase();
                if (!lowered) continue;
                const matched = normalizedTokens.find(
                  (token) => lowered === token || lowered.includes(token)
                );
                if (!matched) continue;
                node.click();
                return {status: 'dismissed', text, selector: 'text:' + matched};
              }
              return {status: 'not_found'};
            }
            """,
            {"tokens": tokens, "locationTokens": location_tokens},
        )
        if isinstance(result, dict) and result.get("status") == "dismissed":
            await page.wait_for_timeout(
                int(crawler_runtime_settings.cookie_consent_postclick_wait_ms)
            )
            if not await _page_might_have_location_interstitial(page):
                return dict(result)
            return {
                **dict(result),
                "status": "still_present",
            }
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, PlaywrightTimeoutError, PlaywrightError):
        logger.debug(
            "Location interstitial text dismissal failed url=%s",
            getattr(page, "url", ""),
            exc_info=True,
        )
    return {"status": "not_found"}


def _select_primary_browser_html(
    *,
    surface: str | None,
    traversal_result,
    traversal_html: str,
    rendered_html: str,
    listing_min_items: int,
) -> str:
    if traversal_result is None or not getattr(traversal_result, "activated", False):
        return traversal_html or rendered_html
    if "listing" not in str(surface or "").strip().lower():
        return traversal_html or rendered_html
    if not str(rendered_html or "").strip():
        return traversal_html
    if not str(traversal_html or "").strip():
        return rendered_html
    progress_events = int(getattr(traversal_result, "progress_events", 0) or 0)
    card_count = int(getattr(traversal_result, "card_count", 0) or 0)
    stop_reason = str(getattr(traversal_result, "stop_reason", "") or "").strip()
    rendered_signal_count = _listing_html_detail_anchor_count(rendered_html)
    traversal_signal_count = _listing_html_detail_anchor_count(traversal_html)
    if rendered_signal_count > traversal_signal_count:
        return rendered_html
    if progress_events > 0 and (
        card_count >= max(1, int(listing_min_items))
        or traversal_signal_count >= max(2, rendered_signal_count)
    ):
        return traversal_html
    if card_count >= max(1, int(listing_min_items)):
        return rendered_html
    if stop_reason.endswith("_blocked") and traversal_signal_count >= max(
        2,
        int(listing_min_items),
    ):
        return traversal_html
    if stop_reason.endswith(
        ("_not_found", "_no_progress", "_click_failed", "_blocked")
    ):
        return rendered_html
    return traversal_html


def _listing_html_detail_anchor_count(html: str) -> int:
    soup = BeautifulSoup(str(html or ""), HTML_PARSER)
    count = 0
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip().lower()
        if any(
            marker in href
            for marker in (
                "/products/",
                "/product/",
                "/p/",
                "/item/",
                "/jobs/",
                "/job/",
            )
        ):
            count += 1
    return count


def _normalize_listing_recovery_mode(value: object) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized.endswith("_retry"):
        normalized = normalized[: -len("_retry")]
    return normalized or None


def _detail_expansion_extractability(
    *,
    html: str,
    soup: BeautifulSoup | None = None,
    surface: str,
    requested_fields: list[str] | None,
) -> dict[str, object]:
    if soup is None and not str(html or "").strip():
        return {
            "verified": False,
            "matched_requested_fields": [],
            "extractable_fields": [],
            "section_fields": [],
        }
    if soup is None:
        soup = BeautifulSoup(str(html or ""), HTML_PARSER)
    return requested_content_extractability(
        soup,
        surface=surface,
        requested_fields=requested_fields,
        probe_fields=_detail_expansion_probe_fields(
            surface=surface,
            requested_fields=requested_fields,
        ),
    )


def _detail_expansion_probe_fields(
    *,
    surface: str,
    requested_fields: list[str] | None,
) -> list[str] | None:
    if requested_fields:
        return sorted({str(field_name).strip() for field_name in requested_fields if str(field_name).strip()}) or None
    normalized_surface = str(surface or "").strip().lower()
    probe_fields = {
        *set(DOM_HIGH_VALUE_FIELDS.get(normalized_surface) or ()),
        *set(DOM_OPTIONAL_CUE_FIELDS.get(normalized_surface) or ()),
    }
    return sorted(probe_fields) or None


def _detail_expansion_can_skip(
    extractability: dict[str, object],
    *,
    surface: str | None,
    requested_fields: list[str] | None,
    readiness_probe: dict[str, object] | None = None,
) -> tuple[bool, str | None]:
    if list(requested_fields or []):
        can_skip = bool(extractability.get("verified")) and bool(
            extractability.get("matched_requested_fields")
        )
        return (
            can_skip,
            "requested_content_already_extractable" if can_skip else None,
        )
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface == ECOMMERCE_DETAIL_SURFACE and bool(
        (readiness_probe or {}).get("is_ready")
    ):
        can_skip = bool(extractability.get("verified"))
        return can_skip, "canonical_detail_already_ready" if can_skip else None
    if not bool(extractability.get("verified")):
        return False, None
    can_skip = "ecommerce" not in normalized_surface
    return can_skip, "requested_content_already_extractable" if can_skip else None


async def _capture_listing_visual_elements(
    page: Any,
    *,
    surface: str | None,
) -> list[dict[str, object]]:
    if "listing" not in str(surface or "").strip().lower():
        return []
    try:
        snapshot = await page.evaluate(
            """(args) => {
                const anchorSelector = String(args?.anchorSelector || '');
                const detailUrlHints = Array.isArray(args?.detailUrlHints) ? args.detailUrlHints : [];
                const utilityUrlTokens = Array.isArray(args?.utilityUrlTokens) ? args.utilityUrlTokens : [];
                const brandSelectors = Array.isArray(args?.brandSelectors) ? args.brandSelectors : [];
                const selectors = [...(Array.isArray(args?.captureSelectors) ? args.captureSelectors : []), ...brandSelectors];
                const structuralAncestorSelectors = Array.isArray(args?.structuralAncestorSelectors) ? args.structuralAncestorSelectors : [];
                const candidateContainerSelectors = Array.isArray(args?.candidateContainerSelectors) ? args.candidateContainerSelectors : [];
                const seenNodes = new Set();
                const rows = [];
                // Extend currencies in LISTING_VISUAL_PRICE_REGEX_PATTERN.
                const priceRegex = new RegExp(String(args?.priceRegexPattern || ''), 'i');
                const isDataImage = (value) => /^data:/i.test(String(value || ''));
                for (const selector of selectors) {
                    for (const node of document.querySelectorAll(selector)) {
                        if (!(node instanceof HTMLElement) || !node.isConnected) {
                            continue;
                        }
                        if (seenNodes.has(node)) {
                            continue;
                        }
                        seenNodes.add(node);
                        const rect = node.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) {
                            continue;
                        }
                        const style = window.getComputedStyle(node);
                        if (
                            style.display === 'none' ||
                            style.visibility === 'hidden' ||
                            style.pointerEvents === 'none'
                        ) {
                            continue;
                        }
                        if (structuralAncestorSelectors.some((selector) => node.closest(selector))) {
                            continue;
                        }
                        const toAbsolute = (value) => {
                            if (!value || /^(#|javascript:)/i.test(value)) return '';
                            try { return new URL(value, location.href).href; } catch { return ''; }
                        };
                        const normalizedText = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
                        const text = normalizedText(node.innerText || node.textContent || '').slice(0, 240);
                        const alt = normalizedText(node.getAttribute('alt') || '').slice(0, 240);
                        const ariaLabel = normalizedText(node.getAttribute('aria-label') || '').slice(0, 240);
                        const title = normalizedText(node.getAttribute('title') || '').slice(0, 240);
                        const src = toAbsolute(node.getAttribute('src') || '');
                        const directHref = toAbsolute(node.getAttribute('href') || '');
                        const closestAnchor = anchorSelector ? node.closest(anchorSelector) : null;
                        let href = directHref || toAbsolute(closestAnchor?.getAttribute('href') || '');
                        if (!href) {
                            const candidateContainerSelector = candidateContainerSelectors.join(',');
                            const container = candidateContainerSelector ? node.closest(candidateContainerSelector) : node;
                            const hintedAnchor = anchorSelector ? Array.from(container?.querySelectorAll?.(anchorSelector) || []).find((candidate) => {
                                const candidateHref = String(candidate?.getAttribute?.('href') || '').toLowerCase();
                                return detailUrlHints.some((hint) => candidateHref.includes(hint));
                            }) : null;
                            href = toAbsolute(hintedAnchor?.getAttribute('href') || '');
                        }
                        const loweredHref = href.toLowerCase();
                        const isDetailHref = detailUrlHints.some((hint) => loweredHref.includes(hint));
                        const isUtilityHref = utilityUrlTokens.some((token) => loweredHref.includes(token));
                        if (isUtilityHref && !isDetailHref) {
                            continue;
                        }
                        if (
                            href &&
                            !isDetailHref &&
                            /^https?:\\/\\/[^/]+\\/?$/i.test(href)
                        ) {
                            continue;
                        }
                        const combinedText = normalizedText([text, alt, ariaLabel, title].filter(Boolean).join(' '));
                        const hasPriceSignal = priceRegex.test(combinedText);
                        const titleLike =
                            combinedText.length >= 6 &&
                            combinedText.length <= 180 &&
                            !hasPriceSignal &&
                            !/^(skip to|sign in|shop now|learn more|view all)$/i.test(combinedText);
                        const largeImage = node.tagName.toLowerCase() === 'img' && Boolean(src) && !isDataImage(src) && rect.width >= 120 && rect.height >= 120;
                        const genericImageLabel = /^(?:product|products?|logo|icon|image)$/i.test(combinedText);
                        const likelyMerchandise = isDetailHref || hasPriceSignal || titleLike || largeImage;
                        if (!likelyMerchandise) {
                            continue;
                        }
                        if (!href && !hasPriceSignal) {
                            continue;
                        }
                        if (genericImageLabel && !isDetailHref && !hasPriceSignal) {
                            continue;
                        }
                        let score = 0;
                        if (isDetailHref) score += 14;
                        if (hasPriceSignal) score += 10;
                        if (titleLike) score += 7;
                        if (largeImage) score += 6;
                        if (href) score += 2;
                        if (node.tagName.toLowerCase() === 'a') score += 1;
                        if (combinedText.length >= 12 && combinedText.length <= 120) score += 2;
                        score -= Math.max(0, Math.floor(Math.max(0, rect.y) / 450));
                        rows.push({
                            tag: node.tagName.toLowerCase(),
                            text,
                            href,
                            src,
                            alt,
                            ariaLabel,
                            title,
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                            score,
                        });
                    }
                }
                rows.sort((left, right) => {
                    const scoreDelta = Number(right.score || 0) - Number(left.score || 0);
                    if (scoreDelta !== 0) return scoreDelta;
                    const yDelta = Number(left.y || 0) - Number(right.y || 0);
                    if (yDelta !== 0) return yDelta;
                    return Number(left.x || 0) - Number(right.x || 0);
                });
                return rows.slice(0, 300);
            }""",
            {
                "detailUrlHints": [
                    hint.lower() for hint in detail_path_hints("ecommerce_detail")
                ],
                "utilityUrlTokens": [
                    token.lower() for token in LISTING_UTILITY_URL_TOKENS
                ],
                "brandSelectors": list(LISTING_BRAND_SELECTORS),
                "anchorSelector": ANCHOR_SELECTOR,
                "captureSelectors": list(LISTING_VISUAL_CAPTURE_SELECTORS),
                "candidateContainerSelectors": list(
                    LISTING_VISUAL_CANDIDATE_CONTAINER_SELECTORS
                ),
                "structuralAncestorSelectors": list(
                    LISTING_CAPTURE_STRUCTURAL_ANCESTOR_SELECTORS
                ),
                "priceRegexPattern": LISTING_VISUAL_PRICE_REGEX_PATTERN,
            },
        )
    except asyncio.CancelledError:
        raise
    except PlaywrightTimeoutError:
        logger.warning("Timed out while capturing listing visual elements")
        return []
    except PlaywrightError as exc:
        logger.debug(
            "Failed to capture listing visual elements status=%s",
            "closed" if is_response_closed_error(exc) else "playwright_error",
            exc_info=True,
        )
        return []
    except Exception:
        logger.exception("Failed to capture listing visual elements unexpectedly")
        return []
    if not isinstance(snapshot, list):
        return []
    rows: list[dict[str, object]] = []
    for item in snapshot[:300]:
        if not isinstance(item, dict):
            continue
        rows.append(dict(item))
    return rows


async def finalize_browser_fetch(
    payload: BrowserFinalizeInput,
    *,
    blocked_html_checker,
    classify_blocked_page_async,
    classify_low_content_reason,
    classify_browser_outcome,
    capture_browser_screenshot,
    emit_browser_event,
    elapsed_ms,
) -> dict[str, object]:
    builder = BrowserAcquisitionResultBuilder(
        payload,
        blocked_html_checker=blocked_html_checker,
        classify_blocked_page_async=classify_blocked_page_async,
        classify_low_content_reason=classify_low_content_reason,
        classify_browser_outcome=classify_browser_outcome,
        capture_browser_screenshot=capture_browser_screenshot,
        emit_browser_event=emit_browser_event,
        elapsed_ms=elapsed_ms,
    )
    return await builder.build()


def append_readiness_probe(
    readiness_probes: list[dict[str, object]],
    *,
    stage: str,
    probe: dict[str, object],
) -> None:
    readiness_probes.append({"stage": stage, **probe})
