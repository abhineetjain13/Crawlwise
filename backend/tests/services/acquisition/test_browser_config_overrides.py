# Integration tests for family-keyed listing readiness overrides
from __future__ import annotations

from app.services.config.platform_readiness import (
    LISTING_READINESS_OVERRIDES,
    load_platform_readiness,
    resolve_listing_readiness_override,
)
def test_listing_readiness_override_requires_matching_domain_not_query_tokens() -> None:
    spoofed_url = (
        "https://example.com/jobs"
        "?source=candidateexperience"
        "&target=oraclecloud.com"
    )

    assert resolve_listing_readiness_override(spoofed_url) is None


def test_listing_readiness_override_accepts_expected_oracle_candidateexperience_shape() -> None:
    oracle_url = (
        "https://candidateexperience.oraclecloud.com/"
        "hcmUI/CandidateExperience/en/sites/CX_1/requisitions"
    )

    override = resolve_listing_readiness_override(oracle_url)

    assert override is not None
    assert override["platform"] == "oracle_hcm"


def test_platform_readiness_config_is_loaded_from_dedicated_section() -> None:
    document = load_platform_readiness()

    assert document.version == 1
    assert "adp" in document.families
    assert ".current-openings-item" in document.families["adp"].selectors
