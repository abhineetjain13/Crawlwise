from app.services.platform_resolver import resolve_platform_family


def test_resolve_platform_family_detects_icims_from_real_url() -> None:
    assert (
        resolve_platform_family(
            "https://ehccareers-emory.icims.com/jobs/search?pr=0&searchRelation=keyword_all"
        )
        == "icims"
    )


def test_resolve_platform_family_detects_workday_from_real_url() -> None:
    assert (
        resolve_platform_family("https://smithnephew.wd5.myworkdayjobs.com/External")
        == "workday"
    )


def test_resolve_platform_family_detects_adp_from_real_url() -> None:
    assert (
        resolve_platform_family(
            "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=14fa7571-bfac-427f-aa18-9488391d4c5e"
        )
        == "adp"
    )


def test_resolve_platform_family_detects_generic_jobs_when_no_specific_family_matches() -> None:
    assert resolve_platform_family("https://example.com/careers/job-search-results") == "generic_jobs"
