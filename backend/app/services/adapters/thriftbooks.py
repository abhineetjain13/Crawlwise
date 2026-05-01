from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import AdapterResult, BaseAdapter, selectolax_node_text
from app.services.acquisition.runtime import curl_fetch
from app.services.field_value_core import clean_text

_THRIFTBOOKS_SEARCH_QUERY_PARAM = "b.search"
_THRIFTBOOKS_SEARCH_PATH = "/browse/"
_THRIFTBOOKS_DETAIL_PATH_MARKER = "/w/"
_THRIFTBOOKS_RESULT_PATH_MARKER = "/w/"
_THRIFTBOOKS_RESULT_EXCLUDE_MARKERS = ("/all-editions/",)


class ThriftBooksAdapter(BaseAdapter):
    name = "thriftbooks"
    platform_family = "thriftbooks"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    async def resolve_acquisition_url(self, url: str | None) -> str | None:
        requested_url = str(url or "").strip()
        if not requested_url or not self._matches_platform_family(requested_url, ""):
            return url
        parsed = urlparse(requested_url)
        if _THRIFTBOOKS_DETAIL_PATH_MARKER not in str(parsed.path or ""):
            return url
        query = _requested_query_from_url(requested_url)
        if not query:
            return url
        search_url = (
            f"{parsed.scheme}://{parsed.netloc}{_THRIFTBOOKS_SEARCH_PATH}"
            f"?{_THRIFTBOOKS_SEARCH_QUERY_PARAM}={quote_plus(query)}"
        )
        try:
            response = await curl_fetch(
                search_url,
                timeout_seconds=20,
            )
        except Exception:
            return url
        html = str(
            getattr(response, "html", None)
            or getattr(response, "text", None)
            or ""
        )
        if response.status_code != 200 or not html:
            return url
        resolved = _best_search_result_url(
            html,
            base_url=f"{parsed.scheme}://{parsed.netloc}",
            query=query,
        )
        return resolved or url

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        del url, html, surface
        return AdapterResult()


def _requested_query_from_url(url: str) -> str:
    parsed = urlparse(url)
    segments = [segment for segment in str(parsed.path or "").split("/") if segment]
    try:
        detail_index = segments.index("w")
    except ValueError:
        detail_index = -1
    slug = segments[detail_index + 1] if detail_index >= 0 and detail_index + 1 < len(segments) else ""
    text = re.sub(r"[_-]+", " ", slug)
    return clean_text(text)


def _best_search_result_url(
    html: str,
    *,
    base_url: str,
    query: str,
) -> str | None:
    parser = LexborHTMLParser(html)
    query_tokens = _scored_tokens(query)
    best_href = ""
    best_score = 0
    for anchor in parser.css("a[href]"):
        href = str(anchor.attributes.get("href") or "").strip()
        if not href or _THRIFTBOOKS_RESULT_PATH_MARKER not in href:
            continue
        lowered_href = href.lower()
        if any(marker in lowered_href for marker in _THRIFTBOOKS_RESULT_EXCLUDE_MARKERS):
            continue
        title = clean_text(selectolax_node_text(anchor, separator=" "))
        if not title:
            continue
        score = _match_score(query_tokens, title)
        if score <= best_score:
            continue
        best_score = score
        best_href = href
    if best_score <= 0 or not best_href:
        return None
    return urljoin(base_url, best_href)


def _scored_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").strip().lower())
        if len(token) >= 3
    }


def _match_score(query_tokens: set[str], candidate_title: str) -> int:
    candidate_tokens = _scored_tokens(candidate_title)
    if not query_tokens or not candidate_tokens:
        return 0
    overlap = query_tokens & candidate_tokens
    return len(overlap)
