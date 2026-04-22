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
    LISTING_ACTION_NOISE_PATTERNS,
    LISTING_DETAIL_PATH_MARKERS,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_FALLBACK_CONTAINER_SELECTOR,
    LISTING_LABEL_NOISE_TOKENS,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_NON_LISTING_PATH_TOKENS,
    LISTING_STRUCTURE_NEGATIVE_HINTS,
    LISTING_STRUCTURE_POSITIVE_HINTS,
    LISTING_TITLE_CTA_TITLES,
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
from app.services.extract.listing_visual import visual_listing_records
from app.services.field_policy import normalize_requested_field
from app.services.field_value_core import (
    PRICE_RE,
    RATING_RE,
    REVIEW_COUNT_RE,
    absolute_url,
    clean_text,
    coerce_field_value,
    coerce_text,
    extract_currency_code,
    extract_price_text,
    finalize_record,
    same_host,
    same_site,
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

logger = logging.getLogger(__name__)
_PRICE_NODE_SELECTORS = (
    "[itemprop='price']",
    "[class*='price']",
    "[data-testid*='price']",
    "[data-price]",
    "[aria-label*='price']",
)
_PROMINENT_TITLE_TAGS = {"strong", "b", "h1", "h2", "h3", "h4", "h5", "h6"}


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
    if not url:
        return {}
    title = clean_text(record.get("title"))
    if not title or _listing_title_is_noise(title):
        fallback_title = _title_from_url(url)
        if fallback_title and not _listing_title_is_noise(fallback_title):
            record["title"] = fallback_title
    if not record.get("title"):
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
        raw_segments = [
            segment.strip().lower()
            for segment in parsed.path.split("/")
            if segment.strip()
        ]
        tokenized_segments = [
            {
                token
                for token in re.split(r"[\-\.]+", segment)
                if token
            }
            for segment in raw_segments
        ]
        terminal_tokens = tokenized_segments[-1] if tokenized_segments else set()
        if terminal_tokens & set(LISTING_NON_LISTING_PATH_TOKENS):
            return True
        leading_tokens = tokenized_segments[:-1] if len(tokenized_segments) <= 2 else []
        if any(tokens & set(LISTING_NON_LISTING_PATH_TOKENS) for tokens in leading_tokens):
            return True
    except Exception:
        logger.debug("URL structural check failed for %s", page_url, exc_info=True)
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
    cleaned = clean_text(title)
    lowered = cleaned.lower()
    if not lowered:
        return True
    if cleaned.isdigit():
        return True
    if "star" in lowered and RATING_RE.search(lowered):
        return True
    if lowered in LISTING_TITLE_CTA_TITLES:
        return True
    if any(pattern.search(lowered) for pattern in LISTING_ACTION_NOISE_PATTERNS):
        return True
    if lowered in LISTING_NAVIGATION_TITLE_HINTS or lowered in LISTING_WEAK_TITLES:
        return True
    if any(lowered.startswith(prefix) for prefix in LISTING_MERCHANDISING_TITLE_PREFIXES):
        return True
    if LISTING_ALT_TEXT_TITLE_PATTERN.search(lowered):
        return True
    return any(pattern.search(lowered) for pattern in LISTING_EDITORIAL_TITLE_PATTERNS)


def _title_from_url(url: str) -> str | None:
    path = str(urlsplit(str(url or "")).path or "").strip("/")
    if not path:
        return None
    terminal = path.rsplit("/", 1)[-1]
    terminal = re.sub(r"\.(html?|htm)$", "", terminal, flags=re.I)
    if not terminal:
        return None
    title = clean_text(re.sub(r"[-_]+", " ", terminal))
    if not title or title.isdigit():
        return None
    return title


def _record_has_supporting_listing_signals(record: dict[str, Any], *, surface: str) -> bool:
    if any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in ("image_url", "price", "rating", "review_count")
    ):
        return True
    if surface.startswith("job_"):
        return any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in ("company", "location", "salary", "job_type")
        )
    return record.get("brand") not in (None, "", [], {})


def _job_listing_url_looks_like_posting(url: str) -> bool:
    terminal = (urlsplit(url).path or "").rstrip("/").rsplit("/", 1)[-1]
    return bool(re.search(r"\d{4,}", terminal))


def _job_listing_url_is_utility(url: str) -> bool:
    lowered = url.lower()
    return any(
        token in lowered
        for token in ("/applicant/", "/careerexplorer/", "/help/", "/savedsearches")
    )


def _record_is_supported_listing_candidate(
    record: dict[str, Any],
    *,
    page_url: str,
    surface: str,
) -> bool:
    title = clean_text(record.get("title"))
    url = str(record.get("url") or "").strip()
    if not title or not url or _listing_title_is_noise(title) or _url_is_structural(url, page_url):
        return False
    if surface.startswith("job_") and _job_listing_url_is_utility(url):
        return False
    if _detail_like_path(url, is_job=surface.startswith("job_")):
        return True
    if _record_has_supporting_listing_signals(record, surface=surface):
        return True
    if surface.startswith("job_") and _job_listing_url_looks_like_posting(url):
        return True
    return False


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
    fragment_limit = max(1, int(crawler_runtime_settings.listing_fallback_fragment_limit))
    for node in dom_parser.css(LISTING_FALLBACK_CONTAINER_SELECTOR):
        scanned += 1
        if scanned > fragment_limit * 40:
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
        limit=fragment_limit,
    )


def _sorted_listing_fragment_nodes(
    scored: list[tuple[int, int, object]],
    *,
    limit: int | None = None,
) -> list[object]:
    scored.sort(key=lambda row: (-row[0], row[1]))
    rows = scored if limit is None else scored[:limit]
    return [node for _score, _order, node in rows]


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


def _node_html(node) -> str:
    try:
        return str(getattr(node, "html", "") or "").strip()
    except Exception:
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


def _extract_price_signal_from_card(card) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    order = 0
    for selector in _PRICE_NODE_SELECTORS:
        for node in _node_css(card, selector):
            order += 1
            raw_text = clean_text(
                _node_attr(node, "content")
                or _node_attr(node, "data-price")
                or _node_attr(node, "aria-label")
                or _node_text(node)
            )
            if not raw_text or len(raw_text) > 120:
                continue
            price_text = extract_price_text(
                raw_text,
                prefer_last=False,
                allow_unmarked=True,
            )
            if not price_text:
                continue
            score = 0
            attrs = _node_signature(node)
            if "price" in attrs:
                score += 5
            if len(raw_text) <= 40:
                score += 2
            if extract_currency_code(price_text):
                score += 2
            candidates.append((score, order, price_text))
    if candidates:
        candidates.sort(key=lambda row: (-row[0], row[1]))
        return candidates[0][2]
    return extract_price_text(_node_text(card), prefer_last=True)


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
        tag_name = _node_tag(node)
        if tag_name in {"a", "button"}:
            continue
        text = _node_text(node)
        if not text or len(text) > 220:
            continue
        lowered_text = text.lower()
        if PRICE_RE.search(text):
            continue
        if any(token in lowered_text for token in ("add to bag", "add to cart", "wishlist")):
            continue
        if tag_name in _PROMINENT_TITLE_TAGS:
            candidates.append(node)
            continue
        attrs = _node_signature(node)
        if not attrs:
            continue
        if not any(token in attrs for token in ("title", "name", "product", "item")):
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
    normalized_text = clean_text(text)
    if any(token in attrs for token in ("title", "name", "product", "item", "listing", "result", "job", "record", "release")):
        score += 6
    if any(token in attrs for token in ("brand", "seller", "vendor", "rating", "price", "size", "wishlist")):
        score -= 6
    if tag_name in {"h1", "h2", "h3", "h4", "h5", "a", "strong", "b"}:
        score += 2
    if normalized_text.isdigit():
        score -= 20
    if re.search(r"[a-z]", normalized_text, flags=re.I):
        score += 2
    text_len = len(normalized_text)
    if 8 <= text_len <= 180:
        score += 3
    elif text_len < 4:
        score -= 6
    elif text_len > 220:
        score -= 2
    if _listing_title_is_noise(normalized_text):
        score -= 4
    if href_present:
        score += 2
    return score


def _select_primary_anchor(
    card,
    page_url: str,
    *,
    surface: str,
    title_node=None,
) -> tuple[object, str, str, int] | None:
    is_job = surface.startswith("job_")
    card_html = _node_html(card)
    title_index = -1
    if title_node is not None and _node_tag(title_node) != "a":
        title_html = _node_html(title_node)
        if card_html and title_html:
            title_index = card_html.find(title_html)
    best: tuple[int, object, str, str] | None = None
    for anchor in _node_css(card, "a[href]"):
        url = absolute_url(page_url, _node_attr(anchor, "href"))
        if not url or (not same_host(page_url, url) and not same_site(page_url, url)):
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
        if title_index >= 0 and card_html:
            anchor_html = _node_html(anchor)
            anchor_index = card_html.find(anchor_html) if anchor_html else -1
            if 0 <= anchor_index < title_index:
                score += 3
            elif anchor_index > title_index:
                score -= 3
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
        if label and value and not _label_value_pair_is_noise(label):
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
        if _label_value_pair_is_noise(label):
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


def _label_value_pair_is_noise(label: str) -> bool:
    normalized = clean_text(label).lower()
    if not normalized:
        return True
    if any(token in normalized for token in LISTING_STRUCTURE_NEGATIVE_HINTS):
        return True
    return any(token in normalized for token in LISTING_LABEL_NOISE_TOKENS)


def _listing_record_from_card(
    card,
    page_url: str,
    surface: str,
    *,
    selector_rules: list[dict[str, object]] | None = None,
) -> dict[str, Any] | None:
    is_job = surface.startswith("job_")
    title_node = _card_title_node(card)
    primary_anchor = _select_primary_anchor(
        card,
        page_url,
        surface=surface,
        title_node=title_node,
    )
    if primary_anchor is None:
        return None
    anchor_node, url, anchor_text, anchor_score = primary_anchor
    title_node = title_node or anchor_node
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
        price_text = _extract_price_signal_from_card(card)
        if price_text:
            add_candidate(candidates, "price", price_text)
    if not is_job and not candidates.get("currency"):
        for price_value in list(candidates.get("price") or []):
            currency_code = extract_currency_code(price_value)
            if currency_code:
                add_candidate(candidates, "currency", currency_code)
                break
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
    if not _record_is_supported_listing_candidate(
        cleaned,
        page_url=page_url,
        surface=surface,
    ):
        return None
    return cleaned


def _detail_anchor_count(
    parser: LexborHTMLParser,
    *,
    page_url: str,
    surface: str,
) -> int:
    is_job = surface.startswith("job_")
    seen_urls: set[str] = set()
    count = 0
    for card in _listing_card_html_fragments(parser, is_job=is_job):
        primary_anchor = _select_primary_anchor(card, page_url, surface=surface)
        if primary_anchor is None:
            continue
        url = str(primary_anchor[1] or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        if _detail_like_path(url, is_job=is_job):
            count += 1
    return count


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
    is_job_surface = surface.startswith("job_")
    if not _listing_card_html_fragments(dom_parser, is_job=is_job_surface):
        original_parser = LexborHTMLParser(context.original_html)
        if _listing_card_html_fragments(original_parser, is_job=is_job_surface):
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
        parser: LexborHTMLParser,
        *,
        seed_urls: set[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen_urls: set[str] = set(seed_urls or ())
        target_limit = max(1, int(limit if limit is not None else max_records))
        for card in _listing_card_html_fragments(parser, is_job=is_job_surface):
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
    dom_records = _dom_stage(dom_parser, seed_urls=structured_urls, limit=remaining)
    original_dom_records: list[dict[str, Any]] = []
    if context.original_html and context.original_html != context.cleaned_html:
        original_parser = LexborHTMLParser(context.original_html)
        cleaned_detail_anchor_count = _detail_anchor_count(
            dom_parser,
            page_url=page_url,
            surface=surface,
        )
        original_detail_anchor_count = _detail_anchor_count(
            original_parser,
            page_url=page_url,
            surface=surface,
        )
        if original_detail_anchor_count >= max(3, cleaned_detail_anchor_count + 2):
            original_dom_records = _dom_stage(
                original_parser,
                seed_urls=structured_urls,
                limit=remaining,
            )
            logger.debug(
                "Using original listing DOM after cleaned DOM lost detail-link evidence for %s",
                page_url,
            )
    rendered_listing_cards = (
        artifacts.get("rendered_listing_cards") if isinstance(artifacts, dict) else None
    )
    rendered_records = rendered_listing_records(
        rendered_listing_cards if isinstance(rendered_listing_cards, list) else None,
        page_url=page_url,
        surface=surface,
        max_records=max_records,
        title_is_noise=_listing_title_is_noise,
        url_is_structural=_url_is_structural,
    )
    rendered_records = [
        record
        for record in rendered_records
        if _record_is_supported_listing_candidate(
            record,
            page_url=page_url,
            surface=surface,
        )
    ]
    candidate_sets: list[tuple[str, list[dict[str, Any]]]] = [
        ("structured", structured_records),
        ("dom", dom_records),
        ("structured_plus_dom", [*structured_records, *dom_records]),
    ]
    if original_dom_records:
        candidate_sets.append(("original_dom", original_dom_records))
    candidate_sets.append(("rendered", rendered_records))
    best_non_visual = best_listing_candidate_set(
        candidate_sets,
        page_url=page_url,
        max_records=max_records,
        title_is_noise=_listing_title_is_noise,
        url_is_structural=_url_is_structural,
    )
    if best_non_visual:
        return best_non_visual[:max_records]
    listing_visual_elements = (
        artifacts.get("listing_visual_elements") if isinstance(artifacts, dict) else None
    )
    visual_records = visual_listing_records(
        listing_visual_elements if isinstance(listing_visual_elements, list) else None,
        page_url=page_url,
        surface=surface,
        max_records=max_records,
        title_is_noise=_listing_title_is_noise,
        url_is_structural=_url_is_structural,
    )
    if visual_records:
        return visual_records[:max_records]
    return []
