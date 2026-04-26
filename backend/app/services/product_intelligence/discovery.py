from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.services.config.product_intelligence import (
    AGGREGATOR_DOMAINS,
    BRAND_DOMAIN_MAP,
    DISCOVERY_SOURCE_TYPE_PRIORITY,
    DUCKDUCKGO_BASE_URL,
    DUCKDUCKGO_HTML_URL,
    DUCKDUCKGO_QUERY_PARAM,
    DUCKDUCKGO_REDIRECT_QUERY_KEY,
    DUCKDUCKGO_REQUEST_HEADERS,
    DUCKDUCKGO_RESULT_LINK_SELECTORS,
    MARKETPLACE_DOMAINS,
    RETAILER_DOMAINS,
    SEARCH_EXCLUDED_DOMAIN_PREFIX,
    SEARCH_PHRASE_BUY,
    SEARCH_PROVIDER_DUCKDUCKGO,
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
    product_intelligence_settings,
)
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
    candidates: list[DiscoveredCandidate] = []
    seen: set[str] = set()
    domain_counts: dict[str, int] = {}
    provider_name = str(provider or product_intelligence_settings.default_search_provider).strip().lower()
    pool_limit = max(
        max_candidates,
        max_candidates * product_intelligence_settings.discovery_pool_multiplier,
    )
    for query_order, query in enumerate(queries):
        results = await _search_results(provider_name, query, limit=pool_limit)
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
    if provider == SEARCH_PROVIDER_SERPAPI:
        if not product_intelligence_settings.serpapi_key:
            logger.warning("Product intelligence SerpAPI discovery skipped: missing API key")
            return []
        return await _search_serpapi(query, limit=limit)
    if provider == SEARCH_PROVIDER_DUCKDUCKGO:
        return await _search_duckduckgo(query)
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


async def _search_duckduckgo(query: str) -> list[SearchResult]:
    try:
        async with httpx.AsyncClient(timeout=product_intelligence_settings.search_timeout_seconds) as client:
            response = await client.get(
                DUCKDUCKGO_HTML_URL,
                params={DUCKDUCKGO_QUERY_PARAM: query},
                headers=DUCKDUCKGO_REQUEST_HEADERS,
                follow_redirects=True,
            )
            response.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Product intelligence DuckDuckGo discovery failed: %s", exc)
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    results: list[SearchResult] = []
    for selector in DUCKDUCKGO_RESULT_LINK_SELECTORS:
        for link in soup.select(selector):
            href = str(link.get("href") or link.get_text(" ", strip=True) or "")
            if href:
                results.append(
                    SearchResult(
                        url=href,
                        payload={
                            "provider": SEARCH_PROVIDER_DUCKDUCKGO,
                            "title": link.get_text(" ", strip=True),
                        },
                    )
                )
    return results


def _clean_result_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    elif text.startswith("/"):
        text = f"{DUCKDUCKGO_BASE_URL}{text}"
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.query:
        redirected = parse_qs(parsed.query).get(DUCKDUCKGO_REDIRECT_QUERY_KEY)
        if redirected:
            text = redirected[0]
            try:
                parsed = urlsplit(text)
            except ValueError:
                return ""
    if (parsed.hostname or "").removeprefix("www.").lower() == "duckduckgo.com" and parsed.path == "/y.js":
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
