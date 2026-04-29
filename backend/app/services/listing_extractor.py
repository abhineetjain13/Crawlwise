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
    JOB_UTILITY_URL_TOKENS,
    LISTING_BRAND_MAX_WORDS,
    LISTING_BRAND_SELECTORS,
    LISTING_CARD_URL_ATTRS,
    LISTING_LABEL_NOISE_TOKENS,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_NON_LISTING_PATH_TOKENS,
    LISTING_PRICE_NODE_SELECTORS,
    LISTING_PROMINENT_TITLE_TAGS,
    LISTING_STRUCTURE_NEGATIVE_HINTS,
    NON_PRODUCT_IMAGE_HINTS,
    NON_PRODUCT_PROVIDER_HINTS,
    TITLE_PROMOTION_PREFIXES,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extraction_context import (
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.extract.listing_candidate_ranking import (
    best_listing_candidate_set,
    looks_like_utility_record,
)
from app.services.extract.detail_identity import (
    listing_detail_like_path,
    listing_url_is_structural,
)
from app.services.extract.listing_card_fragments import (
    listing_node_attr,
    listing_node_css,
    listing_node_text,
    select_listing_fragment_nodes,
)
from app.services.extract.listing_record_finalizer import finalize_listing_price_fields
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
    infer_currency_from_page_url,
    is_title_noise,
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

logger = logging.getLogger(__name__)
def _path_segment_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[\-\.]+", str(value or "").strip().lower())
        if token
    }


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
    if not title or is_title_noise(title):
        fallback_title = _title_from_url(url)
        if fallback_title and not is_title_noise(fallback_title):
            record["title"] = fallback_title
    if not record.get("title"):
        return {}
    if listing_url_is_structural(url, page_url):
        return {}
    return finalize_listing_price_fields(finalize_record(record, surface=surface))


def _structured_listing_url(payload: dict[str, Any], page_url: str) -> str | None:
    for key in ("url", "link", "href"):
        resolved = absolute_url(page_url, payload.get(key))
        if resolved and not listing_url_is_structural(resolved, page_url):
            return resolved
    author = payload.get("author")
    if isinstance(author, dict):
        for key in ("url", "link", "href"):
            resolved = absolute_url(page_url, author.get(key))
            if resolved and not listing_url_is_structural(resolved, page_url):
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
    allow_standalone_typed = _allow_standalone_typed_listing_payloads(payloads)
    for payload in payloads:
        for item in _structured_listing_items(
            payload,
            allow_standalone_typed=allow_standalone_typed,
        ):
            record = _structured_listing_record(item, page_url, surface)
            url = str(record.get("url") or "")
            if not url or url in seen_urls or url == page_url:
                continue
            # Reject external-domain links from JSON-LD (e.g. parent-corp privacy pages)
            if not same_host(page_url, url):
                continue
            seen_urls.add(url)
            records.append(record)
    return records


def _structured_listing_items(
    payload: dict[str, Any],
    *,
    allow_standalone_typed: bool,
) -> list[dict[str, Any]]:
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
            continue
        is_typed_listing_node = any(
            token in normalized_type for token in ("product", "jobposting")
        )
        if allow_standalone_typed and is_typed_listing_node:
            items.append(candidate)
            continue
        if is_typed_listing_node:
            continue
        if _looks_like_untyped_listing_payload(candidate):
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


def _allow_standalone_typed_listing_payloads(
    payloads: list[dict[str, Any]],
) -> bool:
    typed_candidates = 0
    threshold = max(2, int(crawler_runtime_settings.listing_min_items))
    for payload in payloads:
        for candidate in _listing_payload_candidates(payload):
            if not isinstance(candidate, dict):
                continue
            raw_type = candidate.get("@type")
            normalized_type = (
                " ".join(raw_type)
                if isinstance(raw_type, list)
                else str(raw_type or "")
            ).lower()
            if not any(
                token in normalized_type for token in ("product", "jobposting")
            ):
                continue
            title = coerce_text(candidate.get("name") or candidate.get("title"))
            url = candidate.get("url") or candidate.get("link") or candidate.get("href")
            if title and url:
                typed_candidates += 1
                if typed_candidates >= threshold:
                    return True
    return False


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
    parsed = urlsplit(url.lower())
    segments = [segment.strip().lower() for segment in parsed.path.split("/") if segment.strip()]
    if not segments:
        return False
    terminal = segments[-1]
    leading_tokens = [_path_segment_tokens(segment) for segment in segments[:-1]]
    if any(tokens & set(LISTING_NON_LISTING_PATH_TOKENS) for tokens in leading_tokens):
        return False
    terminal_tokens = _path_segment_tokens(terminal)
    if terminal_tokens & set(LISTING_NON_LISTING_PATH_TOKENS):
        return False
    if re.fullmatch(r"(?:19|20)\d{2}", terminal):
        return False
    if not re.search(r"\d{4,}", terminal):
        return False
    if any(
        marker in parsed.path
        for marker in (
            "/job/",
            "/jobs/",
            "/opening/",
            "/openings/",
            "/position/",
            "/positions/",
            "/posting/",
            "/postings/",
            "/career/",
            "/careers/",
            "/requisition/",
            "/requisitions/",
            "/role/",
            "/roles/",
            "/vacancy/",
            "/vacancies/",
        )
    ):
        return True
    terminal_words = [
        token
        for token in re.split(r"[^a-z0-9]+", terminal)
        if len(token) >= 3 and not token.isdigit()
    ]
    return len(terminal_words) >= 2


def _job_listing_title_is_hub(title: str) -> bool:
    lowered = clean_text(title).lower()
    if not lowered:
        return False
    if lowered in {"jobs", "careers", "openings"}:
        return True
    return lowered.startswith(
        (
            "jobs in ",
            "jobs near ",
            "careers in ",
            "roles in ",
            "openings in ",
        )
    )


def _job_listing_url_is_hub(url: str) -> bool:
    parsed = urlsplit(url.lower())
    segments = [segment for segment in parsed.path.split("/") if segment]
    terminal = segments[-1] if segments else ""
    if terminal in {
        "careers",
        "jobs",
        "openings",
        "search",
        "search-jobs",
        "search-results",
    }:
        return True
    if terminal.startswith(
        (
            "jobs-in-",
            "careers-in-",
            "openings-in-",
            "search-jobs",
            "job-search",
        )
    ):
        return True
    return False


def _job_listing_url_is_utility(url: str) -> bool:
    lowered = url.lower()
    return any(
        token in lowered
        for token in JOB_UTILITY_URL_TOKENS
    )


def _record_is_supported_listing_candidate(
    record: dict[str, Any],
    *,
    page_url: str,
    surface: str,
) -> bool:
    title = clean_text(record.get("title"))
    url = str(record.get("url") or "").strip()
    source_kind = str(record.get("_source") or "").strip().lower()
    if not title or not url or is_title_noise(title) or listing_url_is_structural(url, page_url):
        return False
    if looks_like_utility_record(title=title, url=url):
        return False
    is_job_surface = surface.startswith("job_")
    detail_like = listing_detail_like_path(url, is_job=is_job_surface)
    if is_job_surface and (
        _job_listing_url_is_utility(url)
        or _job_listing_url_is_hub(url)
    ):
        return False
    if is_job_surface and _job_listing_title_is_hub(title) and not detail_like:
        return False
    if detail_like:
        return True
    if _record_has_supporting_listing_signals(record, surface=surface):
        return True
    if is_job_surface and _job_listing_url_looks_like_posting(url):
        return True
    return not is_job_surface and source_kind == "structured_listing" and len(title) >= 12


def _listing_card_html_fragments(
    dom_parser: LexborHTMLParser,
    *,
    is_job: bool,
    limit: int | None = None,
) -> list[object]:
    fragment_limit = max(
        int(crawler_runtime_settings.listing_fallback_fragment_limit),
        int(limit or 0),
    )
    return select_listing_fragment_nodes(
        dom_parser,
        surface="job_listing" if is_job else "ecommerce_listing",
        limit=max(1, fragment_limit),
    )


def _node_html(node) -> str:
    try:
        return str(getattr(node, "html", "") or "").strip()
    except Exception:
        return ""


def _node_signature(node) -> str:
    return " ".join(
        [
            listing_node_attr(node, "class"),
            listing_node_attr(node, "id"),
            listing_node_attr(node, "role"),
            listing_node_attr(node, "aria-label"),
            listing_node_attr(node, "title"),
        ]
    ).lower()


def _node_tag(node) -> str:
    return str(getattr(node, "tag", "") or "").strip().lower()


def _meaningful_anchor_texts(card) -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()
    for link in listing_node_css(card, "a[href]"):
        text = clean_text(listing_node_attr(link, "title") or listing_node_text(link))
        if not text or text in seen:
            continue
        seen.add(text)
        texts.append(text)
    return texts


def _same_url_anchor_text_candidates(card, url: str) -> list[str]:
    if not url:
        return []
    texts: list[str] = []
    seen: set[str] = set()
    for link in listing_node_css(card, "a[href]"):
        href = listing_node_attr(link, "href")
        if not href or absolute_url(url, href) != url:
            continue
        text = clean_text(listing_node_attr(link, "title") or listing_node_text(link))
        if not text or text in seen:
            continue
        seen.add(text)
        texts.append(text)
    return texts


def _extract_price_signal_from_card(card) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    order = 0
    for selector in LISTING_PRICE_NODE_SELECTORS:
        for node in listing_node_css(card, selector):
            order += 1
            raw_text = clean_text(
                listing_node_attr(node, "content")
                or listing_node_attr(node, "data-price")
                or listing_node_attr(node, "aria-label")
                or listing_node_text(node)
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
            lowered_raw_text = raw_text.lower()
            if any(token in attrs or token in lowered_raw_text for token in ("sale", "now")):
                score += 4
            if any(
                token in attrs or token in lowered_raw_text
                for token in ("regular", "original", "mrp", "list")
            ):
                score -= 6
            if len(raw_text) <= 40:
                score += 2
            if extract_currency_code(price_text):
                score += 2
            candidates.append((score, order, price_text))
    if candidates:
        candidates.sort(key=lambda row: (-row[0], row[1]))
        return candidates[0][2]
    card_text = listing_node_text(card)
    fallback_price = extract_price_text(card_text, prefer_last=True)
    if not fallback_price:
        return None
    lowered_card_text = card_text.lower()
    if any(symbol in card_text for symbol in ("$", "£", "€", "₹")):
        return fallback_price
    if re.search(r"\b(?:usd|eur|gbp|inr|cad|aud|jpy|zar|aed)\b", lowered_card_text):
        return fallback_price
    if re.search(r"\b(?:price|sale|from|now|only|msrp|mrp)\b", lowered_card_text):
        return fallback_price
    return None


def _card_title_node(card) -> object | None:
    candidates: list[object] = []
    listing_extraction = EXTRACTION_RULES.get("listing_extraction")
    listing_extraction_map = listing_extraction if isinstance(listing_extraction, dict) else {}
    selectors = listing_extraction_map.get("card_title_selectors")
    selector_values = selectors if isinstance(selectors, list) else []
    for selector in selector_values:
        candidates.extend(listing_node_css(card, str(selector)))
    if candidates:
        best = max(candidates, key=lambda node: (_card_title_score(node), len(listing_node_text(node))))
        if _card_title_score(best) > 0:
            return best
    fallback_candidates = _fallback_card_title_candidates(card)
    if fallback_candidates:
        best = max(
            fallback_candidates,
            key=lambda node: (_card_title_score(node), len(listing_node_text(node))),
        )
        if _card_title_score(best) > 0:
            return best
    anchors = listing_node_css(card, "a[href]")
    if not anchors:
        return None
    best = max(anchors, key=_card_title_score)
    return best if _card_title_score(best) > 0 else None


def _card_title_score(
    node=None,
    *,
    text: str | None = None,
    attrs: str | None = None,
    tag_name: str | None = None,
    href_present: bool | None = None,
) -> int:
    if node is not None:
        text = listing_node_text(node)
        attrs = _node_signature(node)
        tag_name = _node_tag(node)
        href_present = bool(listing_node_attr(node, "href"))
    text = clean_text(text)
    if not text:
        return -100
    attrs = str(attrs or "")
    tag_name = str(tag_name or "")
    href_present = bool(href_present)
    score = 0
    if any(token in attrs for token in ("title", "name", "product", "item", "listing", "result", "job", "record", "release")):
        score += 6
    if any(token in attrs for token in ("brand", "seller", "vendor", "rating", "price", "size", "wishlist")):
        score -= 6
    if tag_name in {"h1", "h2", "h3", "h4", "h5", "a", "strong", "b"}:
        score += 2
    if text.isdigit():
        score -= 20
    if re.search(r"[a-z]", text, flags=re.I):
        score += 2
    text_len = len(text)
    if 8 <= text_len <= 180:
        score += 3
    elif text_len < 4:
        score -= 6
    elif text_len > 220:
        score -= 2
    if is_title_noise(text):
        score -= 4
    if href_present:
        score += 2
    return score


def _fallback_card_title_candidates(card) -> list[object]:
    candidates: list[object] = []
    for node in listing_node_css(card, "*"):
        tag_name = _node_tag(node)
        if tag_name in {"a", "button"}:
            continue
        text = listing_node_text(node)
        if not text or len(text) > 220:
            continue
        lowered_text = text.lower()
        if PRICE_RE.search(text):
            continue
        if any(token in lowered_text for token in ("add to bag", "add to cart", "wishlist")):
            continue
        if tag_name in LISTING_PROMINENT_TITLE_TAGS:
            candidates.append(node)
            continue
        attrs = _node_signature(node)
        if not attrs:
            continue
        if not any(token in attrs for token in ("title", "name", "product", "item")):
            continue
        candidates.append(node)
    return candidates


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
    anchors = []
    if listing_node_attr(card, "href"):
        anchors.append(card)
    anchors.extend(listing_node_css(card, "a[href]"))
    for anchor in anchors:
        url = absolute_url(page_url, listing_node_attr(anchor, "href"))
        if not url or (not same_host(page_url, url) and not same_site(page_url, url)):
            continue
        lowered_url = url.lower()
        if listing_url_is_structural(url, page_url):
            continue
        if any(token in lowered_url for token in ("sort=", "filter=", "facet=", "#review", "#details")):
            continue
        text = clean_text(
            listing_node_attr(anchor, "title")
            or listing_node_attr(anchor, "aria-label")
            or listing_node_text(anchor)
        )
        score = _card_title_score(
            text=text,
            attrs=_node_signature(anchor),
            tag_name=_node_tag(anchor),
            href_present=True,
        )
        if listing_detail_like_path(url, is_job=is_job):
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


def _select_primary_card_url(
    card,
    page_url: str,
) -> str:
    selectors = ",".join(f"[{attr}]" for attr in LISTING_CARD_URL_ATTRS)
    candidates = [card, *listing_node_css(card, selectors)]
    for candidate in candidates:
        for attr_name in LISTING_CARD_URL_ATTRS:
            url = absolute_url(page_url, listing_node_attr(candidate, attr_name))
            if url and not listing_url_is_structural(url, page_url):
                return url
    return ""


def _extract_page_images_from_node(root, page_url: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for node in listing_node_css(root, "img"):
        for attr_name in ("data-original", "data-src", "src"):
            candidate = absolute_url(page_url, listing_node_attr(node, attr_name))
            if not candidate:
                continue
            lowered = candidate.lower()
            if lowered.startswith("data:"):
                continue
            if _listing_image_candidate_is_noise(node, candidate_url=candidate):
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
                break
            seen.add(candidate)
            values.append(candidate)
            break
    return values[:12]


def _listing_image_candidate_is_noise(node, *, candidate_url: str = "") -> bool:
    context = " ".join(
        part
        for part in (
            str(candidate_url or "").strip().lower(),
            _node_signature(node),
            listing_node_attr(node, "alt").lower(),
            listing_node_attr(node, "title").lower(),
            listing_node_attr(node, "aria-label").lower(),
        )
        if part
    )
    return any(token in context for token in (*NON_PRODUCT_IMAGE_HINTS, *NON_PRODUCT_PROVIDER_HINTS))


def _extract_image_title_hint(root, *, page_url: str) -> str | None:
    for node in listing_node_css(root, "img"):
        candidate_url = absolute_url(
            page_url,
            listing_node_attr(node, "data-original")
            or listing_node_attr(node, "data-src")
            or listing_node_attr(node, "src"),
        )
        if _listing_image_candidate_is_noise(node, candidate_url=candidate_url):
            continue
        for attr_name in ("alt", "title", "aria-label"):
            candidate = _normalize_listing_title(clean_text(listing_node_attr(node, attr_name)))
            if not candidate or is_title_noise(candidate):
                continue
            return candidate
    return None


def _normalize_listing_title(title: str) -> str:
    normalized = clean_text(title)
    lowered = normalized.lower()
    for prefix in TITLE_PROMOTION_PREFIXES:
        if lowered.startswith(prefix):
            return clean_text(normalized[len(prefix) :])
    return normalized


def _title_token_overlap(left: str, right: str) -> int:
    left_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", clean_text(left).lower())
        if len(token) >= 3 and token not in {"and", "for", "the", "with"}
    }
    right_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", clean_text(right).lower())
        if len(token) >= 3 and token not in {"and", "for", "the", "with"}
    }
    if not left_tokens or not right_tokens:
        return 0
    return len(left_tokens & right_tokens)


def _should_replace_title_with_image_hint(title: str, image_title_hint: str | None) -> bool:
    hint = clean_text(image_title_hint)
    current = clean_text(title)
    if not hint or is_title_noise(hint):
        return False
    if not current:
        return True
    if current == hint:
        return False
    if is_title_noise(current):
        return True
    return _title_token_overlap(current, hint) == 0


def _extract_label_value_pairs_from_node(root) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for tr in listing_node_css(root, "tr"):
        cells = listing_node_css(tr, "th, td")
        if len(cells) < 2:
            continue
        label = listing_node_text(cells[0])
        value = listing_node_text(cells[1])
        if label and value and not _label_value_pair_is_noise(label):
            rows.append((label, value))
    for node in listing_node_css(root, "li, p, div, span"):
        text = listing_node_text(node)
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


def _extract_brand_signal_from_card(card, title: str) -> str | None:
    title_text = clean_text(title).casefold()
    for selector in LISTING_BRAND_SELECTORS:
        try:
            matches = card.css(str(selector))
        except SelectolaxError:
            continue
        for node in matches:
            value = clean_text(
                listing_node_attr(node, "content")
                or listing_node_attr(node, "title")
                or listing_node_attr(node, "aria-label")
                or listing_node_text(node)
            )
            if not value:
                continue
            if value.casefold() == title_text:
                continue
            if PRICE_RE.search(value):
                continue
            if len(re.findall(r"[a-z0-9]+", value, flags=re.I)) > LISTING_BRAND_MAX_WORDS:
                continue
            if is_title_noise(value):
                continue
            return value
    return None


def _listing_record_from_card(
    card,
    page_url: str,
    surface: str,
    *,
    selector_rules: list[dict[str, object]] | None = None,
) -> dict[str, Any] | None:
    def _selected_selector_trace(
        field_name: str,
        finalized_value: object,
    ) -> dict[str, object] | None:
        traces = list(selector_trace_candidates.get(field_name) or [])
        for trace in traces:
            if not isinstance(trace, dict):
                continue
            if trace.get("_candidate_value") == finalized_value:
                return {
                    key: value
                    for key, value in trace.items()
                    if not str(key).startswith("_")
                }
        trace = next((row for row in traces if isinstance(row, dict)), {})
        if not isinstance(trace, dict):
            return None
        return {
            key: value
            for key, value in trace.items()
            if not str(key).startswith("_")
        }

    is_job = surface.startswith("job_")
    title_node = _card_title_node(card)
    primary_anchor = _select_primary_anchor(
        card,
        page_url,
        surface=surface,
        title_node=title_node,
    )
    if primary_anchor is None:
        fallback_url = _select_primary_card_url(card, page_url)
        if not fallback_url or title_node is None:
            return None
        primary_anchor = (
            title_node,
            fallback_url,
            clean_text(listing_node_text(title_node)),
            max(10, _card_title_score(title_node) + 4),
        )
    anchor_node, url, anchor_text, anchor_score = primary_anchor
    title_node = title_node or anchor_node
    title_score = _card_title_score(title_node)
    image_title_hint = _extract_image_title_hint(card, page_url=page_url)
    title = clean_text(
        listing_node_attr(title_node, "title")
        or listing_node_attr(title_node, "alt")
        or listing_node_text(title_node)
        or anchor_text
    )
    same_url_texts = _same_url_anchor_text_candidates(card, url)
    best_same_url_text = next(
        (
            text
            for text in sorted(same_url_texts, key=len, reverse=True)
            if len(re.findall(r"[a-z0-9]+", text, flags=re.I)) >= 3
            and not PRICE_RE.search(text)
            and not is_title_noise(text)
        ),
        None,
    )
    if best_same_url_text and (
        len(re.findall(r"[a-z0-9]+", title, flags=re.I)) < 3 or is_title_noise(title)
    ):
        title = best_same_url_text
    if _should_replace_title_with_image_hint(title, image_title_hint):
        title = clean_text(image_title_hint)
    title = _normalize_listing_title(title)
    if len(title) < 4 or is_title_noise(title):
        return None
    if anchor_score < 4 and title_score < 8:
        return None
    card_text = listing_node_text(card)
    image_urls = _extract_page_images_from_node(card, page_url)
    has_supporting_listing_signals = bool(
        PRICE_RE.search(card_text)
        or RATING_RE.search(card_text)
        or REVIEW_COUNT_RE.search(card_text)
        or image_urls
    )
    if not listing_detail_like_path(url, is_job=is_job):
        if is_job and anchor_score < 8:
            if not any(token in card_text.lower() for token in ("salary", "remote", "location", "apply")):
                return None
        if not is_job and anchor_score < 8 and not has_supporting_listing_signals and title_score < 8:
            return None
    alias_lookup = surface_alias_lookup(surface, None)
    candidates: dict[str, list[object]] = {"title": [title], "url": [url]}
    selector_trace_candidates: dict[str, list[dict[str, object]]] = {}
    card_soup = BeautifulSoup(str(getattr(card, "html", "") or ""), "html.parser")
    apply_selector_fallbacks(
        card_soup,
        page_url,
        surface,
        None,
        candidates,
        selector_rules=selector_rules,
        selector_trace_candidates=selector_trace_candidates,
    )
    if not is_job and not candidates.get("brand"):
        brand_text = _extract_brand_signal_from_card(card, title)
        if brand_text:
            add_candidate(candidates, "brand", brand_text)
    if image_urls and not candidates.get("image_url"):
        add_candidate(candidates, "image_url", image_urls[0])
    if best_same_url_text and not candidates.get("description"):
        description_text = next(
            (
                text
                for text in same_url_texts
                if text != title
                and len(text) >= 20
                and len(re.findall(r"[a-z0-9]+", text, flags=re.I)) >= 3
                and not PRICE_RE.search(text)
                and not is_title_noise(text)
                and (
                    _title_token_overlap(text, title) >= 2
                    or len(re.findall(r"[a-z0-9]+", text, flags=re.I)) >= 5
                )
            ),
            None,
        )
        if description_text:
            add_candidate(candidates, "description", description_text)
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
        else:
            inferred_currency = infer_currency_from_page_url(page_url)
            if inferred_currency and candidates.get("price"):
                add_candidate(candidates, "currency", inferred_currency)
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
    selected_selector_traces: dict[str, dict[str, object]] = {}
    for field_name in surface_fields(surface, None):
        finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
            selector_trace = _selected_selector_trace(field_name, finalized)
            if selector_trace:
                selected_selector_traces[field_name] = selector_trace
    if selected_selector_traces:
        record["_selector_traces"] = selected_selector_traces
    cleaned = finalize_record(record, surface=surface)
    if not cleaned.get("url") or not cleaned.get("title"):
        return None
    cleaned_title = clean_text(cleaned.get("title"))
    cleaned_url = str(cleaned.get("url") or "").strip()
    allow_title_only_dom_candidate = (
        not is_job
        and anchor_score >= 10
        and title_score >= 10
        and len(re.findall(r"[a-z0-9]+", cleaned_title, flags=re.I)) >= 3
        and not listing_url_is_structural(cleaned_url, page_url)
        and not looks_like_utility_record(
            title=cleaned_title,
            url=cleaned_url,
        )
        and not re.match(r"^(?:article|flyer|guide|manual|resource)\s*:", cleaned_title, flags=re.I)
        and not re.search(r"\.(?:pdf|docx?|pptx?)(?:$|[?#])", cleaned_url, flags=re.I)
        and not any(
            token in cleaned_url.lower()
            for token in (
                "/article/",
                "/articles/",
                "/assets/",
                "/deepweb/",
                "/technical-documents/",
                "/technical-article/",
            )
        )
        and _title_token_overlap(cleaned_title, _title_from_url(cleaned_url) or "") >= 2
    )
    if not _record_is_supported_listing_candidate(
        cleaned,
        page_url=page_url,
        surface=surface,
    ):
        if not allow_title_only_dom_candidate:
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
        if listing_detail_like_path(url, is_job=is_job):
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
    network_payloads: list[dict[str, object]] | None = None,
) -> list[dict[str, Any]]:
    del network_payloads
    context = prepare_extraction_context(html)
    dom_parser = context.dom_parser
    is_job_surface = surface.startswith("job_")
    if not _listing_card_html_fragments(
        dom_parser,
        is_job=is_job_surface,
        limit=max_records,
    ):
        original_parser = LexborHTMLParser(context.original_html)
        if _listing_card_html_fragments(
            original_parser,
            is_job=is_job_surface,
            limit=max_records,
        ):
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
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        skipped_urls: set[str] = set(seed_urls or ())
        for card in _listing_card_html_fragments(
            parser,
            is_job=is_job_surface,
            limit=max_records,
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
            if not url or url in skipped_urls:
                continue
            records.append(record)
        return records

    structured_records = _structured_stage()
    dom_records = _dom_stage(
        dom_parser,
    )
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
            )
            logger.debug(
                "Using original listing DOM after cleaned DOM lost detail-link evidence for %s",
                page_url,
            )
    rendered_fragments = (
        artifacts.get("rendered_listing_fragments") if isinstance(artifacts, dict) else None
    )
    rendered_dom_records: list[dict[str, Any]] = []
    if isinstance(rendered_fragments, list):
        rendered_fragment_html = "\n".join(
            fragment
            for fragment in (
                str(item or "").strip() for item in rendered_fragments
            )
            if fragment
        )
        if rendered_fragment_html:
            rendered_parser = LexborHTMLParser(
                f"<html><body>{rendered_fragment_html}</body></html>"
            )
            rendered_dom_records = _dom_stage(
                rendered_parser,
            )
    listing_visual_elements = (
        artifacts.get("listing_visual_elements") if isinstance(artifacts, dict) else None
    )
    visual_records = visual_listing_records(
        listing_visual_elements if isinstance(listing_visual_elements, list) else None,
        page_url=page_url,
        surface=surface,
        max_records=max_records,
        title_is_noise=is_title_noise,
        url_is_structural=listing_url_is_structural,
    )
    visual_records = [
        record
        for record in visual_records
        if _record_is_supported_listing_candidate(
            record,
            page_url=page_url,
            surface=surface,
        )
    ]
    candidate_sets: list[tuple[str, list[dict[str, Any]]]] = [
        ("structured", structured_records),
        ("dom", dom_records),
        ("structured_plus_dom", [*dom_records, *structured_records]),
    ]
    if original_dom_records:
        candidate_sets.append(("original_dom", original_dom_records))
    if rendered_dom_records:
        candidate_sets.append(("rendered_dom", rendered_dom_records))
    if visual_records:
        candidate_sets.append(("visual", visual_records))
    best_records = best_listing_candidate_set(
        candidate_sets,
        page_url=page_url,
        surface=surface,
        max_records=max_records,
        title_is_noise=is_title_noise,
        url_is_structural=listing_url_is_structural,
        detail_like_url=lambda candidate_url: listing_detail_like_path(
            candidate_url,
            is_job=is_job_surface,
        ),
    )
    if best_records:
        return best_records
    return []
