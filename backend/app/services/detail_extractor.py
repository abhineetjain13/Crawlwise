from __future__ import annotations

import logging
import re
from itertools import product
from urllib.parse import urlparse
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.confidence import score_record_confidence
from app.services.config.extraction_rules import (
    EXTRACTION_RULES,
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_ACTION_NOISE_PATTERNS,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
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
    PRICE_RE,
    RATING_RE,
    REVIEW_COUNT_RE,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    clean_text,
    coerce_field_value,
    finalize_record,
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
    extract_heading_sections,
    extract_page_images,
)
from app.services.js_state_mapper import map_js_state_to_fields
from app.services.js_state_helpers import select_variant
from app.services.network_payload_mapper import map_network_payloads_to_fields
from app.services.extract.shared_variant_logic import (
    infer_variant_group_name,
    normalized_variant_axis_key,
    resolve_variants,
    split_variant_axes,
    variant_dom_cues_present,
    variant_node_is_noise,
    variant_value_is_noise,
)
from app.services.extract.detail_tiers import (
    DetailTierState,
    collect_authoritative_tier,
    collect_dom_tier,
    collect_js_state_tier,
    collect_structured_data_tier,
    materialize_detail_tier,
)

logger = logging.getLogger(__name__)

_SOURCE_PRIORITY = (
    "adapter",
    "network_payload",
    "json_ld",
    "microdata",
    "opengraph",
    "embedded_json",
    "js_state",
    "dom_h1",
    "dom_canonical",
    "selector_rule",
    "dom_selector",
    "dom_sections",
    "dom_images",
    "dom_text",
)
_DOM_HIGH_VALUE_FIELDS: dict[str, frozenset[str]] = {
    "ecommerce_detail": frozenset(
        {
            "description",
            "specifications",
        }
    ),
    "job_detail": frozenset(
        {
            "description",
            "responsibilities",
            "qualifications",
        }
    ),
}
_DOM_OPTIONAL_CUE_FIELDS: dict[str, frozenset[str]] = {
    "ecommerce_detail": frozenset({"features", "materials", "care", "dimensions"}),
    "job_detail": frozenset({"benefits", "skills", "requirements"}),
}

_ECOMMERCE_DETAIL_JS_STATE_FIELDS = frozenset(
    {
        "additional_images",
        "availability",
        "available_sizes",
        "brand",
        "color",
        "currency",
        "image_count",
        "image_url",
        "option1_name",
        "option1_values",
        "option2_name",
        "option2_values",
        "original_price",
        "price",
        "product_id",
        "selected_variant",
        "size",
        "sku",
        "stock_quantity",
        "title",
        "variant_axes",
        "variant_count",
        "variants",
    }
)
_VARIANT_DOM_FIELD_NAMES = (
    "available_sizes",
    "option1_name",
    "option1_values",
    "option2_name",
    "option2_values",
    "variant_axes",
    "variant_count",
    "variants",
)


def _field_source_rank(surface: str, field_name: str, source: str | None) -> int:
    if str(surface or "").strip().lower() == "ecommerce_detail":
        if field_name == "title":
            return {"adapter": 0, "network_payload": 1, "json_ld": 2, "microdata": 3, "opengraph": 4, "embedded_json": 5, "js_state": 6, "dom_h1": 10, "dom_canonical": 11, "selector_rule": 12, "dom_selector": 13, "dom_sections": 14, "dom_images": 15, "dom_text": 16}.get(str(source or ""), 20)
        if field_name in _ECOMMERCE_DETAIL_JS_STATE_FIELDS and source == "js_state":
            return 2
    return 100 + _SOURCE_PRIORITY_RANK.get(source, len(_SOURCE_PRIORITY_RANK))


def _detail_title_is_noise(title: object) -> bool:
    cleaned = clean_text(title)
    lowered = cleaned.lower()
    if not lowered:
        return True
    if len(cleaned) < 4 or cleaned.isdigit():
        return True
    if "star" in lowered and RATING_RE.search(lowered):
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
        (candidate for candidate in (h1_title, page_title_text) if candidate and not _detail_title_is_noise(candidate)),
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
        exclude_linked_detail_images=True,
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
    if "price" in fields and not candidates.get("price"):
        price_match = PRICE_RE.search(body_text)
        if price_match:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "price",
                price_match.group(0),
                source="dom_text",
            )
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


_SOURCE_PRIORITY_RANK = {
    source_name: index for index, source_name in enumerate(_SOURCE_PRIORITY)
}

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

def _merged_structured_field_value(
    field_name: str,
    ordered_candidates: list[tuple[str | None, object]],
) -> object | None:
    return finalize_candidate_value(
        field_name,
        [value for _, value in ordered_candidates],
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
    record: dict[str, Any] = {
        "source_url": page_url,
        "url": page_url,
    }
    selected_field_sources: dict[str, str] = {}
    for field_name in fields:
        ordered_candidates = _ordered_candidates_for_field(
            surface,
            field_name,
            candidates,
            candidate_sources,
        )
        winning_values, selected_source = _winning_candidates_for_field(ordered_candidates)
        finalized = (
            _merged_structured_field_value(field_name, ordered_candidates)
            if field_name in STRUCTURED_OBJECT_FIELDS | STRUCTURED_OBJECT_LIST_FIELDS
            else finalize_candidate_value(field_name, winning_values)
        )
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
            if selected_source:
                selected_field_sources[field_name] = selected_source
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
    record["_extraction_tiers"] = {
        "completed": list(completed_tiers),
        "current": tier_name,
    }
    record["_self_heal"] = {
        "enabled": bool(selector_self_heal["enabled"]),
        "triggered": False,
        "threshold": float(selector_self_heal["threshold"]),
    }
    return finalize_record(record, surface=surface)




def _dedupe_primary_and_additional_images(record: dict[str, Any]) -> None:
    primary_image = text_or_none(record.get("image_url"))
    raw_additional_images = record.get("additional_images")
    if raw_additional_images in (None, "", [], {}):
        return
    filtered: list[str] = []
    seen: set[str] = set()
    if primary_image:
        seen.add(primary_image.lower())
    values = (
        list(raw_additional_images)
        if isinstance(raw_additional_images, (list, tuple, set))
        else [raw_additional_images]
    )
    for value in values:
        image = text_or_none(value)
        if not image:
            continue
        lowered = image.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        filtered.append(image)
    if filtered:
        record["additional_images"] = filtered
        return
    record.pop("additional_images", None)


def _variant_fields_are_empty(candidates: dict[str, list[object]]) -> bool:
    return not any(candidates.get(field_name) for field_name in _VARIANT_DOM_FIELD_NAMES)


def _should_collect_dom_variants(candidates: dict[str, list[object]]) -> bool:
    return _variant_fields_are_empty(candidates) or not candidates.get("variants")


def _extract_variants_from_dom(soup: BeautifulSoup) -> dict[str, object]:
    option_groups: list[dict[str, object]] = []
    for select in soup.select(
        "select[name*='variant' i], select[name*='option' i], "
        "select[name*='size' i], select[name*='color' i], "
        "select[id*='variant' i], select[id*='option' i], "
        "select[id*='size' i], select[id*='color' i], "
        "select[aria-label*='size' i], select[aria-label*='color' i], "
        "select[class*='variant' i], select[data-option], select[data-option-name]"
    )[:4]:
        raw_name = (
            select.get("data-option-name")
            or select.get("aria-label")
            or select.get("name")
            or select.get("id")
            or ""
        )
        values = [
            clean_text(option.get_text(" ", strip=True))
            for option in select.find_all("option")
            if clean_text(option.get_text(" ", strip=True))
            and str(option.get("value") or "").strip().lower() not in {"", "select", "choose"}
        ]
        deduped_values = list(dict.fromkeys(values))
        if len(deduped_values) >= 2:
            option_groups.append(
                {
                    "name": clean_text(str(raw_name).replace("_", " ").replace("-", " ")),
                    "values": deduped_values,
                }
            )

    for container in soup.select(
        "[data-option-name], [aria-label*='size' i], [aria-label*='color' i], "
        "[class*='swatch' i], [class*='variant' i], [class*='option' i], "
        "[class*='color-selector' i], [class*='size-selector' i], "
        "[data-testid*='swatch' i], [role='radiogroup'], "
        "[data-qa-action='select-color'], [data-qa-action*='size-selector']"
    )[:8]:
        raw_name = (
            container.get("data-option-name")
            or container.get("aria-label")
            or container.get("data-testid")
            or container.get("data-qa-action")
            or infer_variant_group_name(container)
            or ""
        )
        values: list[str] = []
        for node in container.select(
            "[data-value], [data-option-value], [aria-label], button, label, span, input"
        )[:24]:
            if variant_node_is_noise(node):
                continue
            raw_value = (
                node.get("data-value")
                or node.get("data-option-value")
                or node.get("aria-label")
                or node.get("value")
                or node.get_text(" ", strip=True)
            )
            cleaned = clean_text(raw_value)
            if variant_value_is_noise(cleaned):
                continue
            values.append(cleaned)
        deduped_values = list(dict.fromkeys(values))
        if len(deduped_values) >= 2:
            option_groups.append(
                {
                    "name": clean_text(
                        str(raw_name or infer_variant_group_name(container))
                        .replace("_", " ")
                        .replace("-", " ")
                    ),
                    "values": deduped_values,
                }
            )

    deduped_groups: list[dict[str, object]] = []
    merged_groups: dict[str, dict[str, object]] = {}
    for group in option_groups:
        values = [
            clean_text(value)
            for value in list(group.get("values") or [])
            if not variant_value_is_noise(value)
        ]
        if len(values) < 2:
            continue
        name = clean_text(group.get("name"))
        axis_key = normalized_variant_axis_key(name)
        if not axis_key:
            continue
        merged = merged_groups.setdefault(
            axis_key,
            {"name": name or axis_key, "values": []},
        )
        if len(name) > len(str(merged.get("name") or "")):
            merged["name"] = name
        merged["values"] = list(dict.fromkeys([*list(merged.get("values") or []), *values]))
    for group in merged_groups.values():
        values = [
            clean_text(value)
            for value in list(group.get("values") or [])
            if not variant_value_is_noise(value)
        ]
        if len(values) < 2:
            continue
        deduped_groups.append({"name": clean_text(group.get("name")), "values": values})
        if len(deduped_groups) >= 2:
            break

    if not deduped_groups:
        return {}

    record: dict[str, object] = {}
    variant_axes: dict[str, list[str]] = {}
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
        variants.append(variant)

    selectable_axes, single_value_attributes = split_variant_axes(
        variant_axes,
        always_selectable_axes=frozenset({"size"}),
    )
    resolved_variants = (
        resolve_variants(selectable_axes or variant_axes, variants)
        if variants
        else []
    )
    selected_variant = select_variant(resolved_variants, page_url="")
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
    return normalized_title == host.removeprefix("www.").split(".", 1)[0]


def _missing_requested_fields(
    record: dict[str, Any],
    requested_fields: list[str] | None,
) -> set[str]:
    missing: set[str] = set()
    for field_name in list(requested_fields or []):
        normalized = str(field_name or "").strip().lower()
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
    if normalized_surface == "ecommerce_detail" and variant_dom_cues_present(soup):
        if any(
            record.get(field_name) in (None, "", [], {})
            for field_name in ("variant_axes", "variants", "selected_variant")
        ):
            return True
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    high_value_fields = set(_DOM_HIGH_VALUE_FIELDS.get(normalized_surface) or ())
    advertised_dom_sections = {
        normalized
        for label in extract_heading_sections(soup).keys()
        for normalized in [alias_lookup.get(label.lower())]
        if normalized in high_value_fields
    }
    missing_high_value_fields = {
        field_name
        for field_name in advertised_dom_sections
        if record.get(field_name) in (None, "", [], {})
    }
    missing_high_value_fields.update(
        {
            field_name
            for field_name in high_value_fields
            if field_name in _missing_requested_fields(record, requested_fields)
        }
    )
    requested_missing_fields = _missing_requested_fields(record, requested_fields)
    if missing_high_value_fields or requested_missing_fields & high_value_fields:
        return True
    optional_cue_fields = {
        field_name
        for field_name in set(_DOM_OPTIONAL_CUE_FIELDS.get(normalized_surface) or ())
        if record.get(field_name) in (None, "", [], {})
    }
    dom_patterns = dict(EXTRACTION_RULES.get("dom_patterns") or {})
    for field_name in optional_cue_fields:
        selector = str(dom_patterns.get(field_name) or "").strip()
        if selector and soup.select(selector):
            return True
    selector_backed_fields = {
        str(row.get("field_name") or "").strip().lower()
        for row in list(selector_rules or [])
        if isinstance(row, dict)
        and bool(row.get("is_active", True))
        and (
            str(row.get("css_selector") or "").strip()
            or str(row.get("xpath") or "").strip()
            or str(row.get("regex") or "").strip()
        )
    }
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
    state = DetailTierState(
        page_url=page_url,
        surface=surface,
        requested_fields=requested_fields,
        fields=fields,
        candidates=candidates,
        candidate_sources=candidate_sources,
        field_sources=field_sources,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
        completed_tiers=[],
    )
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
    record = materialize_detail_tier(
        state,
        tier_name="authoritative",
        materialize_record=_materialize_record,
    )

    collect_structured_data_tier(
        state,
        context=context,
        alias_lookup=alias_lookup,
        collect_structured_source_payloads=collect_structured_source_payloads,
        collect_structured_payload_candidates=_collect_structured_payload_candidates,
    )
    record = materialize_detail_tier(
        state,
        tier_name="structured_data",
        materialize_record=_materialize_record,
    )
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
    record = materialize_detail_tier(
        state,
        tier_name="js_state",
        materialize_record=_materialize_record,
    )

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
    record = materialize_detail_tier(
        state,
        tier_name="dom",
        materialize_record=_materialize_record,
    )
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
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
    )
    if record_score(record) <= 0:
        return []
    return [record]
