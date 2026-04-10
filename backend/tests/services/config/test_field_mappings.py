from __future__ import annotations

from app.services.config.field_mappings import get_surface_field_aliases


def test_get_surface_field_aliases_scopes_surface_specific_and_internal_fields():
    job_aliases = get_surface_field_aliases("job_listing")
    ecommerce_aliases = get_surface_field_aliases("ecommerce_listing")
    unknown_aliases = get_surface_field_aliases("")

    assert "brand" not in job_aliases
    assert "sku" not in job_aliases
    assert "salary" not in ecommerce_aliases
    assert "apply_url" not in ecommerce_aliases
    assert "slug" not in job_aliases
    assert "slug" not in ecommerce_aliases
    assert "slug" not in unknown_aliases
    assert "title" in job_aliases
    assert "title" in ecommerce_aliases
