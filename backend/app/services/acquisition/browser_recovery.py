from __future__ import annotations

import time
from typing import Any, Callable

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
        if "akamai" in providers and await _page_has_cookie(page, url=url, name="_abck"):
            html = await get_page_html(page)
            classification = await classify_blocked_page(html, status_code)
            if not classification.blocked:
                phase_timings_ms["challenge_wait"] = elapsed_ms(wait_started_at)
                return response
        remaining_ms = max(0, int((deadline - time.perf_counter()) * 1000))
        if remaining_ms <= 0:
            break
        await page.wait_for_timeout(min(poll_ms, remaining_ms))
        html = await get_page_html(page)
        classification = await classify_blocked_page(html, status_code)
        if not classification.blocked:
            phase_timings_ms["challenge_wait"] = elapsed_ms(wait_started_at)
            return response
    phase_timings_ms["challenge_wait"] = elapsed_ms(wait_started_at)

    retry_started_at = time.perf_counter()
    try:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=min(int(timeout_seconds * 1000), int(navigation_timeout_ms)),
        )
    except Exception:
        phase_timings_ms["challenge_retry"] = elapsed_ms(retry_started_at)
        return response
    phase_timings_ms["challenge_retry"] = elapsed_ms(retry_started_at)
    return response


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
                const selectors = Array.isArray(args?.selectors) ? args.selectors : [];
                const seenFragments = new Set();
                const fragments = [];
                const structuralAncestorSelectors = [
                    'header',
                    'footer',
                    'nav',
                    '[role="navigation"]',
                    '[role="banner"]',
                    '[role="contentinfo"]',
                    'dialog',
                    '[role="dialog"]',
                ];
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
                        const anchors = card.matches('a[href]') ? [card] : Array.from(card.querySelectorAll('a[href]'));
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
                "selectors": listing_capture_selectors(str(surface or "")),
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
