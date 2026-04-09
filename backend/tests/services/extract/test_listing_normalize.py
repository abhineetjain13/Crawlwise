from __future__ import annotations

from app.services.extract.listing_normalize import canonical_listing_fields


def test_canonical_listing_fields_handles_job_surface_prefix() -> None:
    fields = canonical_listing_fields("job_listing", set())
    assert "company" in fields
    assert "salary" in fields
    assert "job_id" in fields


def test_canonical_listing_fields_handles_non_job_surface() -> None:
    fields = canonical_listing_fields("ecommerce_listing", {"custom_field"})
    assert "price" in fields
    assert "image_url" in fields
    assert "custom_field" in fields
