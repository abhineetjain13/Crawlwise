"""
Pipeline package for crawl processing.

This package splits the monolithic pipeline.py into focused modules.
"""

# Import from submodules
from .utils import (
    _elapsed_ms,
    _compact_dict,
    _clean_page_text,
    _first_non_empty_text,
    _normalize_committed_field_name,
    _review_bucket_fingerprint,
    _clean_candidate_text,
)

from .field_normalization import (
    _normalize_review_value,
    _review_values_equal,
    _normalize_record_fields,
    _passes_detail_quality_gate,
    _raw_record_payload,
    _public_record_fields,
    _merge_record_fields,
    _should_prefer_secondary_field,
    _requested_field_coverage,
)

from .verdict import (
    VERDICT_SUCCESS,
    VERDICT_PARTIAL,
    VERDICT_BLOCKED,
    VERDICT_SCHEMA_MISS,
    VERDICT_LISTING_FAILED,
    VERDICT_EMPTY,
    _compute_verdict,
    _passes_core_verdict,
    _aggregate_verdict,
)
from .listing_helpers import (
    _listing_acquisition_blocked,
    _looks_like_loading_listing_shell,
    _sanitize_listing_record_fields,
    _summarize_job_listing_description,
)

from .rendering import (
    _render_fallback_node_markdown,
    _render_fallback_card_group,
    _find_fallback_card_group,
    _should_skip_fallback_node,
    _normalize_target_url,
    _render_manifest_tables_markdown,
)

from .llm_integration import (
    _apply_llm_suggestions_to_candidate_values,
    _build_llm_candidate_evidence,
    _build_llm_discovered_sources,
    _snapshot_for_llm,
    _normalize_llm_cleanup_review,
    _split_llm_cleanup_payload,
    _normalize_llm_review_bucket_item,
    _select_llm_review_candidates,
)

from .trace_builders import (
    _build_acquisition_trace,
    _build_manifest_trace,
    _build_review_bucket,
    _review_bucket_source_for_field,
    _build_field_discovery_summary,
    _build_legible_listing_fallback_record,
)

from .review_helpers import (
    _merge_review_bucket_entries,
    _should_surface_discovered_field,
)

# Import core pipeline functions
from .core import (
    _looks_like_job_listing_page,
    _resolve_listing_surface,
    _process_single_url,
    _extract_listing,
    _extract_detail,
    _process_json_response,
    _log,
    _set_stage,
    _mark_run_failed,
    _supports_parallel_batch_sessions,
    _persist_failure_state,
    _load_domain_requested_fields,
    _normalize_detail_candidate_values,
    _reconcile_detail_candidate_values,
    _refresh_record_commit_metadata,
    _refresh_schema_from_record,
    _split_detail_output_fields,
    _validate_extraction_contract,
    _collect_detail_llm_suggestions,
    STAGE_FETCH,
    STAGE_ANALYZE,
    STAGE_SAVE,
)

__all__ = [
    # Utils
    "_elapsed_ms",
    "_compact_dict",
    "_clean_page_text",
    "_first_non_empty_text",
    "_normalize_committed_field_name",
    "_review_bucket_fingerprint",
    "_clean_candidate_text",
    # Field normalization
    "_normalize_review_value",
    "_review_values_equal",
    "_normalize_record_fields",
    "_passes_detail_quality_gate",
    "_raw_record_payload",
    "_public_record_fields",
    "_merge_record_fields",
    "_should_prefer_secondary_field",
    "_requested_field_coverage",
    # Verdict
    "VERDICT_SUCCESS",
    "VERDICT_PARTIAL",
    "VERDICT_BLOCKED",
    "VERDICT_SCHEMA_MISS",
    "VERDICT_LISTING_FAILED",
    "VERDICT_EMPTY",
    "_compute_verdict",
    "_passes_core_verdict",
    "_aggregate_verdict",
    # Core functions (from legacy)
    "_process_single_url",
    "_looks_like_job_listing_page",
    "_resolve_listing_surface",
    "_extract_listing",
    "_extract_detail",
    "_process_json_response",
    "_log",
    "_set_stage",
    "_mark_run_failed",
    "_supports_parallel_batch_sessions",
    "_persist_failure_state",
    "_apply_llm_suggestions_to_candidate_values",
    "_build_acquisition_trace",
    "_build_field_discovery_summary",
    "_build_legible_listing_fallback_record",
    "_build_llm_candidate_evidence",
    "_build_llm_discovered_sources",
    "_build_manifest_trace",
    "_build_review_bucket",
    "_collect_detail_llm_suggestions",
    "_find_fallback_card_group",
    "_listing_acquisition_blocked",
    "_load_domain_requested_fields",
    "_looks_like_loading_listing_shell",
    "_merge_review_bucket_entries",
    "_normalize_detail_candidate_values",
    "_normalize_llm_cleanup_review",
    "_normalize_llm_review_bucket_item",
    "_normalize_target_url",
    "_reconcile_detail_candidate_values",
    "_refresh_record_commit_metadata",
    "_refresh_schema_from_record",
    "_render_fallback_card_group",
    "_render_fallback_node_markdown",
    "_render_manifest_tables_markdown",
    "_review_bucket_source_for_field",
    "_sanitize_listing_record_fields",
    "_select_llm_review_candidates",
    "_should_skip_fallback_node",
    "_should_surface_discovered_field",
    "_snapshot_for_llm",
    "_split_detail_output_fields",
    "_split_llm_cleanup_payload",
    "_summarize_job_listing_description",
    "_validate_extraction_contract",
    "STAGE_FETCH",
    "STAGE_ANALYZE",
    "STAGE_SAVE",
]
