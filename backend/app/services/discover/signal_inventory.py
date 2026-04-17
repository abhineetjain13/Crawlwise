"""Discover-stage HTML signal inventory and extractability assessment."""

from __future__ import annotations

from dataclasses import dataclass
from json import loads as parse_json
import re
from urllib.parse import urljoin, urlparse

from app.services.config.crawl_runtime import (
    DETAIL_FIELD_SIGNAL_MIN_COUNT,
    EXTRACTABILITY_JSON_LD_MIN_TYPE_SIGNALS,
    EXTRACTABILITY_NEXT_DATA_SIGNAL_MIN,
    EXTRACTABILITY_NEXT_DATA_SIGNAL_TRIGGER,
    EXTRACTABILITY_NON_PRODUCT_TYPE_RATIO_MAX,
    JS_GATE_PHRASES,
)
from app.services.extractability import (
    NEXT_DATA_PRODUCT_SIGNALS,
    html_has_extractable_listings_from_soup,
    json_ld_listing_count,
)
from app.services.platform_policy import acquisition_hint_tokens
from bs4 import BeautifulSoup

HTML_PARSER = "html.parser"


@dataclass(slots=True)
class ListingSignalSummary:
    strong: bool
    score: int
    candidate_count: int
    priced_count: int
    imaged_count: int
    titled_count: int
    card_like_count: int
    pagination_hint_count: int
    same_host_count: int
    path_diversity: int

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "strong": self.strong,
            "score": self.score,
            "candidate_count": self.candidate_count,
            "priced_count": self.priced_count,
            "imaged_count": self.imaged_count,
            "titled_count": self.titled_count,
            "card_like_count": self.card_like_count,
            "pagination_hint_count": self.pagination_hint_count,
            "same_host_count": self.same_host_count,
            "path_diversity": self.path_diversity,
        }


@dataclass(slots=True)
class HtmlSignalAnalysis:
    soup: BeautifulSoup
    visible_text: str
    gate_phrases: bool
    listing_signals: ListingSignalSummary


def analyze_html_signals(
    html: str,
    *,
    url: str,
    surface: str | None,
) -> HtmlSignalAnalysis:
    """Parse HTML once and return discover-owned routing signals."""
    soup = BeautifulSoup(html, HTML_PARSER)
    visible_text = " ".join(soup.get_text(" ", strip=True).lower().split())
    gate_phrases = any(phrase in visible_text for phrase in JS_GATE_PHRASES)
    listing_signals = collect_listing_signal_summary(soup, url=url, surface=surface)
    return HtmlSignalAnalysis(
        soup=soup,
        visible_text=visible_text,
        gate_phrases=gate_phrases,
        listing_signals=listing_signals,
    )


def collect_listing_signal_summary(
    soup: BeautifulSoup,
    *,
    url: str,
    surface: str | None,
) -> ListingSignalSummary:
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_surface.endswith("listing"):
        return ListingSignalSummary(False, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    page_host = str(urlparse(url).netloc or "").strip().lower()
    candidate_count = 0
    priced_count = 0
    imaged_count = 0
    titled_count = 0
    card_like_count = 0
    pagination_hint_count = 0
    same_host_count = 0
    unique_paths: set[str] = set()
    seen_candidates: set[str] = set()
    price_re = re.compile(r"(?:[$€£]\s?\d|\d[\d,]*(?:\.\d{2})?)")

    for anchor in soup.select("a[href]"):
        raw_href = str(anchor.get("href") or "").strip()
        if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute_href = urljoin(url, raw_href)
        parsed = urlparse(absolute_href)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            continue
        normalized_href = parsed._replace(fragment="", query="").geturl().rstrip("/")
        if not normalized_href or normalized_href in seen_candidates:
            continue
        text = " ".join(anchor.get_text(" ", strip=True).split())
        if len(text) < 3:
            continue
        seen_candidates.add(normalized_href)
        candidate_count += 1
        if parsed.netloc.lower() == page_host:
            same_host_count += 1
            unique_paths.add(parsed.path.rstrip("/"))
        if anchor.find("img") is not None:
            imaged_count += 1
        if price_re.search(anchor.get_text(" ", strip=True)):
            priced_count += 1
        if len(text.split()) >= 2:
            titled_count += 1
        parent = anchor.parent
        parent_text = " ".join(parent.get_text(" ", strip=True).split()) if parent else text
        if (
            parent is not None
            and parent.name in {"li", "article", "div"}
            and len(parent_text) >= len(text)
            and (anchor.find("img") is not None or price_re.search(parent_text))
        ):
            card_like_count += 1

    pagination_hint_count += len(
        soup.select(
            "a[rel='next'], link[rel='next'], a[href*='page='], a[aria-label*='next' i], button[aria-label*='next' i]"
        )
    )

    score = 0
    if candidate_count >= 2:
        score += 2
    if normalized_surface.startswith("job_") and candidate_count >= 2 and titled_count >= 2:
        score += 2
    if same_host_count >= 2:
        score += 1
    if len(unique_paths) >= 2:
        score += 2
    if card_like_count >= 2:
        score += 2
    if priced_count >= 2:
        score += 1
    if imaged_count >= 2 and titled_count >= 2:
        score += 1
    if pagination_hint_count > 0:
        score += 1
    strong = score >= 4 and candidate_count >= 2 and titled_count >= 2
    return ListingSignalSummary(
        strong=strong,
        score=score,
        candidate_count=candidate_count,
        priced_count=priced_count,
        imaged_count=imaged_count,
        titled_count=titled_count,
        card_like_count=card_like_count,
        pagination_hint_count=pagination_hint_count,
        same_host_count=same_host_count,
        path_diversity=len(unique_paths),
    )


def html_has_min_listing_link_signals(
    html: str,
    *,
    surface: str | None,
    url: str = "",
    soup: BeautifulSoup | None = None,
) -> bool:
    soup = soup or BeautifulSoup(html, HTML_PARSER)
    return collect_listing_signal_summary(soup, url=url, surface=surface).strong


def find_promotable_iframe_sources(html: str, *, surface: str | None) -> list[dict]:
    normalized_surface = str(surface or "").strip().lower()
    if "job" not in normalized_surface:
        return []
    soup = BeautifulSoup(html, HTML_PARSER)
    promoted: list[dict] = []
    promotable_tokens = promotable_job_iframe_tokens()
    for tag in soup.select("iframe[src], frame[src]"):
        src = str(tag.get("src") or "").strip()
        if not src:
            continue
        lowered = src.lower()
        if any(token in lowered for token in promotable_tokens):
            kind = "frame" if tag.name and tag.name.lower() == "frame" else "iframe"
            promoted.append({"kind": kind, "url": src, "same_origin": False})
    return promoted


def promotable_job_iframe_tokens() -> tuple[str, ...]:
    base_tokens = {"job", "jobs", "career", "careers"}
    merged = {
        token
        for token in (base_tokens | set(acquisition_hint_tokens()))
        if len(token) >= 3
    }
    return tuple(sorted(merged))


def assess_extractable_html(
    html: str,
    *,
    url: str,
    surface: str | None,
    adapter_hint: str | None,
    soup: BeautifulSoup | None = None,
    listing_signals: ListingSignalSummary | None = None,
) -> dict[str, object]:
    normalized_surface = str(surface or "").strip().lower()
    if not html:
        return {"has_extractable_data": False, "reason": "empty_html"}

    soup_probe = soup or BeautifulSoup(html, HTML_PARSER)
    if soup_probe.find("frameset") is not None or "<frameset" in html.lower():
        promoted_iframes = find_promotable_iframe_sources(html, surface=surface)
        return {
            "has_extractable_data": False,
            "reason": "frameset_shell",
            "promoted_sources": promoted_iframes or None,
        }

    if normalized_surface.endswith("listing") or not normalized_surface:
        promoted_iframes = find_promotable_iframe_sources(html, surface=surface)

        json_ld_count = count_json_ld_type_signals(html)
        non_product_types = count_json_ld_non_product_types(html)
        total_types = json_ld_count + non_product_types
        is_mostly_non_product = (
            total_types > 0
            and (non_product_types / total_types)
            > EXTRACTABILITY_NON_PRODUCT_TYPE_RATIO_MAX
        )
        if (
            json_ld_count >= EXTRACTABILITY_JSON_LD_MIN_TYPE_SIGNALS
            and not is_mostly_non_product
        ):
            return {
                "has_extractable_data": True,
                "reason": "structured_listing_markup",
                "json_ld_count": json_ld_count,
                "promoted_sources": promoted_iframes or None,
            }

        signal_hits = sum(html.count(sig) for sig in NEXT_DATA_PRODUCT_SIGNALS)
        has_next_data = "__NEXT_DATA__" in html
        if (
            has_next_data
            or signal_hits >= EXTRACTABILITY_NEXT_DATA_SIGNAL_TRIGGER
        ) and signal_hits >= EXTRACTABILITY_NEXT_DATA_SIGNAL_MIN:
            return {
                "has_extractable_data": True,
                "reason": "next_data_signals"
                if has_next_data
                else "product_signals_in_html",
                "signal_hits": signal_hits,
                "promoted_sources": promoted_iframes or None,
            }

        if promoted_iframes:
            return {
                "has_extractable_data": False,
                "reason": "iframe_shell",
                "promoted_sources": promoted_iframes,
            }

        listing_summary = listing_signals or collect_listing_signal_summary(
            soup_probe,
            url=url,
            surface=surface,
        )
        if listing_summary.strong:
            return {
                "has_extractable_data": True,
                "reason": "listing_link_signals",
                "listing_signals": listing_summary.as_dict(),
                "promoted_sources": promoted_iframes or None,
            }

        if adapter_hint:
            return {
                "has_extractable_data": True,
                "reason": "adapter_hint",
                "adapter_hint": adapter_hint,
            }

        html_lower = html.lower()
        if (
            "window.searchconfig" in html_lower
            or "data-jibe-search-version" in html_lower
            or "window._jibe" in html_lower
        ):
            return {
                "has_extractable_data": False,
                "reason": "listing_search_shell_without_records",
            }

        return {"has_extractable_data": False, "reason": "no_listing_signals"}

    if normalized_surface.endswith("detail"):
        if adapter_hint:
            return {
                "has_extractable_data": True,
                "reason": "adapter_hint",
                "adapter_hint": adapter_hint,
            }
        html_lower = html.lower()
        has_json_ld = '"@type"' in html and any(
            token in html_lower
            for token in ('"product"', '"jobposting"', '"offer"', '"service"')
        )
        if has_json_ld:
            return {"has_extractable_data": True, "reason": "detail_json_ld"}

        visible_text = soup_probe.get_text(" ", strip=True).lower()
        detail_tokens = ("title", "price", "brand", "description", "sku")
        field_hits = sum(1 for token in detail_tokens if token in visible_text)
        if field_hits >= DETAIL_FIELD_SIGNAL_MIN_COUNT:
            return {
                "has_extractable_data": True,
                "reason": "detail_field_signals",
                "field_signal_count": field_hits,
            }

        return {
            "has_extractable_data": False,
            "reason": "insufficient_detail_signals",
            "field_signal_count": field_hits,
        }

    return {"has_extractable_data": True, "reason": "surface_unspecified"}


def count_json_ld_type_signals(html: str) -> int:
    count = 0
    search_start = 0
    html_lower = html.lower()
    while True:
        pos = html_lower.find('"@type"', search_start)
        if pos == -1:
            break
        window = html_lower[pos : pos + 200]
        if '"product"' in window or '"jobposting"' in window:
            count += 1
        search_start = pos + 7
    return count


def count_json_ld_non_product_types(html: str) -> int:
    count = 0
    search_start = 0
    html_lower = html.lower()
    while True:
        pos = html_lower.find('"@type"', search_start)
        if pos == -1:
            break
        window = html_lower[pos : pos + 200]
        if '"product"' not in window and '"jobposting"' not in window:
            count += 1
        search_start = pos + 7
    return count


def json_ld_listing_count_for_payload(
    payload: object, *, max_depth: int = 3, depth: int = 0
) -> int:
    return json_ld_listing_count(payload, _depth=depth, max_depth=max_depth)


def html_has_extractable_listings(html: str, *, soup: BeautifulSoup | None = None) -> bool:
    soup = soup or BeautifulSoup(html, HTML_PARSER)
    return html_has_extractable_listings_from_soup(soup, json_loader=parse_json)
