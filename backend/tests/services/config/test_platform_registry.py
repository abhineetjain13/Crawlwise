from __future__ import annotations

from app.services.config.platform_registry import PlatformConfig, listing_readiness_domains


def test_listing_readiness_domains_merges_domains_for_duplicate_family(monkeypatch) -> None:
    configs = [
        PlatformConfig(
            family="oracle_hcm",
            readiness_domains=["candidateexperience.oraclecloud.com"],
        ),
        PlatformConfig(
            family="oracle_hcm",
            readiness_domains=["fa.ocs.oraclecloud.com", "candidateexperience.oraclecloud.com"],
        ),
    ]

    monkeypatch.setattr(
        "app.services.config.platform_registry.platform_configs",
        lambda: configs,
    )

    assert listing_readiness_domains() == {
        "oracle_hcm": [
            "candidateexperience.oraclecloud.com",
            "fa.ocs.oraclecloud.com",
        ]
    }
