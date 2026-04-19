from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.confidence import score_record_confidence
from app.services.config.extraction_rules import EXTRACTION_RULES
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extraction_context import (
    collect_js_state_objects,
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.field_value_utils import (
    PRICE_RE,
    RATING_RE,
    REVIEW_COUNT_RE,
    add_candidate,
    apply_selector_fallbacks,
    clean_text,
    coerce_field_value,
    collect_structured_candidates,
    extract_heading_sections,
    extract_page_images,
    finalize_candidate_value,
    finalize_record,
    record_score,
    surface_alias_lookup,
    surface_fields,
    text_or_none,
)
from app.services.js_state_mapper import map_js_state_to_fields
from app.services.network_payload_mapper import map_network_payloads_to_fields

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
    title = text_or_none(
        (h1.text(separator=" ", strip=True) if h1 else "")
        or (page_title.text(separator=" ", strip=True) if page_title else "")
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
    prior_lengths = {
        field_name: len(values) for field_name, values in candidates.items()
    }
    apply_selector_fallbacks(
        soup,
        page_url,
        surface,
        requested_fields,
        candidates,
        selector_rules=selector_rules,
    )
    for field_name in surface_fields(surface, requested_fields):
        growth = len(candidates.get(field_name, [])) - prior_lengths.get(field_name, 0)
        if growth > 0:
            candidate_sources.setdefault(field_name, []).extend(
                ["dom_selector"] * growth
            )
            field_sources.setdefault(field_name, [])
            if "dom_selector" not in field_sources[field_name]:
                field_sources[field_name].append("dom_selector")
    canonical = soup.find("link", attrs={"rel": re.compile("canonical", re.I)})
    if canonical is not None:
        from app.services.field_value_utils import absolute_url

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
    field_name: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
) -> list[tuple[str | None, object]]:
    values = list(candidates.get(field_name, []))
    sources = list(candidate_sources.get(field_name, []))
    indexed_entries = [
        (
            _SOURCE_PRIORITY_RANK.get(
                sources[index] if index < len(sources) else None,
                len(_SOURCE_PRIORITY_RANK),
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
            field_name,
            candidates,
            candidate_sources,
        )
        winning_values, selected_source = _winning_candidates_for_field(
            ordered_candidates,
        )
        finalized = finalize_candidate_value(
            field_name,
            winning_values,
        )
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
            if selected_source:
                selected_field_sources[field_name] = selected_source
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
    additional_images = text_or_none(record.get("additional_images"))
    if not primary_image or not additional_images:
        return
    filtered = [
        image
        for image in [part.strip() for part in additional_images.split(",")]
        if image and image != primary_image
    ]
    if filtered:
        record["additional_images"] = ", ".join(filtered)
        return
    record.pop("additional_images", None)


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
    dom_parser = context.dom_parser
    soup = context.soup
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    candidates: dict[str, list[object]] = {}
    candidate_sources: dict[str, list[str]] = {}
    field_sources: dict[str, list[str]] = {}
    fields = surface_fields(surface, requested_fields)
    selector_self_heal = _selector_self_heal_config(extraction_runtime_snapshot)
    completed_tiers: list[str] = []

    def _collect_authoritative_stage() -> None:
        for adapter_record in list(adapter_records or []):
            if isinstance(adapter_record, dict):
                _collect_record_candidates(
                    adapter_record,
                    page_url=page_url,
                    fields=fields,
                    candidates=candidates,
                    candidate_sources=candidate_sources,
                    field_sources=field_sources,
                    source="adapter",
                )
        for mapped_payload in map_network_payloads_to_fields(
            network_payloads,
            surface=surface,
            page_url=page_url,
        ):
            _collect_record_candidates(
                mapped_payload,
                page_url=page_url,
                fields=fields,
                candidates=candidates,
                candidate_sources=candidate_sources,
                field_sources=field_sources,
                source="network_payload",
            )

    def _collect_structured_stage() -> None:
        structured_sources = collect_structured_source_payloads(
            context,
            page_url=page_url,
        )
        for source_name, payloads in structured_sources:
            if source_name == "js_state":
                continue
            for payload in payloads:
                _collect_structured_payload_candidates(
                    payload,
                    alias_lookup=alias_lookup,
                    page_url=page_url,
                    candidates=candidates,
                    candidate_sources=candidate_sources,
                    field_sources=field_sources,
                    source=source_name,
                )

    def _collect_js_state_stage() -> None:
        mapped_js_fields = map_js_state_to_fields(
            collect_js_state_objects(context),
            surface=surface,
            page_url=page_url,
        )
        _collect_record_candidates(
            mapped_js_fields,
            page_url=page_url,
            fields=fields,
            candidates=candidates,
            candidate_sources=candidate_sources,
            field_sources=field_sources,
            source="js_state",
        )

    def _collect_dom_stage() -> None:
        _apply_dom_fallbacks(
            dom_parser,
            soup,
            page_url,
            surface,
            requested_fields,
            candidates,
            candidate_sources,
            field_sources,
            selector_rules=selector_rules,
        )

    record: dict[str, Any] = {}
    stage_collectors = (
        ("authoritative", _collect_authoritative_stage),
        ("structured_data", _collect_structured_stage),
        ("js_state", _collect_js_state_stage),
        ("dom", _collect_dom_stage),
    )
    for tier_name, collector in stage_collectors:
        collector()
        completed_tiers.append(tier_name)
        record = _materialize_record(
            page_url=page_url,
            surface=surface,
            requested_fields=requested_fields,
            fields=fields,
            candidates=candidates,
            candidate_sources=candidate_sources,
            field_sources=field_sources,
            extraction_runtime_snapshot=extraction_runtime_snapshot,
            tier_name=tier_name,
            completed_tiers=completed_tiers,
        )
        if tier_name != "structured_data":
            continue
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
