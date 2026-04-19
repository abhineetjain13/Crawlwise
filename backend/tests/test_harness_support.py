from __future__ import annotations

from pathlib import Path

from harness_support import classify_failure_mode, infer_surface, parse_test_sites_markdown


def test_infer_surface_prefers_explicit_surface() -> None:
    assert infer_surface("https://example.com/collections", explicit_surface="job_listing") == "job_listing"


def test_infer_surface_classifies_job_and_commerce_urls() -> None:
    assert infer_surface("https://example.com/careers") == "job_listing"
    assert infer_surface("https://example.com/products/widget-1") == "ecommerce_detail"
    assert (
        infer_surface(
            "https://secure7.saashr.com/ta/6208610.careers?ein_id=1&career_portal_id=2&ShowJob=587687242"
        )
        == "job_detail"
    )


def test_parse_test_sites_markdown_reads_urls_from_tail(tmp_path: Path) -> None:
    path = tmp_path / "TEST_SITES.md"
    path.write_text("ignore\nhttps://example.com/careers\nnot a url\nhttps://shop.example.com/collections\n", encoding="utf-8")
    rows = parse_test_sites_markdown(path, start_line=2)

    assert rows == [
        {
            "name": "https://example.com/careers",
            "url": "https://example.com/careers",
            "surface": "job_listing",
        },
        {
            "name": "https://shop.example.com/collections",
            "url": "https://shop.example.com/collections",
            "surface": "ecommerce_listing",
        },
    ]


def test_classify_failure_mode_flags_missing_adapter_registration() -> None:
    result = {
        "ok": False,
        "platform_family": "ultipro_ukg",
        "surface": "job_listing",
        "adapter_name": None,
        "adapter_records": 0,
        "records": 0,
    }

    assert classify_failure_mode(result) == "adapter_not_matched"


def test_classify_failure_mode_treats_browser_challenge_diagnostics_as_blocked() -> None:
    result = {
        "ok": False,
        "blocked": False,
        "browser_diagnostics": {
            "browser_outcome": "usable_content",
            "challenge_evidence": [
                "strong:captcha",
                "provider:cloudflare",
            ],
            "challenge_provider_hits": ["cloudflare"],
        },
        "surface": "ecommerce_listing",
        "records": 0,
        "adapter_records": 0,
    }

    assert classify_failure_mode(result) == "blocked"
