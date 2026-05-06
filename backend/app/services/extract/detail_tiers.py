from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.services.config.extraction_rules import (
    DETAIL_BREADCRUMB_JSONLD_TYPES,
    DETAIL_IRRELEVANT_JSON_LD_TYPES,
    DETAIL_SURFACE_KEYWORD,
    ECOMMERCE_DETAIL_SURFACE,
)


@dataclass(slots=True)
class DetailTierState:
    page_url: str
    requested_page_url: str | None
    surface: str
    requested_fields: list[str] | None
    fields: list[str]
    candidates: dict[str, list[object]]
    candidate_sources: dict[str, list[str]]
    field_sources: dict[str, list[str]]
    selector_trace_candidates: dict[str, list[dict[str, object]]]
    extraction_runtime_snapshot: dict[str, object] | None
    completed_tiers: list[str]


@dataclass(frozen=True, slots=True)
class DetailTierRuntime:
    materialize_record: Callable[..., dict[str, Any]]
    collect_record_candidates: Callable[..., None]
    map_network_payloads_to_fields: Callable[..., list[dict[str, Any]]]
    collect_structured_source_payloads: Callable[..., list[tuple[str, list[object]]]]
    collect_structured_payload_candidates: Callable[..., None]
    apply_dom_fallbacks: Callable[..., None]
    extract_variants_from_dom: Callable[..., dict[str, object]]
    should_collect_dom_variants: Callable[..., bool]
    add_sourced_candidate: Callable[..., None]
    coerce_float: Callable[..., float]
    requires_dom_completion: Callable[..., bool]
    promote_dom_detail_title: Callable[..., None]
    fill_missing_dom_detail_title: Callable[..., None]
    finalize_early_detail_record: Callable[..., dict[str, Any]]
    finalize_dom_detail_record: Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class DetailTierInputs:
    adapter_records: list[dict[str, Any]] | None
    network_payloads: list[dict[str, object]] | None
    alias_lookup: dict[str, str]
    selector_rules: list[dict[str, object]] | None
    html: str
    page_url: str
    surface: str
    requested_fields: list[str] | None


class PreparedDetailPage(Protocol):
    state: DetailTierState
    context: Any
    js_state_record: dict[str, Any]
    soup: Any
    raw_soup: Any
    js_state_objects: list[object]
    selector_self_heal: dict[str, object]


_NORMALIZED_DETAIL_BREADCRUMB_JSONLD_TYPES = frozenset(
    str(item).strip().lower()
    for item in tuple(DETAIL_BREADCRUMB_JSONLD_TYPES or ())
    if str(item).strip()
)
_NORMALIZED_DETAIL_IRRELEVANT_JSON_LD_TYPES = frozenset(
    str(value).strip().lower()
    for value in tuple(DETAIL_IRRELEVANT_JSON_LD_TYPES or ())
    if str(value).strip()
)


def _detail_json_ld_payload_is_irrelevant(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    raw_types = payload.get("@type")
    normalized_types = {
        str(item or "").strip().lower()
        for item in (raw_types if isinstance(raw_types, list) else [raw_types])
        if str(item or "").strip()
    }
    if normalized_types & _NORMALIZED_DETAIL_BREADCRUMB_JSONLD_TYPES:
        return False
    if not normalized_types:
        return False
    return normalized_types <= _NORMALIZED_DETAIL_IRRELEVANT_JSON_LD_TYPES


class DetailTierExecutor:
    def __init__(self, runtime: DetailTierRuntime) -> None:
        self._runtime = runtime

    def build_record(
        self,
        prepared: PreparedDetailPage,
        inputs: DetailTierInputs,
    ) -> dict[str, Any]:
        record = self._collect_pre_dom_tiers(prepared, inputs)
        if self._can_skip_dom_tier(record, prepared, inputs):
            if inputs.surface == ECOMMERCE_DETAIL_SURFACE:
                self._promote_dom_title(record, prepared, inputs.page_url)
            return self._runtime.finalize_early_detail_record(
                record,
                html=inputs.html,
                page_url=inputs.page_url,
                surface=inputs.surface,
                requested_fields=inputs.requested_fields,
                soup=prepared.soup,
                js_state_objects=prepared.js_state_objects,
            )

        record = self._build_dom_tier_record(prepared, inputs)
        return self._runtime.finalize_dom_detail_record(
            record,
            html=inputs.html,
            page_url=inputs.page_url,
            surface=inputs.surface,
            requested_fields=inputs.requested_fields,
            soup=prepared.soup,
            js_state_objects=prepared.js_state_objects,
        )

    def _collect_pre_dom_tiers(
        self,
        prepared: PreparedDetailPage,
        inputs: DetailTierInputs,
    ) -> dict[str, Any]:
        self._collect_authoritative_tier(
            prepared.state,
            adapter_records=inputs.adapter_records,
            network_payloads=inputs.network_payloads,
        )
        self._materialize(prepared.state, "authoritative")
        self._collect_structured_data_tier(
            prepared.state,
            context=prepared.context,
            alias_lookup=inputs.alias_lookup,
        )
        self._materialize(prepared.state, "structured_data")
        self._collect_js_state_tier(
            prepared.state,
            js_state_record=prepared.js_state_record,
        )
        return self._materialize(prepared.state, "js_state")

    def _collect_authoritative_tier(
        self,
        state: DetailTierState,
        *,
        adapter_records: list[dict[str, Any]] | None,
        network_payloads: list[dict[str, object]] | None,
    ) -> None:
        for adapter_record in list(adapter_records or []):
            if isinstance(adapter_record, dict):
                self._runtime.collect_record_candidates(
                    adapter_record,
                    page_url=state.page_url,
                    fields=state.fields,
                    candidates=state.candidates,
                    candidate_sources=state.candidate_sources,
                    field_sources=state.field_sources,
                    selector_trace_candidates=state.selector_trace_candidates,
                    source="adapter",
                )
        for mapped_payload in self._runtime.map_network_payloads_to_fields(
            network_payloads,
            surface=state.surface,
            page_url=state.page_url,
            requested_fields=state.requested_fields,
        ):
            self._runtime.collect_record_candidates(
                mapped_payload,
                page_url=state.page_url,
                fields=state.fields,
                candidates=state.candidates,
                candidate_sources=state.candidate_sources,
                field_sources=state.field_sources,
                selector_trace_candidates=state.selector_trace_candidates,
                source="network_payload",
            )

    def _collect_structured_data_tier(
        self,
        state: DetailTierState,
        *,
        context,
        alias_lookup: dict[str, str],
    ) -> None:
        for source_name, payloads in self._runtime.collect_structured_source_payloads(
            context,
            page_url=state.page_url,
        ):
            if source_name == "js_state":
                continue
            for payload in payloads:
                if (
                    source_name == "json_ld"
                    and DETAIL_SURFACE_KEYWORD
                    in str(state.surface or "").strip().lower()
                    and _detail_json_ld_payload_is_irrelevant(payload)
                ):
                    continue
                self._runtime.collect_structured_payload_candidates(
                    payload,
                    alias_lookup=alias_lookup,
                    page_url=state.page_url,
                    requested_page_url=state.requested_page_url,
                    candidates=state.candidates,
                    candidate_sources=state.candidate_sources,
                    field_sources=state.field_sources,
                    selector_trace_candidates=state.selector_trace_candidates,
                    source=source_name,
                )

    def _collect_js_state_tier(
        self,
        state: DetailTierState,
        *,
        js_state_record: dict[str, Any],
    ) -> None:
        self._runtime.collect_record_candidates(
            js_state_record,
            page_url=state.page_url,
            fields=state.fields,
            candidates=state.candidates,
            candidate_sources=state.candidate_sources,
            field_sources=state.field_sources,
            selector_trace_candidates=state.selector_trace_candidates,
            source="js_state",
        )

    def _build_dom_tier_record(
        self,
        prepared: PreparedDetailPage,
        inputs: DetailTierInputs,
    ) -> dict[str, Any]:
        self._collect_dom_tier(
            prepared.state,
            prepared=prepared,
            soup=prepared.soup,
            selector_rules=inputs.selector_rules,
        )
        record = self._materialize(prepared.state, "dom")
        if inputs.surface == ECOMMERCE_DETAIL_SURFACE:
            self._promote_dom_title(record, prepared, inputs.page_url)
        return record

    def _collect_dom_tier(
        self,
        state: DetailTierState,
        *,
        prepared: PreparedDetailPage,
        soup,
        selector_rules: list[dict[str, object]] | None,
    ) -> None:
        self._runtime.apply_dom_fallbacks(
            prepared,
            selector_rules=selector_rules,
        )
        if state.surface == ECOMMERCE_DETAIL_SURFACE:
            dom_variants = self._runtime.extract_variants_from_dom(
                soup,
                page_url=state.page_url,
            )
        else:
            dom_variants = {}
        if (
            state.surface == ECOMMERCE_DETAIL_SURFACE
            and self._runtime.should_collect_dom_variants(
                state.candidates,
                dom_variants,
            )
        ):
            for field_name, value in dom_variants.items():
                self._runtime.add_sourced_candidate(
                    state.candidates,
                    state.candidate_sources,
                    state.field_sources,
                    state.selector_trace_candidates,
                    field_name,
                    value,
                    source="dom_selector",
                )

    def _can_skip_dom_tier(
        self,
        record: dict[str, Any],
        prepared: PreparedDetailPage,
        inputs: DetailTierInputs,
    ) -> bool:
        confidence_score = self._runtime.coerce_float(
            _object_dict(record.get("_confidence")).get("score")
        )
        threshold = self._runtime.coerce_float(
            prepared.selector_self_heal.get("threshold")
        )
        return (
            confidence_score >= threshold
            and not self._runtime.requires_dom_completion(
                record=record,
                surface=inputs.surface,
                requested_fields=inputs.requested_fields,
                selector_rules=inputs.selector_rules,
                soup=prepared.soup,
                breadcrumb_soup=prepared.raw_soup,
            )
        )

    def _materialize(
        self,
        state: DetailTierState,
        tier_name: str,
    ) -> dict[str, Any]:
        # DetailTierState is intentionally mutable; _materialize updates state.completed_tiers in-place.
        state.completed_tiers.append(tier_name)
        return self._runtime.materialize_record(
            page_url=state.page_url,
            requested_page_url=state.requested_page_url,
            surface=state.surface,
            requested_fields=state.requested_fields,
            fields=state.fields,
            candidates=state.candidates,
            candidate_sources=state.candidate_sources,
            field_sources=state.field_sources,
            selector_trace_candidates=state.selector_trace_candidates,
            extraction_runtime_snapshot=state.extraction_runtime_snapshot,
            tier_name=tier_name,
            completed_tiers=state.completed_tiers,
        )

    def _promote_dom_title(
        self,
        record: dict[str, Any],
        prepared,
        page_url: str,
    ) -> None:
        self._runtime.promote_dom_detail_title(
            record,
            js_state_record=prepared.js_state_record,
            page_url=page_url,
        )
        self._runtime.fill_missing_dom_detail_title(record, page_url=page_url)


def _object_dict(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}
