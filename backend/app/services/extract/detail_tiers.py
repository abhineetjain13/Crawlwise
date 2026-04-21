from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DetailTierState:
    page_url: str
    surface: str
    requested_fields: list[str] | None
    fields: list[str]
    candidates: dict[str, list[object]]
    candidate_sources: dict[str, list[str]]
    field_sources: dict[str, list[str]]
    extraction_runtime_snapshot: dict[str, object] | None
    completed_tiers: list[str]


def materialize_detail_tier(
    state: DetailTierState,
    *,
    tier_name: str,
    materialize_record,
) -> dict[str, Any]:
    state.completed_tiers.append(tier_name)
    return materialize_record(
        page_url=state.page_url,
        surface=state.surface,
        requested_fields=state.requested_fields,
        fields=state.fields,
        candidates=state.candidates,
        candidate_sources=state.candidate_sources,
        field_sources=state.field_sources,
        extraction_runtime_snapshot=state.extraction_runtime_snapshot,
        tier_name=tier_name,
        completed_tiers=state.completed_tiers,
    )


def collect_authoritative_tier(
    state: DetailTierState,
    *,
    adapter_records: list[dict[str, Any]] | None,
    network_payloads: list[dict[str, object]] | None,
    collect_record_candidates,
    map_network_payloads_to_fields,
) -> None:
    for adapter_record in list(adapter_records or []):
        if isinstance(adapter_record, dict):
            collect_record_candidates(
                adapter_record,
                page_url=state.page_url,
                fields=state.fields,
                candidates=state.candidates,
                candidate_sources=state.candidate_sources,
                field_sources=state.field_sources,
                source="adapter",
            )
    for mapped_payload in map_network_payloads_to_fields(
        network_payloads,
        surface=state.surface,
        page_url=state.page_url,
    ):
        collect_record_candidates(
            mapped_payload,
            page_url=state.page_url,
            fields=state.fields,
            candidates=state.candidates,
            candidate_sources=state.candidate_sources,
            field_sources=state.field_sources,
            source="network_payload",
        )


def collect_structured_data_tier(
    state: DetailTierState,
    *,
    context,
    alias_lookup: dict[str, str],
    collect_structured_source_payloads,
    collect_structured_payload_candidates,
) -> None:
    for source_name, payloads in collect_structured_source_payloads(
        context,
        page_url=state.page_url,
    ):
        if source_name == "js_state":
            continue
        for payload in payloads:
            collect_structured_payload_candidates(
                payload,
                alias_lookup=alias_lookup,
                page_url=state.page_url,
                candidates=state.candidates,
                candidate_sources=state.candidate_sources,
                field_sources=state.field_sources,
                source=source_name,
            )


def collect_js_state_tier(
    state: DetailTierState,
    *,
    js_state_record: dict[str, Any],
    collect_record_candidates,
) -> None:
    collect_record_candidates(
        js_state_record,
        page_url=state.page_url,
        fields=state.fields,
        candidates=state.candidates,
        candidate_sources=state.candidate_sources,
        field_sources=state.field_sources,
        source="js_state",
    )


def collect_dom_tier(
    state: DetailTierState,
    *,
    dom_parser,
    soup,
    selector_rules: list[dict[str, object]] | None,
    apply_dom_fallbacks,
    extract_variants_from_dom,
    should_collect_dom_variants,
    add_sourced_candidate,
) -> None:
    apply_dom_fallbacks(
        dom_parser,
        soup,
        state.page_url,
        state.surface,
        state.requested_fields,
        state.candidates,
        state.candidate_sources,
        state.field_sources,
        selector_rules=selector_rules,
    )
    if state.surface == "ecommerce_detail" and should_collect_dom_variants(state.candidates):
        for field_name, value in extract_variants_from_dom(soup).items():
            add_sourced_candidate(
                state.candidates,
                state.candidate_sources,
                state.field_sources,
                field_name,
                value,
                source="dom_selector",
            )
