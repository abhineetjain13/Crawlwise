from __future__ import annotations

from typing import Any, Callable

from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.field_value_core import absolute_url, clean_text, finalize_record


def rendered_listing_records(
    rendered_cards: list[dict[str, object]] | None,
    *,
    page_url: str,
    surface: str,
    max_records: int,
    title_is_noise: Callable[[str], bool],
    url_is_structural: Callable[[str, str], bool],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in list(rendered_cards or [])[: max(1, int(max_records)) * 4]:
        if not isinstance(item, dict):
            continue
        url = absolute_url(page_url, item.get("url") or item.get("href"))
        if not url or url in seen_urls or url_is_structural(url, page_url):
            continue
        title = clean_text(item.get("title"))
        if not title or title_is_noise(title):
            continue
        record = finalize_record(
            {
                "source_url": page_url,
                "_source": "rendered_listing",
                "title": title,
                "url": url,
                "price": clean_text(item.get("price")),
                "image_url": absolute_url(
                    page_url,
                    item.get("image_url") or item.get("image"),
                ),
                "brand": clean_text(item.get("brand")),
            },
            surface=surface,
        )
        if not record.get("title") or not record.get("url"):
            continue
        seen_urls.add(url)
        rows.append(record)
        if len(rows) >= max_records:
            break
    return rows


def best_listing_candidate_set(
    candidate_sets: list[tuple[str, list[dict[str, Any]]]],
    *,
    page_url: str,
    max_records: int,
    title_is_noise: Callable[[str], bool],
    url_is_structural: Callable[[str, str], bool],
) -> list[dict[str, Any]]:
    best_records: list[dict[str, Any]] = []
    best_score = (-1, -1, -1, -1, -1)
    for _name, records in candidate_sets:
        limited = [
            record
            for record in list(records or [])[:max_records]
            if isinstance(record, dict)
        ]
        score = _listing_record_set_score(
            limited,
            page_url=page_url,
            title_is_noise=title_is_noise,
            url_is_structural=url_is_structural,
        )
        if score > best_score:
            best_score = score
            best_records = limited
    return best_records


def _listing_record_set_score(
    records: list[dict[str, Any]],
    *,
    page_url: str,
    title_is_noise: Callable[[str], bool],
    url_is_structural: Callable[[str, str], bool],
) -> tuple[int, int, int, int, int]:
    if not records:
        return (-1, -1, -1, -1, -1)
    quality_scores = [
        _listing_record_quality_score(
            record,
            page_url=page_url,
            title_is_noise=title_is_noise,
            url_is_structural=url_is_structural,
        )
        for record in records
        if isinstance(record, dict)
    ]
    if not quality_scores:
        return (-1, -1, -1, -1, -1)
    strong_records = sum(
        score >= crawler_runtime_settings.listing_candidate_strong_score_threshold
        for score in quality_scores
    )
    priced_records = sum(
        record.get("price") not in (None, "", [], {})
        for record in records
        if isinstance(record, dict)
    )
    imaged_records = sum(
        record.get("image_url") not in (None, "", [], {})
        for record in records
        if isinstance(record, dict)
    )
    avg_quality = int(round(sum(quality_scores) / max(1, len(quality_scores)) * 100))
    return (
        strong_records,
        priced_records + imaged_records,
        avg_quality,
        len(records),
        sum(quality_scores),
    )


def _listing_record_quality_score(
    record: dict[str, Any],
    *,
    page_url: str,
    title_is_noise: Callable[[str], bool],
    url_is_structural: Callable[[str, str], bool],
) -> int:
    title = clean_text(record.get("title"))
    url = str(record.get("url") or "").strip()
    score = 0
    if title:
        score += 6
        if len(title) >= 12:
            score += 1
    else:
        score -= 10
    if title and title_is_noise(title):
        score -= 8
    if url and not url_is_structural(url, page_url):
        score += 8
    else:
        score -= 12
    if record.get("price") not in (None, "", [], {}):
        score += 6
    if record.get("image_url") not in (None, "", [], {}):
        score += 4
    if record.get("brand") not in (None, "", [], {}):
        score += 2
    if record.get("rating") not in (None, "", [], {}):
        score += 1
    if record.get("review_count") not in (None, "", [], {}):
        score += 1
    cleaned_description = clean_text(record.get("description"))
    if isinstance(cleaned_description, str) and len(cleaned_description) >= 24:
        score += 1
    if record.get("_source") == "visual_listing":
        score -= 6
    elif record.get("_source") in {"rendered_listing", "dom_listing"}:
        score += 2
    if (
        record.get("price") in (None, "", [], {})
        and record.get("image_url") in (None, "", [], {})
        and record.get("brand") in (None, "", [], {})
    ):
        score -= 5
    return score
