from __future__ import annotations

from importlib import import_module

__all__ = [
    "DatabaseRecordWriter",
    "ExtractionRecordWriter",
    "ListingPersistenceCandidate",
    "MemoryRecordWriter",
    "VERDICT_BLOCKED",
    "VERDICT_EMPTY",
    "VERDICT_ERROR",
    "VERDICT_LISTING_FAILED",
    "VERDICT_PARTIAL",
    "VERDICT_SCHEMA_MISS",
    "VERDICT_SUCCESS",
    "_aggregate_verdict",
    "_build_acquisition_trace",
    "_build_field_discovery_summary",
    "_build_manifest_trace",
    "_build_review_bucket",
    "_passes_core_verdict",
    "build_acquisition_profile",
    "build_crawl_record",
    "build_discovered_data_payload",
    "build_listing_record",
    "build_url_metrics",
    "collect_winning_sources",
    "compute_verdict",
    "dedupe_listing_persistence_candidates",
    "finalize_url_metrics",
    "get_canonical_fields",
    "listing_fallback_identity_key",
    "load_domain_requested_fields",
    "persist_crawl_record",
    "persist_normalized_record",
    "persist_normalized_record_to_session",
    "record_identity_fingerprint",
    "refresh_record_commit_metadata",
    "resolve_record_writer",
]

_EXPORTS = {
    "DatabaseRecordWriter": ("app.services.publish.record_persistence", "DatabaseRecordWriter"),
    "ExtractionRecordWriter": ("app.services.publish.record_persistence", "ExtractionRecordWriter"),
    "ListingPersistenceCandidate": ("app.services.publish.record_persistence", "ListingPersistenceCandidate"),
    "MemoryRecordWriter": ("app.services.publish.record_persistence", "MemoryRecordWriter"),
    "VERDICT_BLOCKED": ("app.services.publish.verdict", "VERDICT_BLOCKED"),
    "VERDICT_EMPTY": ("app.services.publish.verdict", "VERDICT_EMPTY"),
    "VERDICT_ERROR": ("app.services.publish.verdict", "VERDICT_ERROR"),
    "VERDICT_LISTING_FAILED": ("app.services.publish.verdict", "VERDICT_LISTING_FAILED"),
    "VERDICT_PARTIAL": ("app.services.publish.verdict", "VERDICT_PARTIAL"),
    "VERDICT_SCHEMA_MISS": ("app.services.publish.verdict", "VERDICT_SCHEMA_MISS"),
    "VERDICT_SUCCESS": ("app.services.publish.verdict", "VERDICT_SUCCESS"),
    "_aggregate_verdict": ("app.services.publish.verdict", "_aggregate_verdict"),
    "_build_acquisition_trace": ("app.services.publish.trace_builders", "_build_acquisition_trace"),
    "_build_field_discovery_summary": ("app.services.publish.trace_builders", "_build_field_discovery_summary"),
    "_build_manifest_trace": ("app.services.publish.trace_builders", "_build_manifest_trace"),
    "_build_review_bucket": ("app.services.publish.trace_builders", "_build_review_bucket"),
    "_passes_core_verdict": ("app.services.publish.verdict", "_passes_core_verdict"),
    "build_acquisition_profile": ("app.services.publish.metrics", "build_acquisition_profile"),
    "build_crawl_record": ("app.services.publish.record_persistence", "build_crawl_record"),
    "build_discovered_data_payload": ("app.services.publish.record_persistence", "build_discovered_data_payload"),
    "build_listing_record": ("app.services.publish.record_persistence", "build_listing_record"),
    "build_url_metrics": ("app.services.publish.metrics", "build_url_metrics"),
    "collect_winning_sources": ("app.services.publish.record_persistence", "collect_winning_sources"),
    "compute_verdict": ("app.services.publish.verdict", "compute_verdict"),
    "dedupe_listing_persistence_candidates": ("app.services.publish.record_persistence", "dedupe_listing_persistence_candidates"),
    "finalize_url_metrics": ("app.services.publish.metrics", "finalize_url_metrics"),
    "get_canonical_fields": ("app.services.publish.trace_builders", "get_canonical_fields"),
    "listing_fallback_identity_key": ("app.services.publish.record_persistence", "listing_fallback_identity_key"),
    "load_domain_requested_fields": ("app.services.publish.metadata", "load_domain_requested_fields"),
    "persist_crawl_record": ("app.services.publish.record_persistence", "persist_crawl_record"),
    "persist_normalized_record": ("app.services.publish.record_persistence", "persist_normalized_record"),
    "persist_normalized_record_to_session": ("app.services.publish.record_persistence", "persist_normalized_record_to_session"),
    "record_identity_fingerprint": ("app.services.publish.record_persistence", "record_identity_fingerprint"),
    "refresh_record_commit_metadata": ("app.services.publish.metadata", "refresh_record_commit_metadata"),
    "resolve_record_writer": ("app.services.publish.record_persistence", "resolve_record_writer"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
