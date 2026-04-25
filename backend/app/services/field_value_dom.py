from __future__ import annotations

import logging
import regex as regex_lib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse, unquote

from bs4 import BeautifulSoup, Tag
from lxml import etree
from lxml import html as lxml_html
from soupsieve import SelectorSyntaxError

from app.services.config.extraction_rules import (
    CROSS_LINK_CONTAINER_HINTS,
    EXTRACTION_RULES,
    NON_PRODUCT_IMAGE_HINTS,
    NON_PRODUCT_PROVIDER_HINTS,
    PRODUCT_GALLERY_CONTEXT_HINTS,
    SEMANTIC_SECTION_NOISE,
)
from app.services.config.surface_hints import detail_path_hints
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

_candidate_cleanup_raw = EXTRACTION_RULES.get("candidate_cleanup")
_CANDIDATE_CLEANUP = (
    dict(_candidate_cleanup_raw) if isinstance(_candidate_cleanup_raw, dict) else {}
)
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
_CDN_IMAGE_PATH_SUFFIX_RE = regex_lib.compile(
    r"_(?:\d+x\d+|pico|icon|thumb|small|compact|medium|large|grande|original)(?=\.[a-z0-9]+$)",
    regex_lib.I,
)
_SECTION_LABEL_SKIP_TOKENS = tuple(
    sorted(
        {
            *(
                str(token).lower()
                for token in (
                    SEMANTIC_SECTION_NOISE.get("label_skip_tokens")
                    or ()
                )
            ),
            "answer",
            "answers",
            "q&a",
            "question",
            "questions",
            "rating snapshot",
            "review",
            "reviews",
        }
    )
)
_SECTION_SKIP_PATTERNS = tuple(
    str(token).lower()
    for token in (
        SEMANTIC_SECTION_NOISE.get("skip_patterns")
        or ()
    )
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


def canonical_image_url(url: str) -> str:
    effective_url = _effective_image_url(url)
    parsed = urlparse(str(effective_url or "").strip())
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
    text = str(url or "").strip()
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


def _is_proxy_image_url(url: str) -> bool:
    path = str(urlparse(str(url or "").strip()).path or "").lower()
    return "/_next/image" in path


def image_candidate_score(url: str) -> tuple[int, int, int, int]:
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
    return (0 if _is_proxy_image_url(url) else 1, area, width, height)


def dedupe_image_urls(urls: list[str]) -> list[str]:
    best_by_key: dict[str, tuple[tuple[int, int, int, int], int, str]] = {}
    order: list[str] = []
    for index, url in enumerate(urls):
        lowered = str(url or "").strip().lower()
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


def _is_in_product_gallery_context(node: Tag, *, max_depth: int = 6) -> bool:
    current: Tag | None = node
    depth = 0
    in_main = False
    while isinstance(current, Tag) and depth < max_depth:
        if current.name == "main" or str(current.get("role") or "").strip().lower() == "main":
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


def _is_garbage_image_candidate(node: Tag, candidate_url: str) -> bool:
    lowered = str(candidate_url or "").lower()
    context = _image_node_context(node)
    if lowered.endswith(".svg") and not _is_in_product_gallery_context(node):
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
    elif node.find_parent(["main"]) is not None and _looks_like_image_asset_url(candidate_url):
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
    if lowered.startswith(("#", "javascript:", "mailto:")) or _looks_like_image_asset_url(candidate):
        return False
    page_parts = urlparse(page_url)
    candidate_parts = urlparse(candidate)
    same_host = (page_parts.hostname or "").lower() == (candidate_parts.hostname or "").lower()
    same_path = (page_parts.path.rstrip("/") or "/") == (candidate_parts.path.rstrip("/") or "/")
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
    text_value = coerce_field_value(field_name, node.get_text(" ", strip=True), page_url)
    if field_name in LONG_TEXT_FIELDS and not _section_text_is_meaningful(
        node,
        label=field_name,
        text=str(text_value or ""),
    ):
        return None
    return text_value


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
    limited_matches: list[object]
    if isinstance(matches, list):
        limited_matches = [*matches[:12]]
    elif isinstance(matches, (str, bytes, bool, float)):
        limited_matches = [matches]
    else:
        try:
            limited_matches = list(matches)[:12]
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
    return dedupe_image_urls(ordered)[:12]


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
    if any(token in cleaned.lower() for token in _SECTION_LABEL_SKIP_TOKENS):
        return False
    return any(char.isalpha() for char in cleaned)


def _section_text(node: Tag, *, label: str = "") -> str:
    text = clean_text(node.get_text(" ", strip=True))
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
        text = clean_text(
            sibling.get_text(" ", strip=True) if isinstance(sibling, Tag) else str(sibling)
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
        if len(values) >= 8 or sum(len(item) for item in values) >= 1200:
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
    if any(token in lowered_label for token in _SECTION_LABEL_SKIP_TOKENS):
        return False
    if any(pattern in lowered_text for pattern in _SECTION_SKIP_PATTERNS):
        return False
    if isinstance(node, Tag):
        interactive_count = len(
            node.select("a[href], button, [role='button'], [role='tab'], summary")
        )
        content_count = sum(
            1
            for candidate in node.select("p, li, dd, td, dt")
            if candidate.find_parent(
                ["a", "button", "summary"],
            ) is None
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
                if len(text) >= 12 and _section_text_is_meaningful(
                    target,
                    label=label,
                    text=text,
                ) and (not best_text or len(text) < len(best_text)):
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
    if _is_section_label(cleaned) and len(cleaned.split()) <= 6 and not any(
        token in cleaned for token in ".:;!?\n"
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
            if len(text) >= 12 and _section_text_is_meaningful(
                target,
                label=label,
                text=text,
            ) and not _section_matches_page_heading(root, text):
                return text

    if node.name == "summary":
        parent = node.parent if isinstance(node.parent, Tag) else None
        if isinstance(parent, Tag) and parent.name == "details":
            text = _section_text(parent, label=label)
            if len(text) >= 12 and _section_text_is_meaningful(
                parent,
                label=label,
                text=text,
            ) and not _section_matches_page_heading(root, text):
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
    sections: dict[str, str] = {}
    seen: set[int] = set()
    for heading in safe_select(root, _SECTION_LABEL_SELECTOR):
        if id(heading) in seen:
            continue
        seen.add(id(heading))
        heading_text = _section_label_text(heading)
        if not _is_section_label(heading_text):
            continue
        content = _extract_section_content(heading, root)
        if len(content) >= 12:
            sections.setdefault(heading_text, content)
    materials = _extract_product_materials(root)
    if materials:
        sections.setdefault("Composition", materials)
    return sections


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
        if (
            selector := str(dom_patterns.get(field_name) or "").strip()
        ) and _dom_pattern_has_extractable_content(safe_select(root, selector))
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
        "verified": bool(matched_requested_fields or (not requested and section_fields)),
        "matched_requested_fields": matched_requested_fields,
        "extractable_fields": sorted(extractable_fields),
        "section_fields": sorted(section_fields),
        "dom_pattern_fields": sorted(dom_pattern_fields),
        "selector_backed_fields": sorted(field for field in selector_backed_fields if field),
    }


def _dom_pattern_has_extractable_content(nodes: list[Tag]) -> bool:
    for node in list(nodes or [])[:12]:
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
            _add(canonical, coerce_field_value(canonical, value, page_url), "dom_selector")
