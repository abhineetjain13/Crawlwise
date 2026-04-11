# Candidate extraction service — orchestration layer only.
from __future__ import annotations

import logging
from typing import Any

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    CANDIDATE_PLACEHOLDER_VALUES,
)
from app.services.config.field_mappings import (
    CANONICAL_SCHEMAS,
    ECOMMERCE_ONLY_FIELDS,
    JOB_ONLY_FIELDS,
    REQUESTED_FIELD_ALIASES,
)
from app.services.exceptions import ExtractionError, ExtractionParseError
from app.services.extract.candidate_processing import (
    _embedded_blob_metadata,
    _normalized_candidate_text,
    candidate_source_rank,  # noqa: F401 — re-exported for __init__
    coerce_field_candidate_value,  # noqa: F401 — re-exported for callers
    finalize_candidate_rows as _finalize_candidate_rows,
)
from app.services.extract.detail_extractor import (
    _build_dynamic_semantic_rows,
    _build_dynamic_structured_rows,
    _build_platform_detail_rows,
    _build_product_detail_rows,
)
from app.services.extract.dom_extraction import (
    _append_source_candidates,
    _build_label_value_text_sources,
    _dom_pattern,
    _extract_breadcrumb_category,
    extract_label_value_from_text as _extract_label_value_from_text,
    _scope_adapter_records_for_url,
    _scoped_semantic_payload,
)
from app.services.extract.extraction_helpers import (
    _build_xpath_tree,
    _domain,
    _extract_image_urls,  # noqa: F401 — re-exported for detail_extractor deferred import
    _extract_regex_value,
    _extract_xpath_value,
    _index_extraction_contract,
)
from app.services.extract.field_classifier import (
    _dynamic_field_name_is_schema_slug_noise,  # noqa: F401 — re-exported for callers
    _dynamic_field_name_is_valid,
    _dynamic_value_is_bare_ticker_symbol,
    _should_skip_jsonld_block,
)
from app.services.extract.field_type_classifier import (
    _field_is_type,  # noqa: F401 — re-exported for dom_extraction deferred import
)
from app.services.extract.semantic_support import (
    extract_semantic_detail_data,
    resolve_requested_field_values,
)
from app.services.extract.signal_inventory import (
    build_signal_inventory,
    classify_page_type,
)
from app.services.extract.source_parsers import parse_page_sources
from app.services.extract.variant_builder import (
    _NETWORK_PAYLOAD_NOISE_URL_PATTERNS,  # noqa: F401 — re-exported for dom_extraction deferred import
    _build_variant_rows,
    _payload_matches_page_scope,
    _structured_source_candidates,
    _structured_source_payloads,
)
from app.services.extract.variant_extractor import (
    _reconcile_variant_bundle,
    _sanitize_product_attributes,
    _sync_selected_variant_root_fields,
)
from app.services.requested_field_policy import expand_requested_fields
from app.services.xpath_service import extract_selector_value

logger = logging.getLogger(__name__)
_SOURCE_COLLECTION_TIERS: dict[str, tuple[str, ...]] = {
    "contract": ("contract_xpath", "contract_regex"),
    "adapter": ("adapter",),
    "json_ld": ("json_ld",),
    "datalayer": ("datalayer",),
    "network_intercept": ("network_intercept",),
    "structured_state": (
        "next_data",
        "hydrated_state",
        "embedded_json",
        "network_intercept",
    ),
    "dom_meta": ("selector", "dom", "microdata", "open_graph", "dom_breadcrumb"),
    "semantic_section": ("semantic_section",),
    "text_pattern": ("text_pattern",),
}


def _preview_audit_value(value: object, *, limit: int = 80) -> str:
    text = " ".join(str(value).split()).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _record_audit_source_attempt(
    extraction_audit: dict[str, dict[str, object]],
    *,
    field_name: str,
    source_label: str,
    rows: list[dict],
    start_index: int,
) -> None:
    field_audit = extraction_audit.setdefault(field_name, {"sources": []})
    new_rows = [
        row for row in rows[start_index:] if isinstance(row, dict)
    ]
    entry = {
        "source": source_label,
        "status": "produced_candidates" if new_rows else "empty",
        "candidate_count": len(new_rows),
        "row_sources": [
            str(row.get("source") or source_label)
            for row in new_rows
            if str(row.get("source") or source_label).strip()
        ],
        "value_previews": [
            _preview_audit_value(row.get("value"))
            for row in new_rows[-3:]
            if row.get("value") not in (None, "", [], {})
        ],
    }
    field_audit.setdefault("sources", []).append(entry)
    logger.debug(
        "[EXTRACT] field=%s source=%s candidates=%d values=%s",
        field_name,
        source_label,
        len(new_rows),
        entry["value_previews"],
    )


def _record_audit_source_skipped(
    extraction_audit: dict[str, dict[str, object]],
    *,
    field_name: str,
    source_label: str,
    reason: str,
) -> None:
    field_audit = extraction_audit.setdefault(field_name, {"sources": []})
    field_audit.setdefault("sources", []).append(
        {
            "source": source_label,
            "status": "skipped",
            "reason": reason,
            "candidate_count": 0,
            "row_sources": [],
            "value_previews": [],
        }
    )


def _record_field_decision_audit(
    extraction_audit: dict[str, dict[str, object]],
    *,
    field_name: str,
    decision,
    total_rows: int,
) -> None:
    field_audit = extraction_audit.setdefault(field_name, {"sources": []})
    field_audit["candidate_count"] = total_rows
    field_audit["rejected"] = list(decision.rejected_rows)

    if not decision.accepted or decision.winning_row is None:
        field_audit["status"] = "rejected"
        field_audit["winner"] = None
        if decision.rejection_reason:
            field_audit["decision_reason"] = decision.rejection_reason
        return

    losing_rows: list[dict[str, object]] = []
    for row in decision.accepted_rows:
        if row is decision.winning_row:
            continue
        losing_rank = candidate_source_rank(field_name, row.get("source"))
        reason = (
            "lower_source_rank"
            if losing_rank < decision.rank
            else "tie_lost_to_earlier_candidate"
        )
        losing_rows.append(
            {
                "source": row.get("source"),
                "value_preview": _preview_audit_value(row.get("value")),
                "reason": reason,
                "rank": losing_rank,
            }
        )

    field_audit["status"] = "accepted"
    field_audit["winner"] = {
        "source": decision.source,
        "value_preview": _preview_audit_value(decision.value),
        "rank": decision.rank,
        "losing_candidate_count": len(losing_rows),
        "rejected_candidate_count": len(decision.rejected_rows),
    }
    field_audit["losers"] = losing_rows
    logger.info(
        "[EXTRACT] field=%s winner_source=%s value_preview=%s rejected=%d",
        field_name,
        decision.source,
        _preview_audit_value(decision.value),
        max(total_rows - 1, 0),
    )


def _record_final_output_audit(
    extraction_audit: dict[str, dict[str, object]],
    final_candidates: dict[str, list[dict]],
) -> None:
    for field_name, rows in final_candidates.items():
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            continue
        row = rows[0]
        field_audit = extraction_audit.setdefault(field_name, {"sources": []})
        field_audit["final_output"] = {
            "source": row.get("source"),
            "value_preview": _preview_audit_value(row.get("value")),
        }


def get_canonical_fields(surface: str) -> list[str]:
    return list(CANONICAL_SCHEMAS.get(str(surface or "").strip(), []))


def get_domain_mapping(_domain: str, _surface: str) -> dict[str, str]:
    return {}


def get_selector_defaults(_domain: str, _field_name: str) -> list[dict]:
    return []


def extract_candidates(
    url: str,
    surface: str,
    html: str,
    xhr_payloads: list[dict],
    additional_fields: list[str],
    extraction_contract: list[dict] | None = None,
    resolved_fields: list[str] | None = None,
    adapter_records: list[dict] | None = None,
    soup: "BeautifulSoup | None" = None,
) -> tuple[dict, dict]:
    """Extract candidate values for each target field.

    Sources are checked in deterministic priority order and every discovered
    value is preserved as its own candidate row.

    Args:
        soup: Optional pre-parsed BeautifulSoup object — avoids redundant
              CPU-heavy DOM parsing when the caller already has one.

    Returns:
        (candidates, source_trace) — candidates maps field -> list of {value, source}
    """
    try:
        if soup is None:
            soup = BeautifulSoup(html, "html.parser")
        page_sources = parse_page_sources(html, soup=soup)
        signal_inventory = build_signal_inventory(
            html,
            url,
            surface,
            soup=soup,
            page_sources=page_sources,
        )
        page_type = classify_page_type(signal_inventory)

        if "listing" in str(surface or "").lower():
            return {}, {
                "candidates": {},
                "extraction_audit": {},
                "mapping_hint": {},
                "semantic": {},
                "surface_gate": "listing",
                "page_type": page_type,
            }

        tree = _build_xpath_tree(html)
        adapter_records = _scope_adapter_records_for_url(url, adapter_records or [])
        network_payloads = xhr_payloads or []

        base_target_fields = set(resolved_fields or get_canonical_fields(surface))
        if str(surface or "").strip().lower() in {"job_listing", "job_detail"}:
            base_target_fields = set(get_canonical_fields(surface))
        target_fields = sorted(
            base_target_fields | set(expand_requested_fields(additional_fields))
        )

        contract_by_field = _index_extraction_contract(extraction_contract or [])
        semantic = extract_semantic_detail_data(
            html,
            requested_fields=sorted(target_fields),
            soup=soup,
            page_url=url,
            adapter_records=adapter_records,
        )
        semantic = _scoped_semantic_payload(
            semantic, url=url, adapter_records=adapter_records
        )
        label_value_text_sources = _build_label_value_text_sources(
            url=url,
            soup=soup,
            adapter_records=adapter_records,
            network_payloads=network_payloads,
            next_data=page_sources.get("next_data"),
            hydrated_states=page_sources.get("hydrated_states") or [],
            embedded_json=page_sources.get("embedded_json") or [],
            open_graph=page_sources.get("open_graph") or {},
            json_ld=page_sources.get("json_ld") or [],
            microdata=page_sources.get("microdata") or [],
        )

        canonical_target_fields = set(get_canonical_fields(surface))
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionParseError(
            f"Failed to parse extracted content for {url}"
        ) from exc

    # Step 1: Collect all candidates from all sources
    candidates, extraction_audit = _collect_candidates(
        url=url,
        surface=surface,
        html=html,
        soup=soup,
        tree=tree,
        page_sources=page_sources,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        target_fields=target_fields,
        canonical_target_fields=canonical_target_fields,
        contract_by_field=contract_by_field,
        semantic=semantic,
        label_value_text_sources=label_value_text_sources,
    )

    # Step 2: Filter candidates (remove placeholders, validate)
    candidates = _filter_candidates(candidates, base_url=url)

    # Step 3: Finalize candidates (deduplicate, add dynamic fields)
    return _finalize_candidates(
        candidates=candidates,
        extraction_audit=extraction_audit,
        surface=surface,
        url=url,
        semantic=semantic,
        target_fields=set(target_fields),
        canonical_target_fields=canonical_target_fields,
        next_data=page_sources.get("next_data"),
        hydrated_states=page_sources.get("hydrated_states") or [],
        embedded_json=page_sources.get("embedded_json") or [],
        network_payloads=network_payloads,
        soup=soup,
        adapter_records=adapter_records,
    )



def _collect_candidates(
    url: str,
    surface: str,
    html: str,
    soup: BeautifulSoup,
    tree,
    page_sources: dict,
    adapter_records: list[dict],
    network_payloads: list[dict],
    target_fields: list[str],
    canonical_target_fields: set[str],
    contract_by_field: dict,
    semantic: dict,
    label_value_text_sources: dict,
) -> tuple[dict[str, list[dict]], dict[str, dict[str, object]]]:
    """Gather candidate values using a Strategy iteration pattern (first-match wins).

    Implements extraction hierarchy with first-match wins:
    1. Extraction contract (XPath/Regex)
    2. Platform adapter
    3. dataLayer
    4. Network intercept
    5. JSON-LD
    6. Embedded JSON (Next.js, hydrated states)
    7. DOM selectors
    8. Semantic extraction
    9. Text patterns

    Returns: {field_name: [candidate_rows]}
    """
    candidates: dict[str, list[dict]] = {}
    extraction_audit: dict[str, dict[str, object]] = {}
    domain = _domain(url)

    # Extract all page sources
    next_data = page_sources.get("next_data")
    hydrated_states = page_sources.get("hydrated_states") or []
    embedded_json = page_sources.get("embedded_json") or []
    open_graph = page_sources.get("open_graph") or {}
    json_ld = page_sources.get("json_ld") or []
    microdata = page_sources.get("microdata") or []
    datalayer = page_sources.get("datalayer") or {}

    semantic_sections = (
        semantic.get("sections") if isinstance(semantic.get("sections"), dict) else {}
    )
    semantic_specifications = (
        semantic.get("specifications")
        if isinstance(semantic.get("specifications"), dict)
        else {}
    )
    semantic_promoted = (
        semantic.get("promoted_fields")
        if isinstance(semantic.get("promoted_fields"), dict)
        else {}
    )
    from app.services.extract.field_decision import FieldDecisionEngine

    engine = FieldDecisionEngine(base_url=url)

    for field_name in target_fields:
        rows: list[dict] = []
        short_circuited = False

        # Contract rows are terminal when they already beat every remaining tier.
        start_index = len(rows)
        _collect_contract_candidates(
            rows,
            field_name=field_name,
            tree=tree,
            html=html,
            contract_by_field=contract_by_field,
        )
        _record_audit_source_attempt(
            extraction_audit,
            field_name=field_name,
            source_label="contract",
            rows=rows,
            start_index=start_index,
        )
        if _collection_is_decisive(
            field_name,
            rows,
            engine=engine,
            remaining_tiers=(
                "adapter",
                "json_ld",
                "datalayer",
                "network_intercept",
                "structured_state",
                "dom_meta",
                "semantic_section",
                "text_pattern",
            ),
        ):
            _record_remaining_source_skips(
                extraction_audit,
                field_name=field_name,
                source_labels=(
                    "adapter",
                    "json_ld",
                    "datalayer",
                    "network_intercept",
                    "structured_state",
                    "dom_meta",
                    "semantic_section",
                    "text_pattern",
                ),
            )
            short_circuited = True

        if short_circuited:
            if rows:
                candidates[field_name] = rows
            continue

        start_index = len(rows)
        _collect_adapter_candidates(
            rows, field_name=field_name, adapter_records=adapter_records
        )
        _record_audit_source_attempt(
            extraction_audit,
            field_name=field_name,
            source_label="adapter",
            rows=rows,
            start_index=start_index,
        )
        if _collection_is_decisive(
            field_name,
            rows,
            engine=engine,
            remaining_tiers=(
                "json_ld",
                "datalayer",
                "network_intercept",
                "structured_state",
                "dom_meta",
                "semantic_section",
                "text_pattern",
            ),
        ):
            _record_remaining_source_skips(
                extraction_audit,
                field_name=field_name,
                source_labels=(
                    "json_ld",
                    "datalayer",
                    "network_intercept",
                    "structured_state",
                    "dom_meta",
                    "semantic_section",
                    "text_pattern",
                ),
            )
            short_circuited = True

        if short_circuited:
            if rows:
                candidates[field_name] = rows
            continue

        start_index = len(rows)
        _collect_jsonld_candidates(
            rows,
            field_name=field_name,
            json_ld=json_ld,
            base_url=url,
            surface=surface,
        )
        _record_audit_source_attempt(
            extraction_audit,
            field_name=field_name,
            source_label="json_ld",
            rows=rows,
            start_index=start_index,
        )
        if _collection_is_decisive(
            field_name,
            rows,
            engine=engine,
            remaining_tiers=(
                "datalayer",
                "network_intercept",
                "structured_state",
                "dom_meta",
                "semantic_section",
                "text_pattern",
            ),
        ):
            _record_remaining_source_skips(
                extraction_audit,
                field_name=field_name,
                source_labels=(
                    "datalayer",
                    "network_intercept",
                    "structured_state",
                    "dom_meta",
                    "semantic_section",
                    "text_pattern",
                ),
            )
            short_circuited = True

        if short_circuited:
            if rows:
                candidates[field_name] = rows
            continue

        start_index = len(rows)
        _collect_datalayer_candidates(rows, field_name=field_name, datalayer=datalayer)
        _record_audit_source_attempt(
            extraction_audit,
            field_name=field_name,
            source_label="datalayer",
            rows=rows,
            start_index=start_index,
        )
        if _collection_is_decisive(
            field_name,
            rows,
            engine=engine,
            remaining_tiers=(
                "network_intercept",
                "structured_state",
                "dom_meta",
                "semantic_section",
                "text_pattern",
            ),
        ):
            _record_remaining_source_skips(
                extraction_audit,
                field_name=field_name,
                source_labels=(
                    "network_intercept",
                    "structured_state",
                    "dom_meta",
                    "semantic_section",
                    "text_pattern",
                ),
            )
            short_circuited = True

        if short_circuited:
            if rows:
                candidates[field_name] = rows
            continue

        start_index = len(rows)
        _collect_network_payload_candidates(
            rows,
            field_name=field_name,
            network_payloads=network_payloads,
            base_url=url,
            surface=surface,
        )
        _record_audit_source_attempt(
            extraction_audit,
            field_name=field_name,
            source_label="network_intercept",
            rows=rows,
            start_index=start_index,
        )
        if _collection_is_decisive(
            field_name,
            rows,
            engine=engine,
            remaining_tiers=(
                "structured_state",
                "dom_meta",
                "semantic_section",
                "text_pattern",
            ),
        ):
            _record_remaining_source_skips(
                extraction_audit,
                field_name=field_name,
                source_labels=(
                    "structured_state",
                    "dom_meta",
                    "semantic_section",
                    "text_pattern",
                ),
            )
            short_circuited = True

        if short_circuited:
            if rows:
                candidates[field_name] = rows
            continue

        start_index = len(rows)
        _collect_structured_state_candidates(
            rows,
            field_name=field_name,
            next_data=next_data,
            hydrated_states=hydrated_states,
            embedded_json=embedded_json,
            network_payloads=network_payloads,
            base_url=url,
            surface=surface,
        )
        _record_audit_source_attempt(
            extraction_audit,
            field_name=field_name,
            source_label="structured_state",
            rows=rows,
            start_index=start_index,
        )
        if _collection_is_decisive(
            field_name,
            rows,
            engine=engine,
            remaining_tiers=("dom_meta", "semantic_section", "text_pattern"),
        ):
            _record_remaining_source_skips(
                extraction_audit,
                field_name=field_name,
                source_labels=("dom_meta", "semantic_section", "text_pattern"),
            )
            short_circuited = True

        if not short_circuited:
            # 7. DOM selectors
            start_index = len(rows)
            _collect_dom_and_meta_candidates(
                rows,
                field_name=field_name,
                html=html,
                soup=soup,
                domain=domain,
                microdata=microdata,
                open_graph=open_graph,
                base_url=url,
                surface=surface,
            )
            _record_audit_source_attempt(
                extraction_audit,
                field_name=field_name,
                source_label="dom_meta",
                rows=rows,
                start_index=start_index,
            )

            # 8. Semantic extraction
            if _is_semantic_requested_field(field_name, canonical_target_fields):
                start_index = len(rows)
                semantic_rows = resolve_requested_field_values(
                    [field_name],
                    sections=semantic_sections,
                    specifications=semantic_specifications,
                    promoted_fields=semantic_promoted,
                )
                semantic_value = semantic_rows.get(field_name)
                if semantic_value not in (None, "", [], {}):
                    rows.append(
                        {"value": semantic_value, "source": "semantic_section"}
                    )
                _record_audit_source_attempt(
                    extraction_audit,
                    field_name=field_name,
                    source_label="semantic_section",
                    rows=rows,
                    start_index=start_index,
                )

            # 9. Text patterns
            if _is_semantic_requested_field(field_name, canonical_target_fields):
                start_index = len(rows)
                text_value = _extract_label_value_from_text(
                    field_name, label_value_text_sources, html, surface=surface
                )
                if text_value:
                    rows.append({"value": text_value, "source": "text_pattern"})
                _record_audit_source_attempt(
                    extraction_audit,
                    field_name=field_name,
                    source_label="text_pattern",
                    rows=rows,
                    start_index=start_index,
                )

        if rows:
            candidates[field_name] = rows

    return candidates, extraction_audit


def _is_semantic_requested_field(
    field_name: str,
    canonical_target_fields: set[str],
) -> bool:
    return (
        field_name in canonical_target_fields or field_name in REQUESTED_FIELD_ALIASES
    )


def _collection_is_decisive(
    field_name: str,
    rows: list[dict],
    *,
    engine,
    remaining_tiers: tuple[str, ...],
) -> bool:
    if not rows:
        return False
    decision = engine.decide_from_rows(field_name, rows)
    if not decision.accepted:
        return False
    remaining_best_rank = _max_remaining_source_rank(field_name, remaining_tiers)
    return decision.rank >= remaining_best_rank


def _max_remaining_source_rank(
    field_name: str,
    source_labels: tuple[str, ...],
) -> int:
    best_rank = 0
    for source_label in source_labels:
        for candidate_source in _SOURCE_COLLECTION_TIERS.get(source_label, (source_label,)):
            best_rank = max(
                best_rank,
                candidate_source_rank(field_name, candidate_source),
            )
    return best_rank


def _record_remaining_source_skips(
    extraction_audit: dict[str, dict[str, object]],
    *,
    field_name: str,
    source_labels: tuple[str, ...],
) -> None:
    for source_label in source_labels:
        _record_audit_source_skipped(
            extraction_audit,
            field_name=field_name,
            source_label=source_label,
            reason="decisive_higher_rank_candidate",
        )


def _collect_contract_candidates(
    rows: list[dict],
    *,
    field_name: str,
    tree,
    html: str,
    contract_by_field: dict,
) -> bool:
    contract_rule = contract_by_field.get(field_name)
    if not contract_rule:
        return False
    xpath_value = _extract_xpath_value(tree, contract_rule.get("xpath", ""))
    if xpath_value:
        rows.append(
            {
                "value": xpath_value,
                "source": "contract_xpath",
                "xpath": contract_rule.get("xpath"),
                "css_selector": None,
                "regex": None,
                "sample_value": xpath_value,
            }
        )
    regex_value = _extract_regex_value(html, contract_rule.get("regex", ""))
    if regex_value:
        rows.append(
            {
                "value": regex_value,
                "source": "contract_regex",
                "xpath": None,
                "css_selector": None,
                "regex": contract_rule.get("regex"),
                "sample_value": regex_value,
            }
        )
    return bool(rows)


def _collect_adapter_candidates(
    rows: list[dict],
    *,
    field_name: str,
    adapter_records: list[dict],
) -> bool:
    for record in adapter_records:
        if isinstance(record, dict) and field_name in record and record[field_name]:
            rows.append({"value": record[field_name], "source": "adapter"})
    return bool(rows)


def _collect_datalayer_candidates(
    rows: list[dict],
    *,
    field_name: str,
    datalayer: dict,
) -> bool:
    if datalayer and field_name in datalayer and datalayer[field_name]:
        rows.append({"value": datalayer[field_name], "source": "datalayer"})
    return bool(rows)


def _collect_network_payload_candidates(
    rows: list[dict],
    *,
    field_name: str,
    network_payloads: list[dict],
    base_url: str,
    surface: str,
) -> bool:
    for payload in network_payloads:
        if not isinstance(payload, dict):
            continue
        payload_url = str(payload.get("url") or "").lower()
        if _NETWORK_PAYLOAD_NOISE_URL_PATTERNS.search(payload_url):
            continue
        body = payload.get("body", {})
        if isinstance(body, (dict, list)):
            _append_source_candidates(
                rows,
                field_name,
                body,
                "network_intercept",
                base_url=base_url,
                surface=surface,
            )
    return bool(rows)


def _collect_jsonld_candidates(
    rows: list[dict],
    *,
    field_name: str,
    json_ld: list[dict],
    base_url: str,
    surface: str,
) -> bool:
    for payload in json_ld:
        if isinstance(payload, dict):
            if _should_skip_jsonld_block(payload, field_name):
                continue
            if not _payload_matches_page_scope(payload, base_url=base_url):
                continue
            _append_source_candidates(
                rows,
                field_name,
                payload,
                "json_ld",
                base_url=base_url,
                surface=surface,
            )
    return bool(rows)


def _collect_structured_state_candidates(
    rows: list[dict],
    *,
    field_name: str,
    next_data: dict | None,
    hydrated_states: list[dict],
    embedded_json: list[object],
    network_payloads: list[dict],
    base_url: str,
    surface: str,
) -> bool:
    for payload in embedded_json:
        if not _payload_matches_page_scope(payload, base_url=base_url):
            continue
        _append_source_candidates(
            rows,
            field_name,
            payload,
            "embedded_json",
            base_url=base_url,
            source_metadata=_embedded_blob_metadata(payload),
            surface=surface,
        )
    if next_data:
        if _payload_matches_page_scope(next_data, base_url=base_url):
            _append_source_candidates(
                rows,
                field_name,
                next_data,
                "next_data",
                base_url=base_url,
                surface=surface,
            )
    for state in hydrated_states:
        if _payload_matches_page_scope(state, base_url=base_url):
            _append_source_candidates(
                rows,
                field_name,
                state,
                "hydrated_state",
                base_url=base_url,
                surface=surface,
            )
    rows.extend(
        _structured_source_candidates(
            field_name,
            next_data=next_data,
            hydrated_states=hydrated_states,
            embedded_json=embedded_json,
            network_payloads=network_payloads,
            base_url=base_url,
        )
    )
    return bool(rows)


def _collect_dom_and_meta_candidates(
    rows: list[dict],
    *,
    field_name: str,
    html: str,
    soup: BeautifulSoup,
    domain: str,
    microdata: list[dict],
    open_graph: dict[str, object],
    base_url: str,
    surface: str,
) -> None:
    selectors = get_selector_defaults(domain, field_name)
    for selector in selectors:
        value, _, selector_used = extract_selector_value(
            html,
            css_selector=selector.get("css_selector"),
            xpath=selector.get("xpath"),
            regex=selector.get("regex"),
        )
        if value:
            rows.append(
                {
                    "value": value,
                    "source": "selector",
                    "xpath": selector.get("xpath"),
                    "css_selector": selector.get("css_selector"),
                    "regex": selector.get("regex"),
                    "sample_value": selector.get("sample_value") or value,
                    "selector_used": selector_used,
                    "status": selector.get("status") or "validated",
                }
            )
    dom_row = _dom_pattern(soup, field_name)
    if dom_row:
        rows.append(dom_row)
    for item in microdata:
        if isinstance(item, dict):
            _append_source_candidates(
                rows,
                field_name,
                item,
                "microdata",
                base_url=base_url,
                surface=surface,
            )
    if open_graph:
        _append_source_candidates(
            rows,
            field_name,
            open_graph,
            "open_graph",
            base_url=base_url,
            surface=surface,
        )
        if field_name == "company":
            site_name = open_graph.get("og:site_name")
            if site_name not in (None, "", [], {}):
                rows.append({"value": site_name, "source": "open_graph"})
    if field_name == "category":
        breadcrumb_category = _extract_breadcrumb_category(soup)
        if breadcrumb_category:
            rows.append({"value": breadcrumb_category, "source": "dom_breadcrumb"})




def _filter_candidates(
    candidates: dict[str, list[dict]], base_url: str
) -> dict[str, list[dict]]:
    """Apply quality filters to candidates.

    Filters:
    - Placeholder rejection (CANDIDATE_PLACEHOLDER_VALUES)
    - Noise removal (empty strings, null values)
    - URL validation (relative → absolute)
    - Field-specific validation (price format, image URLs)

    Returns: {field_name: [filtered_rows]}
    """
    filtered_candidates: dict[str, list[dict]] = {}

    for field_name, rows in candidates.items():
        filtered_rows = _finalize_candidate_rows(field_name, rows, base_url=base_url)
        if filtered_rows:
            filtered_candidates[field_name] = filtered_rows

    return filtered_candidates


def _finalize_candidates(
    candidates: dict[str, list[dict]],
    extraction_audit: dict[str, dict[str, object]],
    surface: str,
    url: str,
    semantic: dict,
    target_fields: set[str],
    canonical_target_fields: set[str],
    next_data: dict | None,
    hydrated_states: list[dict],
    embedded_json: list[dict],
    network_payloads: list[dict],
    soup: BeautifulSoup,
    adapter_records: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Deduplicate, rank, and prepare final output.

    - Take first valid candidate per field (first-match wins)
    - Apply domain field mappings
    - Build source trace
    - Add dynamic fields (product_attributes, additional_images)

    Returns: (candidates, source_trace)
    """

    # Choose the highest-ranked candidate per field via FieldDecisionEngine.
    from app.services.extract.field_decision import FieldDecisionEngine

    engine = FieldDecisionEngine(base_url=url)
    final_candidates: dict[str, list[dict]] = {}
    for field_name, rows in candidates.items():
        if rows:
            decision = engine.decide_from_rows(field_name, rows)
            _record_field_decision_audit(
                extraction_audit,
                field_name=field_name,
                decision=decision,
                total_rows=len(rows),
            )
            if decision.accepted and decision.winning_row is not None:
                final_candidates[field_name] = [decision.winning_row]

    # Add dynamic fields from semantic and structured sources
    dynamic_rows = _build_dynamic_semantic_rows(
        semantic,
        surface=surface,
        allowed_fields=target_fields,
    )
    structured_sources = _structured_source_payloads(
        next_data=next_data,
        hydrated_states=hydrated_states,
        embedded_json=embedded_json,
        network_payloads=network_payloads,
        base_url=url,
    )
    structured_rows = _build_dynamic_structured_rows(
        surface=surface,
        structured_sources=structured_sources,
        allowed_fields=target_fields,
    )
    for variant_bundle_field in ("variants", "variant_axes", "selected_variant"):
        structured_rows.pop(variant_bundle_field, None)
    product_detail_rows = _build_product_detail_rows(
        soup,
        base_url=url,
        structured_sources=structured_sources,
    )
    platform_detail_rows = _build_platform_detail_rows(
        base_url=url,
        soup=soup,
        adapter_records=adapter_records or [],
    )
    variant_rows = _build_variant_rows(
        base_url=url,
        soup=soup,
        adapter_records=adapter_records or [],
        network_payloads=network_payloads,
        structured_sources=structured_sources,
    )

    # Merge dynamic rows
    merged_dynamic_rows: dict[str, list[dict]] = {}
    for field_name, rows in variant_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in structured_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in product_detail_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in platform_detail_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in dynamic_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)

    # Add dynamic fields if not already present
    dynamic_override_fields = {
        "color",
        "size",
        "image_url",
        "additional_images",
        "category",
        "sku",
        "price",
        "original_price",
        "availability",
        "variants",
        "variant_axes",
        "selected_variant",
        "description",
        "features",
        "specifications",
        "product_attributes",
        "materials",
    }
    surface_name = str(surface or "").strip().lower()
    if surface_name in {"job_listing", "job_detail"}:
        surface_excluded_dynamic_fields = ECOMMERCE_ONLY_FIELDS
    elif surface_name in {"ecommerce_listing", "ecommerce_detail"}:
        surface_excluded_dynamic_fields = JOB_ONLY_FIELDS
    else:
        surface_excluded_dynamic_fields = frozenset()
    discovered_dynamic_fields: dict[str, object] = {}
    for field_name, rows in merged_dynamic_rows.items():
        dynamic_source_rows: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            dynamic_source_rows.setdefault(
                str(row.get("source") or "dynamic"),
                [],
            ).append(row)
        for source_label, source_rows in dynamic_source_rows.items():
            field_audit = extraction_audit.setdefault(field_name, {"sources": []})
            field_audit.setdefault("sources", []).append(
                {
                    "source": source_label,
                    "status": "produced_candidates",
                    "candidate_count": len(source_rows),
                    "row_sources": [source_label],
                    "value_previews": [
                        _preview_audit_value(row.get("value"))
                        for row in source_rows[-3:]
                        if row.get("value") not in (None, "", [], {})
                    ],
                }
            )
        if field_name in surface_excluded_dynamic_fields:
            continue
        filtered_rows = _finalize_candidate_rows(field_name, rows, base_url=url)
        if not filtered_rows:
            continue
        if (
            field_name not in canonical_target_fields
            and not _dynamic_field_name_is_valid(field_name)
        ):
            continue
        if (
            field_name not in canonical_target_fields
            and _dynamic_value_is_bare_ticker_symbol(filtered_rows[0].get("value"))
        ):
            continue
        normalized_value = _normalized_candidate_text(
            filtered_rows[0].get("value")
        ).casefold()
        if normalized_value in CANDIDATE_PLACEHOLDER_VALUES:
            continue
        if field_name not in canonical_target_fields:
            discovered_dynamic_fields[field_name] = filtered_rows[0].get("value")
            continue
        if field_name in final_candidates and field_name not in dynamic_override_fields:
            continue
        if field_name in final_candidates:
            decision = engine.decide_from_rows(
                field_name,
                [*final_candidates[field_name], *filtered_rows],
            )
            _record_field_decision_audit(
                extraction_audit,
                field_name=field_name,
                decision=decision,
                total_rows=len(final_candidates[field_name]) + len(filtered_rows),
            )
            if decision.accepted and decision.winning_row is not None:
                final_candidates[field_name] = [decision.winning_row]
            continue
        final_candidates[field_name] = filtered_rows[:1]

    # Mirror image_url to additional_images if needed
    if (
        "additional_images" in target_fields
        and "additional_images" not in final_candidates
        and final_candidates.get("image_url")
    ):
        mirrored_rows = [
            {**row, "value": row.get("value")}
            for row in final_candidates["image_url"]
            if row.get("value") not in (None, "", [], {})
        ]
        if mirrored_rows:
            final_candidates["additional_images"] = mirrored_rows

    # Add product_attributes from semantic extraction to output
    if "detail" in str(surface or "").lower():
        specifications = semantic.get("specifications")
        if (
            "product_attributes" not in final_candidates
            and specifications
            and isinstance(specifications, dict)
            and specifications
        ):
            final_candidates["product_attributes"] = [
                {"value": specifications, "source": "semantic_specifications"}
            ]

    # Apply domain field mappings
    domain = _domain(url)
    mappings = get_domain_mapping(domain, surface)
    _reconcile_variant_bundle(final_candidates, base_url=url)
    _sync_selected_variant_root_fields(final_candidates)
    _sanitize_product_attributes(final_candidates)
    _record_final_output_audit(extraction_audit, final_candidates)

    return final_candidates, {
        "candidates": dict(final_candidates),
        "extraction_audit": extraction_audit,
        "discovered_data": {
            "discovered_fields": discovered_dynamic_fields,
        },
        "mapping_hint": mappings,
        "semantic": semantic,
    }








