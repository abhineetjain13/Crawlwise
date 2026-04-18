from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from app.services.extract.candidate_processing import clean_page_text
from app.services.extract.noise_policy import is_noise_container
from app.services.pipeline.pipeline_config import PIPELINE_CONFIG
from bs4 import BeautifulSoup


def canonical_listing_path(value: str) -> str:
    path = urlparse(str(value or "").strip()).path.lower().rstrip("/")
    return re.sub(r"\.(?:html?|php|aspx?)$", "", path)


def url_path_tokens(value: str) -> set[str]:
    path = urlparse(str(value or "").strip()).path.lower()
    return {
        token
        for token in re.split(r"[^a-z0-9]+", path)
        if len(token) >= 3 and token not in PIPELINE_CONFIG.listing_path_token_stopwords
    }


def looks_like_detail_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if any(
        marker in lowered
        for marker in ("/p/", "/p.", "/product/", "/products/", "/dp/", "/item/", "/buy")
    ):
        return True
    segments = [segment for segment in urlparse(lowered).path.split("/") if segment]
    return any(segment.startswith("p.") for segment in segments)


def discover_child_listing_candidate(html: str, *, page_url: str) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return discover_child_listing_candidate_from_soup(soup, page_url=page_url)


def discover_child_listing_candidate_from_soup(
    soup: BeautifulSoup,
    *,
    page_url: str,
) -> str | None:
    page = urlparse(page_url)
    page_host = str(page.netloc or "").strip().lower()
    if not page_host:
        return None
    page_tokens = url_path_tokens(page_url)
    page_path = page.path.rstrip("/")
    page_path_canonical = canonical_listing_path(page_url)
    candidates: dict[str, int] = {}
    for anchor in soup.select("a[href]"):
        if is_noise_container(anchor):
            continue
        raw_href = str(anchor.get("href") or "").strip()
        if not raw_href or raw_href.startswith("#"):
            continue
        href = urljoin(page_url, raw_href)
        parsed = urlparse(href)
        host = str(parsed.netloc or "").strip().lower()
        if host != page_host:
            continue
        normalized_href = parsed._replace(fragment="", query="").geturl().rstrip("/")
        candidate_path_canonical = canonical_listing_path(normalized_href)
        if (
            not normalized_href
            or normalized_href == page_url.rstrip("/")
            or candidate_path_canonical == page_path_canonical
        ):
            continue
        if looks_like_detail_url(normalized_href):
            continue
        candidate_tokens = url_path_tokens(normalized_href)
        if not candidate_tokens:
            continue
        shared = len(candidate_tokens & page_tokens)
        if shared <= 0:
            continue
        text = clean_page_text(anchor.get_text(" ", strip=True)).lower()
        if text and any(
            token in text for token in PIPELINE_CONFIG.listing_promotion_text_noise
        ):
            continue
        score = shared * 5
        if parsed.path.rstrip("/").startswith(page_path):
            score += 2
        if len(candidate_tokens) > len(page_tokens):
            score += 1
        if any(hint in text for hint in PIPELINE_CONFIG.listing_promotion_text_hints):
            score += 3
        if any(
            token in candidate_tokens
            for token in PIPELINE_CONFIG.listing_promotion_penalty_tokens
        ):
            score -= 2
        if score >= 5:
            candidates[normalized_href] = max(score, candidates.get(normalized_href, 0))
    if not candidates:
        return None
    ranked = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > 1 and ranked[0][1] <= ranked[1][1]:
        return None
    return ranked[0][0]


def looks_like_category_tile_listing(records: list[dict]) -> bool:
    if len(records) < 2:
        return False
    tile_hints = 0
    for record in records:
        public_fields = {
            key: value
            for key, value in dict(record or {}).items()
            if not str(key).startswith("_") and value not in (None, "", [], {})
        }
        if not public_fields or not public_fields.get("url"):
            return False
        if set(public_fields) & PIPELINE_CONFIG.listing_tile_strong_fields:
            return False
        if any(
            field not in PIPELINE_CONFIG.listing_tile_allowed_fields
            for field in public_fields
        ):
            return False
        url_value = str(public_fields.get("url") or "").strip()
        if not url_value or looks_like_detail_url(url_value):
            return False
        title_value = str(public_fields.get("title") or "").strip().lower()
        image_value = str(public_fields.get("image_url") or "").strip().lower()
        if (
            image_value.startswith("data:image/")
            or "icon" in title_value
            or url_value.rstrip("/").endswith("/see-all")
            or "/all-" in url_value
        ):
            tile_hints += 1
    return tile_hints >= max(1, len(records) // 2)
