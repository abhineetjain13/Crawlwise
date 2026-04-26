from __future__ import annotations

import secrets
import time
from contextlib import suppress
from typing import Any, Callable

from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import (
    ANCHOR_SELECTOR,
    LISTING_CAPTURE_STRUCTURAL_ANCESTOR_SELECTORS,
)
from app.services.extract.listing_card_fragments import listing_capture_selectors


async def recover_browser_challenge(
    page: Any,
    *,
    url: str,
    response: Any,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
    challenge_wait_max_seconds: float,
    challenge_poll_interval_ms: int,
    navigation_timeout_ms: int,
    elapsed_ms: Callable[[float], int],
    classify_blocked_page,
    get_page_html,
):
    phase_timings_ms.setdefault("challenge_wait", 0)
    phase_timings_ms.setdefault("challenge_retry", 0)
    max_wait_seconds = max(0.0, float(challenge_wait_max_seconds or 0))
    if max_wait_seconds <= 0:
        return response
    status_code = int(getattr(response, "status", 0) or 0)
    initial_html = await get_page_html(page)
    classification = await classify_blocked_page(initial_html, status_code)
    if not classification.blocked:
        return response

    providers = {
        str(provider).strip().lower()
        for provider in list(classification.provider_hits or [])
        if str(provider).strip()
    }
    wait_started_at = time.perf_counter()
    poll_ms = max(100, int(challenge_poll_interval_ms))
    deadline = wait_started_at + max_wait_seconds
    while time.perf_counter() < deadline:
        await _emit_challenge_activity(page)
        if "akamai" in providers and await _page_has_cookie(page, url=url, name="_abck"):
            html = await get_page_html(page)
            classification = await classify_blocked_page(
                html,
                _recovered_html_status_code(status_code),
            )
            if not classification.blocked:
                phase_timings_ms["challenge_wait"] = elapsed_ms(wait_started_at)
                return _response_for_recovered_page(response, status_code)
        remaining_ms = max(0, int((deadline - time.perf_counter()) * 1000))
        if remaining_ms <= 0:
            break
        await page.wait_for_timeout(min(poll_ms, remaining_ms))
        html = await get_page_html(page)
        classification = await classify_blocked_page(
            html,
            _recovered_html_status_code(status_code),
        )
        if not classification.blocked:
            phase_timings_ms["challenge_wait"] = elapsed_ms(wait_started_at)
            return _response_for_recovered_page(response, status_code)
    phase_timings_ms["challenge_wait"] = elapsed_ms(wait_started_at)

    retry_started_at = time.perf_counter()
    try:
        retried_response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=min(int(timeout_seconds * 1000), int(navigation_timeout_ms)),
        )
    except Exception:
        phase_timings_ms["challenge_retry"] = elapsed_ms(retry_started_at)
        return response
    phase_timings_ms["challenge_retry"] = elapsed_ms(retry_started_at)
    retry_status_code = int(getattr(retried_response, "status", status_code) or status_code)
    try:
        retry_html = await get_page_html(page)
        retry_classification = await classify_blocked_page(
            retry_html,
            _recovered_html_status_code(retry_status_code),
        )
    except Exception:
        return response
    if retry_classification.blocked:
        return response
    return _response_for_recovered_page(
        retried_response if retried_response is not None else response,
        retry_status_code,
        navigation_strategy="domcontentloaded",
    )


def _recovered_html_status_code(status_code: int) -> int:
    return 200 if int(status_code or 0) in {403, 429} else int(status_code or 0)


def _response_for_recovered_page(
    response: Any,
    status_code: int,
    *,
    navigation_strategy: str | None = None,
) -> Any:
    if int(status_code or 0) not in {403, 429}:
        if navigation_strategy is not None:
            with suppress(Exception):
                setattr(response, "browser_navigation_strategy", navigation_strategy)
        return response
    with suppress(Exception):
        setattr(response, "browser_recovered_status", 200)
    if navigation_strategy is not None:
        with suppress(Exception):
            setattr(response, "browser_navigation_strategy", navigation_strategy)
    return response


async def _emit_challenge_activity(page: Any) -> None:
    mouse = getattr(page, "mouse", None)
    if mouse is None:
        return
    try:
        viewport = await page.evaluate(
            """() => ({
                width: Math.max(
                    window.innerWidth || 0,
                    document.documentElement?.clientWidth || 0,
                    document.body?.clientWidth || 0,
                ),
                height: Math.max(
                    window.innerHeight || 0,
                    document.documentElement?.clientHeight || 0,
                    document.body?.clientHeight || 0,
                ),
            })"""
        )
    except Exception:
        return
    if not isinstance(viewport, dict):
        return
    width = max(1, int(viewport.get("width") or 0))
    height = max(1, int(viewport.get("height") or 0))
    steps = max(1, int(crawler_runtime_settings.challenge_activity_mouse_steps or 1))
    edge_padding = max(
        0, int(crawler_runtime_settings.challenge_activity_edge_padding_px or 0)
    )
    jitter_moves = max(
        1, int(crawler_runtime_settings.challenge_activity_jitter_moves or 1)
    )
    jitter_delta_px = max(
        1, int(crawler_runtime_settings.challenge_activity_jitter_delta_px or 1)
    )
    pause_min_ms = max(
        0, int(crawler_runtime_settings.challenge_activity_pause_min_ms or 0)
    )
    pause_jitter_ms = max(
        0, int(crawler_runtime_settings.challenge_activity_pause_jitter_ms or 0)
    )
    scroll_px = max(0, int(crawler_runtime_settings.challenge_activity_scroll_px or 0))
    move = getattr(mouse, "move", None)
    if callable(move):
        try:
            start_x_offset = secrets.randbelow(400) - 200
            start_y_offset = secrets.randbelow(300) - 150
            current_x = _clamp_mouse_coordinate(
                (width // 2) + start_x_offset,
                width,
                edge_padding,
            )
            current_y = _clamp_mouse_coordinate(
                (height // 2) + start_y_offset,
                height,
                edge_padding,
            )
            await move(current_x, current_y)
            for _ in range(jitter_moves):
                target_x = _clamp_mouse_coordinate(
                    current_x + secrets.randbelow(jitter_delta_px * 2) - jitter_delta_px,
                    width,
                    edge_padding,
                )
                target_y = _clamp_mouse_coordinate(
                    current_y + secrets.randbelow(jitter_delta_px * 2) - jitter_delta_px,
                    height,
                    edge_padding,
                )
                for step_index in range(1, steps + 1):
                    progress = step_index / steps
                    noise_x = secrets.randbelow(7) - 3
                    noise_y = secrets.randbelow(7) - 3
                    inter_x = _clamp_mouse_coordinate(
                        round(current_x + (target_x - current_x) * progress + noise_x),
                        width,
                        edge_padding,
                    )
                    inter_y = _clamp_mouse_coordinate(
                        round(current_y + (target_y - current_y) * progress + noise_y),
                        height,
                        edge_padding,
                    )
                    await move(inter_x, inter_y)
                    await page.wait_for_timeout(secrets.randbelow(15) + 5)
                current_x = target_x
                current_y = target_y
                pause_ms = pause_min_ms
                if pause_jitter_ms:
                    pause_ms += secrets.randbelow(pause_jitter_ms)
                if pause_ms > 0:
                    await page.wait_for_timeout(pause_ms)
        except Exception:
            return
    wheel = getattr(mouse, "wheel", None)
    if callable(wheel) and scroll_px:
        try:
            await wheel(0, scroll_px)
        except Exception:
            return


def _clamp_mouse_coordinate(value: int, limit: int, padding: int) -> int:
    upper_bound = max(0, int(limit) - 1)
    effective_padding = min(max(0, int(padding)), upper_bound)
    lower_bound = min(upper_bound, effective_padding)
    max_value = max(lower_bound, upper_bound - effective_padding)
    return max(lower_bound, min(int(value), max_value))


async def capture_rendered_listing_fragments(
    page: Any,
    *,
    surface: str | None,
    limit: int,
) -> list[str]:
    if "listing" not in str(surface or "").strip().lower():
        return []
    try:
        snapshot = await page.evaluate(
            """(args) => {
                const limit = Number(args?.limit || 0);
                const anchorSelector = String(args?.anchorSelector || '');
                const selectors = Array.isArray(args?.selectors) ? args.selectors : [];
                const seenFragments = new Set();
                const fragments = [];
                const structuralAncestorSelectors = Array.isArray(args?.structuralAncestorSelectors) ? args.structuralAncestorSelectors : [];
                const textOf = (node) =>
                    String(node?.innerText || node?.textContent || '')
                        .replace(/\\s+/g, ' ')
                        .trim();
                for (const selector of selectors) {
                    for (const card of document.querySelectorAll(selector)) {
                        if (!(card instanceof HTMLElement) || !card.isConnected) continue;
                        const rect = card.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) continue;
                        const style = window.getComputedStyle(card);
                        if (style.display === 'none' || style.visibility === 'hidden') continue;
                        if (structuralAncestorSelectors.some((ancestor) => card.closest(ancestor))) continue;
                        const anchors = !anchorSelector
                            ? []
                            : (card.matches(anchorSelector) ? [card] : Array.from(card.querySelectorAll(anchorSelector)));
                        if (!anchors.length) continue;
                        const anchorCount = anchors.length;
                        if (anchorCount > 12) continue;
                        const text = textOf(card);
                        if (text.length < 12 || text.length > 4000) continue;
                        const fragment = String(card.outerHTML || '').trim();
                        if (!fragment || seenFragments.has(fragment)) continue;
                        seenFragments.add(fragment);
                        fragments.push(fragment);
                        if (fragments.length >= limit) return fragments;
                    }
                }
                return fragments;
            }""",
            {
                "limit": int(limit),
                "anchorSelector": ANCHOR_SELECTOR,
                "selectors": listing_capture_selectors(str(surface or "")),
                "structuralAncestorSelectors": list(
                    LISTING_CAPTURE_STRUCTURAL_ANCESTOR_SELECTORS
                ),
            },
        )
    except Exception:
        return []
    if not isinstance(snapshot, list):
        return []
    return [
        str(item).strip()
        for item in snapshot[: int(limit)]
        if str(item or "").strip()
    ]
async def _page_has_cookie(page: Any, *, url: str, name: str) -> bool:
    context = getattr(page, "context", None)
    cookies_fn = getattr(context, "cookies", None)
    if cookies_fn is None:
        return False
    try:
        cookies = await cookies_fn([url])
    except TypeError:
        try:
            cookies = await cookies_fn()
        except Exception:
            return False
    except Exception:
        return False
    for cookie in list(cookies or []):
        if str(cookie.get("name") or "").strip() == str(name).strip():
            return True
    return False
