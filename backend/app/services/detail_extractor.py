from __future__ import annotations

import logging
import re
from itertools import product
from urllib.parse import urlparse
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.confidence import score_record_confidence
from app.services.config.field_mappings import (
    DOM_HIGH_VALUE_FIELDS,
    DOM_OPTIONAL_CUE_FIELDS,
    ECOMMERCE_DETAIL_JS_STATE_FIELDS,
    VARIANT_DOM_FIELD_NAMES,
)
from app.services.config.extraction_rules import (
    DETAIL_UTILITY_PATH_TOKENS,
    DETAIL_TITLE_SOURCE_RANKS,
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_ACTION_NOISE_PATTERNS,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    SOURCE_PRIORITY,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_TITLE_CTA_TITLES,
    LISTING_WEAK_TITLES,
    TITLE_PROMOTION_PREFIXES,
    TITLE_PROMOTION_SEPARATOR,
    TITLE_PROMOTION_SUBSTRINGS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extraction_context import (
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.structured_sources import harvest_js_state_objects
from app.services.field_value_core import (
    LONG_TEXT_FIELDS,
    PRODUCT_URL_HINTS,
    RATING_RE,
    REVIEW_COUNT_RE,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    clean_text,
    coerce_field_value,
    extract_currency_code,
    finalize_record,
    same_site,
    surface_alias_lookup,
    surface_fields,
    text_or_none,
)
from app.services.field_value_candidates import (
    add_candidate,
    collect_structured_candidates,
    finalize_candidate_value,
    record_score,
)
from app.services.field_value_dom import (
    apply_selector_fallbacks,
    dedupe_image_urls,
    extract_heading_sections,
    extract_page_images,
    requested_content_extractability,
)
from app.services.js_state_mapper import map_js_state_to_fields
from app.services.js_state_helpers import select_variant
from app.services.network_payload_mapper import map_network_payloads_to_fields
from app.services.extract.shared_variant_logic import (
    iter_variant_choice_groups,
    iter_variant_select_groups,
    normalized_variant_axis_key,
    resolve_variants,
    resolve_variant_group_name,
    split_variant_axes,
    variant_dom_cues_present,
)
from app.services.field_policy import exact_requested_field_key
from app.services.extract.detail_tiers import (
    DetailTierState,
    collect_authoritative_tier,
    collect_dom_tier,
    collect_js_state_tier,
    collect_structured_data_tier,
    materialize_detail_tier,
)

logger = logging.getLogger(__name__)
_LOW_SIGNAL_LONG_TEXT_VALUES = frozenset(
    {
        "description",
        "details",
        "normal",
        "overview",
        "product summary",
        "specifications",
    }
)
_DETAIL_IDENTITY_STOPWORDS = frozenset(
    {
        "and",
        "buy",
        "fit",
        "for",
        "men",
        "online",
        "oversized",
        "product",
        "products",
        "shirt",
        "shirts",
        "souled",
        "store",
        "tee",
        "tees",
        "the",
        "tshirt",
        "tshirts",
        "women",
    }
)
_LONG_TEXT_SOURCE_RANKS = {
    "adapter": 0,
    "network_payload": 1,
    "dom_sections": 2,
    "selector_rule": 3,
    "dom_selector": 4,
    "json_ld": 5,
    "microdata": 6,
    "embedded_json": 7,
    "js_state": 8,
    "opengraph": 9,
    "dom_h1": 10,
    "dom_canonical": 11,
    "dom_images": 12,
    "dom_text": 13,
}

def _field_source_rank(surface: str, field_name: str, source: str | None) -> int:
    if str(surface or "").strip().lower() == "ecommerce_detail":
        if field_name == "title":
            return DETAIL_TITLE_SOURCE_RANKS.get(str(source or ""), 20)
        if field_name in LONG_TEXT_FIELDS:
            return _LONG_TEXT_SOURCE_RANKS.get(str(source or ""), 20)
        if field_name in ECOMMERCE_DETAIL_JS_STATE_FIELDS and source == "js_state":
            return 2
    return 100 + _SOURCE_PRIORITY_RANK.get(source, len(_SOURCE_PRIORITY_RANK))

def _detail_title_is_noise(title: object) -> bool:
    cleaned = clean_text(title)
    lowered = cleaned.lower()
    if not lowered:
        return True
    if "undefined" in lowered or lowered in {"nan", "none", "null"}:
        return True
    if len(cleaned) < 4 or cleaned.isdigit():
        return True
    if "star" in lowered and RATING_RE.search(lowered) and len(cleaned.split()) <= 4:
        return True
    if lowered in LISTING_TITLE_CTA_TITLES:
        return True
    if lowered in LISTING_NAVIGATION_TITLE_HINTS or lowered in LISTING_WEAK_TITLES:
        return True
    if any(lowered.startswith(prefix) for prefix in LISTING_MERCHANDISING_TITLE_PREFIXES):
        return True
    if any(pattern.search(lowered) for pattern in LISTING_ACTION_NOISE_PATTERNS):
        return True
    if LISTING_ALT_TEXT_TITLE_PATTERN.search(lowered):
        return True
    return any(pattern.search(lowered) for pattern in LISTING_EDITORIAL_TITLE_PATTERNS)

def _detail_title_from_url(page_url: str) -> str | None:
    path_segments = [
        segment
        for segment in str(urlparse(page_url).path or "").strip("/").split("/")
        if segment
    ]
    if not path_segments:
        return None
    for segment in reversed(path_segments):
        terminal = re.sub(r"\.(html?|htm)$", "", segment, flags=re.I)
        if not terminal or terminal.isdigit():
            continue
        if re.fullmatch(r"[a-f0-9]{8,}(?:-[a-f0-9]{4,}){2,}", terminal, re.I):
            continue
        if terminal in {"p", "dp", "product", "products", "job", "jobs", "release"}:
            continue
        title = clean_text(re.sub(r"[-_]+", " ", terminal))
        if title and not _detail_title_is_noise(title):
            return title
    return None

def _apply_dom_fallbacks(
    dom_parser: LexborHTMLParser,
    soup: BeautifulSoup,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_rules: list[dict[str, object]] | None = None,
) -> None:
    fields = surface_fields(surface, requested_fields)
    h1 = dom_parser.css_first("h1")
    page_title = dom_parser.css_first("title")
    h1_title = text_or_none(h1.text(separator=" ", strip=True) if h1 else "")
    page_title_text = text_or_none(page_title.text(separator=" ", strip=True) if page_title else "")
    title = next(
        (
            candidate
            for candidate in (h1_title, page_title_text)
            if candidate and not _detail_title_is_noise(candidate)
        ),
        None,
    )
    if title:
        _add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            "title",
            title,
            source="dom_h1",
        )
    apply_selector_fallbacks(
        soup,
        page_url,
        surface,
        requested_fields,
        candidates,
        selector_rules=selector_rules,
        candidate_sources=candidate_sources,
        field_sources=field_sources,
    )
    canonical = soup.find("link", attrs={"rel": re.compile("canonical", re.I)})
    if canonical is not None:
        from app.services.field_value_core import absolute_url

        _add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            "url",
            absolute_url(page_url, canonical.get("href")),
            source="dom_canonical",
        )
    images = extract_page_images(
        soup,
        page_url,
        exclude_linked_detail_images=False,
        surface=surface,
    )
    if images:
        _add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            "image_url",
            images[0],
            source="dom_images",
        )
        _add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            "additional_images",
            images[1:],
            source="dom_images",
        )
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    for label, value in extract_heading_sections(soup).items():
        normalized = alias_lookup.get(label.lower()) or alias_lookup.get(
            re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        )
        if normalized:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                normalized,
                coerce_field_value(normalized, value, page_url),
                source="dom_sections",
            )
    body_node = dom_parser.body
    body_text = (
        clean_text(body_node.text(separator=" ", strip=True)) if body_node else ""
    )
    if "currency" in fields and not candidates.get("currency"):
        for price_value in list(candidates.get("price") or []):
            currency_code = extract_currency_code(price_value)
            if not currency_code:
                continue
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "currency",
                currency_code,
                source="dom_text",
            )
            break
    if "review_count" in fields and not candidates.get("review_count"):
        review_match = REVIEW_COUNT_RE.search(body_text)
        if review_match:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "review_count",
                review_match.group(1),
                source="dom_text",
            )
    if "rating" in fields and not candidates.get("rating"):
        rating_match = RATING_RE.search(body_text)
        if rating_match:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "rating",
                rating_match.group(1),
                source="dom_text",
            )
    if surface.startswith("job_") and "remote" in fields and not candidates.get(
        "remote"
    ):
        lowered = body_text.lower()
        if "remote" in lowered or "work from home" in lowered:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "remote",
                "remote",
                source="dom_text",
            )

def _add_sourced_candidate(
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    field_name: str,
    value: object,
    *,
    source: str,
) -> None:
    if _long_text_candidate_is_noise(field_name, value, source=source):
        return
    before = len(candidates.get(field_name, []))
    add_candidate(candidates, field_name, value)
    after = len(candidates.get(field_name, []))
    if after <= before:
        return
    candidate_sources.setdefault(field_name, []).extend([source] * (after - before))
    bucket = field_sources.setdefault(field_name, [])
    if source not in bucket:
        bucket.append(source)


def _long_text_candidate_is_noise(
    field_name: str,
    value: object,
    *,
    source: str | None = None,
) -> bool:
    if field_name not in LONG_TEXT_FIELDS:
        return False
    cleaned = clean_text(value)
    lowered = cleaned.lower()
    if not lowered:
        return True
    if lowered in _LOW_SIGNAL_LONG_TEXT_VALUES:
        return True
    if field_name in {"description", "specifications"} and lowered.startswith(
        ("check the details", "product summary")
    ):
        return True
    if (
        source == "dom_sections"
        and field_name in {"description", "specifications", "product_details"}
        and len(cleaned.split()) <= 4
        and not any(token in cleaned for token in ".:;!?\n")
    ):
        return True
    return len(cleaned.split()) < 2

def _collect_record_candidates(
    record: dict[str, Any],
    *,
    page_url: str,
    fields: list[str],
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    source: str,
) -> None:
    allowed_fields = set(fields)
    for field_name, value in dict(record or {}).items():
        normalized_field = str(field_name or "").strip()
        if (
            not normalized_field
            or normalized_field.startswith("_")
            or normalized_field not in allowed_fields
        ):
            continue
        _add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            normalized_field,
            coerce_field_value(normalized_field, value, page_url),
            source=source,
        )

def _collect_structured_payload_candidates(
    payload: object,
    *,
    alias_lookup: dict[str, str],
    page_url: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    source: str,
) -> None:
    structured_candidates: dict[str, list[object]] = {}
    collect_structured_candidates(
        payload,
        alias_lookup,
        page_url,
        structured_candidates,
    )
    for field_name, values in structured_candidates.items():
        for value in values:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                field_name,
                value,
                source=source,
            )

def _primary_source_for_record(
    record: dict[str, Any],
    selected_field_sources: dict[str, str],
) -> str:
    del record
    selected_sources = [
        str(source or "").strip()
        for source in selected_field_sources.values()
        if str(source or "").strip()
    ]
    if selected_sources:
        return min(
            selected_sources,
            key=lambda source_name: _SOURCE_PRIORITY_RANK.get(
                source_name,
                len(_SOURCE_PRIORITY_RANK),
            ),
        )
    return "structured_dom"

_SOURCE_PRIORITY_RANK = {source_name: index for index, source_name in enumerate(SOURCE_PRIORITY)}

def _ordered_candidates_for_field(
    surface: str,
    field_name: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
) -> list[tuple[str | None, object]]:
    values = list(candidates.get(field_name, []))
    sources = list(candidate_sources.get(field_name, []))
    indexed_entries = [
        (
            _field_source_rank(
                surface,
                field_name,
                sources[index] if index < len(sources) else None,
            ),
            index,
            sources[index] if index < len(sources) else None,
            value,
        )
        for index, value in enumerate(values)
    ]
    indexed_entries.sort(key=lambda row: (row[0], row[1]))
    return [(source, value) for _, _, source, value in indexed_entries]

def _winning_candidates_for_field(
    ordered_candidates: list[tuple[str | None, object]],
) -> tuple[list[object], str | None]:
    if not ordered_candidates:
        return [], None
    winning_source = ordered_candidates[0][0]
    return (
        [value for source, value in ordered_candidates if source == winning_source],
        winning_source,
    )


def _detail_url_candidate_is_low_signal(candidate_url: object, *, page_url: str) -> bool:
    candidate = text_or_none(candidate_url)
    if not candidate:
        return False
    candidate_parsed = urlparse(candidate)
    page_parsed = urlparse(page_url)
    candidate_host = (candidate_parsed.hostname or "").lower()
    page_host = (page_parsed.hostname or "").lower()
    if candidate_host and page_host and candidate_host != page_host:
        return False
    candidate_path = str(candidate_parsed.path or "").strip()
    page_path = str(page_parsed.path or "").strip()
    return page_path not in {"", "/"} and candidate_path in {"", "/"}


def _preferred_detail_identity_url(
    *,
    surface: str,
    page_url: str,
    requested_page_url: str | None,
) -> str:
    if str(surface or "").strip().lower() != "ecommerce_detail":
        return page_url
    requested = text_or_none(requested_page_url)
    current = text_or_none(page_url)
    if not requested or not current or requested == current:
        return current or requested or page_url
    if not same_site(requested, current):
        return current
    if not _detail_url_looks_like_product(requested):
        return current
    if not _detail_url_is_utility(current):
        return current
    return requested


def _detail_url_looks_like_product(url: str) -> bool:
    path = str(urlparse(url).path or "").lower()
    return any(hint in path for hint in PRODUCT_URL_HINTS)


def _detail_url_is_utility(url: str) -> bool:
    path_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", str(urlparse(url).path or "").lower())
        if token
    }
    return any(token in path_tokens for token in DETAIL_UTILITY_PATH_TOKENS)


def _record_matches_requested_detail_identity(
    record: dict[str, Any],
    *,
    requested_page_url: str,
) -> bool:
    requested_title = _detail_title_from_url(requested_page_url) or requested_page_url
    requested_tokens = _detail_identity_tokens(requested_title)
    if not requested_tokens:
        return False
    candidate_tokens = _detail_identity_tokens(record.get("title"))
    if not candidate_tokens:
        candidate_tokens = _detail_identity_tokens(record.get("description"))
    if not candidate_tokens:
        return False
    overlap = requested_tokens & candidate_tokens
    if len(requested_tokens) == 1:
        return bool(overlap)
    return len(overlap) >= min(2, len(requested_tokens))


def _detail_identity_tokens(value: object) -> set[str]:
    cleaned = clean_text(value).lower()
    return {
        token
        for token in re.split(r"[^a-z0-9]+", cleaned)
        if len(token) >= 3 and token not in _DETAIL_IDENTITY_STOPWORDS
    }


def _detail_redirect_identity_is_mismatched(
    record: dict[str, Any],
    *,
    page_url: str,
    requested_page_url: str | None,
) -> bool:
    requested = text_or_none(requested_page_url)
    current = text_or_none(page_url)
    if not requested or not current or requested == current:
        return False
    if not same_site(requested, current):
        return False
    if not _detail_url_looks_like_product(requested):
        return False
    if not _detail_url_is_utility(current):
        return False
    return not _record_matches_requested_detail_identity(
        record,
        requested_page_url=requested,
    )

def _selector_self_heal_config(
    extraction_runtime_snapshot: dict[str, object] | None,
) -> dict[str, object]:
    selector_self_heal = (
        extraction_runtime_snapshot.get("selector_self_heal")
        if isinstance(extraction_runtime_snapshot, dict)
        else None
    )
    return {
        "enabled": bool(
            selector_self_heal.get("enabled")
            if isinstance(selector_self_heal, dict)
            and selector_self_heal.get("enabled") is not None
            else crawler_runtime_settings.selector_self_heal_enabled
        ),
        "threshold": float(
            selector_self_heal.get("min_confidence")
            if isinstance(selector_self_heal, dict)
            and selector_self_heal.get("min_confidence") is not None
            else crawler_runtime_settings.selector_self_heal_min_confidence
        ),
    }

def _materialize_record(
    *,
    page_url: str,
    requested_page_url: str | None,
    surface: str,
    requested_fields: list[str] | None,
    fields: list[str],
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    extraction_runtime_snapshot: dict[str, object] | None,
    tier_name: str,
    completed_tiers: list[str],
) -> dict[str, Any]:
    identity_url = _preferred_detail_identity_url(
        surface=surface,
        page_url=page_url,
        requested_page_url=requested_page_url,
    )
    record: dict[str, Any] = {"source_url": identity_url, "url": identity_url}
    selected_field_sources: dict[str, str] = {}
    merged_images, merged_image_source = _materialize_image_fields(
        surface=surface,
        candidates=candidates,
        candidate_sources=candidate_sources,
    )
    for field_name in fields:
        if field_name in {"image_url", "additional_images"}:
            continue
        ordered_candidates = _ordered_candidates_for_field(
            surface,
            field_name,
            candidates,
            candidate_sources,
        )
        winning_values, selected_source = _winning_candidates_for_field(ordered_candidates)
        finalized = (
            finalize_candidate_value(field_name, [value for _, value in ordered_candidates])
            if field_name in STRUCTURED_OBJECT_FIELDS | STRUCTURED_OBJECT_LIST_FIELDS
            else finalize_candidate_value(field_name, winning_values)
        )
        if (
            field_name == "url"
            and "detail" in str(surface or "").strip().lower()
            and _detail_url_candidate_is_low_signal(finalized, page_url=page_url)
        ):
            continue
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
            if selected_source:
                selected_field_sources[field_name] = selected_source
    if merged_images:
        record["image_url"] = merged_images[0]
        if len(merged_images) > 1:
            record["additional_images"] = merged_images[1:]
        if merged_image_source:
            selected_field_sources["image_url"] = merged_image_source
    promoted = _promote_detail_title(
        record,
        page_url=page_url,
        candidates=candidates,
        candidate_sources=candidate_sources,
    )
    if promoted:
        selected_field_sources["title"] = promoted[1]
    record["_field_sources"] = {
        field_name: list(source_list)
        for field_name, source_list in field_sources.items()
        if field_name in record
    }
    record["_source"] = _primary_source_for_record(record, selected_field_sources)
    _dedupe_primary_and_additional_images(record)
    confidence = score_record_confidence(
        record,
        surface=surface,
        requested_fields=requested_fields,
    )
    selector_self_heal = _selector_self_heal_config(extraction_runtime_snapshot)
    record["_confidence"] = confidence
    record["_extraction_tiers"] = {"completed": list(completed_tiers), "current": tier_name}
    record["_self_heal"] = {
        "enabled": bool(selector_self_heal["enabled"]),
        "triggered": False,
        "threshold": float(selector_self_heal["threshold"]),
    }
    return finalize_record(record, surface=surface)
def _dedupe_primary_and_additional_images(record: dict[str, Any]) -> None:
    raw_additional_images = record.get("additional_images")
    additional_images = (
        list(raw_additional_images)
        if isinstance(raw_additional_images, (list, tuple, set))
        else ([raw_additional_images] if raw_additional_images not in (None, "", [], {}) else [])
    )
    values: list[str] = []
    for raw_value in (
        record.get("image_url"),
        *additional_images,
    ):
        image = text_or_none(raw_value)
        if image:
            values.append(image)
    merged = dedupe_image_urls(values)
    if not merged:
        record.pop("image_url", None)
        record.pop("additional_images", None)
        return
    record["image_url"] = merged[0]
    if len(merged) > 1:
        record["additional_images"] = merged[1:]
        return
    record.pop("additional_images", None)


def _looks_like_site_shell_record(record: dict[str, Any], *, page_url: str) -> bool:
    title = text_or_none(record.get("title")) or ""
    if _detail_title_is_noise(title):
        return True
    strong_detail_fields = (
        "brand",
        "sku",
        "part_number",
        "barcode",
        "availability",
        "variant_axes",
        "variants",
        "selected_variant",
    )
    if not _title_needs_promotion(title, page_url=page_url):
        if not _detail_url_is_utility(page_url):
            return False
        record_url = text_or_none(record.get("url")) or ""
        has_strong_detail_fields = any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in strong_detail_fields
        )
        return not has_strong_detail_fields or _detail_url_is_utility(record_url)
    if str(record.get("_source") or "").strip() in {
        "adapter",
        "network_payload",
        "json_ld",
        "microdata",
        "embedded_json",
        "js_state",
    }:
        return False
    return not any(record.get(field_name) not in (None, "", [], {}) for field_name in strong_detail_fields)


def _variant_axis_value_count(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    return sum(len([item for item in values if text_or_none(item)]) for values in value.values() if isinstance(values, list))


def _variant_rows_with_option_values(value: object) -> int:
    if not isinstance(value, list):
        return 0
    return sum(1 for row in value if isinstance(row, dict) and isinstance(row.get("option_values"), dict) and bool(row.get("option_values")))


def _variant_signal_strength(*, variant_axes: object, variants: object, selected_variant: object) -> tuple[int, int, int, int, int]:
    return (
        len(variant_axes) if isinstance(variant_axes, dict) else 0,
        _variant_axis_value_count(variant_axes),
        len(variants) if isinstance(variants, list) else 0,
        _variant_rows_with_option_values(variants),
        int(
            isinstance(selected_variant, dict)
            and isinstance(selected_variant.get("option_values"), dict)
            and bool(selected_variant.get("option_values"))
        ),
    )


def _should_collect_dom_variants(
    candidates: dict[str, list[object]],
    dom_variants: dict[str, object],
) -> bool:
    if not any(candidates.get(field_name) for field_name in VARIANT_DOM_FIELD_NAMES):
        return True
    existing_variant_axes = finalize_candidate_value("variant_axes", list(candidates.get("variant_axes") or []))
    existing_variants = finalize_candidate_value("variants", list(candidates.get("variants") or []))
    existing_selected_variant = finalize_candidate_value("selected_variant", list(candidates.get("selected_variant") or []))
    existing_strength = _variant_signal_strength(
        variant_axes=existing_variant_axes,
        variants=existing_variants,
        selected_variant=existing_selected_variant,
    )
    if 0 in existing_strength[:4] or existing_strength[-1] == 0:
        return True
    dom_strength = _variant_signal_strength(
        variant_axes=dom_variants.get("variant_axes"),
        variants=dom_variants.get("variants"),
        selected_variant=dom_variants.get("selected_variant"),
    )
    return dom_strength > existing_strength


def _materialize_image_fields(
    *,
    surface: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
) -> tuple[list[str], str | None]:
    values: list[str] = []
    primary_source: str | None = None
    ordered_candidates = [
        *_ordered_candidates_for_field(surface, "image_url", candidates, candidate_sources),
        *_ordered_candidates_for_field(surface, "additional_images", candidates, candidate_sources),
    ]
    for source, raw_value in ordered_candidates:
        if primary_source is None and source:
            primary_source = source
        items = raw_value if isinstance(raw_value, list) else [raw_value]
        for item in items:
            image = text_or_none(item)
            if image:
                values.append(image)
    return dedupe_image_urls(values), primary_source


def _resolve_dom_variant_group_name(node: Any) -> str:
    resolved = resolve_variant_group_name(node)
    if resolved:
        return resolved
    if not hasattr(node, "select"):
        return ""
    for input_node in node.select("input[type='radio'], input[type='checkbox']")[:24]:
        resolved = resolve_variant_group_name(input_node)
        if resolved:
            return resolved
    return ""


def _variant_option_value_is_noise(value: str) -> bool:
    lowered = value.lower()
    return (
        not value
        or lowered in {"select", "choose", "option", "size guide"}
        or re.fullmatch(r"\(\d+\)", value) is not None
        or re.fullmatch(r"\d{3,5}/\d{2,5}/\d{2,5}", value) is not None
    )


def _variant_input_label(container: Any, input_node: Any) -> Any | None:
    input_id = text_or_none(input_node.get("id")) if hasattr(input_node, "get") else None
    if input_id:
        label = container.find("label", attrs={"for": input_id})
        if label is not None:
            return label
    if hasattr(input_node, "find_parent"):
        label = input_node.find_parent("label")
        if label is not None:
            return label
    sibling = getattr(input_node, "next_sibling", None)
    while sibling is not None:
        if getattr(sibling, "name", None) == "label":
            return sibling
        sibling = getattr(sibling, "next_sibling", None)
    return None


def _node_state_matches(node: Any, *tokens: str) -> bool:
    if not hasattr(node, "get"):
        return False
    class_attr = node.get("class")
    probe = (
        " ".join(str(value) for value in class_attr)
        if isinstance(class_attr, list)
        else str(class_attr or "")
    ).lower()
    return any(token in probe for token in tokens)


def _node_attr_is_truthy(node: Any, *attr_names: str) -> bool:
    if not hasattr(node, "get"):
        return False
    for attr_name in attr_names:
        value = node.get(attr_name)
        if value in (None, "", [], {}, False):
            continue
        if value is True:
            return True
        normalized = str(value).strip().lower()
        if normalized in {"", "false", "0", "none"}:
            continue
        return True
    return False


def _variant_option_availability(*, node: Any, label_node: Any | None) -> tuple[str | None, int | None]:
    attr_probe_parts: list[str] = []
    text_probe_parts: list[str] = []
    disabled = _node_attr_is_truthy(node, "disabled", "aria-disabled")
    for candidate in (
        node,
        label_node,
        getattr(node, "parent", None),
        getattr(label_node, "parent", None) if label_node is not None else None,
    ):
        if candidate is None or not hasattr(candidate, "get"):
            continue
        class_attr = candidate.get("class")
        if isinstance(class_attr, list):
            attr_probe_parts.extend(str(value) for value in class_attr if value)
        elif class_attr not in (None, "", [], {}):
            attr_probe_parts.append(str(class_attr))
        for attr_name in ("aria-label", "data-testid", "name", "id"):
            value = candidate.get(attr_name)
            if value not in (None, "", [], {}):
                attr_probe_parts.append(str(value))
        if hasattr(candidate, "get_text"):
            text_probe_parts.append(candidate.get_text(" ", strip=True))
    attr_probe = clean_text(" ".join(attr_probe_parts)).lower()
    text_probe = clean_text(" ".join(text_probe_parts)).lower()
    if any(
        token in attr_probe
        for token in ("outstock", "out-stock", "soldout", "sold-out", "unavailable", "disabled")
    ):
        disabled = True
    stock_match = re.search(r"\b(\d+)\s+left\b", text_probe)
    if stock_match:
        quantity = int(stock_match.group(1))
        return ("in_stock" if quantity > 0 else "out_of_stock"), quantity
    if "out of stock" in text_probe or "sold out" in text_probe:
        return "out_of_stock", 0
    if "in stock" in text_probe or "available" in text_probe:
        return "in_stock", None
    if disabled:
        return "out_of_stock", 0
    return None, None


def _merge_variant_option_state(
    entry: dict[str, object],
    *,
    node: Any,
    label_node: Any | None = None,
) -> None:
    selected = _node_state_matches(node, "selected", "active", "current") or _node_attr_is_truthy(
        node,
        "checked",
        "aria-checked",
    )
    if selected:
        entry["selected"] = True
    availability, stock_quantity = _variant_option_availability(node=node, label_node=label_node)
    if availability and entry.get("availability") in (None, "", [], {}):
        entry["availability"] = availability
    if stock_quantity is not None:
        entry["stock_quantity"] = stock_quantity


def _collect_variant_choice_entries(container: Any) -> list[dict[str, object]]:
    entries_by_value: dict[str, dict[str, object]] = {}
    for node in container.select(
        "[data-value], [data-option-value], [aria-label], input[value], [role='radio']"
    )[:24]:
        cleaned = clean_text(
            node.get("data-value")
            or node.get("data-option-value")
            or node.get("aria-label")
            or node.get("value")
        )
        if _variant_option_value_is_noise(cleaned):
            continue
        entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
        _merge_variant_option_state(entry, node=node)
    for input_node in container.select("input[type='radio'], input[type='checkbox']")[:24]:
        label_node = _variant_input_label(container, input_node)
        cleaned = clean_text(
            (label_node.get_text(" ", strip=True) if label_node is not None else "")
            or input_node.get("aria-label")
            or input_node.get("data-value")
            or input_node.get("data-option-value")
            or input_node.get("value")
        )
        if _variant_option_value_is_noise(cleaned):
            continue
        entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
        _merge_variant_option_state(entry, node=input_node, label_node=label_node)
    return list(entries_by_value.values())


def _extract_variants_from_dom(soup: BeautifulSoup, *, page_url: str) -> dict[str, object]:
    option_groups: list[dict[str, object]] = []
    for select in iter_variant_select_groups(soup):
        cleaned_name = resolve_variant_group_name(select)
        if not cleaned_name:
            continue
        values = [
            clean_text(option.get_text(" ", strip=True))
            for option in select.find_all("option")
            if clean_text(option.get_text(" ", strip=True))
            and clean_text(option.get_text(" ", strip=True)).lower()
            not in {"select", "choose", "option", "size guide"}
            and str(option.get("value") or "").strip().lower() not in {"", "select", "choose"}
        ]
        deduped_values = list(dict.fromkeys(values))
        if len(deduped_values) >= 2:
            option_groups.append({"name": cleaned_name, "values": deduped_values, "entries": []})

    for container in iter_variant_choice_groups(soup):
        cleaned_name = _resolve_dom_variant_group_name(container)
        if not cleaned_name:
            continue
        option_entries = _collect_variant_choice_entries(container)
        deduped_values = [str(entry["value"]) for entry in option_entries if text_or_none(entry.get("value"))]
        if len(deduped_values) >= 2:
            option_groups.append(
                {
                    "name": cleaned_name,
                    "values": deduped_values,
                    "entries": option_entries,
                }
            )

    deduped_groups: list[dict[str, object]] = []
    merged_groups: dict[str, dict[str, object]] = {}
    for group in option_groups:
        values = [clean_text(value) for value in list(group.get("values") or []) if clean_text(value)]
        if len(values) < 2:
            continue
        name = clean_text(group.get("name"))
        axis_key = normalized_variant_axis_key(name)
        if not axis_key:
            continue
        merged = merged_groups.setdefault(axis_key, {"name": name or axis_key, "values": [], "entries": {}})
        if len(name) > len(str(merged.get("name") or "")):
            merged["name"] = name
        merged["values"] = list(dict.fromkeys([*list(merged.get("values") or []), *values]))
        merged_entries = merged.setdefault("entries", {})
        for entry in list(group.get("entries") or []):
            value = clean_text(entry.get("value"))
            if not value:
                continue
            existing = merged_entries.get(value, {"value": value})
            availability = text_or_none(entry.get("availability"))
            if availability and existing.get("availability") in (None, "", [], {}):
                existing["availability"] = availability
            if entry.get("stock_quantity") not in (None, "", [], {}):
                existing["stock_quantity"] = entry.get("stock_quantity")
            if entry.get("selected"):
                existing["selected"] = True
            merged_entries[value] = existing
    for group in merged_groups.values():
        values = [clean_text(value) for value in list(group.get("values") or []) if clean_text(value)]
        if len(values) < 2:
            continue
        deduped_groups.append(
            {
                "name": clean_text(group.get("name")),
                "values": values,
                "entries": list((group.get("entries") or {}).values()),
            }
        )
        if len(deduped_groups) >= 2:
            break

    if not deduped_groups:
        return {}

    record: dict[str, object] = {}
    variant_axes: dict[str, list[str]] = {}
    axis_option_metadata: dict[str, dict[str, dict[str, object]]] = {}
    axis_order: list[tuple[str, str, list[str]]] = []
    for group in deduped_groups:
        name = clean_text(group.get("name"))
        values = list(group.get("values") or [])
        axis_key = normalized_variant_axis_key(name)
        if not axis_key:
            continue
        axis_index = len(axis_order) + 1
        record[f"option{axis_index}_name"] = name
        record[f"option{axis_index}_values"] = values
        variant_axes[axis_key] = values
        axis_option_metadata[axis_key] = {
            clean_text(entry.get("value")): {
                key: entry.get(key)
                for key in ("availability", "selected", "stock_quantity")
                if entry.get(key) not in (None, "", [], {})
            }
            for entry in list(group.get("entries") or [])
            if clean_text(entry.get("value"))
        }
        axis_order.append((axis_key, name, values))
        if axis_key == "size" and not record.get("available_sizes"):
            record["available_sizes"] = values
    if not variant_axes:
        return {}

    variants: list[dict[str, object]] = []
    axis_names = [axis_key for axis_key, _label, _values in axis_order]
    axis_value_lists = [values for _axis_key, _label, values in axis_order]
    for combo in product(*axis_value_lists):
        option_values = {
            axis_name: value
            for axis_name, value in zip(axis_names, combo, strict=False)
            if clean_text(value)
        }
        if not option_values:
            continue
        variant: dict[str, object] = {
            "option_values": option_values,
        }
        for axis_name, value in option_values.items():
            variant[axis_name] = value
        if len(axis_names) == 1:
            axis_key = axis_names[0]
            option_metadata = axis_option_metadata.get(axis_key, {}).get(str(combo[0]), {})
            availability = text_or_none(option_metadata.get("availability"))
            if availability:
                variant["availability"] = availability
            if option_metadata.get("stock_quantity") not in (None, "", [], {}):
                variant["stock_quantity"] = option_metadata.get("stock_quantity")
        variants.append(variant)

    selectable_axes, single_value_attributes = split_variant_axes(
        variant_axes,
        always_selectable_axes=frozenset({"size"}),
    )
    resolved_variants = resolve_variants(selectable_axes or variant_axes, variants) if variants else []
    selected_variant = select_variant(resolved_variants, page_url=page_url)
    selected_option_values = {
        axis_name: option_value
        for axis_name, option_value in (
            (
                axis_name,
                next(
                    (
                        value
                        for value, metadata in axis_option_metadata.get(axis_name, {}).items()
                        if metadata.get("selected")
                    ),
                    None,
                ),
            )
            for axis_name in axis_names
        )
        if option_value
    }
    if selected_option_values:
        selected_variant = next(
            (
                variant
                for variant in resolved_variants
                if variant.get("option_values") == selected_option_values
            ),
            selected_variant,
        )
    for axis_name, value in single_value_attributes.items():
        record.setdefault(axis_name, value)
    if selectable_axes:
        record["variant_axes"] = selectable_axes
    elif variant_axes:
        record["variant_axes"] = variant_axes
    if resolved_variants:
        record["variants"] = resolved_variants
        record["variant_count"] = len(resolved_variants)
        if selected_variant:
            record["selected_variant"] = selected_variant
            if record.get("availability") in (None, "", [], {}):
                selected_availability = text_or_none(selected_variant.get("availability"))
                if selected_availability:
                    record["availability"] = selected_availability
    return record


def _promote_detail_title(
    record: dict[str, Any],
    *,
    page_url: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
) -> tuple[str, str] | None:
    title = text_or_none(record.get("title"))
    if not title or not _title_needs_promotion(title, page_url=page_url):
        return None
    values = list(candidates.get("title", []))
    sources = list(candidate_sources.get("title", []))
    ranked_candidates = sorted(
        (
            (
                _field_source_rank("ecommerce_detail", "title", sources[index]),
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
            _field_source_rank("ecommerce_detail", "title", source)
            for source, value in zip(sources, values, strict=False)
            if text_or_none(value) == title
        ),
        default=_field_source_rank("ecommerce_detail", "title", "dom_h1"),
    )
    replacement = next(
        (
            (candidate, source)
            for rank, _, candidate, source in ranked_candidates
            if candidate
            and candidate != title
            and not _detail_title_is_noise(candidate)
            and (rank < current_rank or source in {"network_payload", "json_ld", "microdata", "opengraph", "embedded_json", "js_state"} or len(candidate) > len(title))
        ),
        None,
    )
    if replacement:
        record["title"] = replacement[0]
        return replacement
    return None


def _title_needs_promotion(title: str, *, page_url: str) -> bool:
    normalized_title = str(title or "").strip().lower()
    host = str(urlparse(page_url).hostname or "").strip().lower()
    if not normalized_title:
        return False
    if _detail_title_is_noise(normalized_title):
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


def _missing_requested_fields(
    record: dict[str, Any],
    requested_fields: list[str] | None,
) -> set[str]:
    missing: set[str] = set()
    for field_name in list(requested_fields or []):
        normalized = exact_requested_field_key(str(field_name or ""))
        if normalized and record.get(normalized) in (None, "", [], {}):
            missing.add(normalized)
    return missing


def _requires_dom_completion(
    *,
    record: dict[str, Any],
    surface: str,
    requested_fields: list[str] | None,
    selector_rules: list[dict[str, object]] | None,
    soup: BeautifulSoup,
) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    requested_missing_fields = _missing_requested_fields(record, requested_fields)
    if normalized_surface == "ecommerce_detail" and variant_dom_cues_present(soup):
        if any(
            record.get(field_name) in (None, "", [], {})
            for field_name in ("variant_axes", "variants", "selected_variant")
        ):
            return True
    extractability = requested_content_extractability(
        soup,
        surface=surface,
        requested_fields=requested_fields,
        selector_rules=selector_rules,
    )
    extractable_fields = set(extractability.get("extractable_fields") or [])
    high_value_fields = set(DOM_HIGH_VALUE_FIELDS.get(normalized_surface) or ())
    advertised_high_value_fields = extractable_fields & high_value_fields
    missing_high_value_fields = {
        field_name
        for field_name in advertised_high_value_fields
        if record.get(field_name) in (None, "", [], {})
    }
    missing_high_value_fields.update(
        {
            field_name
            for field_name in high_value_fields
            if field_name in requested_missing_fields
        }
    )
    if extractable_fields & requested_missing_fields:
        return True
    if missing_high_value_fields or requested_missing_fields & high_value_fields:
        return True
    optional_cue_fields = {
        field_name
        for field_name in set(DOM_OPTIONAL_CUE_FIELDS.get(normalized_surface) or ())
        if record.get(field_name) in (None, "", [], {})
    }
    if optional_cue_fields & set(extractability.get("dom_pattern_fields") or []):
        return True
    selector_backed_fields = set(extractability.get("selector_backed_fields") or [])
    return bool(requested_missing_fields & selector_backed_fields)


def _primary_dom_context(
    context,
    *,
    page_url: str,
) -> tuple[LexborHTMLParser, BeautifulSoup]:
    primary_selector = "main, article, h1, [itemprop='name']"
    cleaned_parser = context.dom_parser
    cleaned_soup = context.soup
    if cleaned_parser.css_first(primary_selector) or cleaned_soup.select_one(primary_selector):
        return cleaned_parser, cleaned_soup
    original_parser = LexborHTMLParser(context.original_html)
    original_soup = BeautifulSoup(context.original_html, "html.parser")
    if not (
        original_parser.css_first(primary_selector)
        or original_soup.select_one(primary_selector)
    ):
        return cleaned_parser, cleaned_soup
    logger.debug("Using original DOM after cleaned DOM lost primary content for %s", page_url)
    return original_parser, original_soup


def build_detail_record(
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    *,
    requested_page_url: str | None = None,
    adapter_records: list[dict[str, Any]] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
) -> dict[str, Any]:
    context = prepare_extraction_context(html)
    dom_parser, soup = _primary_dom_context(
        context,
        page_url=page_url,
    )
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    candidates: dict[str, list[object]] = {}
    candidate_sources: dict[str, list[str]] = {}
    field_sources: dict[str, list[str]] = {}
    fields = surface_fields(surface, requested_fields)
    selector_self_heal = _selector_self_heal_config(extraction_runtime_snapshot)
    state = DetailTierState(page_url=page_url, requested_page_url=requested_page_url, surface=surface, requested_fields=requested_fields, fields=fields, candidates=candidates, candidate_sources=candidate_sources, field_sources=field_sources, extraction_runtime_snapshot=extraction_runtime_snapshot, completed_tiers=[])
    js_state_record = map_js_state_to_fields(
        harvest_js_state_objects(None, context.cleaned_html),
        surface=surface,
        page_url=page_url,
    )
    if surface == "ecommerce_detail" and _detail_title_is_noise(js_state_record.get("title")):
        js_state_record = dict(js_state_record)
        js_state_record.pop("title", None)

    collect_authoritative_tier(
        state,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        collect_record_candidates=_collect_record_candidates,
        map_network_payloads_to_fields=map_network_payloads_to_fields,
    )
    record = materialize_detail_tier(state, tier_name="authoritative", materialize_record=_materialize_record)

    collect_structured_data_tier(
        state,
        context=context,
        alias_lookup=alias_lookup,
        collect_structured_source_payloads=collect_structured_source_payloads,
        collect_structured_payload_candidates=_collect_structured_payload_candidates,
    )
    record = materialize_detail_tier(state, tier_name="structured_data", materialize_record=_materialize_record)
    if (
        float(record["_confidence"]["score"])
        >= float(selector_self_heal["threshold"])
        and not _requires_dom_completion(
            record=record,
            surface=surface,
            requested_fields=requested_fields,
            selector_rules=selector_rules,
            soup=soup,
        )
    ):
        record["_extraction_tiers"]["early_exit"] = "structured_data"
        return record

    collect_js_state_tier(
        state,
        js_state_record=js_state_record,
        collect_record_candidates=_collect_record_candidates,
    )
    record = materialize_detail_tier(state, tier_name="js_state", materialize_record=_materialize_record)

    collect_dom_tier(
        state,
        dom_parser=dom_parser,
        soup=soup,
        selector_rules=selector_rules,
        apply_dom_fallbacks=_apply_dom_fallbacks,
        extract_variants_from_dom=_extract_variants_from_dom,
        should_collect_dom_variants=_should_collect_dom_variants,
        add_sourced_candidate=_add_sourced_candidate,
    )
    record = materialize_detail_tier(state, tier_name="dom", materialize_record=_materialize_record)
    if surface == "ecommerce_detail" and _title_needs_promotion(
        text_or_none(record.get("title")) or "",
        page_url=page_url,
    ):
        preferred_title = text_or_none(js_state_record.get("title"))
        if preferred_title:
            record["title"] = preferred_title
        else:
            fallback_title = _detail_title_from_url(page_url)
            if fallback_title:
                record["title"] = fallback_title
                title_sources = record.setdefault("_field_sources", {}).setdefault("title", [])
                if "url_slug" not in title_sources:
                    title_sources.append("url_slug")
    if surface == "ecommerce_detail" and not text_or_none(record.get("title")):
        fallback_title = _detail_title_from_url(page_url)
        if fallback_title:
            record["title"] = fallback_title
            title_sources = record.setdefault("_field_sources", {}).setdefault("title", [])
            if "url_slug" not in title_sources:
                title_sources.append("url_slug")
    record["_confidence"] = score_record_confidence(
        record,
        surface=surface,
        requested_fields=requested_fields,
    )
    record["_extraction_tiers"]["early_exit"] = None
    return record


def extract_detail_records(
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None = None,
    *,
    requested_page_url: str | None = None,
    adapter_records: list[dict[str, Any]] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
) -> list[dict[str, Any]]:
    record = build_detail_record(
        html,
        page_url,
        surface,
        requested_fields,
        requested_page_url=requested_page_url,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
    )
    if surface == "ecommerce_detail" and _looks_like_site_shell_record(
        record,
        page_url=page_url,
    ):
        return []
    if surface == "ecommerce_detail" and _detail_redirect_identity_is_mismatched(
        record,
        page_url=page_url,
        requested_page_url=requested_page_url,
    ):
        return []
    if record_score(record) <= 0:
        return []
    return [record]
