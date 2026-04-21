from __future__ import annotations

import re
from typing import Any, Callable

from app.services.field_value_core import absolute_url, clean_text, finalize_record


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
        rows.append(
            {
                "tag": str(item.get("tag") or "").strip().lower(),
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
    *,
    title_is_noise: Callable[[str], bool],
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
            if x + width < left or x > right or y + height < top or y > bottom:
                continue
            cluster.append(item)
        if _visual_cluster_score(cluster, title_is_noise=title_is_noise) > 0:
            clusters.append(cluster)
    clusters.sort(
        key=lambda cluster: -_visual_cluster_score(cluster, title_is_noise=title_is_noise)
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
    if len(cluster) > 8:
        score -= len(cluster) - 8
    return score


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
    title_candidates = [
        str(item.get("text") or "")
        for item in cluster
        if _visual_element_is_title(item, title_is_noise=title_is_noise)
    ]
    title = next((text for text in title_candidates if not title_is_noise(text)), "")
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
            if re.search(r"[$€£₹]\s?\d", str(item.get("text") or ""))
        ),
        "",
    )
    price_match = re.search(r"[$€£₹]?\s?[\d,.]+", price_text)
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
            price_match.group(0).strip().lstrip("$€£₹").strip().replace(",", "")
        )
    return finalize_record(record, surface=surface)


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
