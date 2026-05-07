"""Shared DOM field recovery, DOM text cleanup, and image/section normalization."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
import regex as regex_lib
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse, unquote

from bs4 import BeautifulSoup, NavigableString, Tag
from lxml import etree
from lxml import html as lxml_html
from soupsieve import SelectorSyntaxError

from app.services.config.extraction_rules import (
    CROSS_LINK_CONTAINER_HINTS,
    CDN_IMAGE_QUERY_PARAMS,
    DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS,
    DETAIL_LONG_TEXT_RANK_FIELDS,
    DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS,
    DETAIL_LONG_TEXT_MAX_SECTION_CHARS,
    DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR,
    DETAIL_TEXT_HIDDEN_STYLE_TOKENS,
    DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS,
    DETAIL_TEXT_SCOPE_PRIORITY_TOKENS,
    DETAIL_TEXT_SCOPE_SELECTORS,
    EXTRACTION_RULES,
    FEATURE_SECTION_ALIASES,
    FEATURE_SECTION_SELECTORS,
    NON_PRODUCT_IMAGE_HINTS,
    NON_PRODUCT_PROVIDER_HINTS,
    PRODUCT_GALLERY_CONTEXT_HINTS,
    SEMANTIC_SECTION_NOISE,
    SEMANTIC_SECTION_LABEL_SKIP_TOKENS,
    MAX_SELECTOR_MATCHES,
    VARIANT_OPTION_TEXT_CHILD_DROP_PATTERNS,
    VARIANT_OPTION_TEXT_FIELDS,
    SCOPE_PRODUCT_CONTEXT_TOKENS,
    SCOPE_SCORE_MAIN_WEIGHT,
    SCOPE_SCORE_PRIORITY_WEIGHT,
    SCOPE_SCORE_PRODUCT_CONTEXT_WEIGHT,
    UNRESOLVED_TEMPLATE_URL_TOKENS,
)
from app.services.config.surface_hints import detail_path_hints
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.field_mappings import ADDITIONAL_IMAGES_FIELD
from app.services.extraction_html_helpers import html_to_text
from app.services.field_policy import (
    exact_requested_field_key,
    normalize_field_key,
    normalize_requested_field,
)
from app.services.field_value_candidates import add_candidate
from app.services.field_value_core import (
    IMAGE_FIELDS,
    LONG_TEXT_FIELDS,
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

def _safe_int(value: object, default: int) -> int:
    try:
        parsed = int(str(value).strip())
        return parsed if parsed >= 0 else default
    except (TypeError, ValueError):
        return default

_max_section_blocks = _safe_int(DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS, 8)
_max_section_chars = _safe_int(DETAIL_LONG_TEXT_MAX_SECTION_CHARS, 1200)
_cross_product_container_tokens = tuple(
    clean_text(token).lower() for token in tuple(DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS or ()) if clean_text(token)
)
_scope_product_context_tokens = tuple(
    clean_text(token).lower() for token in tuple(SCOPE_PRODUCT_CONTEXT_TOKENS or ()) if clean_text(token)
)
_max_selector_matches = _safe_int(MAX_SELECTOR_MATCHES, 12)
_scope_score_main_weight = _safe_int(SCOPE_SCORE_MAIN_WEIGHT, 4000)
_scope_score_priority_weight = _safe_int(SCOPE_SCORE_PRIORITY_WEIGHT, 2000)
_scope_score_product_context_weight = _safe_int(SCOPE_SCORE_PRODUCT_CONTEXT_WEIGHT, 1000)

def _compile_variant_option_child_drop_patterns() -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in tuple(VARIANT_OPTION_TEXT_CHILD_DROP_PATTERNS or ()):
        if not str(pattern).strip():
            continue
        try:
            compiled.append(re.compile(str(pattern), re.I))
        except re.error:
            logger.warning("Skipping invalid variant option child-drop pattern: %r", pattern)
    return tuple(compiled)

_VARIANT_OPTION_CHILD_DROP_RE = _compile_variant_option_child_drop_patterns()

_candidate_cleanup_raw = EXTRACTION_RULES.get("candidate_cleanup")
_CANDIDATE_CLEANUP = (
    dict(_candidate_cleanup_raw) if isinstance(_candidate_cleanup_raw, dict) else {}
)
_IMAGE_FILE_EXTENSIONS = tuple(_CANDIDATE_CLEANUP.get("image_file_extensions") or ())
_PAGE_FILE_EXTENSIONS = (".asp", ".aspx", ".htm", ".html", ".jsp", ".php")
_IMAGE_URL_HINTS = tuple(_CANDIDATE_CLEANUP.get("image_url_hint_tokens") or ())
_NON_PRIMARY_IMAGE_SECTION_HINTS = tuple(
    str(token).lower()
    for token in (SEMANTIC_SECTION_NOISE.get("label_skip_tokens") or ())
)
_CDN_IMAGE_QUERY_PARAMS = frozenset(CDN_IMAGE_QUERY_PARAMS or ())
_CDN_IMAGE_PATH_SUFFIX_RE = regex_lib.compile(
    r"(?:"
    r"_(?:\d+x\d+|pico|icon|thumb|thumbnail|small|compact|medium|large|grande|original)"
    r"|[._](?:AC_)?(?:US|SR|SL|SX|SY|SS)\d+_?"
    r"|/t_(?:default|thumbnail|pdp_\d+_v\d+|web_pdp_\d+_v\d+)"
    r")(?=\.[a-z0-9]+$|/|$)",
    regex_lib.I,
)
_IMAGE_PATH_DIMENSION_RE = re.compile(
    r"(?:[/?_=-])(?:w|wid|width|h|hei|height|sl|sx|sy|us)?[_=-]?(\d{2,4})(?:x(\d{2,4}))?",
    re.I,
)


def _selector_regex_timeout_seconds() -> float | None:
    try:
        timeout = float(crawler_runtime_settings.selector_regex_timeout_seconds)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid selector_regex_timeout_seconds=%r; disabling selector regex timeout",
            crawler_runtime_settings.selector_regex_timeout_seconds,
        )
        return None
    return timeout if timeout > 0 else None


_SECTION_SKIP_PATTERNS = tuple(
    str(token).lower() for token in (SEMANTIC_SECTION_NOISE.get("skip_patterns") or ())
)
_detail_text_scope_selectors = tuple(
    selector
    for selector in tuple(DETAIL_TEXT_SCOPE_SELECTORS or ())
    if str(selector).strip()
)
_detail_text_scope_priority_tokens = tuple(
    str(token).lower()
    for token in tuple(DETAIL_TEXT_SCOPE_PRIORITY_TOKENS or ())
    if str(token).strip()
)
_detail_text_scope_exclude_tokens = tuple(
    str(token).lower()
    for token in tuple(DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS or ())
    if str(token).strip()
)
_detail_text_hidden_style_tokens = tuple(
    str(token).lower()
    for token in tuple(DETAIL_TEXT_HIDDEN_STYLE_TOKENS or ())
    if str(token).strip()
)
_FEATURE_SECTION_ALIASES = frozenset(
    normalize_field_key(str(value))
    for value in tuple(FEATURE_SECTION_ALIASES or ())
    if str(value).strip()
)
_feature_section_selector = ", ".join(str(s) for s in tuple(FEATURE_SECTION_SELECTORS or ()) if str(s).strip())


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


def canonical_image_url(url: str) -> str:
    effective_url = _effective_image_url(url)
    parsed = urlparse(_normalize_image_url_text(effective_url))
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


def _effective_image_url(url: str) -> str:
    text = _normalize_image_url_text(url)
    if not text:
        return ""
    parsed = urlparse(text)
    path = str(parsed.path or "").lower()
    if "/_next/image" not in path:
        return text
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    wrapped = str(query.get("url") or "").strip()
    if not wrapped:
        return text
    return unquote(wrapped) or text


def _normalize_image_url_text(url: object) -> str:
    text = str(url or "").strip()
    for scheme in ("https", "http"):
        prefix = f"{scheme}:"
        if text.lower().startswith(prefix):
            remainder = text[len(prefix) :]
            if remainder.startswith("/"):
                return f"{scheme}://{remainder.lstrip('/')}"
    return text


def _is_proxy_image_url(url: str) -> bool:
    path = str(urlparse(str(url or "").strip()).path or "").lower()
    return "/_next/image" in path


def image_candidate_score(url: str) -> tuple[int, int, int, int]:
    normalized_url = _normalize_image_url_text(url)
    parsed = urlparse(normalized_url)
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
    if not width or not height:
        for match in _IMAGE_PATH_DIMENSION_RE.finditer(normalized_url):
            first = int(match.group(1) or 0)
            second = int(match.group(2) or 0)
            width = max(width, first)
            height = max(height, second or first)
    area = width * height if width and height else max(width, height)
    return (0 if _is_proxy_image_url(url) else 1, area, width, height)


def dedupe_image_urls(urls: list[str]) -> list[str]:
    best_by_key: dict[str, tuple[tuple[int, int, int, int], int, str]] = {}
    order: list[str] = []
    for index, url in enumerate(urls):
        normalized_url = _normalize_image_url_text(url)
        lowered = normalized_url.lower()
        if (
            not lowered
            or lowered.endswith(".mp4")
            or any(token in lowered for token in NON_PRODUCT_IMAGE_HINTS)
            or any(token in lowered for token in NON_PRODUCT_PROVIDER_HINTS)
        ):
            continue
        canonical = canonical_image_url(url)
        if not canonical:
            continue
        score = image_candidate_score(url)
        current = best_by_key.get(canonical)
        if current is None:
            best_by_key[canonical] = (score, index, normalized_url)
            order.append(canonical)
            continue
        current_score, current_index, current_url = current
        if score > current_score or (score == current_score and index < current_index):
            best_by_key[canonical] = (
                score,
                current_index,
                normalized_url if score > current_score else current_url,
            )
    return [best_by_key[key][2] for key in order]


def upgrade_low_resolution_image_url(url: str) -> str:
    normalized_url = _normalize_image_url_text(url)
    parsed = urlparse(normalized_url)
    host = str(parsed.netloc or "").lower()
    if host not in {"m.media-amazon.com", "images-na.ssl-images-amazon.com"}:
        return normalized_url
    path = re.sub(
        r"\._(?:AC_)?(?:US|SR|SL|SX|SY|SS)\d+_?(?=\.[a-z0-9]+$)",
        "",
        parsed.path or "",
        flags=re.I,
    )
    return urlunparse(parsed._replace(path=path))


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

def _field_uses_scoped_text(field_name: str) -> bool:
    return field_name in DETAIL_LONG_TEXT_RANK_FIELDS

def _node_within_scope(node: Tag, scope: Tag) -> bool:
    current: Tag | None = node
    while isinstance(current, Tag):
        if current is scope:
            return True
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return False


def _node_style_is_hidden(node: Tag) -> bool:
    style = str(node.get("style") or "").strip().lower()
    return bool(style) and any(token in style for token in _detail_text_hidden_style_tokens)


def _node_is_hidden_or_auxiliary(node: Tag) -> bool:
    current: Tag | None = node
    depth = 0
    while isinstance(current, Tag) and depth < 8:
        attrs = getattr(current, "attrs", None)
        if not isinstance(attrs, dict):
            parent = current.parent
            current = parent if isinstance(parent, Tag) else None
            depth += 1
            continue
        if "hidden" in attrs:
            return True
        if str(attrs.get("aria-hidden") or "").strip().lower() == "true":
            return True
        if str(attrs.get("aria-modal") or "").strip().lower() == "true":
            return True
        role = str(attrs.get("role") or "").strip().lower()
        if role in {"dialog", "alertdialog"}:
            return True
        if _node_style_is_hidden(current):
            return True
        context = _node_attr_text(current, max_depth=1)
        if any(token in context for token in _detail_text_scope_exclude_tokens):
            return True
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
        depth += 1
    return False

def _node_has_cross_product_cluster(node: Tag, *, page_url: str = "") -> bool:
    if not isinstance(getattr(node, "attrs", None), dict):
        return False
    links: list[str] = []
    for link in node.select("a[href]")[:_max_selector_matches]:
        link_text = clean_text(link.get_text(" ", strip=True) or link.get("aria-label"))
        if not link_text:
            continue
        resolved = absolute_url(page_url, str(link.get("href") or ""))
        if resolved:
            links.append(resolved)
    product_links = [
        link
        for link in links
        if any(marker in urlparse(link).path.lower() for marker in detail_path_hints("ecommerce_detail"))
    ]
    if len(set(product_links)) >= 2:
        return True
    context = _node_attr_text(node, max_depth=1)
    return any(token in context for token in _cross_product_container_tokens)


def _candidate_text_scope_nodes(root: BeautifulSoup | Tag) -> list[Tag]:
    candidates: list[Tag] = []
    seen: set[int] = set()
    for selector in _detail_text_scope_selectors:
        for node in safe_select(root, selector):
            if id(node) in seen or _node_is_hidden_or_auxiliary(node):
                continue
            seen.add(id(node))
            candidates.append(node)
    return candidates


def _scope_score(node: Tag) -> tuple[int, int]:
    context = _node_attr_text(node, max_depth=2)
    text_len = len(clean_text(node.get_text(" ", strip=True)))
    score = text_len
    if node.name in {"main", "article"} or str(node.get("role") or "").strip().lower() == "main":
        score += _scope_score_main_weight
    if any(token in context for token in _detail_text_scope_priority_tokens):
        score += _scope_score_priority_weight
    if DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR and (
        node.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR) is not None
        or any(
            token in context
            for token in _scope_product_context_tokens
        )
    ):
        score += _scope_score_product_context_weight
    return score, text_len


def _scope_is_product_like(node: Tag) -> bool:
    context = _node_attr_text(node, max_depth=2)
    if any(token in context for token in _scope_product_context_tokens):
        return True
    return bool(
        DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR
        and node.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR) is not None
    )


def _best_text_scope(root: BeautifulSoup | Tag) -> Tag | None:
    candidates = _candidate_text_scope_nodes(root)
    if not candidates:
        return None
    best = max(candidates, key=_scope_score)
    return best if _scope_is_product_like(best) else None


def _clone_visible_only(
    node: Tag | NavigableString,
    *,
    remaining_depth: int = 50,
    _soup: BeautifulSoup | None = None,
) -> Tag | NavigableString | None:
    if remaining_depth <= 0:
        return None
    if not isinstance(node, Tag):
        return NavigableString(str(node)) if isinstance(node, NavigableString) else None
    if _node_is_hidden_or_auxiliary(node):
        return None
    _soup = _soup or BeautifulSoup("", "html.parser")
    clone = _soup.new_tag(node.name, attrs=dict(getattr(node, "attrs", {}) or {}))
    for child in node.children:
        if (
            child_clone := _clone_visible_only(
                cast(Tag | NavigableString, child),
                remaining_depth=remaining_depth - 1,
                _soup=_soup,
            )
        ) is not None:
            clone.append(child_clone)
    return clone


def _pruned_text_scope_root(root: BeautifulSoup | Tag) -> BeautifulSoup | Tag:
    scope = _best_text_scope(root)
    if scope is None:
        return root
    cloned_scope = _clone_visible_only(scope)
    return cloned_scope if isinstance(cloned_scope, Tag) else root


def _is_non_primary_image_context(node: Tag) -> bool:
    context = _node_attr_text(node)
    return any(hint in context for hint in _NON_PRIMARY_IMAGE_SECTION_HINTS) or any(
        token in context
        for token in _detail_text_scope_exclude_tokens
    )


def _image_node_context(node: Tag) -> str:
    parts = [_node_attr_text(node)]
    alt = node.get("alt")
    if alt not in (None, "", [], {}):
        parts.append(str(alt))
    return " ".join(parts).lower()


def _is_in_product_gallery_context(node: Tag, *, max_depth: int = 6) -> bool:
    current: Tag | None = node
    depth = 0
    in_main = False
    while isinstance(current, Tag) and depth < max_depth:
        if (
            current.name == "main"
            or str(current.get("role") or "").strip().lower() == "main"
        ):
            in_main = True
        context = _node_attr_text(current)
        if any(hint in context for hint in PRODUCT_GALLERY_CONTEXT_HINTS):
            if in_main or any(
                token in context for token in ("gallery", "media", "pdp", "product")
            ):
                return True
        current = current.parent
        depth += 1
    return False


_UNRESOLVED_TEMPLATE_URL_RE = re.compile(
    "|".join(re.escape(str(token)) for token in tuple(UNRESOLVED_TEMPLATE_URL_TOKENS or ()) if str(token).strip()) or r"(?!)",
    re.IGNORECASE,
)


def _is_garbage_image_candidate(node: Tag, candidate_url: str) -> bool:
    lowered = str(candidate_url or "").lower()
    context = _image_node_context(node)
    if lowered.endswith(".svg") and not _is_in_product_gallery_context(node):
        return True
    if _UNRESOLVED_TEMPLATE_URL_RE.search(candidate_url or ""):
        return True
    if any(token in lowered for token in NON_PRODUCT_IMAGE_HINTS):
        return True
    if any(token in lowered for token in NON_PRODUCT_PROVIDER_HINTS):
        return True
    return any(
        token in context
        for token in (*NON_PRODUCT_IMAGE_HINTS, *NON_PRODUCT_PROVIDER_HINTS)
    )


def _gallery_image_score(node: Tag, candidate_url: str) -> int:
    context = _image_node_context(node)
    score = 0
    if any(hint in context for hint in PRODUCT_GALLERY_CONTEXT_HINTS):
        score += 4
    elif node.find_parent(["main"]) is not None and _looks_like_image_asset_url(
        candidate_url
    ):
        score += 2
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
    if lowered.startswith(
        ("#", "javascript:", "mailto:")
    ) or _looks_like_image_asset_url(candidate):
        return False
    page_parts = urlparse(page_url)
    candidate_parts = urlparse(candidate)
    same_host = (page_parts.hostname or "").lower() == (
        candidate_parts.hostname or ""
    ).lower()
    same_path = (page_parts.path.rstrip("/") or "/") == (
        candidate_parts.path.rstrip("/") or "/"
    )
    if same_host and same_path:
        return False
    is_detail_surface = "detail" in str(surface or "").lower()
    if (
        is_detail_surface
        and link_node is not None
        and _is_in_product_gallery_context(link_node)
    ):
        return False
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
        if any(hint in context for hint in CROSS_LINK_CONTAINER_HINTS):
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
        if (
            node.name not in {"img", "source"}
            and str(node.get("as") or "").lower() != "image"
        ):
            urls = [url for url in urls if _looks_like_image_asset_url(url)]
        if field_name == ADDITIONAL_IMAGES_FIELD:
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
    for attr_name in (
        "content",
        "value",
        "datetime",
        "data-value",
        "data-price",
        "data-availability",
    ):
        attr_value = node.get(attr_name)
        if attr_value not in (None, "", [], {}):
            return coerce_field_value(field_name, attr_value, page_url)
    raw_text = (
        _variant_option_node_text(node, field_name)
        if _looks_like_variant_option_node(node, field_name)
        else (
            html_to_text(str(_clone_visible_only(node) or node), preserve_block_breaks=True)
            if _field_uses_scoped_text(field_name)
            else (_clone_visible_only(node) or node).get_text(" ", strip=True)
        )
    )
    text_value = coerce_field_value(field_name, raw_text, page_url)
    if field_name in LONG_TEXT_FIELDS and not _section_text_is_meaningful(
        node,
        label=field_name,
        text=str(text_value or ""),
    ):
        return None
    return text_value


def _looks_like_variant_option_node(node: Tag, field_name: str) -> bool:
    if field_name not in VARIANT_OPTION_TEXT_FIELDS:
        return False
    if node.name in {"option", "button"}:
        return True
    role = str(node.get("role") or "").strip().lower()
    if role in {"option", "radio", "button", "tab"}:
        return True
    context = " ".join(
        _attribute_text(value)
        for value in (
            node.get("class"),
            node.get("aria-label"),
            node.get("data-testid"),
            node.get("data-test"),
            node.get("data-qa"),
            node.get("name"),
        )
    ).lower()
    return any(
        token in context for token in ("option", "swatch", "variant", field_name)
    )


def _attribute_text(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item or "") for item in value)
    return str(value or "")


def _variant_option_node_text(node: Tag, _field_name: str) -> str:
    if not node.find(True):
        return node.get_text(" ", strip=True)
    pruned = deepcopy(node)
    for child in list(pruned.find_all(True)):
        text = clean_text(child.get_text(" ", strip=True))
        if text and any(
            pattern.search(text) for pattern in _VARIANT_OPTION_CHILD_DROP_RE
        ):
            child.decompose()
    return pruned.get_text(" ", strip=True)


def extract_selector_values(
    root: BeautifulSoup | Tag,
    selector: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    values: list[object] = []
    scoped_text_root = _best_text_scope(root) if _field_uses_scoped_text(field_name) else None
    for node in safe_select(root, selector)[:_max_selector_matches]:
        if _field_uses_scoped_text(field_name):
            if _node_is_hidden_or_auxiliary(node):
                continue
            if scoped_text_root is not None and not _node_within_scope(node, scoped_text_root):
                continue
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
        logger.warning(
            "Failed to evaluate xpath selector for %s: %s", field_name, xpath
        )
        return []
    values: list[object] = []
    limited_matches: list[object]
    if isinstance(matches, list):
        limited_matches = [*matches[:_max_selector_matches]]
    elif isinstance(matches, (str, bytes, bool, float)):
        limited_matches = [matches]
    else:
        try:
            limited_matches = list(matches)[:_max_selector_matches]
        except TypeError:
            limited_matches = [matches]
    for match in limited_matches:
        if isinstance(match, lxml_html.HtmlElement):
            raw_value = match.text_content()
        elif isinstance(match, etree._Element):
            raw_value = " ".join(str(part) for part in match.itertext())
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
    timeout = _selector_regex_timeout_seconds()
    try:
        matches = regex_lib.finditer(
            pattern,
            html_text,
            regex_lib.DOTALL,
            timeout=timeout,
        )
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
    timeout = _selector_regex_timeout_seconds()
    try:
        for candidate in values:
            match = regex_lib.search(
                pattern,
                str(candidate),
                regex_lib.DOTALL,
                timeout=timeout,
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
            scored_values.append(
                (_gallery_image_score(node, candidate), index, candidate)
            )
    ordered = [
        candidate
        for _score, _index, candidate in sorted(
            scored_values,
            key=lambda row: (-int(row[0]), int(row[1]), str(row[2])),
        )
    ]
    return dedupe_image_urls(ordered)[:_max_selector_matches]


def extract_label_value_pairs(root: BeautifulSoup | Tag) -> list[tuple[str, str]]:
    def node_text(node: BeautifulSoup | Tag) -> str:
        return clean_text(node.get_text(" ", strip=True))

    rows: list[tuple[str, str]] = []
    for tr in root.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = node_text(cells[0])
        value = node_text(cells[1])
        if label and value:
            rows.append((label, value))
    for dt in root.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        label = node_text(dt)
        value = node_text(dd)
        if label and value:
            rows.append((label, value))
    for node in root.find_all(["li", "p", "div", "span"]):
        text = node_text(node)
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


_SECTION_LABEL_SELECTOR = ",".join(
    [
        "summary",
        "details > summary",
        "button[aria-controls]",
        "[role='button'][aria-controls]",
        "[role='tab'][aria-controls]",
        "[data-accordion-heading]",
        "[data-tab-heading]",
        "button",
        "[role='button']",
        "[role='tab']",
        "h2",
        "h3",
        "h4",
        "h5",
        "strong",
    ]
)
_SECTION_CONTAINER_SELECTORS = (
    "[data-accordion-content]",
    "[data-collapse-content]",
    "[data-content]",
    "[data-details-content]",
    "[data-tab-content]",
    "[role='tabpanel']",
    "[aria-labelledby]",
    ".accordion__answer",
    ".accordion-content",
    ".accordion-panel",
    ".accordion-body",
    ".tabs__content",
    ".tab-content",
    ".tab-panel",
    ".panel",
    "[class*='accordion' i]",
    "[class*='content' i]",
    "[class*='details' i]",
    "[class*='description' i]",
    "[class*='spec' i]",
)
_SECTION_STOP_TAGS = {"h1", "h2", "h3", "h4", "h5", "summary"}
_MATERIAL_TEXT_HINTS = (
    "acrylic",
    "cashmere",
    "composition",
    "cotton",
    "elastane",
    "fabric",
    "leather",
    "linen",
    "material",
    "nylon",
    "polyester",
    "rayon",
    "shell",
    "silk",
    "spandex",
    "suede",
    "trim",
    "viscose",
    "wool",
)


def _section_label_text(node: Tag) -> str:
    pieces = [
        node.get_text(" ", strip=True),
        node.get("aria-label"),
        node.get("title"),
    ]
    return clean_text(next((piece for piece in pieces if piece), ""))


def _is_section_label(label: str) -> bool:
    cleaned = clean_text(label)
    if len(cleaned) < 3 or len(cleaned) > 80:
        return False
    if cleaned.lower() in {"details", "more", "overview"}:
        return False
    if any(token in cleaned.lower() for token in SEMANTIC_SECTION_LABEL_SKIP_TOKENS):
        return False
    return any(char.isalpha() for char in cleaned)


def _section_text(node: Tag, *, label: str = "") -> str:
    # Audit 2026-05-03: Use visibility-filtered clone to avoid hidden content leakage
    cloned = _clone_visible_only(node)
    if cloned is None:
        return ""
    text = html_to_text(str(cloned), preserve_block_breaks=True)
    text = clean_text(text)
    if not text:
        return ""
    if label and text.lower().startswith(label.lower()):
        text = clean_text(text[len(label) :])
    return text


def _extract_sibling_content(node: Tag, *, label: str = "") -> str:
    values: list[str] = []
    for sibling in node.next_siblings:
        if isinstance(sibling, Tag) and sibling.name in _SECTION_STOP_TAGS:
            break
        if isinstance(sibling, Tag) and _node_is_hidden_or_auxiliary(sibling):
            continue
        text = clean_text(
            sibling.get_text(" ", strip=True)
            if isinstance(sibling, Tag)
            else str(sibling)
        )
        if not text:
            continue
        if isinstance(sibling, Tag) and not _section_text_is_meaningful(
            sibling,
            label=label,
            text=text,
        ):
            continue
        values.append(text)
        if (
            len(values) >= _max_section_blocks
            or sum(len(item) for item in values) >= _max_section_chars
        ):
            break
    return " ".join(values)


def _section_target_ids(node: Tag) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    candidates = [node, *node.select("[aria-controls], a[href^='#']")[:6]]
    for candidate in candidates:
        if not isinstance(candidate, Tag):
            continue
        for raw_value in (
            candidate.get("aria-controls"),
            candidate.get("href"),
        ):
            target = clean_text(raw_value)
            if not target:
                continue
            if target.startswith("#"):
                target = target[1:]
            if not target or target in seen:
                continue
            seen.add(target)
            targets.append(target)
    return targets


def _section_text_is_meaningful(
    node: Tag | None,
    *,
    label: str,
    text: str,
) -> bool:
    lowered_label = clean_text(label).lower()
    lowered_text = clean_text(text).lower()
    if not lowered_text:
        return False
    if any(token in lowered_label for token in SEMANTIC_SECTION_LABEL_SKIP_TOKENS):
        return False
    if any(pattern in lowered_text for pattern in _SECTION_SKIP_PATTERNS):
        return False
    if isinstance(node, Tag):
        role = str(node.get("role") or "").strip().lower()
        if node.name in {"button", "summary"} or role in {"button", "tab"}:
            return False
        interactive_count = len(
            node.select("a[href], button, [role='button'], [role='tab'], summary")
        )
        content_count = sum(
            1
            for candidate in node.select("p, li, dd, td, dt")
            if candidate.find_parent(
                ["a", "button", "summary"],
            )
            is None
            and str(candidate.get("role") or "").strip().lower()
            not in {"button", "tab"}
        )
        if interactive_count >= 2 and content_count == 0:
            return False
    return True


def _page_heading_text(root: BeautifulSoup | Tag) -> str:
    heading = root.select_one("main h1, article h1, h1")
    if isinstance(heading, Tag):
        return clean_text(heading.get_text(" ", strip=True)).lower()
    return ""


def _section_matches_page_heading(
    root: BeautifulSoup | Tag,
    text: str,
) -> bool:
    lowered_text = clean_text(text).lower()
    if not lowered_text:
        return False
    page_heading = _page_heading_text(root)
    return bool(page_heading) and lowered_text == page_heading


def _find_wrapped_section_content(node: Tag, *, label: str) -> str:
    container: Tag | None = node
    best_text = ""
    seen: set[int] = set()
    for _ in range(4):
        if not isinstance(container, Tag):
            break
        for selector in _SECTION_CONTAINER_SELECTORS:
            for target in safe_select(container, selector):
                if id(target) in seen or target is node:
                    continue
                seen.add(id(target))
                text = _section_text(target, label=label)
                if (
                    len(text) >= 12
                    and _section_text_is_meaningful(
                        target,
                        label=label,
                        text=text,
                    )
                    and (not best_text or len(text) < len(best_text))
                ):
                    best_text = text
        parent = container.parent
        container = parent if isinstance(parent, Tag) else None
    return best_text


def _section_content_is_heading_like(
    text: str,
    *,
    label: str,
    root: BeautifulSoup | Tag,
) -> bool:
    cleaned = clean_text(text)
    lowered = cleaned.lower()
    if not lowered:
        return False
    if lowered == clean_text(label).lower():
        return True
    if (
        _is_section_label(cleaned)
        and len(cleaned.split()) <= 6
        and not any(token in cleaned for token in ".:;!?\n")
    ):
        for heading in safe_select(root, _SECTION_LABEL_SELECTOR):
            heading_label = _section_label_text(heading)
            if heading_label and lowered == heading_label.lower():
                return True
    return False


def _first_matching_text(node: Tag, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        candidate = node.select_one(selector)
        if isinstance(candidate, Tag):
            text = clean_text(candidate.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _looks_like_materials_text(text: str) -> bool:
    lowered = clean_text(text).lower()
    if not lowered:
        return False
    if "%" in lowered:
        return True
    return any(token in lowered for token in _MATERIAL_TEXT_HINTS)


def _extract_product_materials(root: BeautifulSoup | Tag) -> str:
    for container in safe_select(
        root,
        ".product-detail-composition, [class*='detailed-composition' i]",
    ):
        rows: list[str] = []
        for part in safe_select(
            container,
            "li.product-detail-composition__part, li[class*='composition__part' i]",
        ):
            part_name = _first_matching_text(
                part,
                (
                    ".product-detail-composition__part-name",
                    "[class*='part-name' i]",
                ),
            )
            area_rows: list[str] = []
            for area in safe_select(
                part,
                "li.product-detail-composition__area, li[class*='composition__area' i]",
            ):
                area_name = _first_matching_text(
                    area,
                    (
                        ".product-detail-composition__part-name",
                        "[class*='part-name' i]",
                    ),
                )
                values = [
                    clean_text(item.get_text(" ", strip=True))
                    for item in area.select("ul > li")
                    if clean_text(item.get_text(" ", strip=True))
                ]
                if not values:
                    continue
                if area_name:
                    area_rows.append(f"{area_name}: {'; '.join(values)}")
                else:
                    area_rows.append("; ".join(values))
            if part_name and area_rows:
                rows.append(f"{part_name}: {' '.join(area_rows)}")
            elif area_rows:
                rows.extend(area_rows)
        if rows:
            return "\n".join(dict.fromkeys(rows))
        text = clean_text(container.get_text(" ", strip=True))
        if len(text) >= 12 and _looks_like_materials_text(text):
            return text
    return ""


def _extract_section_content(node: Tag, root: BeautifulSoup | Tag) -> str:
    label = _section_label_text(node)
    for target_id in _section_target_ids(node):
        target = root.find(id=target_id)
        if isinstance(target, Tag):
            text = _section_text(target, label=label)
            if (
                len(text) >= 12
                and _section_text_is_meaningful(
                    target,
                    label=label,
                    text=text,
                )
                and not _section_matches_page_heading(root, text)
            ):
                return text

    if node.name == "summary":
        parent = node.parent if isinstance(node.parent, Tag) else None
        if isinstance(parent, Tag) and parent.name == "details":
            text = _section_text(parent, label=label)
            if (
                len(text) >= 12
                and _section_text_is_meaningful(
                    parent,
                    label=label,
                    text=text,
                )
                and not _section_matches_page_heading(root, text)
            ):
                return text

    sibling_content = _extract_sibling_content(node, label=label)
    wrapped = _find_wrapped_section_content(node, label=label)
    if wrapped and not _section_matches_page_heading(root, wrapped):
        if not (
            sibling_content
            and _section_content_is_heading_like(wrapped, label=label, root=root)
        ):
            return wrapped
    if _section_text_is_meaningful(
        node,
        label=label,
        text=sibling_content,
    ) and not _section_matches_page_heading(root, sibling_content):
        return sibling_content
    return ""


def extract_heading_sections(root: BeautifulSoup | Tag) -> dict[str, str]:
    scoped_root = _pruned_text_scope_root(root)
    sections: dict[str, str] = {}
    seen: set[int] = set()
    for heading in safe_select(scoped_root, _SECTION_LABEL_SELECTOR):
        if id(heading) in seen:
            continue
        seen.add(id(heading))
        heading_text = _section_label_text(heading)
        if not _is_section_label(heading_text):
            continue
        content = _extract_section_content(heading, scoped_root)
        if len(content) >= 12:
            sections.setdefault(heading_text, content)
    materials = _extract_product_materials(scoped_root) or _extract_product_materials(root)
    if materials:
        sections.setdefault("Composition", materials)
    return sections


def _feature_rows_from_node(node: Tag) -> list[str]:
    rows = [
        clean_text(item.get_text(" ", strip=True))
        for item in node.select("li")
        if clean_text(item.get_text(" ", strip=True))
    ]
    if rows:
        return rows
    text = html_to_text(str(node), preserve_block_breaks=True)
    return [row for row in _split_feature_text(text) if row]


def _split_feature_text(text: str) -> list[str]:
    rows: list[str] = []
    for line in str(text or "").splitlines():
        cleaned = clean_text(line)
        if not cleaned:
            continue
        if re.search(r"(?:^|\s)-\s+\S", cleaned):
            dash_cleaned = re.sub(r"^-\s*", "", cleaned)
            parts = [part for part in re.split(r"\s+-\s+", dash_cleaned) if part]
            if len(parts) > 1:
                rows.extend(clean_text(part) for part in parts if clean_text(part))
                continue
        rows.append(cleaned)
    return rows


def extract_feature_rows(root: BeautifulSoup | Tag) -> list[str]:
    scoped_root = _pruned_text_scope_root(root)
    rows: list[str] = []
    seen: set[str] = set()

    def _add(values: list[str]) -> None:
        for value in values:
            cleaned = clean_text(value)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            rows.append(cleaned)

    for node in safe_select(scoped_root, _feature_section_selector):
        if _node_is_hidden_or_auxiliary(node):
            continue
        _add(_feature_rows_from_node(node))

    for heading in safe_select(scoped_root, _SECTION_LABEL_SELECTOR):
        label = normalize_field_key(_section_label_text(heading))
        if label not in _FEATURE_SECTION_ALIASES:
            continue
        content = _extract_section_content(heading, scoped_root)
        _add(_split_feature_text(content))
    return rows


def requested_content_extractability(
    root: BeautifulSoup | Tag,
    *,
    surface: str,
    requested_fields: list[str] | None,
    selector_rules: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    requested = {
        normalized
        for value in list(requested_fields or [])
        for normalized in (
            exact_requested_field_key(value),
            normalize_requested_field(value),
        )
        if normalized
    }
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    section_fields = {
        normalized
        for label in extract_heading_sections(root).keys()
        for normalized in (alias_lookup.get(normalize_field_key(label)),)
        if normalized
    }
    fields = surface_fields(surface, requested_fields)
    dom_patterns_raw = EXTRACTION_RULES.get("dom_patterns")
    dom_patterns = dict(dom_patterns_raw) if isinstance(dom_patterns_raw, dict) else {}
    dom_pattern_fields = {
        field_name
        for field_name in fields
        if (selector := str(dom_patterns.get(field_name) or "").strip())
        and _dom_pattern_has_extractable_content(safe_select(root, selector))
    }
    selector_backed_fields = {
        normalize_field_key(str(row.get("field_name") or ""))
        for row in list(selector_rules or [])
        if isinstance(row, dict)
        and bool(row.get("is_active", True))
        and (
            str(row.get("css_selector") or "").strip()
            or str(row.get("xpath") or "").strip()
            or str(row.get("regex") or "").strip()
        )
    }
    extractable_fields = section_fields | dom_pattern_fields | selector_backed_fields
    matched_requested_fields = sorted(requested & extractable_fields)
    return {
        "verified": bool(
            matched_requested_fields or (not requested and section_fields)
        ),
        "matched_requested_fields": matched_requested_fields,
        "extractable_fields": sorted(extractable_fields),
        "section_fields": sorted(section_fields),
        "dom_pattern_fields": sorted(dom_pattern_fields),
        "selector_backed_fields": sorted(
            field for field in selector_backed_fields if field
        ),
    }


def _dom_pattern_has_extractable_content(nodes: list[Tag]) -> bool:
    for node in list(nodes or [])[:_max_selector_matches]:
        if clean_text(node.get_text(" ", strip=True)):
            return True
        attrs = getattr(node, "attrs", None)
        if not isinstance(attrs, dict):
            continue
        for key in ("content", "value", "src", "href", "alt", "title", "aria-label"):
            if clean_text(attrs.get(key)):
                return True
    return False


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
    selector_trace_candidates: dict[str, list[dict[str, object]]] | None = None,
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

    def _record_selector_trace(
        field_name: str,
        value: object,
        row: dict[str, object],
        *,
        selector_kind: str,
        selector_value: str,
    ) -> None:
        if selector_trace_candidates is None:
            return
        selector_trace_candidates.setdefault(field_name, []).append(
            {
                "selector_kind": selector_kind,
                "selector_value": selector_value,
                "selector_source": str(row.get("source") or "domain_memory").strip(),
                "selector_record_id": row.get("id"),
                "source_run_id": row.get("source_run_id"),
                "sample_value": str(value),
                "page_url": page_url,
                "_candidate_value": value,
            }
        )

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
        selector_kind = ""
        selector_value = ""
        if xpath:
            values = extract_xpath_values(root, xpath, field_name, page_url)
            selector_kind = "xpath"
            selector_value = xpath
        if not values and css_selector:
            values = extract_selector_values(root, css_selector, field_name, page_url)
            selector_kind = "css_selector"
            selector_value = css_selector
        if values and regex:
            values = filter_values_by_regex(values, regex, field_name, page_url)
        elif not values and regex and not xpath and not css_selector:
            values = extract_regex_values(root, regex, field_name, page_url)
            selector_kind = "regex"
            selector_value = regex
        for value in values:
            _add(field_name, value, "selector_rule")
            if selector_kind and selector_value:
                _record_selector_trace(
                    field_name,
                    value,
                    row,
                    selector_kind=selector_kind,
                    selector_value=selector_value,
                )
        if values:
            selector_hit_fields.add(field_name)
    dom_patterns_raw = EXTRACTION_RULES.get("dom_patterns")
    dom_patterns = dict(dom_patterns_raw) if isinstance(dom_patterns_raw, dict) else {}
    for field_name in fields:
        if field_name in selector_hit_fields:
            continue
        selector = str(dom_patterns.get(field_name) or "").strip()
        if not selector:
            continue
        for value in extract_selector_values(root, selector, field_name, page_url):
            _add(field_name, value, "dom_selector")
    for label, value in extract_label_value_pairs(root):
        normalized_label = normalize_field_key(label)
        canonical = alias_lookup.get(normalized_label)
        if not canonical:
            canonical = alias_lookup.get(normalize_requested_field(label))
        if canonical:
            _add(
                canonical,
                coerce_field_value(canonical, value, page_url),
                "dom_selector",
            )
