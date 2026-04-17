from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from app.services.acquisition import policy


def test_requires_browser_first_has_no_hardcoded_tenant_or_platform_host_literals() -> None:
    source = inspect.getsource(policy.requires_browser_first)
    assert "workforcenow.adp.com" not in source
    assert "myjobs.adp.com" not in source
    assert "recruiting.adp.com" not in source
    assert "careers.clarkassociatesinc.biz" not in source


def test_requires_browser_first_uses_config_driven_domain_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        policy,
        "browser_first_domains",
        lambda: ["careers.clarkassociatesinc.biz"],
    )
    assert policy.requires_browser_first(
        "https://careers.clarkassociatesinc.biz/open-roles",
        "job_listing",
    )


@pytest.mark.parametrize(
    ("traversal_mode", "expected"),
    [
        ("auto", True),
        ("scroll", True),
        ("load_more", True),
        ("paginate", True),
        ("", False),
        (None, False),
        ("click", False),
    ],
)
def test_should_force_browser_for_traversal(traversal_mode: str | None, expected: bool) -> None:
    assert policy.should_force_browser_for_traversal(traversal_mode) is expected


def test_resolve_traversal_surface_policy_marks_detail_surfaces_non_traversable() -> None:
    resolved = policy.resolve_traversal_surface_policy("job_detail")

    assert resolved.is_detail_surface is True
    assert resolved.is_listing_surface is False
    assert resolved.traversal_disabled_reason == "detail_surface"
    assert resolved.card_selectors


def test_resolve_traversal_surface_policy_uses_job_card_selectors_for_listing() -> None:
    resolved = policy.resolve_traversal_surface_policy("job_listing")

    assert resolved.is_listing_surface is True
    assert resolved.is_detail_surface is False
    assert tuple(resolved.card_selectors) == policy.CARD_SELECTORS_JOBS


def test_decide_initial_auto_traversal_prefers_progress_for_hybrid_pages() -> None:
    decision = policy.decide_initial_auto_traversal(
        {"selector": "a.next"},
        {"is_likely_infinite_scroll": True},
    )

    assert decision.decision == "hybrid_progress_first"
    assert decision.should_paginate_now is False


def test_normalize_traversal_summary_fills_page_count_from_combined_html() -> None:
    summary = policy.normalize_traversal_summary(
        {"mode": "paginate", "attempted": True},
        traversal_mode="paginate",
        combined_html="<!-- PAGE BREAK:1 -->\nalpha\n<!-- PAGE BREAK:2 -->\nbeta",
    )

    assert summary["mode_used"] == "paginate"
    assert summary["pages_collected"] == 2
    assert summary["scroll_iterations"] == 0
    assert summary["fallback_used"] is False


def test_should_retry_browser_launch_profile_on_blocked_html() -> None:
    result = SimpleNamespace(
        html="<html><title>Access Denied</title><body>captcha</body></html>",
        diagnostics={},
    )

    assert policy.should_retry_browser_launch_profile(
        result,
        surface="ecommerce_detail",
        html_looks_low_value=lambda _html: False,
    )


def test_should_retry_browser_launch_profile_on_listing_shell_like_low_value_result() -> None:
    result = SimpleNamespace(
        html="<html><body>page not found</body></html>",
        diagnostics={"listing_readiness": {"ready": False, "shell_like": True}},
    )

    assert policy.should_retry_browser_launch_profile(
        result,
        surface="job_listing",
        html_looks_low_value=lambda _html: True,
    )


def test_should_not_retry_browser_launch_profile_for_non_listing_low_value_result() -> None:
    result = SimpleNamespace(
        html="<html><body>" + ("placeholder content " * 12) + "</body></html>",
        diagnostics={"listing_readiness": {"ready": False, "shell_like": True}},
    )

    assert not policy.should_retry_browser_launch_profile(
        result,
        surface="job_detail",
        html_looks_low_value=lambda _html: True,
    )

