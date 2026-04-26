from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx

from app.services.acquisition.browser_recovery import emit_browser_behavior_activity
from app.services.acquisition.browser_runtime import get_browser_runtime, real_chrome_browser_available
from app.services.acquisition.dom_runtime import get_page_html
from app.services.config.product_intelligence import (
    AGGREGATOR_DOMAINS,
    BRAND_DOMAIN_MAP,
    DISCOVERY_SOURCE_TYPE_PRIORITY,
    MARKETPLACE_DOMAINS,
    RETAILER_DOMAINS,
    SEARCH_EXCLUDED_DOMAIN_PREFIX,
    SEARCH_PHRASE_BUY,
    SEARCH_PROVIDER_GOOGLE_NATIVE,
    SEARCH_PROVIDER_SERPAPI,
    SEARCH_SITE_PREFIX,
    SEARCH_STOP_WORDS,
    SERPAPI_ENGINE,
    SERPAPI_ENGINE_PARAM,
    SERPAPI_KEY_PARAM,
    SERPAPI_LINK_FIELD,
    SERPAPI_ORGANIC_RESULTS_FIELD,
    SERPAPI_POSITION_FIELD,
    SERPAPI_QUERY_PARAM,
    SERPAPI_RESULT_COUNT_PARAM,
    SERPAPI_SEARCH_URL,
    SERPAPI_SNIPPET_FIELD,
    SERPAPI_TITLE_FIELD,
    SOURCE_TYPE_AGGREGATOR,
    SOURCE_TYPE_BRAND_DTC,
    SOURCE_TYPE_MARKETPLACE,
    SOURCE_TYPE_RETAILER,
    SOURCE_TYPE_UNKNOWN,
    GOOGLE_NATIVE_BROWSER_ENGINE,
    GOOGLE_NATIVE_HOME_URL,
    GOOGLE_NATIVE_IGNORED_DOMAINS,
    GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS,
    GOOGLE_NATIVE_PROVIDER_PAYLOAD,
    GOOGLE_NATIVE_QUERY_PARAM,
    GOOGLE_NATIVE_REDIRECT_PATH,
    GOOGLE_NATIVE_REDIRECT_TARGET_PARAM,
    GOOGLE_NATIVE_RESULT_COUNT_PARAM,
    GOOGLE_NATIVE_RESULT_LINK_SELECTOR,
    GOOGLE_NATIVE_RESULT_WAIT_MS,
    GOOGLE_NATIVE_SEARCH_URL,
    GOOGLE_NATIVE_THUMBNAIL_ANCESTOR_DEPTH,
    GOOGLE_NATIVE_THUMBNAIL_MIN_SRC_LENGTH,
    GOOGLE_NATIVE_TITLE_SELECTOR,
    product_intelligence_settings,
)
from app.services.field_value_core import clean_text
from app.services.product_intelligence.matching import normalize_brand, source_domain

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DiscoveredCandidate:
    url: str
    domain: str
    source_type: str
    query_used: str
    search_rank: int
    payload: dict[str, object] | None = None
    query_order: int = 0


@dataclass(slots=True)
class SearchResult:
    url: str
    payload: dict[str, object]


def build_search_queries(
    product: dict[str, object],
    *,
    source_domain_value: str = "",
) -> list[str]:
    brand = normalize_brand(product.get("brand"))
    title = _title_slug(product.get("title"))
    excluded = _excluded_domain_clause(source_domain_value)
    queries: list[str] = []
    identifier = _first_identifier(product)
    brand_domain = BRAND_DOMAIN_MAP.get(brand)
    if brand and title and brand_domain:
        queries.append(
            _join_query_parts(
                _quoted(brand),
                _quoted(title),
                f"{SEARCH_SITE_PREFIX}{brand_domain}",
                excluded,
            )
        )
    if brand and title and identifier:
        queries.append(_join_query_parts(_quoted(brand), _quoted(title), _quoted(identifier), excluded))
    if brand and title:
        queries.append(_join_query_parts(_quoted(brand), _quoted(title), SEARCH_PHRASE_BUY, excluded))
    if title and identifier:
        queries.append(_join_query_parts(_quoted(title), _quoted(identifier), excluded))
    if title:
        queries.append(_join_query_parts(_quoted(title), SEARCH_PHRASE_BUY, excluded))
    return _dedupe_keep_order(queries)


async def discover_candidates(
    product: dict[str, object],
    *,
    source_domain_value: str,
    provider: str,
    allowed_domains: list[str],
    excluded_domains: list[str],
    max_candidates: int,
) -> list[DiscoveredCandidate]:
    queries = build_search_queries(product, source_domain_value=source_domain_value)
    if not queries:
        return []
    provider_name = str(provider or product_intelligence_settings.default_search_provider).strip().lower()
    pool_limit = max(
        max_candidates,
        max_candidates * product_intelligence_settings.discovery_pool_multiplier,
    )
    async with _query_runner(provider_name) as run_query:
        if run_query is None:
            return []
        return await _collect_candidates(
            queries=queries,
            run_query=run_query,
            product=product,
            source_domain_value=source_domain_value,
            allowed_domains=allowed_domains,
            excluded_domains=excluded_domains,
            max_candidates=max_candidates,
            pool_limit=pool_limit,
        )


async def _collect_candidates(
    *,
    queries: list[str],
    run_query: Callable[[str, int], Awaitable[list[SearchResult]]],
    product: dict[str, object],
    source_domain_value: str,
    allowed_domains: list[str],
    excluded_domains: list[str],
    max_candidates: int,
    pool_limit: int,
) -> list[DiscoveredCandidate]:
    candidates: list[DiscoveredCandidate] = []
    seen: set[str] = set()
    domain_counts: dict[str, int] = {}
    for query_order, query in enumerate(queries):
        results = await run_query(query, pool_limit)
        for rank, result in enumerate(results, start=1):
            normalized_url = _clean_result_url(result.url)
            if not normalized_url or normalized_url in seen:
                continue
            domain = source_domain(normalized_url)
            if not _domain_allowed(domain, allowed_domains, excluded_domains, source_domain_value):
                continue
            if domain_counts.get(domain, 0) >= product_intelligence_settings.max_urls_per_result_domain:
                continue
            seen.add(normalized_url)
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            candidates.append(
                DiscoveredCandidate(
                    url=normalized_url,
                    domain=domain,
                    source_type=classify_source_type(domain, product),
                    query_used=query,
                    search_rank=rank,
                    payload=result.payload,
                    query_order=query_order,
                )
            )
            if len(candidates) >= pool_limit:
                return _rank_discovered_candidates(candidates)[:max_candidates]
        if (
            product_intelligence_settings.search_delay_ms > 0
            and len(candidates) < pool_limit
            and query_order < len(queries) - 1
        ):
            await asyncio.sleep(product_intelligence_settings.search_delay_ms / 1000)
    return _rank_discovered_candidates(candidates)[:max_candidates]


@contextlib.asynccontextmanager
async def _query_runner(provider: str):
    if provider == SEARCH_PROVIDER_GOOGLE_NATIVE:
        if not real_chrome_browser_available():
            logger.error(
                "Product intelligence google_native discovery requires real Chrome (BROWSER_REAL_CHROME_ENABLED + executable path); refusing to silently downgrade to chromium"
            )
            yield None
            return
        async with _google_native_session() as run:
            yield run
        return

    async def _http_run(query: str, limit: int) -> list[SearchResult]:
        return await _search_results(provider, query, limit=limit)

    yield _http_run


def classify_source_type(domain: str, product: dict[str, object]) -> str:
    normalized_domain = str(domain or "").removeprefix("www.").lower()
    brand_domain = BRAND_DOMAIN_MAP.get(normalize_brand(product.get("brand")))
    if brand_domain and _domain_matches(normalized_domain, brand_domain):
        return SOURCE_TYPE_BRAND_DTC
    if any(_domain_matches(normalized_domain, item) for item in MARKETPLACE_DOMAINS):
        return SOURCE_TYPE_MARKETPLACE
    if any(_domain_matches(normalized_domain, item) for item in AGGREGATOR_DOMAINS):
        return SOURCE_TYPE_AGGREGATOR
    if any(_domain_matches(normalized_domain, item) for item in RETAILER_DOMAINS):
        return SOURCE_TYPE_RETAILER
    return SOURCE_TYPE_UNKNOWN


def _rank_discovered_candidates(
    candidates: list[DiscoveredCandidate],
) -> list[DiscoveredCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            int(DISCOVERY_SOURCE_TYPE_PRIORITY.get(candidate.source_type, 99)),
            candidate.query_order,
            candidate.search_rank,
        ),
    )


async def _search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
    logger.info("Product intelligence search dispatch provider=%r query=%r limit=%s", provider, query, limit)
    if provider == SEARCH_PROVIDER_SERPAPI:
        if not product_intelligence_settings.serpapi_key:
            logger.warning("Product intelligence SerpAPI discovery skipped: missing API key")
            return []
        return await _search_serpapi(query, limit=limit)
    logger.warning("Product intelligence discovery received unknown provider: %r", provider)
    return []


async def _search_serpapi(query: str, *, limit: int | None = None) -> list[SearchResult]:
    params = {
        SERPAPI_ENGINE_PARAM: SERPAPI_ENGINE,
        SERPAPI_QUERY_PARAM: query,
        SERPAPI_KEY_PARAM: product_intelligence_settings.serpapi_key,
    }
    if limit is not None:
        params[SERPAPI_RESULT_COUNT_PARAM] = str(max(1, int(limit)))
    try:
        async with httpx.AsyncClient(timeout=product_intelligence_settings.search_timeout_seconds) as client:
            response = await client.get(SERPAPI_SEARCH_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        logger.warning("Product intelligence SerpAPI discovery failed: %s", exc)
        return []
    rows = payload.get(SERPAPI_ORGANIC_RESULTS_FIELD)
    if not isinstance(rows, list):
        return []
    return [
        SearchResult(
            url=str(item.get(SERPAPI_LINK_FIELD) or ""),
            payload={
                "provider": SEARCH_PROVIDER_SERPAPI,
                "title": str(item.get(SERPAPI_TITLE_FIELD) or ""),
                "snippet": str(item.get(SERPAPI_SNIPPET_FIELD) or ""),
                "position": item.get(SERPAPI_POSITION_FIELD),
                "raw": item,
            },
        )
        for item in rows
        if isinstance(item, dict) and item.get(SERPAPI_LINK_FIELD)
    ]


@contextlib.asynccontextmanager
async def _google_native_session():
    """Open one real-Chrome page on google.com and reuse it across multiple queries.

    Each query then runs as a single ``page.goto('/search?q=...')`` navigation on
    the existing page, instead of opening a fresh browser context per query.
    """
    runtime = await get_browser_runtime(browser_engine=GOOGLE_NATIVE_BROWSER_ENGINE)
    async with runtime.page(domain=source_domain(GOOGLE_NATIVE_HOME_URL)) as page:
        try:
            await page.goto(
                GOOGLE_NATIVE_HOME_URL,
                wait_until="domcontentloaded",
                timeout=int(GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS),
            )
            await emit_browser_behavior_activity(page)
        except Exception as exc:
            logger.warning("Product intelligence native Google session setup failed: %s", exc)

        async def _run(query: str, limit: int) -> list[SearchResult]:
            normalized_query = str(query or "").strip()
            if not normalized_query:
                return []
            result_limit = min(
                max(1, int(limit or product_intelligence_settings.google_native_max_results)),
                int(product_intelligence_settings.google_native_max_results),
            )
            logger.info("Product intelligence search dispatch provider='google_native' query=%r limit=%s", normalized_query, limit)
            try:
                await page.goto(
                    _google_native_search_url(normalized_query, result_limit),
                    wait_until="domcontentloaded",
                    timeout=int(GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS),
                )
                await page.wait_for_timeout(int(GOOGLE_NATIVE_RESULT_WAIT_MS))
                html = await get_page_html(page)
            except Exception as exc:
                logger.warning("Product intelligence native Google query failed: %s", exc)
                return []
            return _parse_google_native_results(html, limit=result_limit)

        yield _run


def _google_native_search_url(query: str, limit: int) -> str:
    return (
        f"{GOOGLE_NATIVE_SEARCH_URL}?"
        f"{urlencode({GOOGLE_NATIVE_QUERY_PARAM: query, GOOGLE_NATIVE_RESULT_COUNT_PARAM: str(limit)})}"
    )


def _parse_google_native_results(html: str, *, limit: int) -> list[SearchResult]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for anchor in soup.select(GOOGLE_NATIVE_RESULT_LINK_SELECTOR):
        href = str(anchor.get("href") or "").strip()
        url = _google_native_result_url(href)
        if not url or url in seen:
            continue
        domain = source_domain(url).removeprefix("www.").lower()
        if any(_domain_matches(domain, item) for item in GOOGLE_NATIVE_IGNORED_DOMAINS):
            continue
        title = _google_native_anchor_title(anchor)
        if not title:
            continue
        thumbnail = _google_native_anchor_thumbnail(anchor)
        seen.add(url)
        results.append(
            SearchResult(
                url=url,
                payload={
                    "provider": GOOGLE_NATIVE_PROVIDER_PAYLOAD,
                    "title": title,
                    "snippet": "",
                    "thumbnail": thumbnail,
                    "position": len(results) + 1,
                    "raw": {"href": href, "thumbnail": thumbnail},
                },
            )
        )
        if len(results) >= max(1, int(limit)):
            break
    return results


def _google_native_anchor_title(anchor) -> str:
    """Return the title text only when the anchor wraps an organic-result h3.

    Google's SERP contains many non-organic anchors (shopping carousels,
    People-also-ask, knowledge-panel cards, ads). Those anchors have text but
    no inner ``<h3>``. Requiring an h3 keeps only the organic blue-link
    results that the user actually wants.
    """
    heading = anchor.select_one(GOOGLE_NATIVE_TITLE_SELECTOR)
    if heading is None:
        return ""
    return clean_text(heading.get_text(" ", strip=True))


def _google_native_anchor_thumbnail(anchor) -> str:
    parent = anchor
    for _ in range(int(GOOGLE_NATIVE_THUMBNAIL_ANCESTOR_DEPTH)):
        parent = getattr(parent, "parent", None)
        if parent is None:
            break
        for img in parent.find_all("img"):
            src = str(img.get("src") or img.get("data-src") or "").strip()
            if len(src) >= int(GOOGLE_NATIVE_THUMBNAIL_MIN_SRC_LENGTH):
                return src
    return ""


def _google_native_result_url(href: str) -> str:
    raw = str(href or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc.endswith("google.com") and parsed.path == GOOGLE_NATIVE_REDIRECT_PATH:
            target = parse_qs(parsed.query).get(GOOGLE_NATIVE_REDIRECT_TARGET_PARAM, [""])[0]
            return _clean_result_url(target)
        return _clean_result_url(raw)
    if raw.startswith(GOOGLE_NATIVE_REDIRECT_PATH):
        target = parse_qs(urlsplit(raw).query).get(GOOGLE_NATIVE_REDIRECT_TARGET_PARAM, [""])[0]
        return _clean_result_url(target)
    if raw.startswith("/"):
        return _clean_result_url(urljoin(GOOGLE_NATIVE_HOME_URL, raw))
    return ""


def _clean_result_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def _domain_allowed(
    domain: str,
    allowed_domains: list[str],
    excluded_domains: list[str],
    source_domain_value: str,
) -> bool:
    normalized = domain.removeprefix("www.").lower()
    if not normalized:
        return False
    excluded = {item.removeprefix("www.").lower() for item in excluded_domains if item}
    source = source_domain_value.removeprefix("www.").lower()
    if source:
        excluded.add(source)
    if any(_domain_matches(normalized, item) for item in excluded):
        return False
    allowed = {item.removeprefix("www.").lower() for item in allowed_domains if item}
    return not allowed or any(_domain_matches(normalized, item) for item in allowed)


def _domain_matches(normalized_domain: str, target: str) -> bool:
    normalized_target = str(target or "").removeprefix("www.").lower()
    return bool(
        normalized_target
        and (
            normalized_domain == normalized_target
            or normalized_domain.endswith(f".{normalized_target}")
        )
    )


def _title_slug(value: object) -> str:
    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").casefold())
        if token and token not in SEARCH_STOP_WORDS
    ]
    return " ".join(tokens[: product_intelligence_settings.title_token_limit])


def _first_identifier(product: dict[str, object]) -> str:
    for key in ("gtin", "mpn", "sku"):
        value = str(product.get(key) or "").strip()
        if value:
            return value
    return ""


def _excluded_domain_clause(domain: str) -> str:
    normalized = source_domain(domain or "")
    if not normalized:
        normalized = str(domain or "").removeprefix("www.").lower().strip()
    return f"{SEARCH_EXCLUDED_DOMAIN_PREFIX}{normalized}" if normalized else ""


def _quoted(value: object) -> str:
    text = str(value or "").strip()
    return f'"{text}"' if text else ""


def _join_query_parts(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
