from __future__ import annotations

import time
from typing import Any, Callable


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


async def capture_rendered_listing_cards(
    page: Any,
    *,
    surface: str | None,
    limit: int,
) -> list[dict[str, object]]:
    if "listing" not in str(surface or "").strip().lower():
        return []
    try:
        snapshot = await page.evaluate(
            """(limit) => {
                const cardSelectors = ['article','[data-testid*="product" i]','[class*="product-card" i]','[class*="product-tile" i]','[class*="plp-card" i]','[class*="catalog-item" i]','[class*="grid-item" i]','li'];
                const priceRegex = /(?:₹|Rs\\.?|INR|\\$|€|£)\\s?[\\d,.]+/i;
                const toAbsolute = (href) => {
                    if (!href || /^(#|javascript:)/i.test(href)) return '';
                    try { return new URL(href, location.href).href; } catch { return ''; }
                };
                const textOf = (node) => ((node?.innerText || node?.textContent || '').replace(/\\s+/g, ' ').trim());
                const seenUrls = new Set();
                const rows = [];
                for (const selector of cardSelectors) {
                    for (const card of document.querySelectorAll(selector)) {
                        if (!(card instanceof HTMLElement) || !card.isConnected) continue;
                        const rect = card.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) continue;
                        const style = window.getComputedStyle(card);
                        if (style.display === 'none' || style.visibility === 'hidden') continue;
                        const anchors = Array.from(card.querySelectorAll('a[href]'));
                        const primaryAnchor = anchors.find((anchor) => {
                            const href = String(anchor.getAttribute('href') || '');
                            return href && !/^(#|javascript:)/i.test(href);
                        }) || (card.matches('a[href]') ? card : null);
                        const url = primaryAnchor ? toAbsolute(primaryAnchor.getAttribute('href')) : '';
                        if (!url || seenUrls.has(url)) continue;
                        const titleNode = card.querySelector('h1, h2, h3, h4, [itemprop="name"], [data-testid*="title" i], [data-testid*="name" i], [class*="title" i], [class*="name" i]');
                        const brandNode = card.querySelector('[data-testid*="brand" i], [class*="brand" i]');
                        const priceNode = card.querySelector('[itemprop="price"], [data-price], [class*="price" i], [aria-label*="price" i]');
                        const imageNode = card.querySelector('img[src], source[srcset]');
                        const title = textOf(titleNode) || textOf(primaryAnchor) || String(imageNode?.getAttribute?.('alt') || '').trim();
                        if (!title || title.length < 3) continue;
                        const rawPrice = String(priceNode?.getAttribute?.('content') || priceNode?.getAttribute?.('data-price') || priceNode?.getAttribute?.('aria-label') || textOf(priceNode) || '').trim();
                        const price = (rawPrice.match(priceRegex)?.[0] || rawPrice).trim();
                        const imageUrl = (() => {
                            if (imageNode instanceof HTMLImageElement) return toAbsolute(imageNode.currentSrc || imageNode.src || imageNode.getAttribute('src') || '');
                            const srcset = String(imageNode?.getAttribute?.('srcset') || '');
                            return toAbsolute(srcset.split(',')[0]?.trim()?.split(' ')[0] || '');
                        })();
                        rows.push({ title, url, price, image_url: imageUrl, brand: textOf(brandNode) });
                        seenUrls.add(url);
                        if (rows.length >= limit) return rows;
                    }
                }
                return rows;
            }""",
            int(limit),
        )
    except Exception:
        return []
    if not isinstance(snapshot, list):
        return []
    rows: list[dict[str, object]] = []
    for item in snapshot[: int(limit)]:
        if isinstance(item, dict):
            rows.append(dict(item))
    return rows


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
