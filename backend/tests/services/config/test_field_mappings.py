from __future__ import annotations

from app.services.config.field_mappings import COLLECTION_KEYS, get_surface_field_aliases


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


def test_get_surface_field_aliases_returns_detached_alias_lists():
    first = get_surface_field_aliases("automobile_detail")
    second = get_surface_field_aliases("automobile_detail")

    first["make"].append("custom_make_alias")

    assert "custom_make_alias" not in second["make"]


def test_collection_keys_excludes_generic_payload_wrappers():
    assert "data" not in COLLECTION_KEYS
    assert "content" not in COLLECTION_KEYS
    assert "response" not in COLLECTION_KEYS
    assert "values" not in COLLECTION_KEYS
    assert "objects" not in COLLECTION_KEYS
    assert "documents" not in COLLECTION_KEYS
