from __future__ import annotations

from app.services.extract.listing_normalize import _normalized_size_tokens, canonical_listing_fields


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


def test_normalized_size_tokens_do_not_match_letter_sizes_inside_words() -> None:
    tokens = _normalized_size_tokens("small mall XS S M XL EU 42 10.5")

    assert "s" in tokens
    assert "m" in tokens
    assert "xl" in tokens
    assert "eu-42" in tokens
    assert "10.5" in tokens
    assert "small" not in tokens
    assert "mall" not in tokens
