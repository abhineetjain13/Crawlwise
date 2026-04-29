from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urlparse
from typing import Any

from app.services.config.extraction_rules import (
    TITLE_PROMOTION_PREFIXES,
    TITLE_PROMOTION_SEPARATOR,
    TITLE_PROMOTION_SUBSTRINGS,
)
from app.services.field_value_core import is_title_noise, text_or_none


def promote_detail_title(
    record: dict[str, Any],
    *,
    page_url: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    source_rank: Callable[[str, str, str | None], int],
) -> tuple[str, str] | None:
    title = text_or_none(record.get("title"))
    if not title or not title_needs_promotion(title, page_url=page_url):
        return None
    values = list(candidates.get("title", []))
    sources = list(candidate_sources.get("title", []))
    ranked_candidates = sorted(
        (
            (
                source_rank("ecommerce_detail", "title", sources[index]),
                index,
                text_or_none(values[index]),
                sources[index],
            )
            for index in range(min(len(values), len(sources)))
            if text_or_none(values[index])
        ),
        key=lambda row: (row[0], row[1]),
    )
    current_rank = min(
        (
            source_rank("ecommerce_detail", "title", source)
            for source, value in zip(sources, values, strict=False)
            if text_or_none(value) == title
        ),
        default=source_rank("ecommerce_detail", "title", "dom_h1"),
    )
    replacement = next(
        (
            (candidate, source)
            for rank, _, candidate, source in ranked_candidates
            if candidate
            and candidate != title
            and not is_title_noise(candidate)
            and (
                rank < current_rank
                or (rank == current_rank and len(candidate) > len(title))
            )
        ),
        None,
    )
    if replacement:
        record["title"] = replacement[0]
        return replacement
    return None


def title_needs_promotion(title: str, *, page_url: str) -> bool:
    normalized_title = str(title or "").strip().lower()
    host = str(urlparse(page_url).hostname or "").strip().lower()
    if not normalized_title:
        return False
    if is_title_noise(normalized_title):
        return True
    if any(normalized_title.startswith(prefix) for prefix in TITLE_PROMOTION_PREFIXES):
        return True
    if TITLE_PROMOTION_SEPARATOR in normalized_title:
        return True
    if any(substring in normalized_title for substring in TITLE_PROMOTION_SUBSTRINGS):
        return True
    if not host:
        return False
    host_label = host.removeprefix("www.").split(".", 1)[0]
    compact_title = re.sub(r"[^a-z0-9]+", "", normalized_title)
    compact_host = re.sub(r"[^a-z0-9]+", "", host_label)
    return compact_title == compact_host
