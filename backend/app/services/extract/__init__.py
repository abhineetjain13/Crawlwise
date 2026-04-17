from __future__ import annotations

from importlib import import_module

__all__ = [
    "FieldDecisionEngine",
    "MergeDecision",
    "assess_listing_record_quality",
    "candidate_source_rank",
    "coerce_field_candidate_value",
    "extract_candidates",
    "extract_json_detail",
    "extract_json_listing",
    "extract_listing_records",
    "finalize_candidate_row",
    "listing_set_quality",
    "merge_detail_reconciliation",
    "merge_record_fields",
    "normalize_detail_candidate_values",
    "reconcile_detail_candidate_values",
    "sanitize_field_value",
    "sanitize_field_value_with_reason",
    "strong_identity_key",
]

_EXPORTS = {
    "FieldDecisionEngine": ("app.services.extract.field_decision", "FieldDecisionEngine"),
    "MergeDecision": ("app.services.extract.field_decision", "MergeDecision"),
    "assess_listing_record_quality": (
        "app.services.extract.listing_quality",
        "assess_listing_record_quality",
    ),
    "candidate_source_rank": ("app.services.extract.service", "candidate_source_rank"),
    "coerce_field_candidate_value": (
        "app.services.extract.candidate_processing",
        "coerce_field_candidate_value",
    ),
    "extract_candidates": ("app.services.extract.service", "extract_candidates"),
    "extract_json_detail": ("app.services.extract.json_extractor", "extract_json_detail"),
    "extract_json_listing": ("app.services.extract.json_extractor", "extract_json_listing"),
    "extract_listing_records": (
        "app.services.extract.listing_extractor",
        "extract_listing_records",
    ),
    "finalize_candidate_row": (
        "app.services.extract.candidate_processing",
        "finalize_candidate_row",
    ),
    "listing_set_quality": ("app.services.extract.listing_quality", "listing_set_quality"),
    "merge_detail_reconciliation": (
        "app.services.extract.detail_reconciliation",
        "merge_detail_reconciliation",
    ),
    "merge_record_fields": (
        "app.services.extract.detail_reconciliation",
        "merge_record_fields",
    ),
    "normalize_detail_candidate_values": (
        "app.services.extract.detail_reconciliation",
        "normalize_detail_candidate_values",
    ),
    "reconcile_detail_candidate_values": (
        "app.services.extract.detail_reconciliation",
        "reconcile_detail_candidate_values",
    ),
    "sanitize_field_value": (
        "app.services.extract.candidate_processing",
        "sanitize_field_value",
    ),
    "sanitize_field_value_with_reason": (
        "app.services.extract.candidate_processing",
        "sanitize_field_value_with_reason",
    ),
    "strong_identity_key": (
        "app.services.extract.listing_identity",
        "strong_identity_key",
    ),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
