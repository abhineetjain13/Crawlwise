from __future__ import annotations

import re
from typing import Any, Callable

from app.services.config.extraction_rules import (
    LISTING_UTILITY_TITLE_PATTERNS,
    LISTING_UTILITY_TITLE_TOKENS,
)
from app.services.field_value_core import (
    absolute_url,
    clean_text,
    extract_currency_code,
    extract_price_text,
    finalize_record,
    infer_brand_from_product_url,
    infer_brand_from_title_marker,
)


def visual_listing_records(
    visual_elements: list[dict[str, object]] | None,
    *,
    page_url: str,
    surface: str,
    max_records: int,
    title_is_noise: Callable[[str], bool],
    url_is_structural: Callable[[str, str], bool],
) -> list[dict[str, Any]]:
    elements = _normalized_visual_elements(visual_elements, page_url=page_url)
    if not elements:
        return []
    clusters = _cluster_visual_elements(elements, title_is_noise=title_is_noise)
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for cluster in clusters:
        record = _visual_cluster_to_record(
            cluster,
            page_url=page_url,
            surface=surface,
            title_is_noise=title_is_noise,
            url_is_structural=url_is_structural,
        )
        if record is None:
            continue
        url = str(record.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        records.append(record)
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
        rows.append(
            {
                "tag": str(item.get("tag") or "").strip().lower(),
                "raw_text": clean_text(item.get("text")),
                "raw_alt": clean_text(item.get("alt")),
                "raw_aria_label": clean_text(item.get("ariaLabel")),
                "raw_title": clean_text(item.get("title")),
                "text": clean_text(
                    " ".join(
                        str(value or "")
                        for value in (
                            item.get("text"),
                            item.get("alt"),
                            item.get("ariaLabel"),
                            item.get("title"),
                        )
                    )
                ),
                "href": absolute_url(page_url, item.get("href")),
                "src": absolute_url(page_url, item.get("src")),
                "x": _coerce_visual_number(item.get("x")),
                "y": _coerce_visual_number(item.get("y")),
                "width": width,
                "height": height,
                "score": _coerce_visual_number(item.get("score")),
            }
        )
    return rows


def _coerce_visual_number(value: object) -> int:
    if value is None:
        return 0
    try:
        if isinstance(value, (int, float)):
            return int(float(value))
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _cluster_visual_elements(
    elements: list[dict[str, Any]],
    *,
    title_is_noise: Callable[[str], bool],
) -> list[list[dict[str, Any]]]:
    anchors = [item for item in elements if item.get("href")]
    if not anchors:
        return []
    anchors.sort(key=lambda item: (int(item.get("y") or 0), int(item.get("x") or 0)))
    clusters_by_href: dict[str, tuple[int, tuple[int, int], list[dict[str, Any]]]] = {}
    for anchor in anchors:
        anchor_href = str(anchor.get("href") or "")
        anchor_y = int(anchor.get("y") or 0)
        cluster = [anchor]
        left = int(anchor.get("x") or 0) - 80
        right = left + int(anchor.get("width") or 0) + 160
        top = int(anchor.get("y") or 0) - 80
        bottom = top + int(anchor.get("height") or 0) + 260
        for item in elements:
            if item is anchor:
                continue
            item_href = str(item.get("href") or "")
            if item_href and item_href != anchor_href:
                continue
            x = int(item.get("x") or 0)
            y = int(item.get("y") or 0)
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if not item_href and y + height < anchor_y:
                continue
            if x + width < left or x > right or y + height < top or y > bottom:
                continue
            cluster.append(item)
        score = _visual_cluster_score(cluster, title_is_noise=title_is_noise)
        if score <= 0:
            continue
        origin = _visual_cluster_origin(cluster)
        current = clusters_by_href.get(anchor_href)
        if current is None or score > current[0] or (
            score == current[0] and origin < current[1]
        ):
            clusters_by_href[anchor_href] = (score, origin, cluster)
    clusters = [entry[2] for entry in clusters_by_href.values()]
    clusters.sort(
        key=lambda cluster: (
            _visual_cluster_origin(cluster)[0],
            _visual_cluster_origin(cluster)[1],
            -_visual_cluster_score(cluster, title_is_noise=title_is_noise),
        )
    )
    return clusters


def _visual_cluster_score(
    cluster: list[dict[str, Any]],
    *,
    title_is_noise: Callable[[str], bool],
) -> int:
    if not cluster:
        return -100
    hrefs = {str(item.get("href") or "") for item in cluster if item.get("href")}
    if len(hrefs) != 1:
        return -50
    score = 10
    if any(
        _visual_element_is_title(item, title_is_noise=title_is_noise) for item in cluster
    ):
        score += 8
    if any(re.search(r"[$€£₹]\s?\d", str(item.get("text") or "")) for item in cluster):
        score += 4
    if any(str(item.get("tag") or "") == "img" and item.get("src") for item in cluster):
        score += 3
    score += max(
        int(item.get("score") or 0)
        for item in cluster
    )
    if len(cluster) > 12:
        score -= (len(cluster) - 12) // 2
    return score


def _visual_cluster_origin(cluster: list[dict[str, Any]]) -> tuple[int, int]:
    if not cluster:
        return (0, 0)
    return (
        min(int(item.get("y") or 0) for item in cluster),
        min(int(item.get("x") or 0) for item in cluster),
    )


def _visual_element_is_title(
    item: dict[str, Any],
    *,
    title_is_noise: Callable[[str], bool],
) -> bool:
    text = str(item.get("text") or "")
    if not text or title_is_noise(text) or re.search(r"[$€£₹]\s?\d", text):
        return False
    return str(item.get("tag") or "") in {"a", "h1", "h2", "h3"} or len(text) <= 180


def _visual_cluster_to_record(
    cluster: list[dict[str, Any]],
    *,
    page_url: str,
    surface: str,
    title_is_noise: Callable[[str], bool],
    url_is_structural: Callable[[str, str], bool],
) -> dict[str, Any] | None:
    href = next((str(item.get("href") or "") for item in cluster if item.get("href")), "")
    if not href or url_is_structural(href, page_url):
        return None
    title_item, title = _visual_cluster_title_candidate(
        cluster,
        href=href,
        title_is_noise=title_is_noise,
    )
    if not title:
        return None
    if _visual_title_is_utility(title):
        return None
    brand = _visual_cluster_brand(
        cluster,
        title=title,
        href=href,
        anchor_item=_visual_primary_anchor_item(cluster, href=href),
        title_item=title_item,
    )
    image_url = next(
        (str(item.get("src") or "") for item in cluster if item.get("src")),
        "",
    )
    price_text = next(
        (
            str(item.get("text") or "")
            for item in cluster
            if extract_price_text(str(item.get("text") or ""))
        ),
        "",
    )
    extracted_price = extract_price_text(price_text, prefer_last=False, allow_unmarked=True)
    is_job = surface.startswith("job_")
    if not is_job and not extracted_price and not _visual_title_matches_url(title, href):
        return None
    record = {
        "source_url": page_url,
        "_source": "visual_listing",
        "title": title,
        "url": href,
    }
    if brand:
        record["brand"] = brand
    if image_url:
        record["image_url"] = image_url
    if extracted_price:
        record["price"] = extracted_price
        currency_code = extract_currency_code(extracted_price)
        if currency_code:
            record["currency"] = currency_code
    return finalize_record(record, surface=surface)


def _visual_cluster_title_candidate(
    cluster: list[dict[str, Any]],
    *,
    href: str,
    title_is_noise: Callable[[str], bool],
) -> tuple[dict[str, Any] | None, str]:
    anchor_item = _visual_primary_anchor_item(cluster, href=href)
    candidates: list[tuple[int, dict[str, Any], str]] = []
    for item in cluster:
        if not _visual_element_is_title(item, title_is_noise=title_is_noise):
            continue
        text = clean_text(item.get("text") or "")
        if not text or title_is_noise(text):
            continue
        candidates.append(
            (
                _visual_title_candidate_score(
                    item,
                    text=text,
                    href=href,
                    anchor_item=anchor_item,
                ),
                item,
                text,
            )
        )
    if not candidates:
        return (None, "")
    candidates.sort(key=lambda item: (-item[0], len(item[2]), item[2]))
    return (candidates[0][1], candidates[0][2])


def _visual_title_candidate_score(
    item: dict[str, Any],
    *,
    text: str,
    href: str,
    anchor_item: dict[str, Any] | None,
) -> int:
    score = 0
    item_href = str(item.get("href") or "")
    if item_href and item_href == href:
        score += 8
    if _visual_title_matches_url(text, href):
        score += 6
    tag = str(item.get("tag") or "")
    if tag in {"h1", "h2", "h3"}:
        score += 4
    if tag == "img" and clean_text(item.get("raw_alt") or ""):
        score += 3
    if 6 <= len(text) <= 120:
        score += 2
    if len(text) > 120:
        score -= max(1, (len(text) - 120) // 12)
    if anchor_item is not None:
        overlap = _visual_horizontal_overlap(item, anchor_item)
        if overlap > 0:
            score += 5
        else:
            score -= 5
    return score


def _visual_title_is_utility(title: str) -> bool:
    lowered = clean_text(title).casefold()
    if not lowered:
        return True
    if any(re.search(pattern, lowered, flags=re.I) for pattern in LISTING_UTILITY_TITLE_PATTERNS):
        return True
    return any(token in lowered for token in LISTING_UTILITY_TITLE_TOKENS)


def _visual_cluster_brand(
    cluster: list[dict[str, Any]],
    *,
    title: str,
    href: str,
    anchor_item: dict[str, Any] | None,
    title_item: dict[str, Any] | None,
) -> str:
    title_text = clean_text(title).casefold()
    for item in cluster:
        item_href = str(item.get("href") or "")
        if item_href and item_href != href:
            continue
        marker = " ".join(
            str(item.get(key) or "")
            for key in ("tag", "text", "raw_aria_label", "raw_title")
        ).casefold()
        if "brand" not in marker:
            continue
        if not _visual_brand_item_aligned(
            item,
            anchor_item=anchor_item,
            title_item=title_item,
        ):
            continue
        value = clean_text(
            item.get("raw_text")
            or item.get("raw_alt")
            or item.get("text")
            or ""
        )
        if not value or value.casefold() == title_text or extract_price_text(value):
            continue
        return value
    return (
        infer_brand_from_title_marker(title)
        or infer_brand_from_product_url(url=href, title=title)
        or ""
    )


def _visual_primary_anchor_item(
    cluster: list[dict[str, Any]],
    *,
    href: str,
) -> dict[str, Any] | None:
    anchors = [item for item in cluster if str(item.get("href") or "") == href]
    if not anchors:
        return None
    anchors.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            -(int(item.get("width") or 0) * int(item.get("height") or 0)),
        )
    )
    return anchors[0]


def _visual_brand_item_aligned(
    item: dict[str, Any],
    *,
    anchor_item: dict[str, Any] | None,
    title_item: dict[str, Any] | None,
) -> bool:
    reference = title_item or anchor_item
    if reference is None:
        return True
    return _visual_horizontal_overlap(item, reference) > 0


def _visual_horizontal_overlap(left: dict[str, Any], right: dict[str, Any]) -> int:
    left_start = int(left.get("x") or 0)
    left_end = left_start + int(left.get("width") or 0)
    right_start = int(right.get("x") or 0)
    right_end = right_start + int(right.get("width") or 0)
    return max(0, min(left_end, right_end) - max(left_start, right_start))


def _visual_title_matches_url(title: str, href: str) -> bool:
    return bool(
        (title_tokens := _visual_match_tokens(title))
        and (path_tokens := _visual_match_tokens(href))
        and title_tokens & path_tokens
    )


def _visual_match_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", clean_text(value).lower())
        if len(token) >= 2
        and token
        not in {
            "and",
            "buy",
            "care",
            "category",
            "collections",
            "details",
            "for",
            "hair",
            "in",
            "item",
            "items",
            "language",
            "location",
            "now",
            "page",
            "product",
            "products",
            "region",
            "select",
            "shop",
            "the",
            "to",
            "with",
            "your",
        }
    }
