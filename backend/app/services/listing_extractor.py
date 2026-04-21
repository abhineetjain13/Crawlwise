from __future__ import annotations
import re
import logging
from typing import Any
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from selectolax.lexbor import SelectolaxError
from selectolax.lexbor import LexborHTMLParser

from app.services.config.extraction_rules import (
    EXTRACTION_RULES,
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_DETAIL_PATH_MARKERS,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_FALLBACK_CONTAINER_SELECTOR,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_NON_LISTING_PATH_TOKENS,
    LISTING_STRUCTURE_NEGATIVE_HINTS,
    LISTING_STRUCTURE_POSITIVE_HINTS,
    LISTING_WEAK_TITLES,
)
from app.services.config.selectors import CARD_SELECTORS
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extraction_context import (
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.extract.listing_candidate_ranking import (
    best_listing_candidate_set,
    rendered_listing_records,
)
from app.services.field_policy import normalize_requested_field
from app.services.field_value_core import (
    PRICE_RE,
    RATING_RE,
    REVIEW_COUNT_RE,
    absolute_url,
    clean_text,
    coerce_field_value,
    coerce_text,
    finalize_record,
    same_host,
    surface_alias_lookup,
    surface_fields,
)
from app.services.field_value_candidates import (
    add_candidate,
    collect_structured_candidates,
    finalize_candidate_value,
)
from app.services.field_value_dom import apply_selector_fallbacks
from app.services.config.surface_hints import detail_path_hints
from app.services.pipeline.pipeline_config import LISTING_FALLBACK_FRAGMENT_LIMIT

logger = logging.getLogger(__name__)

_VISUAL_CTA_TITLES = frozenset(("add to bag", "add to cart", "buy now", "choose options", "learn more", "quick add", "quick view", "read more", "see details", "select options", "shop now", "view details"))
_VISUAL_URL_MATCH_STOPWORDS = frozenset(("and", "buy", "care", "category", "collections", "details", "for", "hair", "in", "item", "items", "language", "location", "now", "page", "product", "products", "region", "select", "shop", "the", "to", "with", "your"))


def _structured_listing_record(
    payload: dict[str, Any],
    page_url: str,
    surface: str,
) -> dict[str, Any]:
    alias_lookup = surface_alias_lookup(surface, None)
    candidates: dict[str, list[object]] = {}
    collect_structured_candidates(payload, alias_lookup, page_url, candidates)
    record: dict[str, Any] = {
        "source_url": page_url,
        "_source": "structured_listing",
    }
    for field_name in surface_fields(surface, None):
        finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
    preferred_title = coerce_text(payload.get("name") or payload.get("title"))
    if preferred_title:
        record["title"] = preferred_title
    if not record.get("url"):
        fallback_url = _structured_listing_url(payload, page_url)
        if fallback_url:
            record["url"] = fallback_url
    url = str(record.get("url") or "")
    if not url or not record.get("title"):
        return {}
    if _url_is_structural(url, page_url):
        return {}
    return finalize_record(record, surface=surface)


def _url_is_structural(url: str, page_url: str) -> bool:
    """Return True for URLs that are site chrome, not product detail pages."""
    from urllib.parse import urlsplit
    lowered = url.lower()
    if lowered.startswith(("javascript:", "#", "mailto:")):
        return True
    if lowered == page_url.lower():
        return True
    try:
        parsed = urlsplit(url)
        page_parsed = urlsplit(page_url)
        # Bare domain root (homepage)
        if parsed.path in ("", "/"):
            return True
        # Same path as source page (query-string/fragment variant of the page itself)
        if parsed.path.rstrip("/").lower() == page_parsed.path.rstrip("/").lower():
            return True
        # Check each path segment (split on both / and -) against non-listing tokens
        import re as _re
        raw_path = parsed.path.lower()
        path_segments = set(_re.split(r"[/\-]", raw_path))
        path_segments = {s.strip("./") for s in path_segments if s.strip("./")}
        if path_segments & set(LISTING_NON_LISTING_PATH_TOKENS):
            return True
    except Exception:
        pass
    return False


def _structured_listing_url(payload: dict[str, Any], page_url: str) -> str | None:
    for key in ("url", "link", "href"):
        resolved = absolute_url(page_url, payload.get(key))
        if resolved and not _url_is_structural(resolved, page_url):
            return resolved
    author = payload.get("author")
    if isinstance(author, dict):
        for key in ("url", "link", "href"):
            resolved = absolute_url(page_url, author.get(key))
            if resolved and not _url_is_structural(resolved, page_url):
                return resolved
    return None


def _extract_structured_listing(
    payloads: list[dict[str, Any]],
    page_url: str,
    surface: str,
    *,
    max_records: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for payload in payloads:
        for item in _structured_listing_items(payload):
            record = _structured_listing_record(item, page_url, surface)
            url = str(record.get("url") or "")
            if not url or url in seen_urls or url == page_url:
                continue
            # Reject external-domain links from JSON-LD (e.g. parent-corp privacy pages)
            if not same_host(page_url, url):
                continue
            seen_urls.add(url)
            records.append(record)
            if len(records) >= max_records:
                return records
    return records


def _structured_listing_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for candidate in _listing_payload_candidates(payload):
        if not isinstance(candidate, dict):
            continue
        raw_type = candidate.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        ).lower()
        if "itemlist" in normalized_type:
            for item in candidate.get("itemListElement") or []:
                entry = item.get("item") if isinstance(item, dict) else None
                if isinstance(entry, dict):
                    items.append(entry)
                elif isinstance(item, dict):
                    items.append(item)
        elif any(token in normalized_type for token in ("product", "jobposting")):
            items.append(candidate)
        elif _looks_like_untyped_listing_payload(candidate):
            items.append(candidate)
    return items


def _listing_payload_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = [payload]
    main_entity = payload.get("mainEntity")
    if isinstance(main_entity, dict):
        candidates.append(main_entity)
    elif isinstance(main_entity, list):
        candidates.extend(item for item in main_entity if isinstance(item, dict))
    return candidates


def _allow_embedded_json_listing_payloads(payloads: list[dict[str, Any]]) -> bool:
    listing_like = 0
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        raw_type = payload.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        ).lower()
        if "itemlist" in normalized_type:
            return True
        if isinstance(payload.get("itemListElement"), list) and payload.get("itemListElement"):
            return True
        if _looks_like_untyped_listing_payload(payload):
            listing_like += 1
        main_entity = payload.get("mainEntity")
        if not isinstance(main_entity, dict):
            continue
        main_entity_type = main_entity.get("@type")
        normalized_main_entity_type = (
            " ".join(main_entity_type)
            if isinstance(main_entity_type, list)
            else str(main_entity_type or "")
        ).lower()
        if "itemlist" in normalized_main_entity_type:
            return True
        if isinstance(main_entity.get("itemListElement"), list) and main_entity.get("itemListElement"):
            return True
    return listing_like >= max(2, int(crawler_runtime_settings.listing_min_items))


def _looks_like_untyped_listing_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False

    title = coerce_text(payload.get("name") or payload.get("title"))
    if not title:
        return False

    # Reject known navigation / UI chrome titles
    if title.lower() in LISTING_NAVIGATION_TITLE_HINTS:
        return False

    has_url = any(payload.get(key) for key in ("url", "link", "href"))

    # Require at least one strong commerce/job signal to avoid scraping menus
    has_price = bool(payload.get("price") or payload.get("offers") or payload.get("sale_price"))
    has_image = bool(payload.get("image") or payload.get("image_url") or payload.get("thumbnail"))
    has_job_data = bool(payload.get("salary") or payload.get("company") or payload.get("location"))

    return has_url and (has_price or has_image or has_job_data)


def _listing_title_is_noise(title: str) -> bool:
    lowered = clean_text(title).lower()
    if not lowered:
        return True
    if lowered in _VISUAL_CTA_TITLES:
        return True
    if lowered in LISTING_NAVIGATION_TITLE_HINTS or lowered in LISTING_WEAK_TITLES:
        return True
    if any(lowered.startswith(prefix) for prefix in LISTING_MERCHANDISING_TITLE_PREFIXES):
        return True
    if LISTING_ALT_TEXT_TITLE_PATTERN.search(lowered):
        return True
    return any(pattern.search(lowered) for pattern in LISTING_EDITORIAL_TITLE_PATTERNS)


def _listing_card_html_fragments(
    dom_parser: LexborHTMLParser, *, is_job: bool
) -> list[object]:
    selector_group = "jobs" if is_job else "ecommerce"
    selectors = list(CARD_SELECTORS.get(selector_group) or [])
    seen: set[str] = set()
    scored: list[tuple[int, int, object]] = []
    order = 0
    for selector in selectors:
        try:
            matches = dom_parser.css(selector)
        except Exception:
            matches = []
        for node in matches:
            order += 1
            score = _listing_fragment_score(node)
            if score <= 0:
                continue
            fragment = str(node.html or "").strip()
            if not fragment or fragment in seen:
                continue
            seen.add(fragment)
            scored.append((score, order, node))
    if scored:
        return _sorted_listing_fragment_nodes(scored)
    scanned = 0
    for node in dom_parser.css(LISTING_FALLBACK_CONTAINER_SELECTOR):
        scanned += 1
        if scanned > LISTING_FALLBACK_FRAGMENT_LIMIT * 40:
            break
        order += 1
        score = _listing_fragment_score(node)
        if score <= 0:
            continue
        fragment = str(node.html or "").strip()
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        scored.append((score, order, node))
    if not scored:
        return []
    return _sorted_listing_fragment_nodes(
        scored,
        limit=int(LISTING_FALLBACK_FRAGMENT_LIMIT),
    )


def _sorted_listing_fragment_nodes(
    scored: list[tuple[int, int, object]],
    *,
    limit: int | None = None,
) -> list[object]:
    scored.sort(key=lambda row: (-row[0], row[1]))
    rows = scored if limit is None else scored[:limit]
    return [node for _score, _order, node in rows]


def _visual_listing_records(
    visual_elements: list[dict[str, object]] | None,
    *,
    page_url: str,
    surface: str,
    max_records: int,
) -> list[dict[str, Any]]:
    elements = _normalized_visual_elements(visual_elements, page_url=page_url)
    if not elements:
        return []
    clusters = _cluster_visual_elements(elements)
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for cluster in clusters:
        record = _visual_cluster_to_record(cluster, page_url=page_url, surface=surface)
        if record is None:
            continue
        url = str(record.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        records.append(record)
        if len(records) >= max_records:
            break
    return records


def _normalized_visual_elements(
    visual_elements: list[dict[str, object]] | None,
    *,
    page_url: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(visual_elements or [])[:300]:
        if not isinstance(item, dict):
            continue
        width = _coerce_visual_number(item.get("width"))
        height = _coerce_visual_number(item.get("height"))
        if width <= 0 or height <= 0:
            continue
        href = absolute_url(page_url, item.get("href"))
        src = absolute_url(page_url, item.get("src"))
        text = clean_text(
            " ".join(
                str(value or "")
                for value in (
                    item.get("text"),
                    item.get("alt"),
                    item.get("ariaLabel"),
                    item.get("title"),
                )
            )
        )
        rows.append(
            {
                "tag": str(item.get("tag") or "").strip().lower(),
                "text": text,
                "href": href,
                "src": src,
                "x": _coerce_visual_number(item.get("x")),
                "y": _coerce_visual_number(item.get("y")),
                "width": width,
                "height": height,
            }
        )
    return rows


def _coerce_visual_number(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _cluster_visual_elements(
    elements: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    anchors = [item for item in elements if item.get("href")]
    if not anchors:
        return []
    anchors.sort(key=lambda item: (int(item.get("y") or 0), int(item.get("x") or 0)))
    clusters: list[list[dict[str, Any]]] = []
    for anchor in anchors:
        cluster = [anchor]
        left = int(anchor.get("x") or 0) - 80
        right = left + int(anchor.get("width") or 0) + 160
        top = int(anchor.get("y") or 0) - 80
        bottom = top + int(anchor.get("height") or 0) + 260
        for item in elements:
            if item is anchor:
                continue
            x = int(item.get("x") or 0)
            y = int(item.get("y") or 0)
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if x + width < left or x > right:
                continue
            if y + height < top or y > bottom:
                continue
            cluster.append(item)
        if _visual_cluster_score(cluster) > 0:
            clusters.append(cluster)
    clusters.sort(key=lambda cluster: -_visual_cluster_score(cluster))
    return clusters


def _visual_cluster_score(cluster: list[dict[str, Any]]) -> int:
    if not cluster:
        return -100
    hrefs = {str(item.get("href") or "") for item in cluster if item.get("href")}
    if len(hrefs) != 1:
        return -50
    score = 10
    if any(_visual_element_is_title(item) for item in cluster):
        score += 8
    if any(PRICE_RE.search(str(item.get("text") or "")) for item in cluster):
        score += 4
    if any(str(item.get("tag") or "") == "img" and item.get("src") for item in cluster):
        score += 3
    if len(cluster) > 8:
        score -= len(cluster) - 8
    return score


def _visual_element_is_title(item: dict[str, Any]) -> bool:
    text = str(item.get("text") or "")
    if not text or _listing_title_is_noise(text) or PRICE_RE.search(text):
        return False
    return str(item.get("tag") or "") in {"a", "h1", "h2", "h3"} or len(text) <= 180


def _visual_cluster_to_record(
    cluster: list[dict[str, Any]],
    *,
    page_url: str,
    surface: str,
) -> dict[str, Any] | None:
    href = next((str(item.get("href") or "") for item in cluster if item.get("href")), "")
    if not href or _url_is_structural(href, page_url):
        return None
    title_candidates = [
        str(item.get("text") or "")
        for item in cluster
        if _visual_element_is_title(item)
    ]
    title = next((text for text in title_candidates if not _listing_title_is_noise(text)), "")
    if not title:
        return None
    image_url = next(
        (str(item.get("src") or "") for item in cluster if item.get("src")),
        "",
    )
    price_text = next(
        (
            str(item.get("text") or "")
            for item in cluster
            if PRICE_RE.search(str(item.get("text") or ""))
        ),
        "",
    )
    price_match = PRICE_RE.search(price_text)
    is_job = surface.startswith("job_")
    if not is_job and not price_match and not _visual_title_matches_url(title, href):
        return None
    record = {
        "source_url": page_url,
        "_source": "visual_listing",
        "title": title,
        "url": href,
    }
    if image_url:
        record["image_url"] = image_url
    if price_match:
        record["price"] = (
            price_match.group(0)
            .strip()
            .lstrip("$€£₹")
            .strip()
            .replace(",", "")
        )
    return finalize_record(record, surface=surface)


def _visual_title_matches_url(title: str, href: str) -> bool:
    return bool(
        (title_tokens := _visual_match_tokens(title))
        and (path_tokens := _visual_match_tokens(urlsplit(href).path))
        and title_tokens & path_tokens
    )


def _visual_match_tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", clean_text(value).lower()) if len(token) >= 2 and token not in _VISUAL_URL_MATCH_STOPWORDS}


def _listing_fragment_score(node) -> int:
    tag_name = str(getattr(node, "tag", "") or "").strip().lower()
    if tag_name in {"header", "nav", "footer"}:
        return -100
    attrs = getattr(node, "attributes", {}) or {}
    signature = " ".join(
        [
            str(attrs.get("class") or ""),
            str(attrs.get("id") or ""),
            str(attrs.get("role") or ""),
            str(attrs.get("aria-label") or ""),
        ]
    ).lower()
    if any(token in signature for token in LISTING_STRUCTURE_NEGATIVE_HINTS):
        return -10
    score = 0
    if any(token in signature for token in LISTING_STRUCTURE_POSITIVE_HINTS):
        score += 6
    try:
        links = node.css("a[href]")
    except Exception:
        return -100
    link_count = len(links)
    if link_count == 0:
        return -100
    if link_count == 1:
        score += 4
    elif link_count <= 6:
        score += 2
    elif link_count <= 12:
        score -= 1
    else:
        score -= 6
    text = clean_text(str(node.text(strip=True) or ""))
    text_len = len(text)
    if text_len < 12:
        score -= 3
    elif text_len <= 2000:
        score += 3
    else:
        score -= 3
    if PRICE_RE.search(text):
        score += 3
    if tag_name in {"article", "li", "tr", "section"}:
        score += 2
    return score


def _node_text(node) -> str:
    try:
        return clean_text(str(node.text(separator=" ", strip=True) or ""))
    except (AttributeError, TypeError, ValueError):
        return ""


def _node_attr(node, name: str) -> str:
    attrs = getattr(node, "attributes", {}) or {}
    return str(attrs.get(name) or "").strip()


def _node_signature(node) -> str:
    return " ".join(
        [
            _node_attr(node, "class"),
            _node_attr(node, "id"),
            _node_attr(node, "role"),
            _node_attr(node, "aria-label"),
            _node_attr(node, "title"),
        ]
    ).lower()


def _node_tag(node) -> str:
    return str(getattr(node, "tag", "") or "").strip().lower()


def _node_css(node, selector: str) -> list[object]:
    if not selector:
        return []
    try:
        return list(node.css(selector))
    except SelectolaxError:
        logger.warning("Skipping invalid listing selector: %s", selector)
        return []


def _card_title_node(card) -> object | None:
    candidates: list[object] = []
    for selector in EXTRACTION_RULES.get("listing_extraction", {}).get(
        "card_title_selectors", []
    ):
        candidates.extend(_node_css(card, str(selector)))
    if candidates:
        best = max(candidates, key=lambda node: (_card_title_score(node), len(_node_text(node))))
        if _card_title_score(best) > 0:
            return best
    fallback_candidates = _fallback_card_title_candidates(card)
    if fallback_candidates:
        best = max(
            fallback_candidates,
            key=lambda node: (_card_title_score(node), len(_node_text(node))),
        )
        if _card_title_score(best) > 0:
            return best
    anchors = _node_css(card, "a[href]")
    if not anchors:
        return None
    best = max(anchors, key=_card_title_score)
    return best if _card_title_score(best) > 0 else None


def _card_title_score(node) -> int:
    text = _node_text(node)
    if not text:
        return -100
    return _card_title_score_parts(
        text=text,
        attrs=_node_signature(node),
        tag_name=_node_tag(node),
        href_present=bool(_node_attr(node, "href")),
    )


def _fallback_card_title_candidates(card) -> list[object]:
    candidates: list[object] = []
    for node in _node_css(card, "*"):
        if _node_tag(node) in {"a", "button"}:
            continue
        attrs = _node_signature(node)
        if not attrs:
            continue
        if not any(token in attrs for token in ("title", "name", "product", "item")):
            continue
        text = _node_text(node)
        if not text or len(text) > 220:
            continue
        lowered_text = text.lower()
        if PRICE_RE.search(text):
            continue
        if any(token in lowered_text for token in ("add to bag", "add to cart", "wishlist")):
            continue
        candidates.append(node)
    return candidates


def _card_title_score_parts(
    *,
    text: str,
    attrs: str,
    tag_name: str,
    href_present: bool,
) -> int:
    score = 0
    if any(token in attrs for token in ("title", "name", "product", "item", "listing", "result", "job", "record", "release")):
        score += 6
    if any(token in attrs for token in ("brand", "seller", "vendor", "rating", "price", "size", "wishlist")):
        score -= 6
    if tag_name in {"h1", "h2", "h3", "h4", "h5", "a"}:
        score += 2
    text_len = len(text)
    if 8 <= text_len <= 180:
        score += 3
    elif text_len < 4:
        score -= 6
    elif text_len > 220:
        score -= 2
    if _listing_title_is_noise(text):
        score -= 4
    if href_present:
        score += 2
    return score


def _select_primary_anchor(card, page_url: str, *, surface: str) -> tuple[object, str, str, int] | None:
    is_job = surface.startswith("job_")
    best: tuple[int, object, str, str] | None = None
    for anchor in _node_css(card, "a[href]"):
        url = absolute_url(page_url, _node_attr(anchor, "href"))
        if not url or not same_host(page_url, url):
            continue
        lowered_url = url.lower()
        if _url_is_structural(url, page_url):
            continue
        if any(token in lowered_url for token in ("sort=", "filter=", "facet=", "#review", "#details")):
            continue
        text = clean_text(
            _node_attr(anchor, "title")
            or _node_attr(anchor, "aria-label")
            or _node_text(anchor)
        )
        score = _card_title_score_parts(
            text=text,
            attrs=_node_signature(anchor),
            tag_name=_node_tag(anchor),
            href_present=True,
        )
        if _detail_like_path(url, is_job=is_job):
            score += 6
        if any(token in lowered_url for token in ("/seller/", "/profile/", "/brand/", "/help/", "/search")):
            score -= 5
        if best is None or score > best[0]:
            best = (score, anchor, url, text)
    if best is None:
        return None
    score, anchor, url, text = best
    return anchor, url, text, score


def _detail_like_path(url: str, *, is_job: bool) -> bool:
    lowered = url.lower()
    if any(marker in lowered for marker in LISTING_DETAIL_PATH_MARKERS):
        return True
    hints = detail_path_hints("job_detail" if is_job else "ecommerce_detail")
    return any(marker in lowered for marker in hints)


def _extract_page_images_from_node(root, page_url: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for node in _node_css(root, "img"):
        candidate = absolute_url(
            page_url,
            _node_attr(node, "src")
            or _node_attr(node, "data-src")
            or _node_attr(node, "data-original"),
        )
        if not candidate:
            continue
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
        if candidate in seen:
            continue
        seen.add(candidate)
        values.append(candidate)
    return values[:12]


def _extract_label_value_pairs_from_node(root) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for tr in _node_css(root, "tr"):
        cells = _node_css(tr, "th, td")
        if len(cells) < 2:
            continue
        label = _node_text(cells[0])
        value = _node_text(cells[1])
        if label and value:
            rows.append((label, value))
    for node in _node_css(root, "li, p, div, span"):
        text = _node_text(node)
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


def _listing_record_from_card(
    card,
    page_url: str,
    surface: str,
    *,
    selector_rules: list[dict[str, object]] | None = None,
) -> dict[str, Any] | None:
    is_job = surface.startswith("job_")
    primary_anchor = _select_primary_anchor(card, page_url, surface=surface)
    if primary_anchor is None:
        return None
    anchor_node, url, anchor_text, anchor_score = primary_anchor
    title_node = _card_title_node(card) or anchor_node
    title_score = _card_title_score(title_node)
    title = clean_text(
        _node_attr(title_node, "title")
        or _node_attr(title_node, "alt")
        or _node_text(title_node)
        or anchor_text
    )
    if len(title) < 4 or _listing_title_is_noise(title):
        return None
    if anchor_score < 4 and title_score < 8:
        return None
    card_text = _node_text(card)
    image_urls = _extract_page_images_from_node(card, page_url)
    has_supporting_listing_signals = bool(
        PRICE_RE.search(card_text)
        or RATING_RE.search(card_text)
        or REVIEW_COUNT_RE.search(card_text)
        or image_urls
    )
    if not _detail_like_path(url, is_job=is_job):
        if is_job and anchor_score < 8:
            if not any(token in card_text.lower() for token in ("salary", "remote", "location", "apply")):
                return None
        if not is_job and anchor_score < 8 and not has_supporting_listing_signals and title_score < 8:
            return None
    alias_lookup = surface_alias_lookup(surface, None)
    candidates: dict[str, list[object]] = {"title": [title], "url": [url]}
    card_soup = BeautifulSoup(str(getattr(card, "html", "") or ""), "html.parser")
    apply_selector_fallbacks(
        card_soup,
        page_url,
        surface,
        None,
        candidates,
        selector_rules=selector_rules,
    )
    if image_urls and not candidates.get("image_url"):
        add_candidate(candidates, "image_url", image_urls[0])
    if image_urls[1:] and not candidates.get("additional_images"):
        add_candidate(candidates, "additional_images", image_urls[1:])
    for label, value in _extract_label_value_pairs_from_node(card):
        normalized_label = normalize_requested_field(label)
        if not normalized_label:
            normalized_label = clean_text(label).lower().replace(" ", "_")
        canonical = alias_lookup.get(normalized_label)
        if canonical:
            add_candidate(
                candidates,
                canonical,
                coerce_field_value(canonical, value, page_url),
            )
    if not is_job and not candidates.get("price"):
        price_match = PRICE_RE.search(card_text)
        if price_match:
            add_candidate(candidates, "price", price_match.group(0))
    if is_job and not candidates.get("salary"):
        salary_match = PRICE_RE.search(card_text)
        if salary_match:
            add_candidate(candidates, "salary", salary_match.group(0))
    if not candidates.get("rating"):
        rating_match = RATING_RE.search(card_text)
        if rating_match:
            add_candidate(candidates, "rating", rating_match.group(1))
    if not candidates.get("review_count"):
        review_match = REVIEW_COUNT_RE.search(card_text)
        if review_match:
            add_candidate(candidates, "review_count", review_match.group(1))
    record: dict[str, Any] = {
        "source_url": page_url,
        "_source": "dom_listing",
    }
    for field_name in surface_fields(surface, None):
        finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
    cleaned = finalize_record(record, surface=surface)
    if not cleaned.get("url") or not cleaned.get("title"):
        return None
    return cleaned


def extract_listing_records(
    html: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    artifacts: dict[str, object] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
) -> list[dict[str, Any]]:
    context = prepare_extraction_context(html)
    dom_parser = context.dom_parser
    if not _listing_card_html_fragments(dom_parser, is_job=surface.startswith("job_")):
        original_parser = LexborHTMLParser(context.original_html)
        if _listing_card_html_fragments(original_parser, is_job=surface.startswith("job_")):
            logger.debug("Using original listing DOM after cleaned DOM lost card fragments for %s", page_url)
            dom_parser = original_parser

    def _structured_stage() -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for source_name, source_payloads in collect_structured_source_payloads(
            context,
            page_url=page_url,
        ):
            if source_name == "js_state":
                continue
            payload_list = [
                payload for payload in list(source_payloads) if isinstance(payload, dict)
            ]
            if source_name == "embedded_json" and not _allow_embedded_json_listing_payloads(
                payload_list
            ):
                continue
            payloads.extend(payload_list)
        return _extract_structured_listing(
            payloads,
            page_url,
            surface,
            max_records=max_records,
        )

    def _dom_stage(
        *,
        seed_urls: set[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen_urls: set[str] = set(seed_urls or ())
        target_limit = max(1, int(limit if limit is not None else max_records))
        for card in _listing_card_html_fragments(
            dom_parser, is_job=surface.startswith("job_")
        ):
            record = _listing_record_from_card(
                card,
                page_url,
                surface,
                selector_rules=selector_rules,
            )
            if record is None:
                continue
            url = str(record.get("url") or "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            records.append(record)
            if len(records) >= target_limit:
                break
        return records

    structured_records = _structured_stage()
    structured_urls = {
        str(record.get("url") or "")
        for record in structured_records
        if str(record.get("url") or "").strip()
    }
    remaining = max(1, int(max_records) - len(structured_records))
    dom_records = _dom_stage(seed_urls=structured_urls, limit=remaining)
    rendered_records = rendered_listing_records(
        artifacts.get("rendered_listing_cards") if isinstance(artifacts, dict) else None,
        page_url=page_url,
        surface=surface,
        max_records=max_records,
        title_is_noise=_listing_title_is_noise,
        url_is_structural=_url_is_structural,
    )
    best_non_visual = best_listing_candidate_set(
        [
            ("structured", structured_records),
            ("dom", dom_records),
            ("structured_plus_dom", [*structured_records, *dom_records]),
            ("rendered", rendered_records),
        ],
        page_url=page_url,
        max_records=max_records,
        title_is_noise=_listing_title_is_noise,
        url_is_structural=_url_is_structural,
    )
    if best_non_visual:
        return best_non_visual[:max_records]
    visual_records = _visual_listing_records(
        artifacts.get("listing_visual_elements") if isinstance(artifacts, dict) else None,
        page_url=page_url,
        surface=surface,
        max_records=max_records,
    )
    if visual_records:
        return visual_records[:max_records]
    return []
