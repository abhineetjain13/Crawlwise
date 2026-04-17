from __future__ import annotations

from app.services.config.platform_registry import (
    PlatformConfig,
    browser_first_domains,
    configured_adapter_names,
    detect_platform_family,
    listing_readiness_domains,
)


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


def test_detect_platform_family_ignores_external_oracle_hcm_footer_link() -> None:
    html = """
    <html><body>
      <a href="https://hcml.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/AEO-Careers/requisitions">
        Careers
      </a>
      <script>Shopify.theme = {};</script>
    </body></html>
    """

    assert (
        detect_platform_family(
            "https://www.toddsnyder.com/products/zip-mocklight-grey-mix",
            html,
        )
        == "generic_commerce"
    )


def test_platform_registry_exposes_browser_first_domains_and_adapter_names(monkeypatch) -> None:
    configs = [
        PlatformConfig(
            family="example_browser",
            domain_patterns=["www.example.com", "careers.example.com"],
            adapter_names=["greenhouse"],
            requires_browser=True,
        ),
        PlatformConfig(
            family="example_data",
            adapter_names=["oracle_hcm"],
        ),
    ]

    monkeypatch.setattr(
        "app.services.config.platform_registry.platform_configs",
        lambda: configs,
    )

    assert browser_first_domains() == ["careers.example.com", "example.com"]
    assert configured_adapter_names() == (
        "greenhouse",
        "oracle_hcm",
        "amazon",
        "walmart",
        "ebay",
        "shopify",
    )
