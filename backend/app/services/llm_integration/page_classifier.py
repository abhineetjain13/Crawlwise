from __future__ import annotations

import asyncio
import html
import hashlib
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from cachetools import TTLCache
import httpx

from app.services.acquisition.acquirer import _html_has_extractable_listings_from_soup
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.llm_runtime import run_prompt_task
from app.services.pipeline_config import CARD_SELECTORS_COMMERCE, CARD_SELECTORS_JOBS, DOM_PATTERNS

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class PageClassification:
    page_type: str
    confidence: float
    has_secondary_listing: bool
    wait_selector_hint: str
    reasoning: str
    used_llm: bool
    source: str


_CACHE_TTL_SECONDS = 300
_CLASSIFICATION_CACHE_MAXSIZE = 512
_CLASSIFICATION_CACHE: TTLCache[str, PageClassification] = TTLCache(
    maxsize=_CLASSIFICATION_CACHE_MAXSIZE,
    ttl=_CACHE_TTL_SECONDS,
)
_ERROR_TEXT_PATTERNS = (
    re.compile(r"\berror\s*404\b", re.IGNORECASE),
    re.compile(r"\bhttp\s*404\b", re.IGNORECASE),
    re.compile(r"\bpage not found\b", re.IGNORECASE),
    re.compile(r"\berror\s*500\b", re.IGNORECASE),
    re.compile(r"\bhttp\s*500\b", re.IGNORECASE),
    re.compile(r"\bserver error\s*500\b", re.IGNORECASE),
    re.compile(r"\baccess denied\b", re.IGNORECASE),
)
_DETAIL_QUERY_KEYS = frozenset({"id", "product_id", "job_id", "slug", "sku", "item", "item_id", "listing_id"})
_PROMPT_ESCAPE_PATTERNS = (
    re.compile(r"ignore\s+previous", re.IGNORECASE),
    re.compile(r"\bsystem\s*:", re.IGNORECASE),
    re.compile(r"\byou must\b", re.IGNORECASE),
)
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?system", re.IGNORECASE),
    re.compile(r"you are now", re.IGNORECASE),
    re.compile(r"repeat after me", re.IGNORECASE),
)
_REASONING_MAX_CHARS = 160
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"\b(?:api[_-]?key|token|secret|password)\b\s*[:=]\s*\S+", re.IGNORECASE)
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s]+")
_POSIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])/(?:[^/\s]+/)*[^/\s]+")


def _cache_key(url: str, html: str) -> str:
    return hashlib.sha256(f"{url}\0{html}".encode("utf-8")).hexdigest()


def css_escape(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    escaped: list[str] = []
    for index, char in enumerate(text):
        if char == "\x00":
            escaped.append("\uFFFD")
            continue
        if char.isalnum() or char in {"-", "_"}:
            if index == 0 and char.isdigit():
                escaped.append(f"\\{ord(char):x} ")
            else:
                escaped.append(char)
            continue
        escaped.append(f"\\{ord(char):x} ")
    return "".join(escaped)


def _prune_html_for_llm(html: str, max_chars: int = 3500) -> str:
    stripped = re.sub(r"<(script|style|svg|noscript)\b[^>]*>.*?</\1\s*>", "", html, flags=re.IGNORECASE | re.DOTALL)
    stripped = re.sub(r"<!--.*?-->", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"\s{3,}", "  ", stripped)
    return stripped[:max_chars]


def _classify_by_heuristics(html: str, url: str, hint_surface: str | None) -> PageClassification | None:
    block = detect_blocked_page(html)
    if block.is_blocked and block.provider:
        return PageClassification("challenge", 0.95, False, "", f"blocked by {block.provider}", False, "heuristic")
    soup = BeautifulSoup(html, "html.parser")
    semantic_error_text = " ".join(
        text.strip()
        for text in (
            soup.title.get_text(" ", strip=True) if soup.title else "",
            soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "",
        )
        if text and text.strip()
    )
    if any(pattern.search(semantic_error_text) for pattern in _ERROR_TEXT_PATTERNS):
        return PageClassification("error", 0.8, False, "", "page error markers present", False, "heuristic")
    if _html_has_extractable_listings_from_soup(soup):
        return PageClassification("listing", 0.92, False, _derive_wait_selector_hint(html, hint_surface), "structured listing signals", False, "heuristic")
    if _has_detail_signals(html, hint_surface=hint_surface):
        return PageClassification("detail", 0.9, _has_secondary_listing(html), "", "detail html signals", False, "heuristic")
    if hint_surface in {"ecommerce_listing", "job_listing"} or _confidence_from_url(url, hint_surface) > 0.85:
        return PageClassification("listing", 0.88, False, _derive_wait_selector_hint(html, hint_surface), "listing URL pattern matched", False, "heuristic")
    if hint_surface in {"ecommerce_detail", "job_detail"}:
        return PageClassification("detail", 0.88, _has_secondary_listing(html), "", "detail surface hint matched", False, "heuristic")
    return None


def _derive_wait_selector_hint(html: str, hint_surface: str | None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    selectors = CARD_SELECTORS_JOBS if hint_surface == "job_listing" else CARD_SELECTORS_COMMERCE
    for selector in selectors:
        try:
            if len(soup.select(selector)) >= 2:
                return selector
        except Exception:
            continue
    cards, selector = _find_repeating_cards(soup)
    return selector if len(cards) >= 2 else ""


def _find_repeating_cards(soup: BeautifulSoup) -> tuple[list[Tag], str]:
    best_cards: list[Tag] = []
    best_selector = ""
    for container in soup.select("main, section, ul, ol, div"):
        children = [child for child in container.children if isinstance(child, Tag)]
        if len(children) < 3:
            continue
        grouped: dict[tuple[str, tuple[str, ...]], list[Tag]] = {}
        for child in children:
            key = (child.name, tuple(sorted(child.get("class", []))))
            grouped.setdefault(key, []).append(child)
        for (name, classes), group in grouped.items():
            if len(group) < 3:
                continue
            if sum(1 for item in group[:10] if item.select_one("a[href]")) < 3:
                continue
            if len(group) > len(best_cards):
                best_cards = group
                escaped_name = css_escape(name)
                escaped_classes = ".".join(css_escape(class_name) for class_name in classes if class_name)
                best_selector = f"{escaped_name}.{escaped_classes}" if escaped_classes else escaped_name
    return best_cards, best_selector


def _confidence_from_url(url: str, hint_surface: str | None) -> float:
    parsed = urlparse(url)
    tokens = "/".join([parsed.path.lower(), parsed.query.lower()])
    listing_hits = sum(token in tokens for token in ("/search", "/category", "page=", "sort=", "filter=", "results"))
    query_keys = {
        str(key or "").strip().lower()
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        if str(key or "").strip()
    }
    detail_hits = sum(token in tokens for token in ("/product", "/products/", "/job", "/jobs/")) + sum(
        1 for key in query_keys if key in _DETAIL_QUERY_KEYS
    )
    if hint_surface in {"ecommerce_listing", "job_listing"}:
        return 0.9 if listing_hits >= 1 else 0.0
    if hint_surface in {"ecommerce_detail", "job_detail"}:
        return 0.9 if detail_hits >= 1 else 0.0
    return 0.0


def _has_secondary_listing(html: str) -> bool:
    lowered = html.lower()
    return "related products" in lowered or "similar jobs" in lowered or "you may also like" in lowered


def _has_detail_signals(html: str, *, hint_surface: str | None) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    normalized_surface = str(hint_surface or "").strip().lower()
    is_job = normalized_surface.startswith("job")
    selectors = (
        [DOM_PATTERNS.get("title", ""), DOM_PATTERNS.get("company", ""), DOM_PATTERNS.get("salary", "")]
        if is_job
        else [DOM_PATTERNS.get("title", ""), DOM_PATTERNS.get("price", ""), DOM_PATTERNS.get("sku", "")]
    )
    selector_hits = 0
    for selector in selectors:
        selector = str(selector or "").strip()
        if not selector:
            continue
        try:
            if soup.select_one(selector) is not None:
                selector_hits += 1
        except Exception:
            continue

    visible_text = " ".join(soup.get_text(" ", strip=True).lower().split())
    detail_markers = (
        ("salary", "apply now", "job type", "responsibilities")
        if is_job
        else ("add to cart", "sku", "model", "availability", "specifications")
    )
    marker_hits = sum(marker in visible_text for marker in detail_markers)

    headings = [node.get_text(" ", strip=True) for node in soup.select("h1") if node.get_text(" ", strip=True)]
    repeating_cards, _ = _find_repeating_cards(soup)

    return bool(
        headings
        and len(repeating_cards) < 3
        and (
            selector_hits >= 2
            or marker_hits >= 2
        )
    )


def _load_cached_classification(url: str, html: str) -> PageClassification | None:
    cached = _CLASSIFICATION_CACHE.get(_cache_key(url, html))
    if cached is None:
        return None
    return PageClassification(**{**cached.__dict__, "source": "cache"})


def _store_cached_classification(url: str, html: str, classification: PageClassification) -> PageClassification:
    _CLASSIFICATION_CACHE[_cache_key(url, html)] = classification
    return classification


def _normalize_prompt_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Invalid page classification URL")
    normalized = parsed._replace(fragment="", netloc=parsed.netloc.lower())
    return urlunparse(normalized)


def _escape_for_prompt(text: str) -> str:
    escaped = text
    for pattern in _PROMPT_ESCAPE_PATTERNS:
        escaped = pattern.sub(lambda match: " ".join(f"`{part}`" for part in match.group(0).split()), escaped)
    return escaped


def _sanitize_html_snippet_for_prompt(html_text: str) -> str:
    decoded_raw = html.unescape(html_text)
    cleaned = re.sub(r"<(script|iframe)\b[^>]*>.*?</\1\s*>", "", decoded_raw, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\son\w+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"javascript\s*:", "", cleaned, flags=re.IGNORECASE)
    return _escape_for_prompt(cleaned)


def _prompt_injection_detected(text: str) -> bool:
    normalized = str(text or "")
    return any(pattern.search(normalized) for pattern in _PROMPT_INJECTION_PATTERNS)


def _sanitize_exception_reason(exc: Exception) -> str:
    details = str(exc).strip()
    sanitized = re.sub(r"[\r\n\t]+", " ", details)
    sanitized = re.sub(r"\s{2,}", " ", sanitized)
    sanitized = _EMAIL_RE.sub("[redacted-email]", sanitized)
    sanitized = _TOKEN_RE.sub("[redacted-secret]", sanitized)
    sanitized = _WINDOWS_PATH_RE.sub("[redacted-path]", sanitized)
    sanitized = _POSIX_PATH_RE.sub("[redacted-path]", sanitized)
    sanitized = sanitized.strip(" :")
    reason = f"error: {type(exc).__name__}"
    if sanitized:
        reason = f"{reason}: {sanitized}"
    return reason[:_REASONING_MAX_CHARS]


async def classify_page(
    session: AsyncSession | None,
    *,
    url: str,
    html: str,
    run_id: int | None = None,
    hint_surface: str | None = None,
    content_type: str = "html",
    llm_enabled: bool = False,
) -> PageClassification:
    cached = _load_cached_classification(url, html)
    if cached is not None:
        return cached
    heuristic = _classify_by_heuristics(html, url, hint_surface)
    if heuristic is not None or content_type == "json" or not llm_enabled or session is None:
        return _store_cached_classification(
            url,
            html,
            heuristic or PageClassification("unknown", 0.0, False, "", "heuristics inconclusive", False, "heuristic"),
        )
    try:
        normalized_url = _normalize_prompt_url(url)
        sanitized_html = _sanitize_html_snippet_for_prompt(_prune_html_for_llm(html))
        if _prompt_injection_detected(sanitized_html):
            blocked = PageClassification("unknown", 0.0, False, "", "prompt injection detected", False, "guard")
            return _store_cached_classification(url, html, blocked)
        result = await asyncio.wait_for(
            run_prompt_task(
                session,
                task_type="page_classification",
                run_id=run_id,
                domain=urlparse(normalized_url).netloc.lower(),
                variables={"url": normalized_url, "html_snippet": sanitized_html},
            ),
            timeout=8.0,
        )
        if result.error_message:
            logger.warning("Page classification LLM unavailable for %s: %s", normalized_url, result.error_message)
            return PageClassification("unknown", 0.0, False, "", "llm unavailable", True, "llm_error")
        payload = result.payload if isinstance(result.payload, dict) else {}
        page_type = str(payload.get("page_type") or "unknown").strip().lower()
        classification = PageClassification(
            page_type if page_type in {"listing", "detail", "challenge", "error", "unknown"} else "unknown",
            max(0.0, min(float(payload.get("confidence", 0.0) or 0.0), 1.0)),
            bool(payload.get("has_secondary_listing")),
            str(payload.get("wait_selector_hint") or "").strip(),
            str(payload.get("reasoning") or "llm classification").strip()[:_REASONING_MAX_CHARS],
            True,
            "llm",
        )
        return _store_cached_classification(url, html, classification)
    except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException):
        logger.warning("Page classification LLM timed out for %s", url)
        fallback = PageClassification("unknown", 0.0, False, "", "timeout", True, "llm")
        return _store_cached_classification(url, html, fallback)
    except Exception as exc:
        logger.exception("Page classification LLM failed for %s: %s", url, exc)
        fallback = PageClassification("unknown", 0.0, False, "", _sanitize_exception_reason(exc), True, "llm")
        return _store_cached_classification(url, html, fallback)
