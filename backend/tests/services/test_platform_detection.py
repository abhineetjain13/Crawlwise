from __future__ import annotations

from app.services.platform_policy import detect_platform_family


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
