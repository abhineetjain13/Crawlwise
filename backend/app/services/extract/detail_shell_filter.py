from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.services.config.extraction_rules import (
    DETAIL_BRAND_SHELL_DESCRIPTION_PHRASES,
    DETAIL_BRAND_SHELL_TITLE_TOKENS,
    TRACKING_PIXEL_PATTERNS,
)
from app.services.extract.detail_identity import (
    detail_url_is_collection_like,
    detail_url_is_utility,
)
from app.services.extract.detail_record_finalizer import (
    detail_title_looks_like_placeholder,
)
from app.services.extract.detail_title_scorer import (
    title_needs_promotion,
)
from app.services.field_value_core import (
    clean_text,
    is_title_noise,
    object_dict,
    object_list,
    text_or_none,
)

_ALNUM_SPLIT_PATTERN = r"[^a-z0-9]+"


def looks_like_site_shell_record(record: dict[str, Any], *, page_url: str) -> bool:
    title = text_or_none(record.get("title")) or ""
    field_sources = object_dict(record.get("_field_sources"))
    title_field_sources = object_list(field_sources.get("title"))
    title_sources = {
        str(source).strip() for source in title_field_sources if str(source).strip()
    }
    if detail_url_has_multiple_product_segments(page_url):
        return True
    if is_title_noise(title):
        return True
    if detail_url_is_collection_like(page_url):
        return True
    generic_detail_fields = ("price", "currency", "brand", "category")
    strong_detail_fields = (
        "brand",
        "sku",
        "part_number",
        "barcode",
        "availability",
        "variants",
    )
    has_generic_detail_fields = any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in generic_detail_fields
    )
    has_strong_detail_fields = any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in strong_detail_fields
    )
    has_identity_fields = any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in (
            "price",
            "original_price",
            "currency",
            "brand",
            "sku",
            "part_number",
            "barcode",
            "description",
            "image_url",
        )
    )
    confidence_score = float((record.get("_confidence") or {}).get("score") or 0.0)
    description_text = clean_text(record.get("description"))
    has_rich_pdp_corroboration = bool(
        record.get("price") not in (None, "", [], {})
        and record.get("image_url") not in (None, "", [], {})
        and len(description_text) >= 160
    )
    if (
        confidence_score < 0.2
        and bool(record.get("_irrelevant_detail_structured_product"))
        and title_sources == {"dom_h1"}
        and not any(
            value not in (None, "", [], {})
            for key, value in record.items()
            if not str(key).startswith("_")
            and key not in {"source_url", "url", "title"}
        )
        and not has_generic_detail_fields
        and not has_strong_detail_fields
        and not has_identity_fields
    ):
        return True
    if (
        confidence_score < 0.5
        and not has_strong_detail_fields
        and "url_slug" in title_sources
        and not has_rich_pdp_corroboration
    ):
        return True
    if (
        confidence_score < 0.5
        and description_looks_like_shell_copy(record.get("description"))
        and not has_generic_detail_fields
        and not has_strong_detail_fields
    ):
        return True
    if (
        confidence_score < 0.5
        and description_looks_like_shell_copy(record.get("description"))
        and title_looks_like_brand_shell(title, page_url=page_url)
        and not any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in (
                "price",
                "original_price",
                "currency",
                "brand",
                "availability",
                "variants",
            )
        )
    ):
        return True
    if (
        confidence_score < 0.4
        and "url_slug" in title_sources
        and has_strong_detail_fields
        and not has_identity_fields
    ):
        return True
    if detail_title_looks_like_placeholder(title) and not any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in (
            "price",
            "original_price",
            "image_url",
            "sku",
            "part_number",
            "barcode",
            "brand",
        )
    ):
        return True
    if (
        "url_slug" in title_sources
        and confidence_score < 0.5
        and str(record.get("_source") or "").strip()
        in {"opengraph", "json_ld_page_level", "microdata"}
        and not any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in strong_detail_fields
        )
    ):
        return True
    if (
        detail_title_looks_like_placeholder(title)
        and not has_generic_detail_fields
        and not any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in strong_detail_fields
        )
    ):
        return True
    if (
        has_rich_pdp_corroboration
        and "url_slug" not in title_sources
        and not detail_url_is_utility(page_url)
    ):
        return False
    if not title_needs_promotion(title, page_url=page_url):
        if (
            title_looks_like_brand_shell(title, page_url=page_url)
            and not has_generic_detail_fields
            and not any(
                record.get(field_name) not in (None, "", [], {})
                for field_name in strong_detail_fields
            )
            and (
                description_looks_like_shell_copy(record.get("description"))
                or detail_image_looks_like_tracking_or_shell(record.get("image_url"))
                or len(clean_text(record.get("description"))) <= 120
            )
        ):
            return True
        if not detail_url_is_utility(page_url):
            return False
        record_url = text_or_none(record.get("url")) or ""
        return not has_strong_detail_fields or detail_url_is_utility(record_url)
    if str(record.get("_source") or "").strip() in {
        "adapter",
        "network_payload",
        "json_ld",
        "microdata",
        "embedded_json",
        "js_state",
    }:
        return False
    if (
        title_looks_like_brand_shell(title, page_url=page_url)
        and not has_generic_detail_fields
        and description_looks_like_shell_copy(record.get("description"))
    ):
        return True
    return not any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in strong_detail_fields
    )


def detail_url_has_multiple_product_segments(url: str) -> bool:
    path = str(urlparse(url).path or "").lower()
    return any(path.count(segment) > 1 for segment in ("/prd/", "/dp/", "/products/"))


def detail_image_looks_like_tracking_or_shell(value: object) -> bool:
    image_url = text_or_none(value)
    if not image_url:
        return False
    lowered = image_url.lower()
    return any(token in lowered for token in tuple(TRACKING_PIXEL_PATTERNS or ()))


def title_looks_like_brand_shell(title: str, *, page_url: str) -> bool:
    normalized_title = str(title or "").strip().lower()
    if not normalized_title:
        return False
    host = str(urlparse(page_url).hostname or "").strip().lower()
    host_label = host.removeprefix("www.").split(".", 1)[0]
    compact_title = re.sub(_ALNUM_SPLIT_PATTERN, "", normalized_title)
    compact_host = re.sub(_ALNUM_SPLIT_PATTERN, "", host_label)
    if compact_title and compact_host and compact_title == compact_host:
        return True
    host_tokens = {
        token for token in re.split(_ALNUM_SPLIT_PATTERN, host_label) if len(token) >= 3
    }
    if not host_tokens:
        return False
    title_tokens = {
        token
        for token in re.split(_ALNUM_SPLIT_PATTERN, normalized_title)
        if len(token) >= 3
    }
    if not title_tokens or not (title_tokens & host_tokens):
        return False
    extra_tokens = title_tokens - host_tokens
    return bool(extra_tokens) and (
        extra_tokens <= set(DETAIL_BRAND_SHELL_TITLE_TOKENS)
        or (len(extra_tokens) <= 3 and len(title_tokens) <= 5)
    )


def description_looks_like_shell_copy(description: object) -> bool:
    normalized_description = str(text_or_none(description) or "").strip().lower()
    if not normalized_description:
        return False
    return any(
        phrase in normalized_description
        for phrase in DETAIL_BRAND_SHELL_DESCRIPTION_PHRASES
    )
