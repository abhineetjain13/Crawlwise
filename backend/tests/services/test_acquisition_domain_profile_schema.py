from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.acquisition.domain_profile_schema import (
    DomainProfileV2,
    SelectorRule,
    domain_profile_v2_from_legacy,
    parse_domain_profile_v2,
)
from app.services.config.domain_profiles import DOMAIN_PROFILE_SCHEMA_VERSION


def test_legacy_profile_dict_parses_into_v2_schema() -> None:
    profile = domain_profile_v2_from_legacy(
        {
            "fetch_profile": {
                "fetch_mode": "browser_only",
                "max_pages": 3,
            },
            "acquisition_contract": {
                "prefer_browser": True,
                "stale_after_failures": {"failure_count": 2, "stale": False},
            },
            "selector_rules": [
                {"field": "title", "css_selector": "h1", "hits": 4, "misses": 1}
            ],
            "saved_at": "2026-05-08T00:00:00+00:00",
        },
        domain="example.com",
        surface="ecommerce_detail",
    )

    assert profile.schema_version == DOMAIN_PROFILE_SCHEMA_VERSION
    assert profile.domain == "example.com"
    assert profile.fetch_profile.fetch_mode == "browser_only"
    assert profile.acquisition_contract.failure_count == 2
    assert profile.selector_rules[0].field_name == "title"
    assert profile.selector_rules[0].hit_count == 4


def test_parse_v2_profile_round_trips() -> None:
    profile = DomainProfileV2(domain="example.com")
    payload = profile.model_dump(mode="json")

    assert parse_domain_profile_v2(payload).model_dump(mode="json") == payload


def test_v2_auto_traversal_is_rejected() -> None:
    with pytest.raises(ValidationError, match="traversal_mode"):
        parse_domain_profile_v2(
            {
                "schema_version": DOMAIN_PROFILE_SCHEMA_VERSION,
                "domain": "example.com",
                "fetch_profile": {
                    "fetch_mode": "browser_only",
                    "traversal_mode": "auto",
                },
            }
        )


def test_legacy_auto_traversal_is_normalized_to_none() -> None:
    profile = parse_domain_profile_v2(
        {
            "domain": "example.com",
            "fetch_profile": {
                "fetch_mode": "browser_only",
                "traversal_mode": "auto",
            },
        }
    )

    assert profile.domain == "example.com"
    assert profile.fetch_profile.fetch_mode == "browser_only"
    assert profile.fetch_profile.traversal_mode is None


def test_v2_valid_traversal_mode_round_trips() -> None:
    profile = parse_domain_profile_v2(
        {
            "schema_version": DOMAIN_PROFILE_SCHEMA_VERSION,
            "domain": "example.com",
            "fetch_profile": {
                "fetch_mode": "browser_only",
                "traversal_mode": "paginate",
            },
        }
    )

    assert profile.fetch_profile.traversal_mode == "paginate"


def test_invalid_profile_data_has_explicit_validation_errors() -> None:
    with pytest.raises(ValidationError) as exc:
        SelectorRule(field_name="", selector="", hit_count=-1)

    text = str(exc.value)
    assert "field_name" in text
    assert "selector" in text
    assert "hit_count" in text
