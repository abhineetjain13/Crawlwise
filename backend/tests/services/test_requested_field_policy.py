# Regression tests for requested-field normalization.
from __future__ import annotations

from app.services.requested_field_policy import expand_requested_fields, normalize_requested_field


def test_requested_field_normalization_preserves_distinct_semantic_fields():
    assert normalize_requested_field("Responsibilities") == "responsibilities"
    assert normalize_requested_field("Qualifications") == "qualifications"
    assert normalize_requested_field("Requirements") == "requirements"


def test_requested_field_expansion_keeps_canonical_fields_unique():
    assert expand_requested_fields(["Responsibilities", "requirements", "job qualifications"]) == [
        "responsibilities",
        "requirements",
        "qualifications",
    ]
