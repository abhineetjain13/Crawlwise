# Low-level extraction helpers: XPath, regex, URL parsing, image URL collection.
from __future__ import annotations

import re
from urllib.parse import urlparse

from lxml import etree
from lxml import html as lxml_html

from app.services.config.extraction_rules import (
    CANDIDATE_IMAGE_CANDIDATE_DICT_KEYS,
    CANDIDATE_IMAGE_FILE_EXTENSIONS,
    CANDIDATE_IMAGE_NOISE_TOKENS,
    CANDIDATE_IMAGE_URL_HINT_TOKENS,
    CANDIDATE_NESTED_COLLECTION_SCAN_LIMIT,
)
from app.services.extract.candidate_processing import (
    _normalized_candidate_text,
    resolve_candidate_url as _resolve_candidate_url,
)


def _extract_image_urls(value: object, *, base_url: str = "") -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def _append(candidate: str) -> None:
        resolved = _resolve_candidate_url(candidate, base_url)
        if not resolved:
            return
        lowered = resolved.lower()
        path = urlparse(resolved).path.lower()
        if any(token in lowered for token in CANDIDATE_IMAGE_NOISE_TOKENS):
            return
        if not (
            path.endswith(CANDIDATE_IMAGE_FILE_EXTENSIONS)
            or re.search(r"/(?:webp|jpeg|jpg|png)$", path)
            or any(token in lowered for token in CANDIDATE_IMAGE_URL_HINT_TOKENS)
        ):
            return
        if resolved in seen:
            return
        seen.add(resolved)
        urls.append(resolved)

    def _collect(node: object) -> None:
        if node in (None, "", [], {}):
            return
        if isinstance(node, str):
            for part in re.split(r"\s*\|\s*|\s*,\s*(?=https?://|//|/)", node):
                cleaned = _normalized_candidate_text(part)
                if cleaned:
                    _append(cleaned)
            return
        if isinstance(node, dict):
            for key in CANDIDATE_IMAGE_CANDIDATE_DICT_KEYS:
                candidate = node.get(key)
                if isinstance(candidate, str):
                    _append(candidate)
            for item in list(node.values())[:CANDIDATE_NESTED_COLLECTION_SCAN_LIMIT]:
                _collect(item)
            return
        if isinstance(node, list):
            for item in node[:CANDIDATE_NESTED_COLLECTION_SCAN_LIMIT]:
                _collect(item)

    _collect(value)
    return urls


def _domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or parsed.path.lower()


def _build_xpath_tree(document_html: str):
    try:
        return lxml_html.fromstring(document_html)
    except (etree.ParserError, ValueError):
        return None


def _index_extraction_contract(extraction_contract: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in extraction_contract:
        field_name = str(row.get("field_name", "")).strip()
        if field_name and field_name not in indexed:
            indexed[field_name] = row
    return indexed


def _extract_xpath_value(tree, xpath: str) -> str | None:
    xpath = str(xpath or "").strip()
    if tree is None or not xpath:
        return None
    try:
        results = tree.xpath(xpath)
    except etree.XPathError:
        return None
    if not results:
        return None
    first = results[0]
    if isinstance(first, str):
        return first.strip() or None
    if hasattr(first, "text_content"):
        value = first.text_content().strip()
        return value or None
    value = str(first).strip()
    return value or None


def _extract_regex_value(document_html: str, pattern: str) -> str | None:
    pattern = str(pattern or "").strip()
    if not pattern:
        return None
    try:
        match = re.search(pattern, document_html, re.DOTALL)
    except re.error:
        return None
    if not match:
        return None
    if match.groups():
        return next((group for group in match.groups() if group), None)
    return match.group(0)
