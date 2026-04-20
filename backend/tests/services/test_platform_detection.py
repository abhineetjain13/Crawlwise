from __future__ import annotations

from app.services.platform_policy import (
    detect_platform_family,
    is_job_platform_signal,
    resolve_browser_readiness_policy,
    resolve_listing_readiness_override,
)


def test_detect_platform_family_for_real_client_ats_urls() -> None:
    assert (
        detect_platform_family(
            "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699"
        )
        == "greenhouse"
    )
    assert (
        detect_platform_family("https://smithnephew.wd5.myworkdayjobs.com/External")
        == "workday"
    )
    assert (
        detect_platform_family("https://ats.rippling.com/en-GB/inhance-technologies/jobs")
        == "rippling"
    )
    assert (
        detect_platform_family(
            "https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?mode=location"
        )
        == "oracle_hcm"
    )
    assert (
        detect_platform_family(
            "https://www.paycomonline.net/v4/ats/web.php/portal/8EC14E985B45C7F52C531F487F62A2B8/career-page"
        )
        == "paycom"
    )
    assert (
        detect_platform_family(
            "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=14fa7571-bfac-427f-aa18-9488391d4c5e&ccId=19000101_000001&type=MP&lang=en_US&selectedMenuKey=CurrentOpenings"
        )
        == "adp"
    )


def test_resolve_listing_readiness_override_uses_platform_registry_config() -> None:
    workday = resolve_listing_readiness_override(
        "https://smithnephew.wd5.myworkdayjobs.com/External"
    )
    adp = resolve_listing_readiness_override(
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=1"
    )

    assert workday == {
        "platform": "workday",
        "domain": "smithnephew.wd5.myworkdayjobs.com",
        "selectors": [
            "a[href*='/External/job/']",
            "a[href*='/job/']",
            "[data-automation-id='jobTitle']",
        ],
        "max_wait_ms": 15000,
    }
    assert adp == {
        "platform": "adp",
        "domain": "workforcenow.adp.com",
        "selectors": [".current-openings-item", "[id^='lblTitle_']"],
        "max_wait_ms": 20000,
    }


def test_detect_platform_family_ignores_html_marker_matches_on_unrelated_domains() -> None:
    html = """
    <html>
      <head>
        <script>window.__NEXT_DATA__ = {};</script>
      </head>
      <body>
        <footer>Workday privacy choices</footer>
      </body>
    </html>
    """

    assert (
        detect_platform_family(
            "https://www.kitchenaid.com/countertop-appliances/food-processors/food-processor-and-chopper-products",
            html,
        )
        is None
    )


def test_platform_registry_does_not_treat_detection_only_families_as_job_adapters() -> None:
    assert detect_platform_family("https://ats.rippling.com/en-GB/acme/jobs") == "rippling"
    assert is_job_platform_signal(platform_family="rippling") is False


def test_detect_platform_family_for_stable_spa_canaries() -> None:
    assert detect_platform_family("https://practicesoftwaretesting.com/#/shop") == "practicesoftwaretesting"
    assert detect_platform_family("https://demo.spreecommerce.org/products") == "spree_commerce"
    assert detect_platform_family("https://demo.saleor.io/products") == "saleor"


def test_resolve_browser_readiness_policy_requires_networkidle_for_platform_or_traversal() -> None:
    platform_policy = resolve_browser_readiness_policy(
        "https://smithnephew.wd5.myworkdayjobs.com/External",
    )
    traversal_policy = resolve_browser_readiness_policy(
        "https://example.com/collections/widgets",
        traversal_active=True,
    )
    default_policy = resolve_browser_readiness_policy(
        "https://example.com/products/widget-prime",
    )

    assert platform_policy["require_networkidle"] is True
    assert platform_policy["networkidle_reason"] == "platform-readiness"
    assert platform_policy["listing_override"]["platform"] == "workday"
    assert traversal_policy["require_networkidle"] is True
    assert traversal_policy["networkidle_reason"] == "traversal"
    assert default_policy["require_networkidle"] is False
    assert default_policy["networkidle_reason"] is None


def test_resolve_browser_readiness_policy_uses_spree_canary_override() -> None:
    policy = resolve_browser_readiness_policy(
        "https://demo.spreecommerce.org/products",
    )

    assert policy["require_networkidle"] is True
    assert policy["networkidle_reason"] == "platform-readiness"
    assert policy["listing_override"] == {
        "platform": "spree_commerce",
        "domain": "demo.spreecommerce.org",
        "selectors": [
            "[data-testid='product-card']",
            ".products .card",
            "a[href*='/products/']",
        ],
        "max_wait_ms": 15000,
    }
