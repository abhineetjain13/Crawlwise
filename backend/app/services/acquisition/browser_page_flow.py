from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Any

import httpx

from app.services.acquisition.dom_runtime import get_page_html
from app.services.acquisition.runtime import copy_headers
from app.services.platform_policy import resolve_browser_readiness_policy, resolve_platform_runtime_policy

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
    payload_capture: Any
    html: str
    traversal_result: Any
    rendered_html: str
    phase_timings_ms: dict[str, int]
    started_at: float


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
        status_code = payload.response.status if payload.response is not None else 0
        payload_capture_started_at = time.perf_counter()
        capture_summary = await payload.payload_capture.close(payload.page)
        payload.phase_timings_ms["payload_capture"] = self.elapsed_ms(
            payload_capture_started_at
        )
        blocked_classification = await self.classify_blocked_page_async(
            payload.html,
            status_code,
        )
        blocked = bool(
            blocked_classification.blocked
            or await self.blocked_html_checker(payload.html, status_code)
        )
        html_bytes = len(payload.html.encode("utf-8"))
        challenge_evidence = list(blocked_classification.evidence or [])
        low_content_reason = self.classify_low_content_reason(
            payload.html,
            html_bytes=html_bytes,
        )
        browser_outcome = self.classify_browser_outcome(
            html=payload.html,
            html_bytes=html_bytes,
            blocked=blocked,
            block_classification=blocked_classification,
            traversal_result=payload.traversal_result,
        )
        await self._emit_events(
            browser_outcome=browser_outcome,
            blocked=blocked,
        )
        screenshot_path = await self._capture_screenshot(browser_outcome=browser_outcome)
        payload.phase_timings_ms["total"] = self.elapsed_ms(payload.started_at)
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
            traversal_result=payload.traversal_result,
        )
        listing_visual_elements = await _capture_listing_visual_elements(
            payload.page,
            surface=payload.surface,
        )
        artifacts = build_browser_artifacts(
            screenshot_path=screenshot_path,
            traversal_result=payload.traversal_result,
            html=payload.html,
            rendered_html=payload.rendered_html,
            listing_visual_elements=listing_visual_elements,
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
                    f"Traversal complete - {int(payload.traversal_result.card_count or 0)} records, "
                    f"stop reason: {payload.traversal_result.stop_reason}"
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
        screenshot_path = await self.capture_browser_screenshot(payload.page)
        payload.phase_timings_ms["screenshot_capture"] = self.elapsed_ms(
            screenshot_started_at
        )
        return screenshot_path


def remaining_timeout_factory(deadline: float):
    def _remaining() -> float:
        return max(2.0, deadline - time.perf_counter())

    return _remaining


async def navigate_browser_page_impl(
    page: Any,
    *,
    url: str,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
    readiness_policy: dict[str, object] | None,
    crawler_runtime_settings,
    elapsed_ms,
):
    navigation_wait_until = str(
        (readiness_policy or {}).get("navigation_wait_until") or "domcontentloaded"
    ).strip().lower()
    primary_timeout_cap_ms = (
        int(crawler_runtime_settings.browser_navigation_networkidle_timeout_ms)
        if navigation_wait_until == "networkidle"
        else int(crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms)
    )
    goto_timeout_ms = min(int(timeout_seconds * 1000), primary_timeout_cap_ms)
    fallback_timeout_ms = min(
        int(timeout_seconds * 1000),
        int(crawler_runtime_settings.browser_navigation_min_final_commit_timeout_ms),
    )
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    navigation_strategy = navigation_wait_until
    navigation_started_at = time.perf_counter()
    try:
        response = await page.goto(
            url,
            wait_until=navigation_wait_until,
            timeout=goto_timeout_ms,
        )
    except asyncio.CancelledError:
        raise
    except (PlaywrightTimeoutError, PlaywrightError):
        fallback_strategy = (
            "domcontentloaded" if navigation_wait_until == "networkidle" else "commit"
        )
        navigation_strategy = fallback_strategy
        try:
            response = await page.goto(
                url,
                wait_until=fallback_strategy,
                timeout=(
                    min(
                        int(timeout_seconds * 1000),
                        int(crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms),
                    )
                    if fallback_strategy == "domcontentloaded"
                    else fallback_timeout_ms
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if fallback_strategy != "commit":
                navigation_strategy = "commit"
                try:
                    response = await page.goto(
                        url,
                        wait_until="commit",
                        timeout=fallback_timeout_ms,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as final_exc:
                    phase_timings_ms["navigation"] = elapsed_ms(navigation_started_at)
                    setattr(final_exc, "browser_phase_timings_ms", dict(phase_timings_ms))
                    setattr(final_exc, "browser_navigation_strategy", navigation_strategy)
                    raise
            else:
                phase_timings_ms["navigation"] = elapsed_ms(navigation_started_at)
                setattr(exc, "browser_phase_timings_ms", dict(phase_timings_ms))
                setattr(exc, "browser_navigation_strategy", navigation_strategy)
                raise
    finally:
        phase_timings_ms["navigation"] = elapsed_ms(navigation_started_at)
    return response, navigation_strategy


async def settle_browser_page_impl(
    page: Any,
    *,
    url: str,
    surface: str,
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

    async def _cached_probe(*, refresh_html: bool = False) -> dict[str, object]:
        nonlocal cached_html
        if refresh_html or cached_html is None:
            cached_html = await get_page_html_impl(page)
        return await probe_browser_readiness(
            page,
            url=url,
            surface=surface,
            listing_override=readiness_override,
            html=cached_html,
        )

    current_probe = await _cached_probe(refresh_html=True)
    append_readiness_probe(
        readiness_probes,
        stage="after_navigation",
        probe=current_probe,
    )
    wait_ms = min(
        int(timeout_seconds * 1000),
        int(crawler_runtime_settings.browser_navigation_optimistic_wait_ms),
    )
    if wait_ms > 0 and not current_probe["is_ready"]:
        optimistic_wait_started_at = time.perf_counter()
        await page.wait_for_timeout(wait_ms)
        phase_timings_ms["optimistic_wait"] = elapsed_ms(optimistic_wait_started_at)
        current_probe = await _cached_probe(refresh_html=True)
        append_readiness_probe(
            readiness_probes,
            stage="after_optimistic_wait",
            probe=current_probe,
        )
    else:
        phase_timings_ms["optimistic_wait"] = 0

    networkidle_timed_out = False
    networkidle_skip_reason = None
    explicit_require_networkidle = bool(readiness_policy.get("require_networkidle"))
    implicit_networkidle_attempt = bool(
        not current_probe["is_ready"]
        and not explicit_require_networkidle
        and not current_probe.get("structured_data_present")
    )
    if not current_probe["is_ready"] and (
        explicit_require_networkidle or implicit_networkidle_attempt
    ):
        networkidle_wait_started_at = time.perf_counter()
        networkidle_timeout_cap_ms = (
            int(crawler_runtime_settings.browser_navigation_networkidle_timeout_ms)
            if explicit_require_networkidle
            else int(crawler_runtime_settings.browser_spa_implicit_networkidle_timeout_ms)
        )
        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=min(
                    int(timeout_seconds * 1000),
                    networkidle_timeout_cap_ms,
                ),
            )
        except Exception:
            networkidle_timed_out = True
        phase_timings_ms["networkidle_wait"] = elapsed_ms(networkidle_wait_started_at)
        current_probe = await _cached_probe(refresh_html=True)
        append_readiness_probe(
            readiness_probes,
            stage="after_networkidle",
            probe=current_probe,
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
            readiness_probes,
            stage="after_platform_readiness",
            probe=current_probe,
        )
    else:
        phase_timings_ms["readiness_wait"] = 0
        readiness_diagnostics = {
            "status": "skipped",
            "reason": (
                "fast_path_ready" if current_probe["is_ready"] else "no_platform_override"
            ),
        }

    expansion_started_at = time.perf_counter()
    expansion_diagnostics = await expand_detail_content_if_needed(
        page,
        surface=surface,
        readiness_probe=current_probe,
    )
    phase_timings_ms["expansion"] = elapsed_ms(expansion_started_at)
    if expansion_diagnostics.get("clicked_count", 0):
        current_probe = await _cached_probe(refresh_html=True)
        append_readiness_probe(
            readiness_probes,
            stage="after_detail_expansion",
            probe=current_probe,
        )
    return (
        current_probe,
        readiness_probes,
        networkidle_timed_out,
        networkidle_skip_reason,
        readiness_diagnostics,
        expansion_diagnostics,
    )


async def serialize_browser_page_content_impl(
    page: Any,
    *,
    surface: str | None,
    traversal_mode: str | None,
    traversal_active: bool,
    timeout_seconds: float,
    max_pages: int,
    max_scrolls: int,
    phase_timings_ms: dict[str, int],
    execute_listing_traversal,
    elapsed_ms,
    on_event=None,
):
    traversal_result = None
    rendered_html = ""
    traversal_started_at = time.perf_counter()
    if traversal_active:
        traversal_result = await execute_listing_traversal(
            page,
            surface=str(surface or ""),
            traversal_mode=str(traversal_mode or ""),
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            timeout_seconds=timeout_seconds,
            on_event=on_event,
        )
        rendered_html = await get_page_html(page)
        html = traversal_result.compose_html()
    else:
        html = ""
    phase_timings_ms["traversal"] = elapsed_ms(traversal_started_at)

    serialization_started_at = time.perf_counter()
    if traversal_result is None:
        html = await get_page_html(page)
        rendered_html = html
    phase_timings_ms["content_serialization"] = elapsed_ms(serialization_started_at)
    return html, traversal_result, rendered_html


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
        "closed_network_payloads": capture_summary.closed_network_payloads,
        "skipped_oversized_network_payloads": capture_summary.skipped_oversized_network_payloads,
        "dropped_network_payload_events": capture_summary.dropped_payload_events,
        "listing_readiness": readiness_diagnostics,
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
    listing_visual_elements: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    artifacts: dict[str, object] = {}
    if screenshot_path:
        artifacts["browser_screenshot_path"] = screenshot_path
    if listing_visual_elements:
        artifacts["listing_visual_elements"] = listing_visual_elements
    if traversal_result is not None and traversal_result.activated:
        artifacts["traversal_composed_html"] = html
        artifacts["full_rendered_html"] = rendered_html
    return artifacts


async def _capture_listing_visual_elements(
    page: Any,
    *,
    surface: str | None,
) -> list[dict[str, object]]:
    if "listing" not in str(surface or "").strip().lower():
        return []
    try:
        snapshot = await page.evaluate(
            """() => {
                const selectors = [
                    'a[href]',
                    'img[src]',
                    'h1',
                    'h2',
                    'h3',
                    '[class*="price" i]',
                    '[data-testid*="price" i]',
                    '[aria-label*="price" i]',
                    '[class*="title" i]',
                ];
                const seen = new Set();
                const rows = [];
                for (const selector of selectors) {
                    for (const node of document.querySelectorAll(selector)) {
                        if (!(node instanceof HTMLElement) || !node.isConnected) {
                            continue;
                        }
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
                        const key = [
                            node.tagName,
                            node.getAttribute('href') || '',
                            node.getAttribute('src') || '',
                            Math.round(rect.x),
                            Math.round(rect.y),
                            Math.round(rect.width),
                            Math.round(rect.height),
                        ].join('|');
                        if (seen.has(key)) {
                            continue;
                        }
                        seen.add(key);
                        rows.push({
                            tag: node.tagName.toLowerCase(),
                            text: (node.innerText || node.textContent || '').trim().slice(0, 240),
                            href: node.getAttribute('href') || '',
                            src: node.getAttribute('src') || '',
                            alt: node.getAttribute('alt') || '',
                            ariaLabel: node.getAttribute('aria-label') || '',
                            title: node.getAttribute('title') || '',
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        });
                        if (rows.length >= 300) {
                            return rows;
                        }
                    }
                }
                return rows;
            }"""
        )
    except Exception:
        logger.debug("Failed to capture listing visual elements", exc_info=True)
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
) -> object:
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
