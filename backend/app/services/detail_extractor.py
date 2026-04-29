from __future__ import annotations

import logging
import re
from itertools import product
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlsplit, urlunsplit
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
    CANDIDATE_PLACEHOLDER_VALUES,
    DETAIL_BRAND_SHELL_DESCRIPTION_PHRASES,
    DETAIL_BRAND_SHELL_TITLE_TOKENS,
    DETAIL_DOCUMENT_LINK_LABEL_PATTERNS,
    DETAIL_TITLE_SOURCE_RANKS,
    SOURCE_PRIORITY,
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS,
    VARIANT_OPTION_VALUE_NOISE_TOKENS,
    VARIANT_SIZE_VALUE_PATTERNS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extraction_context import (
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.structured_sources import harvest_js_state_objects
from app.services.field_value_core import (
    LONG_TEXT_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    _object_dict,
    _object_list,
    absolute_url,
    clean_text,
    coerce_field_value,
    finalize_record,
    is_title_noise,
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
    dedupe_image_urls,
    requested_content_extractability,
)
from app.services.js_state_mapper import map_js_state_to_fields
from app.services.js_state_helpers import select_variant
from app.services.network_payload_mapper import map_network_payloads_to_fields
from app.services.extract.detail_dom_extractor import (
    apply_dom_fallbacks,
    primary_dom_context,
)
from app.services.extract.detail_identity import (
    _detail_identity_codes_from_record_fields,
    _detail_identity_codes_from_url,
    _detail_identity_tokens,
    _detail_redirect_identity_is_mismatched,
    _detail_title_from_url,
    _detail_url_candidate_is_low_signal,
    _detail_url_is_collection_like,
    _detail_url_is_utility,
    _detail_url_looks_like_product,
    _detail_url_matches_requested_identity,
    _preferred_detail_identity_url,
    _record_matches_requested_detail_identity,
    _semantic_detail_identity_tokens,
    detail_identity_codes_match,
)
from app.services.extract.detail_price_extractor import (
    append_record_field_source as _append_record_field_source,
    backfill_detail_price_from_html,
    drop_low_signal_zero_detail_price,
    reconcile_detail_currency_with_url as _reconcile_detail_currency_with_url,
    record_field_sources as _record_field_sources,
)
from app.services.extract.detail_title_scorer import (
    promote_detail_title,
    title_needs_promotion,
)
from app.services.extract.shared_variant_logic import (
    infer_variant_group_name_from_values,
    iter_variant_choice_groups,
    iter_variant_select_groups,
    normalized_variant_axis_display_name,
    normalized_variant_axis_key,
    resolve_variants,
    resolve_variant_group_name,
    split_variant_axes,
    variant_axis_name_is_semantic,
    variant_dom_cues_present,
)
from app.services.extract.variant_record_normalization import (
    normalize_variant_record,
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
_DETAIL_VARIANT_SIZE_VALUE_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in VARIANT_SIZE_VALUE_PATTERNS
    if str(pattern).strip()
)
_VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS
    if str(pattern).strip()
)
_VARIANT_OPTION_VALUE_NOISE_TOKENS = frozenset(
    str(token).strip().lower()
    for token in VARIANT_OPTION_VALUE_NOISE_TOKENS
    if str(token).strip()
)
_LOW_SIGNAL_LONG_TEXT_VALUES = frozenset(
    {
        "description",
        "details",
        "normal",
        "overview",
        "product label",
        "product summary",
        "specifications",
    }
)
_UUID_LIKE_PATTERN = re.compile(
    r"(?i)^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
)
_MERCH_CODE_PATTERN = re.compile(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{2,})+\b", re.I)
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
_DETAIL_PLACEHOLDER_TITLE_PATTERNS = (
    re.compile(r"^404$"),
    re.compile(r"^(?:error\s*)?404\b", re.I),
    re.compile(r"^error\s+page$", re.I),
    re.compile(r"^your\s+ai-generated\s+outfit$", re.I),
    re.compile(r"^oops,?\s+something\s+went\s+wrong\.?$", re.I),
    re.compile(r"^oops!? the page you(?:'|’)re looking for can(?:'|’)t be found\.?$", re.I),
    re.compile(r"\bpage not found\b", re.I),
    re.compile(r"\bnot found\b", re.I),
    re.compile(r"\baccess denied\b", re.I),
)
_DETAIL_DOCUMENT_LINK_LABEL_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(DETAIL_DOCUMENT_LINK_LABEL_PATTERNS or ())
    if str(pattern).strip()
)
def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _field_source_rank(surface: str, field_name: str, source: str | None) -> int:
    if str(surface or "").strip().lower() == "ecommerce_detail":
        if field_name == "title":
            return DETAIL_TITLE_SOURCE_RANKS.get(str(source or ""), 20)
        if field_name in LONG_TEXT_FIELDS:
            return _LONG_TEXT_SOURCE_RANKS.get(str(source or ""), 20)
        if field_name in ECOMMERCE_DETAIL_JS_STATE_FIELDS and source == "js_state":
            return 2
    return 100 + _SOURCE_PRIORITY_RANK.get(str(source or ""), len(_SOURCE_PRIORITY_RANK))
def _add_sourced_candidate(
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
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
    selector_trace_candidates: dict[str, list[dict[str, object]]],
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
            selector_trace_candidates,
            normalized_field,
            coerce_field_value(normalized_field, value, page_url),
            source=source,
        )
def _collect_structured_payload_candidates(
    payload: object,
    *,
    alias_lookup: dict[str, str],
    page_url: str,
    requested_page_url: str | None,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    source: str,
) -> None:
    identity_url = requested_page_url or page_url
    if identity_url:
        payload = _prune_irrelevant_detail_structured_payload(
            payload,
            page_url=page_url,
            requested_page_url=identity_url,
        )
    if payload in (None, "", [], {}):
        return
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
                selector_trace_candidates,
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
        "threshold": _coerce_float(
            selector_self_heal.get("min_confidence")
            if isinstance(selector_self_heal, dict)
            and selector_self_heal.get("min_confidence") is not None
            else crawler_runtime_settings.selector_self_heal_min_confidence,
            default=float(crawler_runtime_settings.selector_self_heal_min_confidence),
        ),
    }

def _selected_selector_trace(
    *,
    field_name: str,
    finalized_value: object,
    selector_trace_candidates: dict[str, list[dict[str, object]]],
) -> dict[str, object] | None:
    traces = list(selector_trace_candidates.get(field_name) or [])
    if not traces:
        return None
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
    selector_trace_candidates: dict[str, list[dict[str, object]]],
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
    selected_selector_traces: dict[str, dict[str, object]] = {}
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
                if selected_source == "selector_rule":
                    selector_trace = _selected_selector_trace(
                        field_name=field_name,
                        finalized_value=finalized,
                        selector_trace_candidates=selector_trace_candidates,
                    )
                    if selector_trace:
                        selected_selector_traces[field_name] = selector_trace
    if merged_images:
        record["image_url"] = merged_images[0]
        if len(merged_images) > 1:
            record["additional_images"] = merged_images[1:]
        if merged_image_source:
            selected_field_sources["image_url"] = merged_image_source
    promoted = promote_detail_title(
        record,
        page_url=page_url,
        candidates=candidates,
        candidate_sources=candidate_sources,
        source_rank=_field_source_rank,
    )
    if promoted:
        selected_field_sources["title"] = promoted[1]
        selected_selector_traces.pop("title", None)
    record["_field_sources"] = {
        field_name: list(source_list)
        for field_name, source_list in field_sources.items()
        if field_name in record
    }
    if selected_selector_traces:
        record["_selector_traces"] = selected_selector_traces
    record["_source"] = _primary_source_for_record(record, selected_field_sources)
    if str(surface or "").strip().lower() == "ecommerce_detail":
        _reconcile_detail_currency_with_url(record, page_url=page_url)
    normalize_variant_record(record)
    if str(surface or "").strip().lower() == "ecommerce_detail":
        repair_ecommerce_detail_record_quality(
            record,
            html="",
            page_url=page_url,
            requested_page_url=requested_page_url,
        )
    drop_low_signal_zero_detail_price(record)
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
        "threshold": _coerce_float(selector_self_heal.get("threshold")),
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


def _sanitize_ecommerce_detail_record(
    record: dict[str, Any],
    *,
    page_url: str,
    requested_page_url: str | None,
) -> None:
    identity_url = text_or_none(requested_page_url) or page_url
    _sanitize_detail_placeholder_scalars(record)
    _sanitize_detail_identity_scalars(record, identity_url=identity_url)
    _sanitize_detail_variant_payload(record, identity_url=identity_url)
    _sanitize_detail_long_text_fields(record)
    _sanitize_detail_images(record, identity_url=identity_url)
    _reconcile_detail_availability_from_variants(record)


def _sanitize_detail_placeholder_scalars(record: dict[str, Any]) -> None:
    title = clean_text(record.get("title"))
    if _detail_title_looks_like_placeholder(title):
        record.pop("title", None)
        record["_placeholder_title_removed"] = True
    category = clean_text(record.get("category"))
    if category.lower() in {"category", "categories", "uncategorized"}:
        record.pop("category", None)
    features = text_or_none(record.get("features"))
    if features and features.startswith("{") and features.endswith("}"):
        record.pop("features", None)
    materials = text_or_none(record.get("materials"))
    if materials and _materials_value_looks_like_org_name(materials):
        record.pop("materials", None)
    product_attributes = record.get("product_attributes")
    if isinstance(product_attributes, dict):
        cleaned_attributes = {
            str(key): value
            for key, value in product_attributes.items()
            if not _detail_scalar_value_is_placeholder(value)
        }
        if cleaned_attributes:
            record["product_attributes"] = cleaned_attributes
        else:
            record.pop("product_attributes", None)


def _sanitize_detail_identity_scalars(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> None:
    sku = text_or_none(record.get("sku"))
    preferred_code = _preferred_detail_merch_code(record, identity_url=identity_url)
    if preferred_code and (not sku or _looks_like_uuid(sku)):
        record["sku"] = preferred_code
        if text_or_none(record.get("part_number")) in (None, ""):
            record["part_number"] = preferred_code
    placeholder_title_removed = bool(record.pop("_placeholder_title_removed", False))
    if not text_or_none(record.get("title")):
        if placeholder_title_removed and not _detail_title_fallback_is_safe(record):
            return
        fallback_title = _detail_title_from_url(identity_url)
        if fallback_title:
            record["title"] = fallback_title.title()
            field_sources = record.setdefault("_field_sources", {})
            field_sources["title"] = ["url_slug"]


def _detail_title_fallback_is_safe(record: dict[str, Any]) -> bool:
    return any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in (
            "price",
            "original_price",
            "sku",
            "part_number",
            "barcode",
            "brand",
            "image_url",
            "availability",
            "product_attributes",
            "variants",
            "selected_variant",
        )
    )


def _preferred_detail_merch_code(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> str | None:
    expected_codes = _detail_identity_codes_from_url(identity_url)
    raw_values = (
        record.get("sku"),
        record.get("part_number"),
        record.get("product_details"),
        record.get("description"),
        record.get("url"),
        identity_url,
    )
    fallback: str | None = None
    for raw_value in raw_values:
        text = text_or_none(raw_value)
        if not text:
            continue
        for match in _MERCH_CODE_PATTERN.findall(text):
            candidate = match.upper()
            if candidate.count("-") > 2:
                continue
            normalized = re.sub(r"[^A-Z0-9]+", "", candidate)
            if len(normalized) < 8 or not re.search(r"[A-Z]", normalized) or not re.search(r"\d", normalized):
                continue
            if fallback is None:
                fallback = candidate
            if not expected_codes or normalized in expected_codes:
                return candidate
    return fallback


def _looks_like_uuid(value: str) -> bool:
    return bool(_UUID_LIKE_PATTERN.fullmatch(str(value or "").strip()))


def _detail_scalar_value_is_placeholder(value: object) -> bool:
    cleaned = clean_text(value).lower()
    if not cleaned:
        return True
    if cleaned in {str(item).strip().lower() for item in CANDIDATE_PLACEHOLDER_VALUES}:
        return True
    return cleaned in {"category", "default title", "uncategorized"}


def _materials_value_looks_like_org_name(value: str) -> bool:
    lowered = value.lower()
    if any(
        token in lowered
        for token in (
            "cotton",
            "polyester",
            "rubber",
            "leather",
            "wool",
            "nylon",
            "polyamide",
            "spandex",
            "linen",
        )
    ):
        return False
    return bool(
        re.search(r"\b(?:inc|llc|ltd|corp|company|co|se)\b", lowered)
        or re.fullmatch(r"[A-Z0-9 .,&'-]{6,}", value)
    )


def _sanitize_detail_variant_payload(record: dict[str, Any], *, identity_url: str) -> None:
    cleaned_variants: list[dict[str, Any]] = []
    for variant in list(record.get("variants") or []):
        if not isinstance(variant, dict):
            continue
        if not _sanitize_variant_row(variant, identity_url=identity_url):
            continue
        cleaned_variants.append(variant)
    if _detail_variant_cluster_is_low_signal_numeric_only(cleaned_variants):
        cleaned_variants = []
    if cleaned_variants:
        record["variants"] = cleaned_variants
        record["variant_count"] = len(cleaned_variants)
    else:
        record.pop("variants", None)
        record.pop("variant_count", None)
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict) and not _sanitize_variant_row(
        selected_variant,
        identity_url=identity_url,
    ):
        selected_variant = None
    if (
        isinstance(selected_variant, dict)
        and cleaned_variants
        and selected_variant.get("option_values") in (None, "", [], {})
        and not any(
            selected_variant.get(field_name) not in (None, "", [], {})
            for field_name in ("sku", "variant_id", "barcode", "availability", "title")
        )
    ):
        selected_variant = dict(cleaned_variants[0])
    if isinstance(selected_variant, dict):
        record["selected_variant"] = selected_variant
    else:
        record.pop("selected_variant", None)
    _rebuild_variant_axes_from_rows(record)
    _drop_detail_variant_scalar_noise(record)


def _sanitize_variant_row(variant: dict[str, Any], *, identity_url: str) -> bool:
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        cleaned_options: dict[str, str] = {}
        for axis_name, axis_value in option_values.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned_value = clean_text(axis_value)
            if not axis_key or not cleaned_value:
                continue
            if axis_key.startswith("toggle") or _variant_option_value_is_noise(cleaned_value):
                continue
            if not variant_axis_name_is_semantic(axis_name):
                continue
            cleaned_options[axis_key] = cleaned_value
            if axis_key in {"size", "color"} and variant.get(axis_key) not in (None, "", [], {}):
                variant[axis_key] = cleaned_value
        if cleaned_options:
            variant["option_values"] = cleaned_options
        else:
            variant.pop("option_values", None)
    for field_name in ("size", "color"):
        cleaned_value = clean_text(variant.get(field_name))
        if cleaned_value and not _variant_option_value_is_noise(cleaned_value):
            variant[field_name] = cleaned_value
        else:
            variant.pop(field_name, None)
    variant_url = text_or_none(variant.get("url"))
    if (
        variant_url
        and same_site(identity_url, variant_url)
        and _detail_url_looks_like_product(variant_url)
        and not _detail_url_matches_requested_identity(
            variant_url,
            requested_page_url=identity_url,
        )
    ):
        return False
    title = clean_text(variant.get("title"))
    if (
        title
        and not _variant_url_matches_requested_base(variant.get("url"), identity_url=identity_url)
        and _variant_title_looks_like_other_product(title, identity_url=identity_url)
        and not _variant_title_can_be_option_label(variant, title=title)
    ):
        return False
    if _detail_variant_row_is_low_signal_numeric_only(variant):
        return False
    return any(
        variant.get(field_name) not in (None, "", [], {})
        for field_name in (
            "sku",
            "variant_id",
            "barcode",
            "image_url",
            "availability",
            "option_values",
            "size",
            "color",
        )
    )


def repair_ecommerce_detail_record_quality(
    record: dict[str, Any],
    *,
    html: str,
    page_url: str,
    requested_page_url: str | None = None,
) -> None:
    identity_url = text_or_none(requested_page_url) or page_url
    _sanitize_ecommerce_detail_record(
        record,
        page_url=page_url,
        requested_page_url=identity_url,
    )
    backfill_detail_price_from_html(record, html=html)
    _repair_detail_variant_prices_and_identity(record)


def _repair_detail_variant_prices_and_identity(record: dict[str, Any]) -> None:
    parent_price = text_or_none(record.get("price"))
    selected_variant = record.get("selected_variant")
    if not parent_price and isinstance(selected_variant, dict):
        parent_price = text_or_none(selected_variant.get("price"))
    parent_availability = text_or_none(record.get("availability"))
    parent_sku = text_or_none(record.get("sku"))
    parent_title = clean_text(record.get("title"))
    rows = [
        row
        for row in [selected_variant, *list(record.get("variants") or [])]
        if isinstance(row, dict)
    ]
    if (
        parent_availability
        and isinstance(selected_variant, dict)
        and selected_variant.get("availability") in (None, "", [], {})
    ):
        selected_variant["availability"] = parent_availability
    for row in rows:
        if parent_price:
            row_price = text_or_none(row.get("price"))
            if not row_price or _price_is_cents_copy(row_price, parent_price):
                row["price"] = parent_price
        if (
            parent_availability
            and row.get("availability") in (None, "", [], {})
            and any(
                row.get(field_name) not in (None, "", [], {})
                for field_name in (
                    "sku",
                    "variant_id",
                    "barcode",
                    "image_url",
                    "title",
                    "size",
                    "color",
                    "url",
                )
            )
        ):
            row["availability"] = parent_availability
        row_sku = text_or_none(row.get("sku"))
        if row_sku and _looks_like_uuid(row_sku):
            row.pop("sku", None)
        barcode = text_or_none(row.get("barcode"))
        if barcode and row.get("sku") == barcode and len(re.sub(r"\D+", "", barcode)) <= 8:
            row.pop("barcode", None)
        title = clean_text(row.get("title"))
        if title and _variant_title_is_low_signal(title):
            replacement = _variant_title_from_parent(parent_title, row)
            if replacement:
                row["title"] = replacement
            else:
                row.pop("title", None)
    variant_rows = [
        row for row in list(record.get("variants") or []) if isinstance(row, dict)
    ]
    if (
        parent_availability
        == "in_stock"
        and variant_rows
        and all(
            text_or_none(row.get("availability")) == parent_availability
            for row in variant_rows
        )
    ):
        for row in variant_rows:
            row.pop("availability", None)
    if parent_sku and _looks_like_uuid(parent_sku):
        record.pop("sku", None)


def _price_is_cents_copy(value: str, parent_price: str) -> bool:
    value_number = _price_number(value)
    parent_number = _price_number(parent_price)
    if value_number is None or parent_number is None or parent_number <= 0:
        return False
    return abs(value_number - (parent_number * 100)) < 0.01


def _price_number(value: object) -> float | None:
    text = text_or_none(value)
    if not text:
        return None
    try:
        return float(re.sub(r"[^0-9.]+", "", text))
    except ValueError:
        return None


def _variant_title_is_low_signal(title: str) -> bool:
    normalized = clean_text(title)
    return bool(normalized) and (
        normalized.isdigit()
        or normalized.lower() in _VARIANT_OPTION_VALUE_NOISE_TOKENS
        or len(normalized) <= 2
    )


def _variant_title_from_parent(parent_title: str, row: dict[str, Any]) -> str | None:
    if not parent_title:
        return None
    option_values = row.get("option_values")
    values: list[str] = []
    if isinstance(option_values, dict):
        values.extend(clean_text(value) for value in option_values.values() if clean_text(value))
    for field_name in ("size", "color"):
        value = clean_text(row.get(field_name))
        if value and value not in values:
            values.append(value)
    if values:
        return f"{parent_title} - {' / '.join(values)}"
    return parent_title


def _variant_url_matches_requested_base(value: object, *, identity_url: str) -> bool:
    variant_url = text_or_none(value)
    if not variant_url or not identity_url or not same_site(identity_url, variant_url):
        return False
    requested = urlparse(identity_url)
    candidate = urlparse(variant_url)
    return requested.path.rstrip("/") == candidate.path.rstrip("/")


def _detail_variant_row_is_low_signal_numeric_only(variant: object) -> bool:
    if not isinstance(variant, dict):
        return False
    if any(clean_text(variant.get(field_name)) for field_name in ("variant_id", "barcode", "image_url", "title")):
        return False
    if clean_text(variant.get("url")):
        return False
    option_values = variant.get("option_values")
    if not isinstance(option_values, dict) or set(option_values) != {"size"}:
        return False
    size_value = clean_text(option_values.get("size") or variant.get("size"))
    return bool(size_value) and size_value.isdigit() and int(size_value) <= 4


def _detail_variant_cluster_is_low_signal_numeric_only(variants: list[dict[str, Any]]) -> bool:
    return bool(variants) and all(
        _detail_variant_row_is_low_signal_numeric_only(variant) for variant in variants
    )


def _variant_title_looks_like_other_product(title: str, *, identity_url: str) -> bool:
    candidate = {"title": title}
    return not _record_matches_requested_detail_identity(
        candidate,
        requested_page_url=identity_url,
    )


def _variant_title_can_be_option_label(variant: dict[str, Any], *, title: str) -> bool:
    if len(clean_text(title).split()) > 6:
        return False
    return any(
        variant.get(field_name) not in (None, "", [], {})
        for field_name in (
            "sku",
            "variant_id",
            "barcode",
            "price",
            "availability",
            "option_values",
            "size",
            "color",
        )
    )


def _rebuild_variant_axes_from_rows(record: dict[str, Any]) -> None:
    variant_axes: dict[str, list[str]] = {}
    existing_axes = record.get("variant_axes")
    if isinstance(existing_axes, dict):
        for axis_name, axis_values in existing_axes.items():
            cleaned_values = [
                clean_text(value)
                for value in list(axis_values or [])
                if clean_text(value) and not _variant_option_value_is_noise(clean_text(value))
            ]
            if cleaned_values:
                variant_axes[str(axis_name)] = list(dict.fromkeys(cleaned_values))
    rows = [record.get("selected_variant"), *list(record.get("variants") or [])]
    for row in rows:
        if not isinstance(row, dict):
            continue
        option_values = row.get("option_values")
        if not isinstance(option_values, dict):
            continue
        for axis_name, axis_value in option_values.items():
            cleaned_value = clean_text(axis_value)
            if not cleaned_value or _variant_option_value_is_noise(cleaned_value):
                continue
            variant_axes.setdefault(str(axis_name), [])
            if cleaned_value not in variant_axes[str(axis_name)]:
                variant_axes[str(axis_name)].append(cleaned_value)
    if variant_axes:
        record["variant_axes"] = variant_axes
        for axis_name, axis_values in variant_axes.items():
            if axis_name in {"size", "color"} and len(axis_values) == 1:
                record[axis_name] = axis_values[0]
    else:
        record.pop("variant_axes", None)


def _drop_detail_variant_scalar_noise(record: dict[str, Any]) -> None:
    for field_name in list(record.keys()):
        if str(field_name).startswith("toggle_"):
            record.pop(field_name, None)
    for field_name in ("size", "color"):
        cleaned_value = clean_text(record.get(field_name))
        if cleaned_value and not _variant_option_value_is_noise(cleaned_value):
            record[field_name] = cleaned_value
            continue
        record.pop(field_name, None)


def _sanitize_detail_long_text_fields(record: dict[str, Any]) -> None:
    record_title = clean_text(record.get("title"))
    for field_name in LONG_TEXT_FIELDS:
        text = text_or_none(record.get(field_name))
        if not text:
            continue
        cleaned = _sanitize_detail_long_text(text, title=record_title)
        if cleaned:
            record[field_name] = cleaned
        else:
            record.pop(field_name, None)


def _sanitize_detail_long_text(text: str, *, title: str) -> str:
    if clean_text(text).lower() in _LOW_SIGNAL_LONG_TEXT_VALUES:
        return ""
    if _detail_long_text_is_document_label_cluster(text):
        return ""
    chunks = [
        clean_text(chunk)
        for chunk in re.split(r"(?<=[.!?])\s+|\s+:\s+|\n+", text)
        if clean_text(chunk)
    ]
    seen: set[str] = set()
    kept: list[str] = []
    for chunk in chunks:
        lowered = chunk.lower()
        if lowered in seen:
            continue
        if _detail_long_text_chunk_is_legal_tail(chunk):
            continue
        if _detail_long_text_chunk_is_variant_title(chunk, title=title):
            continue
        seen.add(lowered)
        kept.append(chunk)
    if kept and all(_detail_long_text_chunk_is_document_label(chunk) for chunk in kept):
        return ""
    return " ".join(kept).strip()


def _detail_long_text_chunk_is_legal_tail(chunk: str) -> bool:
    lowered = chunk.lower()
    return (
        "product safety" in lowered
        or "powered by product details have been supplied by the manufacturer" in lowered
        or ("customer service" in lowered and any(char.isdigit() for char in chunk))
        or ("contact " in lowered and any(char.isdigit() for char in chunk))
        or ("privacy" in lowered and "policy" in lowered)
        or lowered == "view more"
    )


def _detail_long_text_chunk_is_document_label(chunk: str) -> bool:
    normalized = clean_text(chunk)
    if not normalized:
        return False
    return any(pattern.fullmatch(normalized) for pattern in _DETAIL_DOCUMENT_LINK_LABEL_PATTERNS)


def _detail_long_text_is_document_label_cluster(text: str) -> bool:
    normalized = clean_text(text)
    if not normalized:
        return False
    normalized = re.sub(r"\b(guide|label|manual)\b\s+", r"\1\n", normalized, flags=re.I)
    parts = [
        clean_text(part)
        for part in normalized.splitlines()
        if clean_text(part)
    ]
    return len(parts) >= 2 and all(_detail_long_text_chunk_is_document_label(part) for part in parts)


def _detail_long_text_chunk_is_variant_title(chunk: str, *, title: str) -> bool:
    if not title:
        return False
    normalized_chunk = clean_text(chunk)
    if len(normalized_chunk.split()) > 16:
        return False
    if " - " not in normalized_chunk:
        return False
    title_tokens = _detail_identity_tokens(title)
    chunk_tokens = _detail_identity_tokens(normalized_chunk)
    return bool(title_tokens) and len(title_tokens & chunk_tokens) >= max(
        1,
        min(2, len(title_tokens)),
    )


def _sanitize_detail_images(record: dict[str, Any], *, identity_url: str) -> None:
    raw_images = [
        text_or_none(record.get("image_url")),
        *[
            text_or_none(value)
            for value in list(record.get("additional_images") or [])
        ],
    ]
    images = [image for image in raw_images if image]
    if not images:
        return
    primary_image = (
        "https://" + images[0][7:]
        if images[0].lower().startswith("http://")
        else images[0]
    )
    cleaned: list[str] = []
    for image in images:
        normalized_image = (
            "https://" + image[7:]
            if image.lower().startswith("http://")
            else image
        )
        if not _detail_image_candidate_is_usable(normalized_image, identity_url=identity_url):
            continue
        if not _detail_image_matches_primary_family(
            normalized_image,
            primary_image=primary_image,
            title=record.get("title"),
        ):
            continue
        cleaned.append(normalized_image)
    merged = dedupe_image_urls(cleaned)
    if not merged:
        record.pop("image_url", None)
        record.pop("additional_images", None)
        return
    record["image_url"] = merged[0]
    if len(merged) > 1:
        record["additional_images"] = merged[1:]
    else:
        record.pop("additional_images", None)


def _detail_image_candidate_is_usable(url: str, *, identity_url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    path = str(parsed.path or "").strip()
    if not path or path == "/":
        return False
    lowered = url.lower()
    if "base64," in lowered or lowered.startswith("data:"):
        return False
    if (
        same_site(identity_url, url)
        and _detail_url_looks_like_product(url)
        and not _detail_path_looks_like_image_asset(path, lowered)
    ):
        return False
    if re.search(r"/products?/[\d?=&-]*$", lowered):
        return False
    candidate_title = _detail_image_title_from_url(url)
    if (
        candidate_title
        and _detail_image_title_has_identity_signal(candidate_title)
        and not _detail_image_title_matches_requested_identity(
            candidate_title,
            requested_page_url=identity_url,
        )
    ):
        return False
    return True


def _detail_path_looks_like_image_asset(path: str, lowered_url: str) -> bool:
    lowered_path = str(path or "").lower()
    if re.search(r"\.(?:avif|gif|jpe?g|png|svg|tiff?|webp)(?:$|\?)", lowered_url):
        return True
    return any(
        token in lowered_path
        for token in ("/image/", "/images/", "/media/", "/picture", "/is/image/", "/cdn/")
    )


def _detail_image_matches_primary_family(
    url: str,
    *,
    primary_image: str,
    title: object,
) -> bool:
    if url == primary_image:
        return True
    primary_tokens = _detail_image_family_tokens(primary_image)
    candidate_tokens = _detail_image_family_tokens(url)
    if primary_tokens and candidate_tokens and primary_tokens & candidate_tokens:
        return True
    title_tokens = _semantic_detail_identity_tokens(title)
    if title_tokens and candidate_tokens and len(title_tokens & candidate_tokens) >= min(2, len(title_tokens)):
        return True
    primary_code = _detail_image_media_code(primary_image)
    candidate_code = _detail_image_media_code(url)
    if primary_code and candidate_code and primary_code == candidate_code:
        return True
    return not primary_tokens and not title_tokens


def _detail_image_title_from_url(url: str) -> str | None:
    path = unquote(urlparse(url).path)
    filename = path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.(?:avif|gif|jpe?g|png|svg|tiff?|webp)$", "", filename, flags=re.I)
    if not stem or re.fullmatch(r"img\d+", stem, re.I):
        return None
    normalized = clean_text(
        re.sub(
            r"[_-]+",
            " ",
            re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem),
        )
    )
    return normalized or None


def _detail_image_title_has_identity_signal(title: str) -> bool:
    return bool(
        len(_semantic_detail_identity_tokens(title)) >= 2
        or _detail_identity_codes_from_record_fields({"title": title})
    )


def _detail_image_title_matches_requested_identity(
    title: str,
    *,
    requested_page_url: str,
) -> bool:
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    candidate_codes = _detail_identity_codes_from_record_fields({"title": title})
    if requested_codes and candidate_codes and detail_identity_codes_match(requested_codes, candidate_codes):
        return True
    requested_title = _detail_title_from_url(requested_page_url)
    normalized_requested_title = clean_text(requested_title)
    normalized_candidate_title = clean_text(title)
    if (
        normalized_requested_title
        and normalized_candidate_title
        and normalized_candidate_title.lower().startswith(
            normalized_requested_title.lower()
        )
    ):
        return True
    requested_path = str(urlparse(requested_page_url).path or "")
    requested_segments = [
        clean_text(re.sub(r"[_-]+", " ", segment))
        for segment in requested_path.split("/")
        if clean_text(re.sub(r"[_-]+", " ", segment))
    ]
    requested_slug = next(
        (
            segment
            for segment in reversed(requested_segments)
            if segment.lower() not in {"product", "products", "p", "pd", "dp"}
        ),
        "",
    )
    if (
        requested_slug
        and normalized_candidate_title
        and normalized_candidate_title.lower().startswith(requested_slug.lower())
    ):
        return True
    requested_tokens = _detail_identity_tokens(requested_title or requested_page_url)
    candidate_tokens = _detail_identity_tokens(title)
    if not requested_tokens or not candidate_tokens:
        return False
    overlap = requested_tokens & candidate_tokens
    minimum_overlap = (
        2 if min(len(requested_tokens), len(candidate_tokens)) <= 4 else 4
    )
    return len(overlap) >= min(minimum_overlap, len(requested_tokens))


def _detail_image_family_tokens(url: str) -> set[str]:
    parts = [
        segment
        for segment in re.split(r"[^a-z0-9]+", unquote(urlparse(url).path).lower())
        if len(segment) >= 4
    ]
    noise = {
        "image",
        "images",
        "product",
        "products",
        "media",
        "picture",
        "files",
        "file",
        "main",
        "hero",
        "detail",
        "standard",
        "hover",
        "editorial",
        "square",
        "width",
        "height",
        "crop",
        "shop",
        "cdn",
    }
    return {part for part in parts if part not in noise}


def _detail_image_media_code(url: str) -> str | None:
    match = re.search(r"/([a-z]\d{5,})/", urlparse(url).path.lower())
    if match is not None:
        return match.group(1)
    return None


def _reconcile_detail_availability_from_variants(record: dict[str, Any]) -> None:
    variants = list(record.get("variants") or [])
    if not variants:
        return
    availabilities = {
        clean_text(variant.get("availability")).lower()
        for variant in variants
        if isinstance(variant, dict) and clean_text(variant.get("availability"))
    }
    if "in_stock" in availabilities:
        record["availability"] = "in_stock"
    elif availabilities == {"out_of_stock"}:
        record["availability"] = "out_of_stock"


def _prune_irrelevant_detail_structured_payload(
    payload: object,
    *,
    page_url: str,
    requested_page_url: str,
) -> object | None:
    if isinstance(payload, list):
        cleaned_items = [
            _prune_irrelevant_detail_structured_payload(
                item,
                page_url=page_url,
                requested_page_url=requested_page_url,
            )
            for item in payload[:50]
        ]
        return [item for item in cleaned_items if item not in (None, "", [], {})]
    if not isinstance(payload, dict):
        return payload
    if _detail_structured_payload_is_irrelevant_product(
        payload,
        page_url=page_url,
        requested_page_url=requested_page_url,
    ):
        return None
    cleaned: dict[str, object] = {}
    for key, value in payload.items():
        cleaned_value = _prune_irrelevant_detail_structured_payload(
            value,
            page_url=page_url,
            requested_page_url=requested_page_url,
        )
        if cleaned_value in (None, "", [], {}):
            continue
        cleaned[str(key)] = cleaned_value
    return cleaned or None


def _detail_structured_payload_is_irrelevant_product(
    payload: dict[str, object],
    *,
    page_url: str,
    requested_page_url: str,
) -> bool:
    raw_type = payload.get("@type")
    normalized_type = " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
    lowered_type = normalized_type.lower()
    payload_keys = {str(key).lower() for key in payload}
    looks_product_like = (
        "product" in lowered_type
        or bool({"sku", "mpn", "productid", "offers", "price", "image", "url"} & payload_keys)
        or (
            {"name", "description"} <= payload_keys
            and bool({"offers", "price", "image", "url"} & payload_keys)
        )
    )
    if not looks_product_like:
        return False
    candidate_url = absolute_url(page_url, payload.get("url") or payload.get("@id"))
    candidate_record = {
        "title": payload.get("name") or payload.get("title"),
        "description": payload.get("description"),
        "url": candidate_url,
        "sku": payload.get("sku") or payload.get("productId") or payload.get("productID"),
        "part_number": payload.get("mpn"),
    }
    if _record_matches_requested_detail_identity(
        candidate_record,
        requested_page_url=requested_page_url,
    ):
        return False
    if candidate_url and _detail_url_matches_requested_identity(
        candidate_url,
        requested_page_url=requested_page_url,
    ):
        return False
    requested_title = _detail_title_from_url(requested_page_url)
    candidate_title = clean_text(candidate_record.get("title"))
    requested_tokens = _detail_identity_tokens(requested_title)
    candidate_tokens = _detail_identity_tokens(candidate_title)
    if requested_tokens and candidate_tokens and requested_tokens.isdisjoint(candidate_tokens):
        return True
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    candidate_codes = _detail_identity_codes_from_record_fields(candidate_record)
    if requested_codes and candidate_codes and requested_codes.isdisjoint(candidate_codes):
        return True
    return False

def _looks_like_site_shell_record(record: dict[str, Any], *, page_url: str) -> bool:
    title = text_or_none(record.get("title")) or ""
    field_sources = _object_dict(record.get("_field_sources"))
    title_field_sources = _object_list(field_sources.get("title"))
    title_sources = {
        str(source).strip()
        for source in title_field_sources
        if str(source).strip()
    }
    if _detail_url_has_multiple_product_segments(page_url):
        return True
    if is_title_noise(title):
        return True
    if _detail_url_is_collection_like(page_url):
        return True
    generic_detail_fields = (
        "price",
        "currency",
        "brand",
        "category",
    )
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
    if (
        confidence_score < 0.5
        and not has_strong_detail_fields
        and "url_slug" in title_sources
    ):
        return True
    if (
        confidence_score < 0.5
        and _description_looks_like_shell_copy(record.get("description"))
        and not has_generic_detail_fields
        and not has_strong_detail_fields
    ):
        return True
    if (
        confidence_score < 0.5
        and _description_looks_like_shell_copy(record.get("description"))
        and _title_looks_like_brand_shell(title, page_url=page_url)
        and not any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in (
                "price",
                "original_price",
                "currency",
                "brand",
                "availability",
                "variants",
                "selected_variant",
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
    if _detail_title_looks_like_placeholder(title) and not any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in (
            "price",
            "original_price",
            "image_url",
            "sku",
            "part_number",
            "barcode",
        )
    ):
        return True
    if _detail_title_looks_like_placeholder(title) and not any(
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
        and str(record.get("_source") or "").strip() in {"opengraph", "json_ld_page_level", "microdata"}
        and not any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in strong_detail_fields
        )
    ):
        return True
    if (
        _detail_title_looks_like_placeholder(title)
        and not has_generic_detail_fields
        and not any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in strong_detail_fields
        )
    ):
        return True
    if not title_needs_promotion(title, page_url=page_url):
        if (
            _title_looks_like_brand_shell(title, page_url=page_url)
            and not has_generic_detail_fields
            and not any(
                record.get(field_name) not in (None, "", [], {})
                for field_name in strong_detail_fields
            )
            and (
                _description_looks_like_shell_copy(record.get("description"))
                or _detail_image_looks_like_tracking_or_shell(record.get("image_url"))
                or len(clean_text(record.get("description"))) <= 120
            )
        ):
            return True
        if not _detail_url_is_utility(page_url):
            return False
        record_url = text_or_none(record.get("url")) or ""
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
    if (
        _title_looks_like_brand_shell(title, page_url=page_url)
        and not has_generic_detail_fields
        and _description_looks_like_shell_copy(record.get("description"))
    ):
        return True
    return not any(record.get(field_name) not in (None, "", [], {}) for field_name in strong_detail_fields)


def _detail_url_has_multiple_product_segments(url: str) -> bool:
    path = str(urlparse(url).path or "").lower()
    return any(path.count(segment) > 1 for segment in ("/prd/", "/dp/", "/products/"))

def _detail_title_looks_like_placeholder(title: str) -> bool:
    normalized = clean_text(title)
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered in {"404", "not found"}:
        return True
    return any(pattern.search(normalized) for pattern in _DETAIL_PLACEHOLDER_TITLE_PATTERNS)

def _detail_image_looks_like_tracking_or_shell(value: object) -> bool:
    image_url = text_or_none(value)
    if not image_url:
        return False
    lowered = image_url.lower()
    return any(
        token in lowered
        for token in (
            "facebook.com/tr?",
            "facebook.com/tr&id=",
            "/tr?id=",
            "doubleclick",
            "googletagmanager",
            "google-analytics",
            "pixel",
        )
    )

def _title_looks_like_brand_shell(title: str, *, page_url: str) -> bool:
    normalized_title = str(title or "").strip().lower()
    if not normalized_title:
        return False
    host = str(urlparse(page_url).hostname or "").strip().lower()
    host_label = host.removeprefix("www.").split(".", 1)[0]
    compact_title = re.sub(r"[^a-z0-9]+", "", normalized_title)
    compact_host = re.sub(r"[^a-z0-9]+", "", host_label)
    if compact_title and compact_host and compact_title == compact_host:
        return True
    host_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", host_label)
        if len(token) >= 3
    }
    if not host_tokens:
        return False
    title_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", normalized_title)
        if len(token) >= 3
    }
    if not title_tokens or not (title_tokens & host_tokens):
        return False
    extra_tokens = title_tokens - host_tokens
    return bool(extra_tokens) and (
        extra_tokens <= set(DETAIL_BRAND_SHELL_TITLE_TOKENS)
        or (len(extra_tokens) <= 3 and len(title_tokens) <= 5)
    )

def _description_looks_like_shell_copy(description: object) -> bool:
    normalized_description = str(text_or_none(description) or "").strip().lower()
    if not normalized_description:
        return False
    return any(
        phrase in normalized_description
        for phrase in DETAIL_BRAND_SHELL_DESCRIPTION_PHRASES
    )

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

def _variant_option_value_is_noise(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.lower()
    return (
        not value
        or re.sub(r"[^a-z0-9]+", "", lowered) in _VARIANT_OPTION_VALUE_NOISE_TOKENS
        or lowered in {"select", "choose", "option", "size guide"}
        or re.fullmatch(r"[-\s]*(?:click\s+to\s+)?(?:choose|select)\b.*", lowered) is not None
        or re.fullmatch(r"[-\s]+.+[-\s]+", lowered) is not None
        or re.fullmatch(r"\(\d+\)", value) is not None
        or re.fullmatch(r"\d{3,5}/\d{2,5}/\d{2,5}", value) is not None
    )


def _strip_variant_option_value_suffix_noise(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    stripped = cleaned
    for pattern in _VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS:
        stripped = pattern.sub("", stripped).strip()
    return stripped or cleaned

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

def variant_option_availability(*, node: Any, label_node: Any | None) -> tuple[str | None, int | None]:
    attr_probe_parts: list[str] = []
    text_probe_parts: list[str] = []
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
        for token in ("outstock", "out-stock", "soldout", "sold-out", "unavailable")
    ):
        return "out_of_stock", 0
    stock_match = re.search(r"\b(\d+)\s+left\b", text_probe)
    if stock_match:
        quantity = int(stock_match.group(1))
        return ("in_stock" if quantity > 0 else "out_of_stock"), quantity
    if "out of stock" in text_probe or "sold out" in text_probe:
        return "out_of_stock", 0
    if "in stock" in text_probe or "available" in text_probe:
        return "in_stock", None
    return None, None

def _variant_option_url(
    *,
    container: Any,
    node: Any,
    label_node: Any | None,
    page_url: str,
) -> str | None:
    attr_names = (
        "href",
        "data-href",
        "data-url",
        "data-product-url",
        "data-target-url",
        "data-link",
        "data-variant-url",
    )
    candidates: list[Any] = [node, label_node]
    if hasattr(node, "find_parent"):
        parent_anchor = node.find_parent("a", href=True)
        if parent_anchor is not None:
            candidates.append(parent_anchor)
    if label_node is not None and hasattr(label_node, "find_parent"):
        parent_anchor = label_node.find_parent("a", href=True)
        if parent_anchor is not None:
            candidates.append(parent_anchor)
    if hasattr(node, "find"):
        anchor = node.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    if label_node is not None and hasattr(label_node, "find"):
        anchor = label_node.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    if hasattr(container, "find"):
        anchor = container.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    for candidate in candidates:
        if candidate is None or not hasattr(candidate, "get"):
            continue
        for attr_name in attr_names:
            raw = candidate.get(attr_name)
            url = text_or_none(raw)
            if url:
                from app.services.field_value_core import absolute_url

                return absolute_url(page_url, url)
    return None

def _merge_variant_option_state(
    entry: dict[str, object],
    *,
    container: Any,
    node: Any,
    page_url: str,
    label_node: Any | None = None,
) -> None:
    selected = (
        _node_state_matches(node, "selected", "active", "current", "highlight", "checked")
        or _node_attr_is_truthy(
            node,
            "checked",
            "aria-checked",
        )
        or text_or_none(getattr(node, "get", lambda *_args, **_kwargs: None)("data-state")) == "checked"
    )
    if selected:
        entry["selected"] = True
    availability, stock_quantity = variant_option_availability(node=node, label_node=label_node)
    if availability and entry.get("availability") in (None, "", [], {}):
        entry["availability"] = availability
    if stock_quantity is not None:
        entry["stock_quantity"] = stock_quantity
    variant_url = _variant_option_url(
        container=container,
        node=node,
        label_node=label_node,
        page_url=page_url,
    )
    if variant_url and entry.get("url") in (None, "", [], {}):
        entry["url"] = variant_url

def _collect_variant_choice_entries(container: Any, *, page_url: str) -> list[dict[str, object]]:
    axis_name = normalized_variant_axis_key(_resolve_dom_variant_group_name(container))
    entries_by_value: dict[str, dict[str, object]] = {}
    for node in container.select(
        "[data-value], [data-option-value], [aria-label], input[value], [role='radio']"
    )[:24]:
        cleaned = text_or_none(
            coerce_field_value(
                axis_name if axis_name in {"color", "size"} else "size",
                _variant_choice_entry_value(container, node),
                page_url,
            )
        )
        cleaned = _strip_variant_option_value_suffix_noise(cleaned)
        if _variant_option_value_is_noise(cleaned):
            continue
        entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
        _merge_variant_option_state(
            entry,
            container=container,
            node=node,
            page_url=page_url,
        )
        variant_id = text_or_none(
            node.get("data-sku")
            or node.get("data-variant-id")
            or node.get("data-product-id")
        )
        if variant_id and entry.get("variant_id") in (None, "", [], {}):
            entry["variant_id"] = variant_id
    for input_node in container.select("input[type='radio'], input[type='checkbox']")[:24]:
        label_node = _variant_input_label(container, input_node)
        cleaned = text_or_none(
            coerce_field_value(
                axis_name if axis_name in {"color", "size"} else "size",
                _variant_choice_entry_value(container, input_node, label_node=label_node),
                page_url,
            )
        )
        cleaned = _strip_variant_option_value_suffix_noise(cleaned)
        if _variant_option_value_is_noise(cleaned):
            continue
        entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
        _merge_variant_option_state(
            entry,
            container=container,
            node=input_node,
            page_url=page_url,
            label_node=label_node,
        )
    return list(entries_by_value.values())


def _variant_choice_entry_value(
    container: Any,
    node: Any,
    *,
    label_node: Any | None = None,
) -> str:
    resolved_label = label_node or _variant_input_label(container, node)
    label_text = (
        resolved_label.get_text(" ", strip=True)
        if resolved_label is not None and hasattr(resolved_label, "get_text")
        else ""
    )
    return clean_text(
        label_text
        or node.get("data-value")
        or node.get("data-option-value")
        or node.get("aria-label")
        or node.get("value")
    )


def _split_compound_axis_name(name: object) -> list[tuple[str, str]]:
    cleaned = clean_text(name)
    if not cleaned:
        return []
    parts = [
        clean_text(part)
        for part in re.split(r"\s*(?:&|/|\band\b)\s*", cleaned, flags=re.I)
        if clean_text(part)
    ]
    if len(parts) < 2:
        return []
    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for part in parts:
        if not variant_axis_name_is_semantic(part):
            return []
        axis_key = normalized_variant_axis_key(part)
        if not axis_key or axis_key in seen:
            return []
        seen.add(axis_key)
        resolved.append((axis_key, normalized_variant_axis_display_name(part) or part))
    return resolved if len(resolved) >= 2 else []


def _strip_variant_option_price_suffix(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    without_price = re.sub(r"\s*\([^)]*[\d][^)]*\)\s*$", "", cleaned).strip()
    return without_price or cleaned


def _split_compound_option_value(
    value: object,
    *,
    axis_keys: tuple[str, ...],
) -> dict[str, str] | None:
    cleaned = _strip_variant_option_price_suffix(value)
    if not cleaned or len(axis_keys) != 2 or "size" not in axis_keys:
        return None
    other_axis = next((axis for axis in axis_keys if axis != "size"), "")
    if not other_axis:
        return None
    tokens = [token for token in cleaned.split() if token]
    for width in range(min(3, len(tokens)), 0, -1):
        size_candidate = " ".join(tokens[-width:])
        if not any(pattern.fullmatch(size_candidate) for pattern in _DETAIL_VARIANT_SIZE_VALUE_PATTERNS):
            continue
        other_value = clean_text(" ".join(tokens[:-width]))
        if not other_value:
            return None
        return {
            other_axis: other_value,
            "size": size_candidate,
        }
    return None


def _expand_compound_option_group(group: dict[str, object]) -> list[dict[str, object]] | None:
    axis_parts = _split_compound_axis_name(group.get("name"))
    if len(axis_parts) != 2:
        return None
    entries = [entry for entry in _object_list(group.get("entries")) if isinstance(entry, dict)]
    if not entries:
        return None
    axis_keys = tuple(axis_key for axis_key, _ in axis_parts)
    parsed_rows: list[dict[str, str]] = []
    for entry in entries:
        parsed = _split_compound_option_value(entry.get("value"), axis_keys=axis_keys)
        if not parsed:
            return None
        parsed_rows.append(parsed)
    axis_values: dict[str, list[str]] = {axis_key: [] for axis_key, _ in axis_parts}
    observed_combos: set[tuple[str, ...]] = set()
    for parsed in parsed_rows:
        combo = tuple(parsed.get(axis_key, "") for axis_key, _ in axis_parts)
        if any(not value for value in combo):
            return None
        observed_combos.add(combo)
        for axis_key, _ in axis_parts:
            axis_value = parsed[axis_key]
            if axis_value not in axis_values[axis_key]:
                axis_values[axis_key].append(axis_value)
    expected_combo_count = 1
    for axis_key, _ in axis_parts:
        values = axis_values.get(axis_key) or []
        if len(values) < 2:
            return None
        expected_combo_count *= len(values)
    if len(observed_combos) != len(parsed_rows) or len(observed_combos) != expected_combo_count:
        return None
    return [
        {
            "name": display_name,
            "values": axis_values[axis_key],
            "entries": [{"value": axis_value} for axis_value in axis_values[axis_key]],
        }
        for axis_key, display_name in axis_parts
    ]

def _variant_query_url(page_url: str, *, query_key: str, query_value: str) -> str | None:
    normalized_key = text_or_none(query_key)
    normalized_value = text_or_none(query_value)
    if not normalized_key or not normalized_value:
        return None
    parsed = urlsplit(str(page_url or "").strip())
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != normalized_key
    ]
    query_pairs.append((normalized_key, normalized_value))
    return urlunsplit(parsed._replace(query=urlencode(query_pairs, doseq=True)))

def _iter_variant_mapping_payloads(value: Any, *, depth: int = 0, limit: int = 8) -> list[dict[str, Any]]:
    if depth > limit:
        return []
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("options"), list):
            matches.append(value)
        for item in value.values():
            matches.extend(_iter_variant_mapping_payloads(item, depth=depth + 1, limit=limit))
    elif isinstance(value, list):
        for item in value[:25]:
            matches.extend(_iter_variant_mapping_payloads(item, depth=depth + 1, limit=limit))
    return matches

def _state_variant_targets(
    js_state_objects: dict[str, Any] | None,
    *,
    page_url: str,
) -> tuple[dict[str, dict[str, dict[str, object]]], dict[tuple[tuple[str, str], ...], dict[str, object]]]:
    axis_targets: dict[str, dict[str, dict[str, object]]] = {}
    combo_targets: dict[tuple[tuple[str, str], ...], dict[str, object]] = {}
    if not isinstance(js_state_objects, dict):
        return axis_targets, combo_targets
    mapping_row_id_keys = ("productId", "product_id", "variantId", "variant_id", "sku", "id")
    url_keys = ("url", "href", "productUrl", "product_url", "targetUrl", "target_url")
    for payload in _iter_variant_mapping_payloads(js_state_objects):
        raw_options = payload.get("options")
        if not isinstance(raw_options, list):
            continue
        option_definitions: list[dict[str, object]] = []
        for option in raw_options:
            if not isinstance(option, dict):
                continue
            axis_field = text_or_none(option.get("id") or option.get("key") or option.get("name"))
            axis_key = normalized_variant_axis_key(option.get("label") or axis_field)
            option_list = option.get("optionList") if isinstance(option.get("optionList"), list) else None
            if not axis_field or not axis_key or not option_list:
                continue
            value_by_id: dict[str, str] = {}
            for item in option_list:
                if not isinstance(item, dict):
                    continue
                option_id = text_or_none(item.get("id") or item.get("value"))
                option_value = text_or_none(item.get("title") or item.get("label") or item.get("value"))
                if option_id and option_value and not _variant_option_value_is_noise(option_value):
                    value_by_id[option_id] = option_value
            if value_by_id:
                option_definitions.append(
                    {
                        "axis_field": axis_field,
                        "axis_key": axis_key,
                        "value_by_id": value_by_id,
                    }
                )
        if not option_definitions:
            continue
        mapping_lists = [
            item
            for item in payload.values()
            if isinstance(item, list) and item and all(isinstance(row, dict) for row in item)
        ]
        for mapping_rows in mapping_lists:
            for mapping_row in mapping_rows:
                option_values: dict[str, str] = {}
                for option_definition in option_definitions:
                    axis_field = str(option_definition["axis_field"])
                    axis_key = str(option_definition["axis_key"])
                    mapping_value_by_id = _object_dict(option_definition.get("value_by_id"))
                    option_id = text_or_none(mapping_row.get(axis_field))
                    mapped_option_value = mapping_value_by_id.get(option_id or "")
                    if mapped_option_value:
                        option_values[axis_key] = str(mapped_option_value)
                if not option_values:
                    continue
                row_metadata: dict[str, object] = {}
                explicit_url = next(
                    (
                        text_or_none(mapping_row.get(key))
                        for key in url_keys
                        if text_or_none(mapping_row.get(key))
                    ),
                    None,
                )
                if explicit_url:
                    from app.services.field_value_core import absolute_url

                    row_metadata["url"] = absolute_url(page_url, explicit_url)
                for key in mapping_row_id_keys:
                    raw_value = text_or_none(mapping_row.get(key))
                    if not raw_value:
                        continue
                    row_metadata.setdefault("variant_id", raw_value)
                    if "url" not in row_metadata:
                        inferred_url = _variant_query_url(
                            page_url,
                            query_key=key,
                            query_value=raw_value,
                        )
                        if inferred_url:
                            row_metadata["url"] = inferred_url
                    break
                if not row_metadata:
                    continue
                if len(option_values) == 1:
                    axis_key, option_value = next(iter(option_values.items()))
                    axis_targets.setdefault(axis_key, {}).setdefault(option_value, {}).update(row_metadata)
                combo_targets[tuple(sorted(option_values.items()))] = row_metadata
    return axis_targets, combo_targets

def _extract_variants_from_dom(
    soup: BeautifulSoup,
    *,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> dict[str, object]:
    option_groups: list[dict[str, object]] = []
    for select in iter_variant_select_groups(soup):
        raw_option_values = [
            clean_text(option.get_text(" ", strip=True))
            for option in select.find_all("option")
            if clean_text(option.get_text(" ", strip=True))
        ]
        cleaned_name = (
            resolve_variant_group_name(select)
            or infer_variant_group_name_from_values(raw_option_values)
        )
        inferred_name = infer_variant_group_name_from_values(raw_option_values)
        if inferred_name and normalized_variant_axis_key(cleaned_name) != inferred_name:
            cleaned_name = inferred_name
        if not cleaned_name:
            continue
        option_entries: list[dict[str, object]] = []
        axis_key = normalized_variant_axis_key(cleaned_name)
        select_options = list(select.find_all("option"))
        for option_index, option in enumerate(select_options):
            cleaned_value = text_or_none(
                coerce_field_value(
                    axis_key if axis_key in {"color", "size"} else "size",
                    option.get_text(" ", strip=True),
                    page_url,
                )
            ) or clean_text(option.get_text(" ", strip=True))
            cleaned_value = _strip_variant_option_value_suffix_noise(cleaned_value)
            raw_value_attr = text_or_none(option.get("value"))
            if (
                not cleaned_value
                or _variant_option_value_is_noise(cleaned_value)
                or (raw_value_attr is not None and raw_value_attr.lower() in {"select", "choose"})
            ):
                continue
            entry: dict[str, object] = {"value": cleaned_value}
            if _node_attr_is_truthy(option, "selected", "aria-selected"):
                entry["selected"] = True
            variant_url = _variant_option_url(
                container=select,
                node=option,
                label_node=None,
                page_url=page_url,
            )
            if variant_url:
                entry["url"] = variant_url
            option_entries.append(entry)
        deduped_values = list(
            dict.fromkeys(
                str(entry["value"])
                for entry in option_entries
                if text_or_none(entry.get("value"))
            )
        )
        if len(deduped_values) >= 2:
            option_groups.append({"name": cleaned_name, "values": deduped_values, "entries": option_entries})

    for container in iter_variant_choice_groups(soup):
        cleaned_name = _resolve_dom_variant_group_name(container)
        if not cleaned_name:
            continue
        option_entries = _collect_variant_choice_entries(container, page_url=page_url)
        deduped_values = [str(entry["value"]) for entry in option_entries if text_or_none(entry.get("value"))]
        inferred_name = infer_variant_group_name_from_values(deduped_values)
        if (
            inferred_name
            and normalized_variant_axis_key(cleaned_name) != inferred_name
            and not variant_axis_name_is_semantic(cleaned_name)
        ):
            cleaned_name = inferred_name
        if len(deduped_values) >= 2:
            option_groups.append(
                {
                    "name": cleaned_name,
                    "values": deduped_values,
                    "entries": option_entries,
                }
            )

    expanded_option_groups: list[dict[str, object]] = []
    for group in option_groups:
        compound_groups = _expand_compound_option_group(group)
        if compound_groups:
            expanded_option_groups.extend(compound_groups)
            continue
        expanded_option_groups.append(group)

    deduped_groups: list[dict[str, object]] = []
    merged_groups: dict[str, dict[str, object]] = {}
    for group in expanded_option_groups:
        values = [clean_text(value) for value in _object_list(group.get("values")) if clean_text(value)]
        if len(values) < 2:
            continue
        name = clean_text(group.get("name"))
        axis_key = normalized_variant_axis_key(name)
        if not axis_key:
            continue
        merged = merged_groups.setdefault(axis_key, {"name": name or axis_key, "values": [], "entries": {}})
        if len(name) > len(str(merged.get("name") or "")):
            merged["name"] = name
        existing_values = _object_list(merged.get("values"))
        merged["values"] = list(dict.fromkeys([*existing_values, *values]))
        merged_entries = merged.setdefault("entries", {})
        if not isinstance(merged_entries, dict):
            merged_entries = {}
            merged["entries"] = merged_entries
        for group_entry in _object_list(group.get("entries")):
            if not isinstance(group_entry, dict):
                continue
            value = clean_text(group_entry.get("value"))
            if not value:
                continue
            existing = _object_dict(merged_entries.get(value, {"value": value}))
            availability = text_or_none(group_entry.get("availability"))
            if availability and existing.get("availability") in (None, "", [], {}):
                existing["availability"] = availability
            if group_entry.get("stock_quantity") not in (None, "", [], {}):
                existing["stock_quantity"] = group_entry.get("stock_quantity")
            if group_entry.get("selected"):
                existing["selected"] = True
            if group_entry.get("url") not in (None, "", [], {}) and existing.get("url") in (None, "", [], {}):
                existing["url"] = group_entry.get("url")
            if group_entry.get("variant_id") not in (None, "", [], {}) and existing.get("variant_id") in (None, "", [], {}):
                existing["variant_id"] = group_entry.get("variant_id")
            merged_entries[value] = existing
    for group in merged_groups.values():
        values = [clean_text(value) for value in _object_list(group.get("values")) if clean_text(value)]
        if len(values) < 2:
            continue
        merged_entries = _object_dict(group.get("entries"))
        deduped_groups.append(
            {
                "name": clean_text(group.get("name")),
                "values": values,
                "entries": list(merged_entries.values()),
            }
        )
        if len(deduped_groups) >= 4:
            break

    if not deduped_groups:
        return {}

    state_axis_targets, state_combo_targets = _state_variant_targets(
        js_state_objects,
        page_url=page_url,
    )
    record: dict[str, object] = {}
    variant_axes: dict[str, list[str]] = {}
    axis_option_metadata: dict[str, dict[str, dict[str, object]]] = {}
    axis_order: list[tuple[str, str, list[str]]] = []
    for group in deduped_groups:
        name = clean_text(group.get("name"))
        values = [str(value) for value in _object_list(group.get("values"))]
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
                for key in ("availability", "selected", "stock_quantity", "url", "variant_id")
                if entry.get(key) not in (None, "", [], {})
            }
            for entry in _object_list(group.get("entries"))
            if isinstance(entry, dict)
            if clean_text(entry.get("value"))
        }
        for option_value, state_metadata in dict(state_axis_targets.get(axis_key) or {}).items():
            merged_metadata = axis_option_metadata[axis_key].setdefault(option_value, {})
            for key in ("url", "variant_id"):
                if state_metadata.get(key) not in (None, "", [], {}) and merged_metadata.get(key) in (None, "", [], {}):
                    merged_metadata[key] = state_metadata[key]
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
        combo_metadata = state_combo_targets.get(tuple(sorted(option_values.items())), {})
        for key in ("url", "variant_id"):
            if combo_metadata.get(key) not in (None, "", [], {}):
                variant[key] = combo_metadata[key]
        if len(axis_names) == 1:
            axis_key = axis_names[0]
            option_metadata = axis_option_metadata.get(axis_key, {}).get(str(combo[0]), {})
            availability = text_or_none(option_metadata.get("availability"))
            if availability:
                variant["availability"] = availability
            if option_metadata.get("stock_quantity") not in (None, "", [], {}):
                variant["stock_quantity"] = option_metadata.get("stock_quantity")
            for key in ("url", "variant_id"):
                if option_metadata.get(key) not in (None, "", [], {}):
                    variant[key] = option_metadata.get(key)
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
    if (
        normalized_surface == "ecommerce_detail"
        and record.get("variant_axes") in (None, "", [], {})
        and variant_dom_cues_present(soup)
    ):
        return True
    if normalized_surface == "ecommerce_detail" and variant_dom_cues_present(soup):
        if any(
            record.get(field_name) in (None, "", [], {})
            for field_name in ("variant_axes", "variants", "selected_variant")
        ):
            return True
    if (
        normalized_surface == "ecommerce_detail"
        and record.get("image_url") in (None, "", [], {})
        and soup.select_one("main img, article img, [role='main'] img, img") is not None
    ):
        return True
    extractability = requested_content_extractability(
        soup,
        surface=surface,
        requested_fields=requested_fields,
        selector_rules=selector_rules,
    )
    extractable_fields = {
        str(field_name).strip()
        for field_name in _object_list(extractability.get("extractable_fields"))
        if str(field_name).strip()
    }
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
    dom_pattern_fields = {
        str(field_name).strip()
        for field_name in _object_list(extractability.get("dom_pattern_fields"))
        if str(field_name).strip()
    }
    if optional_cue_fields & dom_pattern_fields:
        return True
    selector_backed_fields = {
        str(field_name).strip()
        for field_name in _object_list(extractability.get("selector_backed_fields"))
        if str(field_name).strip()
    }
    return bool(requested_missing_fields & selector_backed_fields)

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
    dom_parser, soup = primary_dom_context(
        context,
        page_url=page_url,
    )
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    candidates: dict[str, list[object]] = {}
    candidate_sources: dict[str, list[str]] = {}
    field_sources: dict[str, list[str]] = {}
    selector_trace_candidates: dict[str, list[dict[str, object]]] = {}
    fields = surface_fields(surface, requested_fields)
    selector_self_heal = _selector_self_heal_config(extraction_runtime_snapshot)
    state = DetailTierState(page_url=page_url, requested_page_url=requested_page_url, surface=surface, requested_fields=requested_fields, fields=fields, candidates=candidates, candidate_sources=candidate_sources, field_sources=field_sources, selector_trace_candidates=selector_trace_candidates, extraction_runtime_snapshot=extraction_runtime_snapshot, completed_tiers=[])
    js_state_objects = harvest_js_state_objects(None, context.cleaned_html)
    js_state_record = map_js_state_to_fields(
        js_state_objects,
        surface=surface,
        page_url=page_url,
    )
    if surface == "ecommerce_detail" and is_title_noise(js_state_record.get("title")):
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
    collect_js_state_tier(
        state,
        js_state_record=js_state_record,
        collect_record_candidates=_collect_record_candidates,
    )
    record = materialize_detail_tier(state, tier_name="js_state", materialize_record=_materialize_record)
    if (
        _coerce_float(_object_dict(record.get("_confidence")).get("score"))
        >= _coerce_float(selector_self_heal.get("threshold"))
        and not _requires_dom_completion(
            record=record,
            surface=surface,
            requested_fields=requested_fields,
            selector_rules=selector_rules,
            soup=soup,
        )
    ):
        backfill_detail_price_from_html(record, html=html)
        _backfill_variants_from_dom_if_missing(
            record,
            soup=soup,
            page_url=page_url,
            js_state_objects=js_state_objects,
        )
        _reconcile_detail_currency_with_url(record, page_url=page_url)
        drop_low_signal_zero_detail_price(record)
        record["_confidence"] = score_record_confidence(
            record,
            surface=surface,
            requested_fields=requested_fields,
        )
        record["_extraction_tiers"]["early_exit"] = "js_state"
        return record

    collect_dom_tier(
        state,
        dom_parser=dom_parser,
        soup=soup,
        selector_rules=selector_rules,
        apply_dom_fallbacks=(
            lambda dom_parser, soup, page_url, surface, requested_fields, candidates,
            candidate_sources, field_sources, selector_trace_candidates, *,
            selector_rules=None: apply_dom_fallbacks(
                dom_parser,
                soup,
                page_url=page_url,
                surface=surface,
                requested_fields=requested_fields,
                candidates=candidates,
                candidate_sources=candidate_sources,
                field_sources=field_sources,
                selector_trace_candidates=selector_trace_candidates,
                selector_rules=selector_rules,
                add_sourced_candidate=_add_sourced_candidate,
            )
        ),
        extract_variants_from_dom=(
            lambda dom_soup, *, page_url: _extract_variants_from_dom(
                dom_soup,
                page_url=page_url,
                js_state_objects=js_state_objects,
            )
        ),
        should_collect_dom_variants=_should_collect_dom_variants,
        add_sourced_candidate=_add_sourced_candidate,
    )
    record = materialize_detail_tier(state, tier_name="dom", materialize_record=_materialize_record)
    if surface == "ecommerce_detail" and title_needs_promotion(
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
    backfill_detail_price_from_html(record, html=html)
    _backfill_variants_from_dom_if_missing(
        record,
        soup=soup,
        page_url=page_url,
        js_state_objects=js_state_objects,
    )
    _reconcile_detail_currency_with_url(record, page_url=page_url)
    record["_confidence"] = score_record_confidence(
        record,
        surface=surface,
        requested_fields=requested_fields,
    )
    record["_extraction_tiers"]["early_exit"] = None
    return record


def detail_record_rejection_reason(
    record: dict[str, Any],
    *,
    page_url: str,
    requested_page_url: str | None = None,
) -> str | None:
    if _detail_redirect_identity_is_mismatched(
        record,
        page_url=page_url,
        requested_page_url=requested_page_url,
    ):
        return "detail_identity_mismatch"
    if _looks_like_site_shell_record(record, page_url=page_url):
        return "non_detail_seed"
    return None


def infer_detail_failure_reason(
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
) -> str | None:
    if "detail" not in str(surface or "").strip().lower():
        return None
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
    return detail_record_rejection_reason(
        record,
        page_url=page_url,
        requested_page_url=requested_page_url,
    )

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
    if surface == "ecommerce_detail":
        normalize_variant_record(record)
        backfill_detail_price_from_html(record, html=html)
        _reconcile_detail_currency_with_url(record, page_url=page_url)
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

def _backfill_variants_from_dom_if_missing(
    record: dict[str, Any],
    *,
    soup: BeautifulSoup,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> None:
    if record.get("variant_axes") not in (None, "", [], {}):
        return
    if not variant_dom_cues_present(soup):
        return
    dom_variants = _extract_variants_from_dom(
        soup,
        page_url=page_url,
        js_state_objects=js_state_objects,
    )
    for field_name in ("variant_axes", "variants", "variant_count", "selected_variant"):
        if record.get(field_name) in (None, "", [], {}) and dom_variants.get(field_name) not in (
            None,
            "",
            [],
            {},
        ):
            record[field_name] = dom_variants[field_name]
    currency = text_or_none(record.get("currency"))
    selected_variant = record.get("selected_variant")
    if not currency and isinstance(selected_variant, dict):
        currency = text_or_none(selected_variant.get("currency"))
    price = text_or_none(record.get("price"))
    if not price and isinstance(selected_variant, dict):
        price = text_or_none(selected_variant.get("price"))
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    if any(
        isinstance(variant, dict) and variant.get("price") not in (None, "", [], {})
        for variant in variants
    ):
        return
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if price:
            variant["price"] = price
        if currency and variant.get("currency") in (None, "", [], {}):
            variant["currency"] = currency

