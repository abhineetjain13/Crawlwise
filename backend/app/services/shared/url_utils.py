from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from app.services.config.extraction_rules import (
    BARE_HOST_URL_RE,
    GIF_BASE64_PREFIX,
    PLACEHOLDER_IMAGE_URL_PATTERNS,
    UNRESOLVED_TEMPLATE_URL_TOKENS,
    URL_DETECTION_TOKENS,
)
from app.services.field_url_normalization import is_concatenated_url
from app.services.shared.text_coerce import clean_text

__all__ = [
    "absolute_url",
    "extract_urls",
    "same_host",
    "_ensure_scheme",
    "_is_placeholder_image_url",
]

_BARE_HOST_URL_RE = BARE_HOST_URL_RE
gif_base64_prefix = str(GIF_BASE64_PREFIX or "")
url_detection_tokens = tuple(URL_DETECTION_TOKENS or ())
unresolved_template_url_tokens_lower: tuple[str, ...] = tuple(
    str(token).strip().lower()
    for token in tuple(UNRESOLVED_TEMPLATE_URL_TOKENS or ())
    if str(token).strip()
)
placeholder_image_url_tokens = tuple(
    token.lower()
    for token in tuple(PLACEHOLDER_IMAGE_URL_PATTERNS or ())
    if str(token).strip()
)


def absolute_url(base_url: str, candidate: object) -> str:
    text = clean_text(candidate)
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme:
        return text
    if text.startswith(("//", "/", "#", "?", "./", "../")):
        return urljoin(base_url, text)
    if _BARE_HOST_URL_RE.fullmatch(text):
        return f"https://{text}"
    return urljoin(base_url, text)


def same_host(base_url: str, candidate_url: str) -> bool:
    base_host = (urlparse(base_url).hostname or "").lower()
    candidate_host = (urlparse(candidate_url).hostname or "").lower()
    return bool(candidate_host) and candidate_host == base_host


def extract_urls(value: object, page_url: str) -> list[str]:
    results: list[str] = []
    if isinstance(value, str):
        text = str(value or "").strip()
        if not text:
            return results
        if _looks_like_malformed_relative_url_candidate(text):
            return results
        if is_concatenated_url(text):
            return results
        embedded_urls = re.findall(r"https?://(?:(?!https?://)[^\s,])+", text)
        if len(embedded_urls) >= 2:
            for candidate in embedded_urls:
                absolute = absolute_url(
                    page_url,
                    _trim_trailing_url_candidate(candidate),
                )
                if absolute:
                    results.append(absolute)
        else:
            absolute = absolute_url(page_url, _trim_trailing_url_candidate(text))
            if absolute:
                results.append(absolute)
    elif isinstance(value, dict):
        for key in ("url", "href", "src", "contentUrl", "image", "thumbnail"):
            candidate = value.get(key)
            if candidate in (None, "", [], {}):
                continue
            results.extend(extract_urls(candidate, page_url))
    elif isinstance(value, list):
        for item in value:
            results.extend(extract_urls(item, page_url))
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in results:
        normalized = candidate.lower()
        if not candidate or normalized in seen:
            continue
        if _is_placeholder_image_url(candidate) or _is_template_url(candidate):
            continue
        if is_concatenated_url(candidate):
            continue
        seen.add(normalized)
        deduped.append(candidate)
    return deduped


def _ensure_scheme(url: str) -> str:
    stripped = str(url or "").strip()
    if not stripped:
        return stripped
    parsed = urlparse(stripped)
    if parsed.scheme:
        return stripped
    if stripped.startswith(("/", "#", "javascript:")):
        return stripped
    return f"https://{stripped}"


def _is_placeholder_image_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in placeholder_image_url_tokens)


def _trim_trailing_url_candidate(value: str) -> str:
    trimmed = str(value or "").rstrip(".,:;!?}'\"")
    while trimmed.endswith((")", "]")):
        closer = trimmed[-1]
        opener = "(" if closer == ")" else "["
        if trimmed.count(closer) <= trimmed.count(opener):
            break
        trimmed = trimmed[:-1].rstrip(".,:;!?}'\"")
    return trimmed


def _looks_like_malformed_relative_url_candidate(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if urlparse(text).scheme or text.startswith(("//", "/", "#", "?", "./", "../")):
        return False
    head = text.split("/", 1)[0].lower()
    if gif_base64_prefix and head.startswith(gif_base64_prefix):
        return True
    return any(token in head for token in url_detection_tokens)


def _is_template_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(token in lowered for token in unresolved_template_url_tokens_lower)
