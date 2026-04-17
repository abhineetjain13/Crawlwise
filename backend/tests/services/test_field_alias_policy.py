from __future__ import annotations

from app.services.config.field_mappings import CANONICAL_SCHEMAS
from app.services.field_alias_policy import (
    excluded_fields_for_surface,
    field_allowed_for_surface,
    get_surface_field_aliases,
)


def test_field_allowed_for_surface_matches_canonical_schema_cartesian_product():
    all_fields = {
        field_name
        for fields in CANONICAL_SCHEMAS.values()
        for field_name in fields
    }

    for surface, allowed_fields in CANONICAL_SCHEMAS.items():
        allowed = frozenset(allowed_fields)
        for field_name in all_fields:
            assert field_allowed_for_surface(surface, field_name) is (field_name in allowed)


def test_excluded_fields_for_surface_is_complement_of_allowed_schema_fields():
    all_fields = frozenset(
        field_name
        for fields in CANONICAL_SCHEMAS.values()
        for field_name in fields
    )

    for surface, allowed_fields in CANONICAL_SCHEMAS.items():
        allowed = frozenset(allowed_fields)
        excluded = excluded_fields_for_surface(surface)
        assert (all_fields - allowed).issubset(excluded)


def test_get_surface_field_aliases_only_returns_allowed_canonical_fields():
    for surface, allowed_fields in CANONICAL_SCHEMAS.items():
        aliases = get_surface_field_aliases(surface)
        assert set(aliases).issubset(set(allowed_fields))
