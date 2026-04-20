from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

import harness_support
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


def test_classify_failure_mode_rejects_placeholder_success_titles() -> None:
    result = {
        "verdict": "success",
        "records": 1,
        "sample_title": "Page Not Found",
        "populated_fields": 1,
        "surface": "ecommerce_listing",
    }

    assert classify_failure_mode(result) == "wrong_content_or_placeholder"


def test_classify_failure_mode_buckets_spa_shell_failures() -> None:
    shell_404 = {
        "status_code": 404,
        "browser_diagnostics": {"browser_outcome": "low_content_shell"},
        "surface": "ecommerce_listing",
        "records": 0,
    }
    shell_low_content = {
        "status_code": 200,
        "browser_diagnostics": {"browser_outcome": "low_content_shell"},
        "surface": "ecommerce_listing",
        "records": 0,
    }
    readiness_timeout = {
        "status_code": 200,
        "browser_diagnostics": {
            "browser_outcome": "usable_content",
            "networkidle_timed_out": True,
        },
        "surface": "ecommerce_listing",
        "records": 0,
    }

    assert classify_failure_mode(shell_404) == "spa_shell_404"
    assert classify_failure_mode(shell_low_content) == "spa_shell_low_content"
    assert classify_failure_mode(readiness_timeout) == "spa_readiness_timeout"


def test_classify_failure_mode_treats_uppercase_success_verdict_as_success() -> None:
    result = {
        "verdict": "SUCCESS",
        "browser_diagnostics": {},
        "records": 1,
        "sample_title": "Widget",
        "populated_fields": 3,
    }

    assert classify_failure_mode(result) == "success"


@pytest.mark.asyncio
async def test_ensure_harness_user_id_reuses_user_by_configured_email(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("HARNESS_EMAIL", "harness@example.invalid")
    monkeypatch.setenv("HARNESS_PASSWORD", "HarnessSecret123!")
    monkeypatch.setenv("HARNESS_ROLE", "harness")

    first_user_id = await harness_support._ensure_harness_user_id(db_session)
    second_user_id = await harness_support._ensure_harness_user_id(db_session)
    user = (
        await db_session.execute(
            select(harness_support.User).where(
                harness_support.User.email == "harness@example.invalid"
            )
        )
    ).scalar_one()

    assert first_user_id == second_user_id == user.id
    assert user.role == "harness"


@pytest.mark.asyncio
async def test_ensure_harness_user_id_rejects_production_environment(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("HARNESS_EMAIL", "harness@example.invalid")
    monkeypatch.setenv("HARNESS_PASSWORD", "HarnessSecret123!")

    with pytest.raises(
        RuntimeError,
        match="Harness user access is disabled outside local/test environments",
    ):
        await harness_support._ensure_harness_user_id(db_session)
