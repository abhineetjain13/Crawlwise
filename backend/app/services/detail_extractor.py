from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Any

from bs4 import BeautifulSoup

from app.services.confidence import score_record_confidence
from app.services.config.field_mappings import (
    DOM_HIGH_VALUE_FIELDS,
    DOM_OPTIONAL_CUE_FIELDS,
    ECOMMERCE_DETAIL_JS_STATE_FIELDS,
    VARIANT_DOM_FIELD_NAMES,
)
from app.services.config.extraction_rules import (
    DETAIL_BRAND_SHELL_DESCRIPTION_PHRASES,
    DETAIL_BRAND_SHELL_TITLE_TOKENS,
    DETAIL_CATEGORY_SOURCE_RANKS,
    DETAIL_LONG_TEXT_RANK_FIELDS,
    DETAIL_LONG_TEXT_SOURCE_RANKS,
    DETAIL_TITLE_SOURCE_RANKS,
    SOURCE_PRIORITY,
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
    absolute_url,
    clean_text,
    coerce_field_value,
    enforce_flat_variant_public_contract,
    finalize_record,
    is_title_noise,
    object_dict as _object_dict,
    object_list as _object_list,
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
from app.services.network_payload_mapper import map_network_payloads_to_fields
from app.services.extract.detail_dom_extractor import (
    apply_dom_fallbacks,
    backfill_variants_from_dom_if_missing as _backfill_variants_from_dom_if_missing,
    extract_variants_from_dom as _extract_variants_from_dom,
    primary_dom_context,
    variant_option_availability,  # noqa: F401
)
from app.services.extract.detail_raw_signals import breadcrumb_category_from_dom
from app.services.extract.detail_identity import (
    detail_identity_codes_match,  # noqa: F401
    detail_identity_codes_from_record_fields as _detail_identity_codes_from_record_fields,
    detail_identity_codes_from_url as _detail_identity_codes_from_url,
    detail_identity_tokens as _detail_identity_tokens,
    detail_redirect_identity_is_mismatched as _detail_redirect_identity_is_mismatched,
    detail_title_from_url as _detail_title_from_url,
    detail_url_candidate_is_low_signal as _detail_url_candidate_is_low_signal,
    detail_url_is_collection_like as _detail_url_is_collection_like,
    detail_url_is_utility as _detail_url_is_utility,
    detail_url_matches_requested_identity as _detail_url_matches_requested_identity,
    preferred_detail_identity_url as _preferred_detail_identity_url,
    record_matches_requested_detail_identity as _record_matches_requested_detail_identity,
)
from app.services.extract.detail_record_finalizer import (
    dedupe_primary_and_additional_images as _dedupe_primary_and_additional_images,
    detail_image_matches_primary_family as _detail_image_matches_primary_family,  # noqa: F401
    detail_title_looks_like_placeholder as _detail_title_looks_like_placeholder,
    repair_ecommerce_detail_record_quality,
    sanitize_variant_row as _sanitize_variant_row,  # noqa: F401
)
from app.services.extract.detail_text_sanitizer import detail_candidate_is_valid
from app.services.extract.detail_price_extractor import (
    backfill_detail_price_from_html,
    drop_low_signal_zero_detail_price,
    reconcile_detail_price_magnitudes,
    reconcile_detail_currency_with_url as _reconcile_detail_currency_with_url,
)
from app.services.extract.detail_title_scorer import (
    promote_detail_title,
    title_needs_promotion,
)
from app.services.extract.shared_variant_logic import (
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


@dataclass(slots=True)
class PreparedDetailExtraction:
    context: Any
    dom_parser: Any
    soup: BeautifulSoup
    raw_soup: BeautifulSoup
    state: DetailTierState
    js_state_objects: dict[str, Any]
    js_state_record: dict[str, Any]
    selector_self_heal: dict[str, object]


def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _field_source_rank(surface: str, field_name: str, source: str | None) -> int:
    if str(surface or "").strip().lower() == "ecommerce_detail":
        if field_name == "category":
            configured_rank = DETAIL_CATEGORY_SOURCE_RANKS.get(str(source or ""))
            if configured_rank is not None:
                return configured_rank
        if field_name == "title":
            return DETAIL_TITLE_SOURCE_RANKS.get(str(source or ""), 20)
        if field_name in DETAIL_LONG_TEXT_RANK_FIELDS:
            return DETAIL_LONG_TEXT_SOURCE_RANKS.get(str(source or ""), 20)
        if field_name in ECOMMERCE_DETAIL_JS_STATE_FIELDS and source == "js_state":
            return 2
    return 100 + _SOURCE_PRIORITY_RANK.get(
        str(source or ""), len(_SOURCE_PRIORITY_RANK)
    )


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
    if not detail_candidate_is_valid(field_name, value, source=source):
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
            candidate_source = source
            if (
                field_name == "category"
                and source == "json_ld"
                and _structured_payload_is_breadcrumb_list(payload)
            ):
                candidate_source = "json_ld_breadcrumb"
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                field_name,
                value,
                source=candidate_source,
            )


def _structured_payload_is_breadcrumb_list(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    raw_type = payload.get("@type")
    type_values = raw_type if isinstance(raw_type, list) else [raw_type]
    return any(
        str(value or "").strip().lower() in {"breadcrumblist", "breadcrumb_list"}
        for value in type_values
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


_SOURCE_PRIORITY_RANK = {
    source_name: index for index, source_name in enumerate(SOURCE_PRIORITY)
}


def _ordered_candidates_for_field(
    surface: str,
    field_name: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
) -> list[tuple[str | None, object]]:
    sources = candidate_sources.get(field_name, [])
    indexed_entries = sorted(
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
        for index, value in enumerate(candidates.get(field_name, []))
    )
    return [(source, value) for _, _, source, value in indexed_entries]


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
    return {key: value for key, value in trace.items() if not str(key).startswith("_")}


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
        selected_source = ordered_candidates[0][0] if ordered_candidates else None
        winning_values = [
            value for source, value in ordered_candidates if source == selected_source
        ]
        finalized = (
            finalize_candidate_value(
                field_name, [value for _, value in ordered_candidates]
            )
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
        enforce_flat_variant_public_contract(record, page_url=page_url)
    drop_low_signal_zero_detail_price(record)
    _dedupe_primary_and_additional_images(record)
    confidence = score_record_confidence(
        record,
        surface=surface,
        requested_fields=requested_fields,
    )
    selector_self_heal = _selector_self_heal_config(extraction_runtime_snapshot)
    record["_confidence"] = confidence
    record["_extraction_tiers"] = {
        "completed": list(completed_tiers),
        "current": tier_name,
    }
    record["_self_heal"] = {
        "enabled": bool(selector_self_heal["enabled"]),
        "triggered": False,
        "threshold": _coerce_float(selector_self_heal.get("threshold")),
    }
    return finalize_record(record, surface=surface)


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
    normalized_type = (
        " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
    )
    lowered_type = normalized_type.lower()
    payload_keys = {str(key).lower() for key in payload}
    looks_product_like = (
        "product" in lowered_type
        or bool(
            {"sku", "mpn", "productid", "offers", "price", "image", "url"}
            & payload_keys
        )
        or (
            {"name", "description"} <= payload_keys
            and bool({"offers", "price", "image", "url"} & payload_keys)
        )
    )
    if not looks_product_like:
        return False
    raw_candidate_url = payload.get("url") or payload.get("@id")
    candidate_url = absolute_url(page_url, raw_candidate_url)
    candidate_record = {
        "title": payload.get("name") or payload.get("title"),
        "description": payload.get("description"),
        "url": candidate_url,
        "sku": payload.get("sku")
        or payload.get("productId")
        or payload.get("productID"),
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
    if not text_or_none(raw_candidate_url):
        return False
    requested_title = _detail_title_from_url(requested_page_url)
    candidate_title = clean_text(candidate_record.get("title"))
    requested_tokens = _detail_identity_tokens(requested_title)
    candidate_tokens = _detail_identity_tokens(candidate_title)
    if (
        requested_tokens
        and candidate_tokens
        and requested_tokens.isdisjoint(candidate_tokens)
    ):
        return True
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    candidate_codes = _detail_identity_codes_from_record_fields(candidate_record)
    if (
        requested_codes
        and candidate_codes
        and requested_codes.isdisjoint(candidate_codes)
    ):
        return True
    return False


def _looks_like_site_shell_record(record: dict[str, Any], *, page_url: str) -> bool:
    title = text_or_none(record.get("title")) or ""
    field_sources = _object_dict(record.get("_field_sources"))
    title_field_sources = _object_list(field_sources.get("title"))
    title_sources = {
        str(source).strip() for source in title_field_sources if str(source).strip()
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
        and str(record.get("_source") or "").strip()
        in {"opengraph", "json_ld_page_level", "microdata"}
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
    return not any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in strong_detail_fields
    )


def _detail_url_has_multiple_product_segments(url: str) -> bool:
    path = str(urlparse(url).path or "").lower()
    return any(path.count(segment) > 1 for segment in ("/prd/", "/dp/", "/products/"))


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
        token for token in re.split(r"[^a-z0-9]+", host_label) if len(token) >= 3
    }
    if not host_tokens:
        return False
    title_tokens = {
        token for token in re.split(r"[^a-z0-9]+", normalized_title) if len(token) >= 3
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


def _variant_signal_strength(variants: object) -> tuple[int, int, int]:
    if not isinstance(variants, list):
        return (0, 0, 0)
    rows = [row for row in variants if isinstance(row, dict)]
    return (
        len(rows),
        sum(
            1
            for row in rows
            if text_or_none(row.get("color")) or text_or_none(row.get("size"))
        ),
        sum(1 for row in rows if text_or_none(row.get("price"))),
    )


def _should_collect_dom_variants(
    candidates: dict[str, list[object]],
    dom_variants: dict[str, object],
) -> bool:
    if not any(candidates.get(field_name) for field_name in VARIANT_DOM_FIELD_NAMES):
        return True
    existing_variants = finalize_candidate_value(
        "variants", list(candidates.get("variants") or [])
    )
    existing_strength = _variant_signal_strength(existing_variants)
    if 0 in existing_strength:
        return True
    dom_strength = _variant_signal_strength(dom_variants.get("variants"))
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
        *_ordered_candidates_for_field(
            surface, "image_url", candidates, candidate_sources
        ),
        *_ordered_candidates_for_field(
            surface, "additional_images", candidates, candidate_sources
        ),
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
    breadcrumb_soup: BeautifulSoup | None = None,
) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    requested_missing_fields = _missing_requested_fields(record, requested_fields)
    if normalized_surface == "ecommerce_detail":
        breadcrumb_category = breadcrumb_category_from_dom(
            breadcrumb_soup or soup,
            current_title=text_or_none(record.get("title")),
        )
        record_category = _normalized_category_path(record.get("category"))
        dom_category = _normalized_category_path(breadcrumb_category)
        if dom_category and record_category != dom_category:
            return True
    if normalized_surface == "ecommerce_detail" and variant_dom_cues_present(soup):
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


def _normalized_category_path(value: object) -> str:
    text = clean_text(value).casefold()
    return " > ".join(
        part
        for part in re.split(r"\s*(?:>|/|›|»|→|\|)\s*", text)
        if part
    )


def _finalize_early_detail_record(
    record: dict[str, Any],
    *,
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    soup: BeautifulSoup,
    js_state_objects: dict[str, Any],
) -> dict[str, Any]:
    backfill_detail_price_from_html(record, html=html)
    reconcile_detail_price_magnitudes(record)
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


def _promote_dom_detail_title(
    record: dict[str, Any],
    *,
    js_state_record: dict[str, Any],
    page_url: str,
) -> None:
    if not title_needs_promotion(
        text_or_none(record.get("title")) or "",
        page_url=page_url,
    ):
        return
    preferred_title = text_or_none(js_state_record.get("title"))
    if preferred_title:
        record["title"] = preferred_title
        return
    fallback_title = _detail_title_from_url(page_url)
    if not fallback_title:
        return
    record["title"] = fallback_title
    title_sources = record.setdefault("_field_sources", {}).setdefault("title", [])
    if "url_slug" not in title_sources:
        title_sources.append("url_slug")


def _fill_missing_dom_detail_title(record: dict[str, Any], *, page_url: str) -> None:
    if text_or_none(record.get("title")):
        return
    fallback_title = _detail_title_from_url(page_url)
    if not fallback_title:
        return
    record["title"] = fallback_title
    title_sources = record.setdefault("_field_sources", {}).setdefault("title", [])
    if "url_slug" not in title_sources:
        title_sources.append("url_slug")


def _finalize_dom_detail_record(
    record: dict[str, Any],
    *,
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    soup: BeautifulSoup,
    js_state_objects: dict[str, Any],
) -> dict[str, Any]:
    backfill_detail_price_from_html(record, html=html)
    reconcile_detail_price_magnitudes(record)
    drop_low_signal_zero_detail_price(record)
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


def _prepare_detail_extraction(
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    *,
    requested_page_url: str | None,
    extraction_runtime_snapshot: dict[str, object] | None,
) -> PreparedDetailExtraction:
    context = prepare_extraction_context(html)
    dom_parser, soup = primary_dom_context(context, page_url=page_url)
    raw_soup = BeautifulSoup(context.original_html, "html.parser")
    candidates: dict[str, list[object]] = {}
    candidate_sources: dict[str, list[str]] = {}
    field_sources: dict[str, list[str]] = {}
    selector_trace_candidates: dict[str, list[dict[str, object]]] = {}
    state = DetailTierState(
        page_url=page_url,
        requested_page_url=requested_page_url,
        surface=surface,
        requested_fields=requested_fields,
        fields=surface_fields(surface, requested_fields),
        candidates=candidates,
        candidate_sources=candidate_sources,
        field_sources=field_sources,
        selector_trace_candidates=selector_trace_candidates,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
        completed_tiers=[],
    )
    js_state_objects = harvest_js_state_objects(None, context.cleaned_html)
    js_state_record = map_js_state_to_fields(
        js_state_objects,
        surface=surface,
        page_url=page_url,
    )
    if surface == "ecommerce_detail" and is_title_noise(js_state_record.get("title")):
        js_state_record = dict(js_state_record)
        js_state_record.pop("title", None)
    return PreparedDetailExtraction(
        context=context,
        dom_parser=dom_parser,
        soup=soup,
        raw_soup=raw_soup,
        state=state,
        js_state_objects=js_state_objects,
        js_state_record=js_state_record,
        selector_self_heal=_selector_self_heal_config(extraction_runtime_snapshot),
    )


def _collect_pre_dom_detail_tiers(
    prepared: PreparedDetailExtraction,
    *,
    adapter_records: list[dict[str, Any]] | None,
    network_payloads: list[dict[str, object]] | None,
    alias_lookup: dict[str, str],
) -> dict[str, Any]:
    collect_authoritative_tier(
        prepared.state,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        collect_record_candidates=_collect_record_candidates,
        map_network_payloads_to_fields=map_network_payloads_to_fields,
    )
    materialize_detail_tier(
        prepared.state,
        tier_name="authoritative",
        materialize_record=_materialize_record,
    )
    collect_structured_data_tier(
        prepared.state,
        context=prepared.context,
        alias_lookup=alias_lookup,
        collect_structured_source_payloads=collect_structured_source_payloads,
        collect_structured_payload_candidates=_collect_structured_payload_candidates,
    )
    materialize_detail_tier(
        prepared.state,
        tier_name="structured_data",
        materialize_record=_materialize_record,
    )
    collect_js_state_tier(
        prepared.state,
        js_state_record=prepared.js_state_record,
        collect_record_candidates=_collect_record_candidates,
    )
    return materialize_detail_tier(
        prepared.state,
        tier_name="js_state",
        materialize_record=_materialize_record,
    )


def _collect_dom_detail_tier(
    prepared: PreparedDetailExtraction,
    *,
    selector_rules: list[dict[str, object]] | None,
) -> dict[str, Any]:
    collect_dom_tier(
        prepared.state,
        dom_parser=prepared.dom_parser,
        soup=prepared.soup,
        selector_rules=selector_rules,
        apply_dom_fallbacks=(
            lambda dom_parser, soup, page_url, surface, requested_fields, candidates, candidate_sources, field_sources, selector_trace_candidates, *, selector_rules=None: (
                apply_dom_fallbacks(
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
                    breadcrumb_soup=prepared.raw_soup,
                )
            )
        ),
        extract_variants_from_dom=(
            lambda dom_soup, *, page_url: _extract_variants_from_dom(
                dom_soup,
                page_url=page_url,
                js_state_objects=prepared.js_state_objects,
            )
        ),
        should_collect_dom_variants=_should_collect_dom_variants,
        add_sourced_candidate=_add_sourced_candidate,
    )
    return materialize_detail_tier(
        prepared.state,
        tier_name="dom",
        materialize_record=_materialize_record,
    )


def _can_skip_dom_tier(
    record: dict[str, Any],
    prepared: PreparedDetailExtraction,
    *,
    surface: str,
    requested_fields: list[str] | None,
    selector_rules: list[dict[str, object]] | None,
) -> bool:
    confidence_score = _coerce_float(
        _object_dict(record.get("_confidence")).get("score")
    )
    threshold = _coerce_float(prepared.selector_self_heal.get("threshold"))
    return confidence_score >= threshold and not _requires_dom_completion(
        record=record,
        surface=surface,
        requested_fields=requested_fields,
        selector_rules=selector_rules,
        soup=prepared.soup,
        breadcrumb_soup=prepared.raw_soup,
    )


def _build_dom_tier_record(
    prepared: PreparedDetailExtraction,
    *,
    selector_rules: list[dict[str, object]] | None,
    surface: str,
    page_url: str,
) -> dict[str, Any]:
    record = _collect_dom_detail_tier(prepared, selector_rules=selector_rules)
    if surface == "ecommerce_detail":
        _promote_dom_detail_title(
            record,
            js_state_record=prepared.js_state_record,
            page_url=page_url,
        )
        _fill_missing_dom_detail_title(record, page_url=page_url)
    return record


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
    prepared = _prepare_detail_extraction(
        html,
        page_url,
        surface,
        requested_fields,
        requested_page_url=requested_page_url,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
    )
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    record = _collect_pre_dom_detail_tiers(
        prepared,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        alias_lookup=alias_lookup,
    )
    if _can_skip_dom_tier(
        record,
        prepared,
        surface=surface,
        requested_fields=requested_fields,
        selector_rules=selector_rules,
    ):
        if surface == "ecommerce_detail":
            _promote_dom_detail_title(
                record,
                js_state_record=prepared.js_state_record,
                page_url=page_url,
            )
            _fill_missing_dom_detail_title(record, page_url=page_url)
        return _finalize_early_detail_record(
            record,
            html=html,
            page_url=page_url,
            surface=surface,
            requested_fields=requested_fields,
            soup=prepared.soup,
            js_state_objects=prepared.js_state_objects,
        )

    record = _build_dom_tier_record(
        prepared,
        selector_rules=selector_rules,
        surface=surface,
        page_url=page_url,
    )
    return _finalize_dom_detail_record(
        record,
        html=html,
        page_url=page_url,
        surface=surface,
        requested_fields=requested_fields,
        soup=prepared.soup,
        js_state_objects=prepared.js_state_objects,
    )


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
        reconcile_detail_price_magnitudes(record)
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
