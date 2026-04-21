from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
import time
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from app.services.acquisition.browser_recovery import (
    capture_rendered_listing_cards,
    recover_browser_challenge,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.acquisition.dom_runtime import get_page_html
from app.services.field_policy import normalize_requested_field
from app.services.field_value_dom import extract_heading_sections
from app.services.acquisition.runtime import classify_blocked_page_async, copy_headers
from app.services.platform_policy import resolve_browser_readiness_policy, resolve_platform_runtime_policy

logger = logging.getLogger(__name__)
_ACCESSIBILITY_SNAPSHOT_TIMEOUT_SECONDS = 0.5
_MARKDOWN_ROOT_SELECTORS = (
    "main",
    "[role='main']",
    "article",
    ".product-detail-view__main-content",
    ".product-detail-info",
    "[data-qa-id='product-detail-info']",
)
_MARKDOWN_NOISE_SELECTORS = (
    "nav",
    "footer",
    "header",
    "script",
    "style",
    "noscript",
    "svg",
    "template",
    "iframe",
    "dialog",
    "[role='dialog']",
    "[aria-modal='true']",
    "[hidden]",
    "[aria-hidden='true']",
    "[inert]",
    "[role='navigation']",
    "[role='banner']",
    "[role='contentinfo']",
)
_MARKDOWN_NOISE_TOKENS = ("cookie", "consent", "modal", "popup", "banner")
_DETAIL_MARKDOWN_SECTION_NOISE_TOKENS = (
    "affirm",
    "amex",
    "answer",
    "answers",
    "ask a question",
    "filter reviews",
    "helpful",
    "klarna",
    "mastercard",
    "overall rating",
    "payment",
    "paypal",
    "q&a",
    "question",
    "questions",
    "rating snapshot",
    "report this answer",
    "report this review",
    "review",
    "reviews",
    "secure payment",
    "verified reviewer",
    "visa",
    "what are other people saying",
)
_DETAIL_MARKDOWN_LINE_NOISE = (
    "add to cart",
    "home",
    "skip the navigation",
)


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
    page_markdown: str
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
            listing_recovery_diagnostics=payload.listing_recovery_diagnostics,
            traversal_result=payload.traversal_result,
        )
        rendered_listing_cards = await capture_rendered_listing_cards(
            payload.page,
            surface=payload.surface,
            limit=int(crawler_runtime_settings.rendered_listing_card_capture_limit),
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
            rendered_listing_cards=rendered_listing_cards,
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
            "page_markdown": payload.page_markdown,
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
    response = await recover_browser_challenge(
        page,
        url=url,
        response=response,
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
            requested_fields=requested_fields,
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
    listing_recovery_mode: str | None,
    traversal_active: bool,
    timeout_seconds: float,
    max_pages: int,
    max_scrolls: int,
    phase_timings_ms: dict[str, int],
    execute_listing_traversal,
    recover_listing_page_content,
    elapsed_ms,
    on_event=None,
):
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
        listing_recovery_diagnostics["requested_mode"] = normalized_listing_recovery_mode
    if traversal_active and normalized_listing_recovery_mode == "thin_listing":
        listing_recovery_diagnostics = await recover_listing_page_content(
            page,
            on_event=on_event,
        )
        listing_recovery_diagnostics["requested_mode"] = normalized_listing_recovery_mode
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
            timeout_seconds=timeout_seconds,
            on_event=on_event,
        )
        rendered_html = await get_page_html(page)
        traversal_html = traversal_result.compose_html()
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
        html = await get_page_html(page)
        rendered_html = html
    phase_timings_ms["content_serialization"] = elapsed_ms(serialization_started_at)
    markdown_started_at = time.perf_counter()
    page_markdown = await _generate_page_markdown(
        page,
        html=rendered_html or html,
        surface=surface,
    )
    phase_timings_ms["page_markdown"] = elapsed_ms(markdown_started_at)
    return html, traversal_result, rendered_html, listing_recovery_diagnostics, page_markdown


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
        "listing_recovery": listing_recovery_diagnostics,
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
    rendered_listing_cards: list[dict[str, object]] | None = None,
    listing_visual_elements: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    artifacts: dict[str, object] = {}
    if screenshot_path:
        artifacts["browser_screenshot_path"] = screenshot_path
    if rendered_listing_cards:
        artifacts["rendered_listing_cards"] = rendered_listing_cards
    if listing_visual_elements:
        artifacts["listing_visual_elements"] = listing_visual_elements
    if traversal_result is not None and traversal_result.activated:
        artifacts["traversal_composed_html"] = traversal_result.compose_html()
        artifacts["full_rendered_html"] = rendered_html
    return artifacts

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
    if progress_events > 0 and (
        card_count >= max(1, int(listing_min_items))
        or traversal_signal_count >= max(2, rendered_signal_count)
    ):
        return traversal_html
    if rendered_signal_count > traversal_signal_count:
        return rendered_html
    if card_count >= max(1, int(listing_min_items)):
        return rendered_html
    if stop_reason.endswith(("_not_found", "_no_progress", "_click_failed", "_blocked")):
        return rendered_html
    return traversal_html

async def _generate_page_markdown(
    page: Any,
    *,
    html: str,
    surface: str | None = None,
) -> str:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    for node in list(soup.find_all(True)):
        if not isinstance(getattr(node, "attrs", None), dict):
            node.attrs = {}
    for selector in _MARKDOWN_NOISE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()
    for node in list(soup.find_all(True)):
        attrs = getattr(node, "attrs", None)
        if not isinstance(attrs, dict):
            continue
        attr_text = " ".join(
            [
                " ".join(str(item) for item in attrs.get("class", []) if item),
                str(attrs.get("id") or ""),
                str(attrs.get("data-testid") or ""),
                str(attrs.get("data-qa-id") or ""),
                str(attrs.get("data-qa-action") or ""),
            ]
        ).lower()
        if any(token in attr_text for token in _MARKDOWN_NOISE_TOKENS):
            node.decompose()
    if "detail" in str(surface or "").strip().lower():
        _prune_detail_markdown_noise(soup)

    content_root = _select_markdown_root(soup)
    body_or_soup = soup.body if soup.body is not None else soup
    markdown, link_lines = _serialize_markdown_root(content_root)
    if content_root is not body_or_soup:
        full_markdown, full_link_lines = _serialize_markdown_root(body_or_soup)
        if (
            len(full_markdown) >= len(markdown) + 120
            or len(full_link_lines) > len(link_lines)
        ):
            markdown, link_lines = full_markdown, full_link_lines
    if "detail" in str(surface or "").strip().lower():
        markdown, link_lines = _filter_detail_markdown_payload(markdown, link_lines)
    if link_lines:
        markdown = (
            f"{markdown}\n\nVisible links:\n" + "\n".join(link_lines[:120])
            if markdown
            else "Visible links:\n" + "\n".join(link_lines[:120])
        )

    accessibility = getattr(page, "accessibility", None)
    snapshot_fn = getattr(accessibility, "snapshot", None)
    if snapshot_fn is not None:
        try:
            snapshot = await asyncio.wait_for(
                snapshot_fn(),
                timeout=_ACCESSIBILITY_SNAPSHOT_TIMEOUT_SECONDS,
            )
        except Exception:
            snapshot = None
        aria_text = _serialize_accessibility_snapshot(snapshot)
        if aria_text:
            markdown = (
                f"{markdown}\n\n=== SEMANTIC ACCESSIBILITY SNAPSHOT ===\n{aria_text}"
                if markdown
                else f"=== SEMANTIC ACCESSIBILITY SNAPSHOT ===\n{aria_text}"
            )
    return markdown.strip()

def _serialize_markdown_root(root: BeautifulSoup | Any) -> tuple[str, list[str]]:
    text = root.get_text("\n", strip=True)
    lines = [
        " ".join(str(line or "").split()).strip()
        for line in text.splitlines()
        if str(line or "").strip()
    ]
    link_lines: list[str] = []
    for anchor in root.select("a[href]"):
        attrs = getattr(anchor, "attrs", None)
        if not isinstance(attrs, dict):
            continue
        href = " ".join(str(attrs.get("href") or "").split()).strip()
        label = " ".join(anchor.get_text(" ", strip=True).split()).strip()
        if href and label and len(label) >= 3:
            link_lines.append(f"- {label} -> {href}")
    return "\n".join(lines), link_lines

def _node_markdown_probe(node: Tag) -> str:
    attrs = getattr(node, "attrs", None)
    attr_text = ""
    if isinstance(attrs, dict):
        attr_text = " ".join(
            [
                " ".join(str(item) for item in attrs.get("class", []) if item),
                str(attrs.get("id") or ""),
                str(attrs.get("data-testid") or ""),
                str(attrs.get("data-qa-id") or ""),
                str(attrs.get("data-qa-action") or ""),
                str(attrs.get("aria-label") or ""),
            ]
        )
    headings: list[str] = []
    for candidate in node.select("h1, h2, h3, h4, summary, button, [role='tab']")[:4]:
        headings.append(candidate.get_text(" ", strip=True))
    return " ".join([attr_text, *headings]).lower()

def _prune_detail_markdown_noise(soup: BeautifulSoup) -> None:
    for node in list(soup.find_all(["section", "div", "aside", "article", "details"])):
        if not isinstance(node, Tag):
            continue
        if node.name in {"body", "main"}:
            continue
        if not _detail_markdown_probe_is_noise(node):
            continue
        node.decompose()


def _detail_markdown_line_is_noise(line: str) -> bool:
    compact = " ".join(str(line or "").split()).strip()
    lowered = compact.lower()
    if not lowered:
        return True
    if lowered == ">":
        return True
    if any(token in lowered for token in _DETAIL_MARKDOWN_LINE_NOISE):
        return True
    if compact.isupper() and len(compact) <= 24:
        return True
    return False


def _detail_markdown_probe_is_noise(node: Tag) -> bool:
    attr_probe = _node_markdown_attr_text(node)
    heading_probe = _node_markdown_heading_text(node)
    if not attr_probe and not heading_probe:
        return False
    attr_hits = {
        _detail_markdown_token_key(token)
        for token in _DETAIL_MARKDOWN_SECTION_NOISE_TOKENS
        if _detail_markdown_contains_token(attr_probe, token)
    }
    heading_hits = {
        _detail_markdown_token_key(token)
        for token in _DETAIL_MARKDOWN_SECTION_NOISE_TOKENS
        if _detail_markdown_contains_token(heading_probe, token)
    }
    if any(" " in token or "&" in token for token in attr_hits | heading_hits):
        return True
    return bool(attr_hits and heading_hits)


def _detail_markdown_contains_token(text: str, token: str) -> bool:
    normalized_token = str(token or "").strip().lower()
    if not normalized_token:
        return False
    pattern = r"\b" + re.escape(normalized_token).replace(r"\ ", r"[\s_-]+") + r"\b"
    return bool(re.search(pattern, text))


def _detail_markdown_token_key(token: str) -> str:
    normalized_token = str(token or "").strip().lower()
    if normalized_token.endswith("s") and " " not in normalized_token:
        return normalized_token[:-1]
    return normalized_token


def _listing_html_detail_anchor_count(html: str) -> int:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    count = 0
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip().lower()
        if any(marker in href for marker in ("/products/", "/product/", "/p/", "/item/", "/jobs/", "/job/")):
            count += 1
    return count


def _node_markdown_attr_text(node: Tag) -> str:
    attrs = getattr(node, "attrs", None)
    if not isinstance(attrs, dict):
        return ""
    return " ".join(
        [
            " ".join(str(item) for item in attrs.get("class", []) if item),
            str(attrs.get("id") or ""),
            str(attrs.get("data-testid") or ""),
            str(attrs.get("data-qa-id") or ""),
            str(attrs.get("data-qa-action") or ""),
            str(attrs.get("aria-label") or ""),
        ]
    ).lower()


def _node_markdown_heading_text(node: Tag) -> str:
    headings: list[str] = []
    for candidate in node.select("h1, h2, h3, h4, summary, button, [role='tab']")[:4]:
        headings.append(candidate.get_text(" ", strip=True))
    return " ".join(headings).lower()


def _filter_detail_markdown_payload(
    markdown: str,
    link_lines: list[str],
) -> tuple[str, list[str]]:
    filtered_lines = [
        line
        for line in str(markdown or "").splitlines()
        if not _detail_markdown_line_is_noise(line)
    ]
    filtered_links = [
        line
        for line in link_lines
        if not any(
            token in line.lower() for token in _DETAIL_MARKDOWN_SECTION_NOISE_TOKENS
        )
    ]
    return "\n".join(filtered_lines), filtered_links

def _select_markdown_root(soup: BeautifulSoup) -> BeautifulSoup | Any:
    body = soup.body
    body_text = ""
    if body is not None:
        body_text = " ".join(body.get_text(" ", strip=True).split()).strip()
    for selector in _MARKDOWN_ROOT_SELECTORS:
        candidate = soup.select_one(selector)
        if candidate is None:
            continue
        text = " ".join(candidate.get_text(" ", strip=True).split()).strip()
        if len(text) >= 80:
            if body is not None and candidate is not body and body_text:
                if len(text) < max(80, int(len(body_text) * 0.4)):
                    continue
            return candidate
    return body if body is not None else soup

def _serialize_accessibility_snapshot(
    node: dict[str, object] | None,
    *,
    depth: int = 0,
) -> str:
    if not isinstance(node, dict) or depth > 8:
        return ""
    lines: list[str] = []
    name = " ".join(str(node.get("name") or "").split()).strip()
    lowered_name = name.lower()
    if any(token in lowered_name for token in _DETAIL_MARKDOWN_SECTION_NOISE_TOKENS):
        return ""
    if name:
        role = " ".join(str(node.get("role") or "element").split()).strip() or "element"
        lines.append(f"{'  ' * depth}[{role}] {name}")
    raw_children = node.get("children")
    children = raw_children if isinstance(raw_children, list) else []
    for child in children:
        if isinstance(child, dict):
            child_text = _serialize_accessibility_snapshot(child, depth=depth + 1)
            if child_text:
                lines.append(child_text)
    return "\n".join(lines)

def _normalize_listing_recovery_mode(value: object) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized.endswith("_retry"):
        normalized = normalized[: -len("_retry")]
    return normalized or None


def _detail_expansion_extractability(
    *,
    html: str,
    requested_fields: list[str] | None,
) -> dict[str, object]:
    if not str(html or "").strip():
        return {
            "verified": False,
            "section_count": 0,
            "matched_requested_fields": [],
            "section_fields": [],
        }
    soup = BeautifulSoup(str(html or ""), "html.parser")
    section_fields = {
        normalized
        for label in extract_heading_sections(soup).keys()
        if (normalized := normalize_requested_field(label))
    }
    requested = [
        normalized
        for value in list(requested_fields or [])
        if (normalized := normalize_requested_field(value))
    ]
    matched_requested_fields = [
        field_name for field_name in requested if field_name in section_fields
    ]
    return {
        "verified": bool(matched_requested_fields or (not requested and section_fields)),
        "section_count": len(section_fields),
        "matched_requested_fields": matched_requested_fields,
        "section_fields": sorted(section_fields),
    }


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
