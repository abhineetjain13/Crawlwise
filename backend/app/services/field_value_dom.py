from __future__ import annotations

import logging
import regex as regex_lib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from lxml import etree
from lxml import html as lxml_html
from soupsieve import SelectorSyntaxError

from app.services.config.extraction_rules import EXTRACTION_RULES, SEMANTIC_SECTION_NOISE
from app.services.config.surface_hints import detail_path_hints
from app.services.field_policy import normalize_field_key, normalize_requested_field

from app.services.field_value_candidates import add_candidate
from app.services.field_value_core import (
    IMAGE_FIELDS,
    URL_FIELDS,
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_urls,
    surface_alias_lookup,
    surface_fields,
)
from app.services.xpath_service import validate_xpath_syntax

logger = logging.getLogger(__name__)

_CANDIDATE_CLEANUP = dict(EXTRACTION_RULES.get("candidate_cleanup") or {})
_IMAGE_FILE_EXTENSIONS = tuple(_CANDIDATE_CLEANUP.get("image_file_extensions") or ())
_PAGE_FILE_EXTENSIONS = (".asp", ".aspx", ".htm", ".html", ".jsp", ".php")
_IMAGE_URL_HINTS = tuple(_CANDIDATE_CLEANUP.get("image_url_hint_tokens") or ())
_NON_PRIMARY_IMAGE_SECTION_HINTS = tuple(
    str(token).lower()
    for token in (
        SEMANTIC_SECTION_NOISE.get("label_skip_tokens")
        or ()
    )
)
_CDN_IMAGE_QUERY_PARAMS = frozenset(
    {
        "width",
        "w",
        "height",
        "h",
        "quality",
        "q",
        "dpr",
        "fit",
        "crop",
        "format",
        "fm",
        "auto",
    }
)
_CROSS_LINK_CONTAINER_HINTS = (
    "carousel",
    "cross-sell",
    "crosssell",
    "grid",
    "related",
    "recommend",
    "similar",
    "slider",
    "upsell",
    "widget",
)
_PRODUCT_GALLERY_CONTEXT_HINTS = (
    "carousel",
    "gallery",
    "media",
    "pdp",
    "photo",
    "product",
    "slider",
    "thumb",
    "zoom",
)
_NON_PRODUCT_IMAGE_HINTS = (
    "avatar",
    "badge",
    "blog",
    "brand",
    "breadcrumb",
    "flag",
    "icon",
    "logo",
    "payment",
    "placeholder",
    "promo",
    "rating",
    "review",
    "social",
    "sprite",
)
_CDN_IMAGE_PATH_SUFFIX_RE = regex_lib.compile(
    r"_(?:\d+x\d+|pico|icon|thumb|small|compact|medium|large|grande|original)(?=\.[a-z0-9]+$)",
    regex_lib.I,
)


def _srcset_urls(value: object) -> list[str]:
    urls: list[str] = []
    for part in str(value or "").split(","):
        token = " ".join(str(part or "").split()).strip()
        if not token:
            continue
        urls.append(token.split(" ", 1)[0].strip())
    return [url for url in urls if url]


def _looks_like_image_asset_url(url: str) -> bool:
    lowered = clean_text(url).lower()
    if not lowered or lowered.startswith(("data:", "javascript:", "mailto:")):
        return False
    parsed = urlparse(lowered)
    path = parsed.path or ""
    host_and_path = f"{parsed.netloc}{path}"
    if any(path.endswith(ext) for ext in _IMAGE_FILE_EXTENSIONS):
        return True
    if any(path.endswith(ext) for ext in _PAGE_FILE_EXTENSIONS):
        return False
    if any(marker in path for marker in detail_path_hints()):
        return False
    if any(hint in host_and_path for hint in _IMAGE_URL_HINTS):
        return True
    query = parsed.query
    return "format=" in query or "fm=" in query


def _canonical_image_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if str(key or "").strip().lower() not in _CDN_IMAGE_QUERY_PARAMS
    ]
    normalized_path = _CDN_IMAGE_PATH_SUFFIX_RE.sub("", parsed.path or "")
    return urlunparse(
        parsed._replace(
            path=normalized_path,
            query=urlencode(filtered_query, doseq=True),
            fragment="",
        )
    ).lower()


def _image_candidate_score(url: str) -> tuple[int, int, int]:
    parsed = urlparse(str(url or "").strip())
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    numeric_params = {
        str(key or "").strip().lower(): str(value or "").strip()
        for key, value in query_pairs
    }

    def _int_param(*names: str) -> int:
        for name in names:
            try:
                return int(numeric_params.get(name, "0") or "0")
            except ValueError:
                continue
        return 0

    _WIDTH_NAMES = tuple(p for p in ("width", "w") if p in _CDN_IMAGE_QUERY_PARAMS)
    _HEIGHT_NAMES = tuple(p for p in ("height", "h") if p in _CDN_IMAGE_QUERY_PARAMS)
    width = _int_param(*_WIDTH_NAMES)
    height = _int_param(*_HEIGHT_NAMES)
    area = width * height if width and height else max(width, height)
    return (area, width, height)


def _dedupe_image_urls(urls: list[str]) -> list[str]:
    best_by_key: dict[str, tuple[tuple[int, int, int], int, str]] = {}
    order: list[str] = []
    for index, url in enumerate(urls):
        canonical = _canonical_image_url(url)
        if not canonical:
            continue
        score = _image_candidate_score(url)
        current = best_by_key.get(canonical)
        if current is None:
            best_by_key[canonical] = (score, index, url)
            order.append(canonical)
            continue
        current_score, current_index, current_url = current
        if score > current_score or (score == current_score and index < current_index):
            best_by_key[canonical] = (score, current_index, url if score > current_score else current_url)
    return [best_by_key[key][2] for key in order]


def _node_attr_text(node: Tag, *, max_depth: int = 6) -> str:
    parts: list[str] = []
    current: Tag | None = node
    depth = 0
    while isinstance(current, Tag) and depth < max_depth:
        for attr_name in (
            "id",
            "class",
            "data-component",
            "data-qa",
            "data-section",
            "data-section-id",
            "data-section-type",
            "data-testid",
            "aria-label",
        ):
            value = current.get(attr_name)
            if isinstance(value, list):
                parts.extend(str(item) for item in value if item)
            elif value not in (None, "", [], {}):
                parts.append(str(value))
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
        depth += 1
    return " ".join(parts).lower()


def _is_non_primary_image_context(node: Tag) -> bool:
    context = _node_attr_text(node)
    return any(hint in context for hint in _NON_PRIMARY_IMAGE_SECTION_HINTS)


def _image_node_context(node: Tag) -> str:
    parts = [_node_attr_text(node)]
    alt = node.get("alt")
    if alt not in (None, "", [], {}):
        parts.append(str(alt))
    return " ".join(parts).lower()


def _is_garbage_image_candidate(node: Tag, candidate_url: str) -> bool:
    lowered = str(candidate_url or "").lower()
    context = _image_node_context(node)
    if any(token in lowered for token in _NON_PRODUCT_IMAGE_HINTS):
        return True
    return any(token in context for token in _NON_PRODUCT_IMAGE_HINTS)


def _gallery_image_score(node: Tag, candidate_url: str) -> int:
    context = _image_node_context(node)
    score = 0
    if any(hint in context for hint in _PRODUCT_GALLERY_CONTEXT_HINTS):
        score += 4
    width = str(node.get("width") or "").strip()
    height = str(node.get("height") or "").strip()
    try:
        if int(width or "0") >= 120 or int(height or "0") >= 120:
            score += 1
    except ValueError:
        pass
    if "srcset" in node.attrs or "data-srcset" in node.attrs:
        score += 1
    if _looks_like_image_asset_url(candidate_url):
        score += 1
    if node.find_parent("picture") is not None:
        score += 1
    return score


def _candidate_image_urls_from_node(node: Tag, page_url: str) -> list[str]:
    candidates: list[str] = []
    for raw_value in (
        node.get("srcset"),
        node.get("data-srcset"),
    ):
        if raw_value not in (None, "", [], {}):
            candidates.extend(extract_urls(_srcset_urls(raw_value), page_url))
    fallback = (
        node.get("src")
        or node.get("data-src")
        or node.get("data-original")
        or node.get("data-image")
        or ""
    )
    if fallback:
        candidates.extend(extract_urls(fallback, page_url))
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def _is_other_detail_link(
    url: str,
    page_url: str,
    *,
    surface: str | None = None,
    link_node: Tag | None = None,
) -> bool:
    candidate = clean_text(url)
    if not candidate:
        return False
    lowered = candidate.lower()
    if lowered.startswith(("#", "javascript:", "mailto:")) or _looks_like_image_asset_url(candidate):
        return False
    page_parts = urlparse(page_url)
    candidate_parts = urlparse(candidate)
    same_host = (page_parts.hostname or "").lower() == (candidate_parts.hostname or "").lower()
    same_path = (page_parts.path.rstrip("/") or "/") == (candidate_parts.path.rstrip("/") or "/")
    if same_host and same_path:
        return False
    is_detail_surface = "detail" in str(surface or "").lower()
    path = (candidate_parts.path or "").lower()
    if any(path.endswith(ext) for ext in _PAGE_FILE_EXTENSIONS):
        return True
    if any(marker in path for marker in detail_path_hints(surface)):
        return True
    if is_detail_surface and same_host and not same_path:
        return True
    if link_node is not None and _is_in_cross_link_container(link_node):
        return True
    return False


def _is_in_cross_link_container(node: Tag, *, max_depth: int = 6) -> bool:
    current: Tag | None = node
    depth = 0
    while isinstance(current, Tag) and depth < max_depth:
        context = _node_attr_text(current)
        if any(hint in context for hint in _CROSS_LINK_CONTAINER_HINTS):
            return True
        current = current.parent
        depth += 1
    return False


def safe_select(root: BeautifulSoup | Tag, selector: str) -> list[Tag]:
    if not selector:
        return []
    try:
        return [node for node in root.select(selector) if isinstance(node, Tag)]
    except SelectorSyntaxError:
        logger.warning("Skipping invalid css selector: %s", selector)
        return []


def extract_node_value(node: Tag, field_name: str, page_url: str) -> object | None:
    if field_name in IMAGE_FIELDS:
        srcset = node.get("srcset")
        image_candidates: object = (
            _srcset_urls(srcset)
            if srcset not in (None, "", [], {})
            else (
                node.get("content")
                or node.get("src")
                or node.get("data-src")
                or node.get("data-image")
                or node.get("href")
                or ""
            )
        )
        urls = extract_urls(
            image_candidates,
            page_url,
        )
        if node.name not in {"img", "source"} and str(node.get("as") or "").lower() != "image":
            urls = [url for url in urls if _looks_like_image_asset_url(url)]
        if field_name == "additional_images":
            return urls or None
        return urls[0] if urls else None
    if field_name in URL_FIELDS:
        urls = extract_urls(
            node.get("href") or node.get("content") or node.get("data-apply-url") or "",
            page_url,
        )
        return urls[0] if urls else None
    if node.name == "meta":
        return coerce_field_value(field_name, node.get("content"), page_url)
    for attr_name in ("content", "value", "datetime", "data-value", "data-price", "data-availability"):
        attr_value = node.get(attr_name)
        if attr_value not in (None, "", [], {}):
            return coerce_field_value(field_name, attr_value, page_url)
    return coerce_field_value(field_name, node.get_text(" ", strip=True), page_url)


def extract_selector_values(
    root: BeautifulSoup | Tag,
    selector: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    values: list[object] = []
    for node in safe_select(root, selector)[:12]:
        value = extract_node_value(node, field_name, page_url)
        if value in (None, "", [], {}):
            continue
        values.append(value)
    return values


def extract_xpath_values(
    root: BeautifulSoup | Tag,
    xpath: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    valid_xpath, _ = validate_xpath_syntax(xpath)
    if not valid_xpath:
        logger.warning("Skipping invalid xpath selector for %s: %s", field_name, xpath)
        return []
    try:
        tree = lxml_html.fromstring(str(root))
    except (etree.ParserError, ValueError):
        return []
    try:
        matches = tree.xpath(xpath)
    except etree.XPathError:
        logger.warning("Failed to evaluate xpath selector for %s: %s", field_name, xpath)
        return []
    values: list[object] = []
    for match in matches[:12]:
        if hasattr(match, "text_content"):
            raw_value = match.text_content()
        else:
            raw_value = str(match)
        value = coerce_field_value(field_name, raw_value, page_url)
        if value in (None, "", [], {}):
            continue
        values.append(value)
    return values


def extract_regex_values(
    root: BeautifulSoup | Tag,
    pattern: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    html_text = str(root)
    values: list[object] = []
    try:
        matches = regex_lib.finditer(pattern, html_text, regex_lib.DOTALL, timeout=0.05)
        for match in matches:
            raw_value = next((group for group in match.groups() if group), None)
            if raw_value is None:
                raw_value = match.group(0)
            value = coerce_field_value(field_name, raw_value, page_url)
            if value in (None, "", [], {}):
                continue
            values.append(value)
            if len(values) >= 12:
                break
    except TimeoutError:
        logger.warning("Timed out while evaluating selector regex for %s", field_name)
    except regex_lib.error:
        logger.warning("Failed to evaluate selector regex for %s", field_name)
    return values


def filter_values_by_regex(
    values: list[object],
    pattern: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    filtered: list[object] = []
    try:
        for candidate in values:
            match = regex_lib.search(
                pattern,
                str(candidate),
                regex_lib.DOTALL,
                timeout=0.05,
            )
            if not match:
                continue
            raw_value = next((group for group in match.groups() if group), None)
            if raw_value is None:
                raw_value = match.group(0)
            value = coerce_field_value(field_name, raw_value, page_url)
            if value in (None, "", [], {}):
                continue
            filtered.append(value)
            if len(filtered) >= 12:
                break
    except TimeoutError:
        logger.warning("Timed out while evaluating selector regex for %s", field_name)
    except regex_lib.error:
        logger.warning("Failed to evaluate selector regex for %s", field_name)
    return filtered


def extract_page_images(
    root: BeautifulSoup | Tag,
    page_url: str,
    *,
    exclude_linked_detail_images: bool = False,
    surface: str | None = None,
) -> list[str]:
    scored_values: list[tuple[int, int, str]] = []
    for index, node in enumerate(root.find_all(["img", "source"])):
        if _is_non_primary_image_context(node):
            continue
        if exclude_linked_detail_images:
            link = node.find_parent("a", href=True)
            if link is not None and _is_other_detail_link(
                absolute_url(page_url, link.get("href")),
                page_url,
                surface=surface,
                link_node=link,
            ):
                continue
        for candidate in _candidate_image_urls_from_node(node, page_url):
            lowered = candidate.lower()
            if lowered.startswith("data:"):
                continue
            if any(
                token in lowered
                for token in (
                    "analytics",
                    "tracking",
                    "pixel",
                    "spacer",
                    "blank.gif",
                    "doubleclick",
                    "google-analytics",
                    "googletagmanager",
                )
            ):
                continue
            if _is_garbage_image_candidate(node, candidate):
                continue
            scored_values.append((_gallery_image_score(node, candidate), index, candidate))
    ordered = [
        candidate
        for _score, _index, candidate in sorted(
            scored_values,
            key=lambda row: (-int(row[0]), int(row[1]), str(row[2])),
        )
    ]
    return _dedupe_image_urls(ordered)[:12]


def extract_label_value_pairs(root: BeautifulSoup | Tag) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for tr in root.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = clean_text(cells[0].get_text(" ", strip=True))
        value = clean_text(cells[1].get_text(" ", strip=True))
        if label and value:
            rows.append((label, value))
    for dt in root.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        label = clean_text(dt.get_text(" ", strip=True))
        value = clean_text(dd.get_text(" ", strip=True))
        if label and value:
            rows.append((label, value))
    for node in root.find_all(["li", "p", "div", "span"]):
        text = clean_text(node.get_text(" ", strip=True))
        if ":" not in text:
            continue
        label, value = text.split(":", 1)
        label = clean_text(label)
        value = clean_text(value)
        if not label or not value:
            continue
        if len(label) > 40 or len(value) > 250:
            continue
        rows.append((label, value))
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, value in rows:
        key = (label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, value))
    return deduped


def extract_heading_sections(root: BeautifulSoup | Tag) -> dict[str, str]:
    sections: dict[str, str] = {}
    for heading in root.find_all(["h2", "h3", "h4", "h5", "strong"]):
        heading_text = clean_text(heading.get_text(" ", strip=True))
        if len(heading_text) < 3 or len(heading_text) > 60:
            continue
        values: list[str] = []
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in {"h1", "h2", "h3", "h4", "h5"}:
                break
            text = clean_text(
                sibling.get_text(" ", strip=True) if isinstance(sibling, Tag) else str(sibling)
            )
            if not text:
                continue
            values.append(text)
            if len(values) >= 4 or sum(len(item) for item in values) >= 1000:
                break
        if values:
            sections[heading_text] = " ".join(values)
    return sections


def apply_selector_fallbacks(
    root: BeautifulSoup | Tag,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    candidates: dict[str, list[object]],
    selector_rules: list[dict[str, object]] | None = None,
    *,
    candidate_sources: dict[str, list[str]] | None = None,
    field_sources: dict[str, list[str]] | None = None,
) -> None:
    def _add(field_name: str, value: object, source: str) -> None:
        growth = add_candidate(candidates, field_name, value)
        if growth <= 0:
            return
        if candidate_sources is not None:
            candidate_sources.setdefault(field_name, []).extend([source] * growth)
        if field_sources is not None:
            bucket = field_sources.setdefault(field_name, [])
            public_source = "dom_selector" if source == "selector_rule" else source
            if public_source not in bucket:
                bucket.append(public_source)

    fields = surface_fields(surface, requested_fields)
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    selector_hit_fields: set[str] = set()
    for row in list(selector_rules or []):
        if not isinstance(row, dict):
            continue
        field_name = normalize_field_key(str(row.get("field_name") or ""))
        if field_name not in fields or not bool(row.get("is_active", True)):
            continue
        xpath = str(row.get("xpath") or "").strip()
        css_selector = str(row.get("css_selector") or "").strip()
        regex = str(row.get("regex") or "").strip()
        values: list[object] = []
        if xpath:
            values = extract_xpath_values(root, xpath, field_name, page_url)
        if not values and css_selector:
            values = extract_selector_values(root, css_selector, field_name, page_url)
        if values and regex:
            values = filter_values_by_regex(values, regex, field_name, page_url)
        elif not values and regex and not xpath and not css_selector:
            values = extract_regex_values(root, regex, field_name, page_url)
        for value in values:
            _add(field_name, value, "selector_rule")
        if values:
            selector_hit_fields.add(field_name)
    dom_patterns = dict(EXTRACTION_RULES.get("dom_patterns") or {})
    for field_name in fields:
        if field_name in selector_hit_fields:
            continue
        selector = str(dom_patterns.get(field_name) or "").strip()
        if not selector:
            continue
        for value in extract_selector_values(root, selector, field_name, page_url):
            _add(field_name, value, "dom_selector")
    for label, value in extract_label_value_pairs(root):
        normalized_label = normalize_requested_field(label) or normalize_field_key(label)
        canonical = alias_lookup.get(normalized_label)
        if canonical:
            _add(canonical, coerce_field_value(canonical, value, page_url), "dom_selector")
