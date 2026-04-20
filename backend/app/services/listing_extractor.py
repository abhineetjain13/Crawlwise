from __future__ import annotations
import logging
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.config.extraction_rules import (
    EXTRACTION_RULES,
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_DETAIL_PATH_MARKERS,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_FALLBACK_CONTAINER_SELECTOR,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_STRUCTURE_NEGATIVE_HINTS,
    LISTING_STRUCTURE_POSITIVE_HINTS,
    LISTING_WEAK_TITLES,
)
from app.services.config.selectors import CARD_SELECTORS
from app.services.extraction_context import (
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.field_policy import normalize_requested_field
from app.services.field_value_core import (
    IMAGE_FIELDS,
    PRICE_RE,
    RATING_RE,
    REVIEW_COUNT_RE,
    URL_FIELDS,
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
    if not record.get("url") or not record.get("title"):
        return {}
    return finalize_record(record, surface=surface)


def _structured_listing_url(payload: dict[str, Any], page_url: str) -> str | None:
    for key in ("url", "link", "href"):
        resolved = absolute_url(page_url, payload.get(key))
        if resolved:
            return resolved
    author = payload.get("author")
    if isinstance(author, dict):
        for key in ("url", "link", "href"):
            resolved = absolute_url(page_url, author.get(key))
            if resolved:
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
    if len(payloads) >= 2:
        return True
    for payload in payloads:
        raw_type = payload.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        ).lower()
        if "itemlist" in normalized_type:
            return True
        if isinstance(payload.get("itemListElement"), list) and payload.get("itemListElement"):
            return True
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
    return False


def _looks_like_untyped_listing_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    has_title = bool(coerce_text(payload.get("name") or payload.get("title")))
    if not has_title:
        return False
    if any(payload.get(key) for key in ("url", "link", "href")):
        return True
    author = payload.get("author")
    if isinstance(author, dict) and any(author.get(key) for key in ("url", "link", "href")):
        return True
    return bool(payload.get("price") or payload.get("offers"))


def _listing_title_is_noise(title: str) -> bool:
    lowered = clean_text(title).lower()
    if not lowered:
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
        return clean_text(str(node.text(strip=True) or ""))
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
    except Exception:
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
        if lowered_url.startswith(("javascript:", "#")) or lowered_url == page_url.lower():
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


def _extract_node_value(node, field_name: str, page_url: str) -> object | None:
    if field_name in IMAGE_FIELDS:
        srcset = _node_attr(node, "srcset")
        if srcset:
            first_candidate = str(srcset).split(",")[0].strip().split(" ")[0]
            resolved = absolute_url(page_url, first_candidate)
            if resolved:
                return resolved
        for attr_name in ("content", "src", "data-src", "data-image", "href"):
            resolved = absolute_url(page_url, _node_attr(node, attr_name))
            if resolved:
                return resolved
        return None
    if field_name in URL_FIELDS:
        for attr_name in ("href", "content", "data-apply-url"):
            resolved = absolute_url(page_url, _node_attr(node, attr_name))
            if resolved:
                return resolved
        return None
    for attr_name in ("content", "value", "datetime", "data-value", "data-price", "data-availability"):
        attr_value = _node_attr(node, attr_name)
        if attr_value:
            return coerce_field_value(field_name, attr_value, page_url)
    return coerce_field_value(field_name, _node_text(node), page_url)


def _extract_selector_values_from_node(
    root,
    selector: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    values: list[object] = []
    for node in _node_css(root, selector)[:12]:
        value = _extract_node_value(node, field_name, page_url)
        if value in (None, "", [], {}):
            continue
        values.append(value)
    return values


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


def _apply_dom_pattern_fallbacks_from_node(
    card,
    *,
    page_url: str,
    surface: str,
    candidates: dict[str, list[object]],
) -> None:
    dom_patterns = dict(EXTRACTION_RULES.get("dom_patterns") or {})
    for field_name in surface_fields(surface, None):
        selector = str(dom_patterns.get(field_name) or "").strip()
        if not selector:
            continue
        for value in _extract_selector_values_from_node(card, selector, field_name, page_url):
            add_candidate(candidates, field_name, value)


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
    title = clean_text(
        _node_attr(title_node, "title")
        or _node_attr(title_node, "alt")
        or _node_text(title_node)
        or anchor_text
    )
    if len(title) < 4 or _listing_title_is_noise(title):
        return None
    if anchor_score < 4:
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
        if not is_job and anchor_score < 8 and not has_supporting_listing_signals:
            return None
    alias_lookup = surface_alias_lookup(surface, None)
    candidates: dict[str, list[object]] = {"title": [title], "url": [url]}
    _apply_dom_pattern_fallbacks_from_node(
        card,
        page_url=page_url,
        surface=surface,
        candidates=candidates,
    )
    if selector_rules:
        card_soup = BeautifulSoup(str(getattr(card, "html", "") or ""), "html.parser")
        apply_selector_fallbacks(
            card_soup,
            page_url,
            surface,
            None,
            candidates,
            selector_rules=selector_rules,
        )
    if image_urls:
        add_candidate(candidates, "image_url", image_urls[0])
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
    selector_rules: list[dict[str, object]] | None = None,
) -> list[dict[str, Any]]:
    context = prepare_extraction_context(html)
    dom_parser = context.dom_parser

    def _structured_stage() -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for source_name, source_payloads in collect_structured_source_payloads(
            context,
            page_url=page_url,
        ):
            if source_name == "js_state":
                continue
            payload_list = list(source_payloads)
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
    if len(structured_records) >= max_records:
        return structured_records[:max_records]

    structured_urls = {
        str(record.get("url") or "")
        for record in structured_records
        if str(record.get("url") or "").strip()
    }
    remaining = max(1, int(max_records) - len(structured_records))
    dom_records = _dom_stage(seed_urls=structured_urls, limit=remaining)

    if structured_records:
        return [*structured_records, *dom_records][:max_records]
    if dom_records:
        return dom_records[:max_records]
    return []
