from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.confidence import score_record_confidence
from app.services.config.extraction_rules import NOISE_CONTAINER_REMOVAL_SELECTOR
from app.services.field_value_utils import (
    PERCENT_RE,
    PRICE_RE,
    RATING_RE,
    REVIEW_COUNT_RE,
    add_candidate,
    apply_selector_fallbacks,
    clean_text,
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
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.structured_sources import (
    harvest_js_state_objects,
    parse_microdata,
    parse_opengraph,
    parse_embedded_json,
    parse_json_ld,
)
from app.services.field_value_utils import collect_structured_candidates, coerce_field_value


def _prepare_detail_dom(html: str) -> tuple[LexborHTMLParser, str]:
    parser = LexborHTMLParser(html)
import logging

logger = logging.getLogger(__name__)

def _prepare_detail_dom(html: str) -> tuple[LexborHTMLParser, str]:
    parser = LexborHTMLParser(html)
    try:
        for node in parser.css(NOISE_CONTAINER_REMOVAL_SELECTOR):
            node.decompose()
    except Exception as exc:
        logger.debug("noise_removal_failed selector=%s error=%s", NOISE_CONTAINER_REMOVAL_SELECTOR, exc)
    return parser, parser.html
    return parser, parser.html


def _apply_dom_fallbacks(
    dom_parser: LexborHTMLParser,
    soup: BeautifulSoup,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    candidates: dict[str, list[object]],
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
            field_sources,
            "title",
            title,
            source="dom_h1",
        )
    prior_lengths = {field_name: len(values) for field_name, values in candidates.items()}
    apply_selector_fallbacks(
        soup,
        page_url,
        surface,
        requested_fields,
        candidates,
        selector_rules=selector_rules,
    )
    for field_name in surface_fields(surface, requested_fields):
        if len(candidates.get(field_name, [])) > prior_lengths.get(field_name, 0):
            field_sources.setdefault(field_name, [])
            if "dom_selector" not in field_sources[field_name]:
                field_sources[field_name].append("dom_selector")
    canonical = soup.find("link", attrs={"rel": re.compile("canonical", re.I)})
    if canonical is not None:
        from app.services.field_value_utils import absolute_url

        _add_sourced_candidate(
            candidates,
            field_sources,
            "url",
            absolute_url(page_url, canonical.get("href")),
            source="dom_canonical",
        )
    images = extract_page_images(soup, page_url)
    if images:
        _add_sourced_candidate(
            candidates,
            field_sources,
            "image_url",
            images[0],
            source="dom_images",
        )
        _add_sourced_candidate(
            candidates,
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
                field_sources,
                normalized,
                coerce_field_value(normalized, value, page_url),
                source="dom_sections",
            )
    body_node = dom_parser.body
    body_text = clean_text(body_node.text(separator=" ", strip=True)) if body_node else ""
    if "price" in fields and not candidates.get("price"):
        price_match = PRICE_RE.search(body_text)
        if price_match:
            _add_sourced_candidate(
                candidates,
                field_sources,
                "price",
                price_match.group(0),
                source="dom_text",
            )
    if "discount_percentage" in fields and not candidates.get("discount_percentage"):
        percent_match = PERCENT_RE.search(body_text)
        if percent_match:
            _add_sourced_candidate(
                candidates,
                field_sources,
                "discount_percentage",
                percent_match.group(0),
                source="dom_text",
            )
    if "review_count" in fields and not candidates.get("review_count"):
        review_match = REVIEW_COUNT_RE.search(body_text)
        if review_match:
            _add_sourced_candidate(
                candidates,
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
                field_sources,
                "rating",
                rating_match.group(1),
                source="dom_text",
            )
    if surface.startswith("job_") and "remote" in fields and not candidates.get("remote"):
        lowered = body_text.lower()
        if "remote" in lowered or "work from home" in lowered:
            _add_sourced_candidate(
                candidates,
                field_sources,
                "remote",
                "remote",
                source="dom_text",
            )


def _add_sourced_candidate(
    candidates: dict[str, list[object]],
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
    bucket = field_sources.setdefault(field_name, [])
    if source not in bucket:
        bucket.append(source)


def _collect_record_candidates(
    record: dict[str, Any],
    *,
    page_url: str,
    fields: list[str],
    candidates: dict[str, list[object]],
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
    field_sources: dict[str, list[str]],
    source: str,
) -> None:
    structured_candidates: dict[str, list[object]] = {}
    collect_structured_candidates(payload, alias_lookup, page_url, structured_candidates)
    for field_name, values in structured_candidates.items():
        for value in values:
            _add_sourced_candidate(
                candidates,
                field_sources,
                field_name,
                value,
                source=source,
            )


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
    dom_parser, cleaned_html = _prepare_detail_dom(html)
    soup = BeautifulSoup(cleaned_html, "html.parser")
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    candidates: dict[str, list[object]] = {}
    field_sources: dict[str, list[str]] = {}
    fields = surface_fields(surface, requested_fields)

    for adapter_record in list(adapter_records or []):
        if isinstance(adapter_record, dict):
            _collect_record_candidates(
                adapter_record,
                page_url=page_url,
                fields=fields,
                candidates=candidates,
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
            field_sources=field_sources,
            source="network_payload",
        )

    js_state_objects = harvest_js_state_objects(soup, html)
    mapped_js_fields = map_js_state_to_fields(
        js_state_objects,
        surface=surface,
        page_url=page_url,
    )
    _collect_record_candidates(
        mapped_js_fields,
        page_url=page_url,
        fields=fields,
        candidates=candidates,
        field_sources=field_sources,
        source="js_state",
    )

    for payload in parse_json_ld(soup):
        _collect_structured_payload_candidates(
            payload,
            alias_lookup=alias_lookup,
            page_url=page_url,
            candidates=candidates,
            field_sources=field_sources,
            source="json_ld",
        )
    for payload in parse_microdata(soup, html, page_url):
        _collect_structured_payload_candidates(
            payload,
            alias_lookup=alias_lookup,
            page_url=page_url,
            candidates=candidates,
            field_sources=field_sources,
            source="microdata",
        )
    for payload in parse_opengraph(soup, html, page_url):
        _collect_structured_payload_candidates(
            payload,
            alias_lookup=alias_lookup,
            page_url=page_url,
            candidates=candidates,
            field_sources=field_sources,
            source="opengraph",
        )
    for payload in parse_embedded_json(soup, html):
        _collect_structured_payload_candidates(
            payload,
            alias_lookup=alias_lookup,
            page_url=page_url,
            candidates=candidates,
            field_sources=field_sources,
            source="embedded_json",
        )
    _apply_dom_fallbacks(
        dom_parser,
        soup,
        page_url,
        surface,
        requested_fields,
        candidates,
        field_sources,
        selector_rules=selector_rules,
    )
    record: dict[str, Any] = {
        "source_url": page_url,
        "url": page_url,
        "_source": next(
            (
                source
                for source_name in (
                    "adapter",
                    "network_payload",
                    "js_state",
                    "json_ld",
                    "microdata",
                    "opengraph",
                    "embedded_json",
                    "dom_h1",
                    "dom_selector",
                    "dom_sections",
                    "dom_text",
                )
                for field_name, source_list in field_sources.items()
                if field_name in candidates and source_name in source_list
                for source in [source_name]
            ),
            "structured_dom",
        ),
    }
    for field_name in fields:
        finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
    record["_field_sources"] = {
        field_name: list(source_list)
        for field_name, source_list in field_sources.items()
        if field_name in record
    }
    primary_image = text_or_none(record.get("image_url"))
    additional_images = text_or_none(record.get("additional_images"))
    if primary_image and additional_images:
        filtered = [
            image
            for image in [part.strip() for part in additional_images.split(",")]
            if image and image != primary_image
        ]
        if filtered:
            record["additional_images"] = ", ".join(filtered)
        else:
            record.pop("additional_images", None)
    confidence = score_record_confidence(
        record,
        surface=surface,
        requested_fields=requested_fields,
    )
    record["_confidence"] = confidence
    selector_self_heal = (
        extraction_runtime_snapshot.get("selector_self_heal")
        if isinstance(extraction_runtime_snapshot, dict)
        else None
    )
    record["_self_heal"] = {
        "enabled": bool(
            selector_self_heal.get("enabled")
            if isinstance(selector_self_heal, dict)
            else crawler_runtime_settings.selector_self_heal_enabled
        ),
        "triggered": False,
        "threshold": float(
            selector_self_heal.get("min_confidence")
            if isinstance(selector_self_heal, dict)
            and selector_self_heal.get("min_confidence") is not None
            else crawler_runtime_settings.selector_self_heal_min_confidence
        ),
    }
    return finalize_record(record, surface=surface)


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
