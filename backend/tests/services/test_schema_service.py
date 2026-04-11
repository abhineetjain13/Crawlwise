from __future__ import annotations

from app.services.schema_service import _snapshot_to_resolved


def test_snapshot_to_resolved_does_not_mark_all_baseline_fields_deprecated_without_snapshot_fields():
    resolved = _snapshot_to_resolved(
        surface="ecommerce_listing",
        domain="example.com",
        baseline_fields=["title", "url"],
        snapshot=None,
        explicit_fields=[],
    )

    assert resolved.deprecated_fields == []
