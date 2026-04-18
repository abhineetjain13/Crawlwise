from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.acquisition import policy


def _request(
    surface: str,
    *,
    url: str = "https://example.com",
    traversal_mode: str | None = None,
    requested_fields: list[str] | None = None,
):
    return SimpleNamespace(
        url=url,
        surface=surface,
        traversal_mode=traversal_mode,
        requested_fields=list(requested_fields or []),
    )


def _http_result(**analysis):
    return SimpleNamespace(
        content_type="html",
        status_code=200,
        error=None,
        acquirer_analysis=analysis,
    )


@pytest.mark.parametrize(
    ("surface", "platform_family", "page_type", "readiness_profile", "traversal_enabled"),
    [
        ("ecommerce_listing", "", "category", "listing", True),
        ("ecommerce_detail", "", "pdp", "detail", False),
        ("job_listing", "generic_jobs", "category", "listing", True),
        ("job_detail", "greenhouse", "pdp", "detail", False),
    ],
)
def test_plan_acquisition_covers_surface_family_matrix(
    surface: str,
    platform_family: str,
    page_type: str,
    readiness_profile: str,
    traversal_enabled: bool,
) -> None:
    plan = policy.plan_acquisition(
        _request(surface),
        platform_family=platform_family,
    )

    assert plan.surface == surface
    assert plan.page_type == page_type
    assert plan.readiness_profile == readiness_profile
    assert plan.traversal_enabled is traversal_enabled


def test_plan_acquisition_uses_job_listing_card_selectors() -> None:
    plan = policy.plan_acquisition(
        _request("job_listing"),
        platform_family="generic_jobs",
    )

    assert plan.traversal_card_selectors == policy.CARD_SELECTORS_JOBS
    assert plan.readiness_selectors == policy.CARD_SELECTORS_JOBS


def test_plan_acquisition_uses_detail_readiness_selectors_for_commerce_detail() -> None:
    plan = policy.plan_acquisition(_request("ecommerce_detail"))

    assert plan.readiness_selectors == (
        policy.DOM_PATTERNS["title"],
        policy.DOM_PATTERNS["price"],
        policy.DOM_PATTERNS["sku"],
    )
    assert plan.diagnostic_payload_kind == "variant_completeness"


def test_plan_acquisition_marks_listing_retry_profile_and_adapter_recovery() -> None:
    plan = policy.plan_acquisition(_request("ecommerce_listing"))

    assert plan.retry_profile == "listing_low_value"
    assert plan.adapter_recovery_enabled is True
    assert plan.diagnostic_payload_kind == "listing_completeness"


def test_plan_acquisition_respects_browser_first_domain_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        policy,
        "browser_first_domains",
        lambda: ["careers.example.com"],
    )

    plan = policy.plan_acquisition(
        _request("ecommerce_listing", url="https://careers.example.com/openings")
    )

    assert plan.require_browser_first is True


def test_plan_acquisition_respects_job_family_browser_first_rule() -> None:
    plan = policy.plan_acquisition(
        _request("job_detail"),
        platform_family="greenhouse",
    )

    assert plan.require_browser_first is True


def test_browser_escalation_decision_requires_browser_for_detail_requested_fields_js_shell() -> None:
    plan = policy.plan_acquisition(_request("job_detail", requested_fields=["salary"]))

    decision = policy.browser_escalation_decision(
        _http_result(
            blocked=SimpleNamespace(is_blocked=False),
            visible_text="tiny",
            content_len=50,
            gate_phrases=False,
            listing_signals=SimpleNamespace(strong=False),
            extractability={
                "has_extractable_data": False,
                "reason": "surface_unspecified",
            },
            invalid_surface_page=False,
            js_shell_detected=True,
            curl_diagnostics={},
        ),
        plan=plan,
        requested_fields=["salary"],
    )

    assert decision.needs_browser is True
    assert decision.reason == "requested_fields_require_browser"


def test_browser_escalation_decision_preserves_listing_signal_override() -> None:
    plan = policy.plan_acquisition(_request("ecommerce_listing"))

    decision = policy.browser_escalation_decision(
        _http_result(
            blocked=SimpleNamespace(is_blocked=False),
            visible_text=("enough visible text " * 20).strip(),
            content_len=100000,
            gate_phrases=False,
            listing_signals=SimpleNamespace(strong=True),
            extractability={"has_extractable_data": False, "reason": "no_listing_signals"},
            invalid_surface_page=False,
            js_shell_detected=False,
            curl_diagnostics={},
        ),
        plan=plan,
        requested_fields=[],
    )

    assert decision.needs_browser is False
    assert decision.reason == "extractable_data_found"


def test_browser_escalation_decision_preserves_listing_structured_override() -> None:
    plan = policy.plan_acquisition(_request("job_listing"))

    decision = policy.browser_escalation_decision(
        _http_result(
            blocked=SimpleNamespace(is_blocked=False),
            visible_text="body",
            content_len=20,
            gate_phrases=False,
            listing_signals=SimpleNamespace(strong=False),
            extractability={
                "has_extractable_data": True,
                "reason": "structured_listing_markup",
            },
            invalid_surface_page=False,
            js_shell_detected=False,
            curl_diagnostics={},
        ),
        plan=plan,
        requested_fields=[],
    )

    assert decision.needs_browser is False
    assert decision.structured_override is True
    assert decision.reason == "structured_data_found"


@pytest.mark.parametrize(
    ("surface", "expected_evidence"),
    [
        ("ecommerce_listing", ["listing_completeness"]),
        ("ecommerce_detail", ["variant_completeness"]),
        ("job_listing", None),
    ],
)
def test_decide_acquisition_execution_uses_plan_diagnostic_payload_kind(
    surface: str,
    expected_evidence: list[str] | None,
) -> None:
    plan = policy.plan_acquisition(_request(surface))

    decision = policy.decide_acquisition_execution(
        _http_result(
            blocked=SimpleNamespace(is_blocked=True),
            visible_text="",
            content_len=0,
            gate_phrases=False,
            listing_signals=SimpleNamespace(strong=False),
            extractability={"has_extractable_data": False, "reason": "empty_html"},
            invalid_surface_page=False,
            js_shell_detected=False,
            curl_diagnostics={},
        ),
        plan=plan,
        traversal_mode=None,
        requested_fields=[],
    )

    assert decision.runtime == "playwright_attempt_required"
    assert decision.reason == "blocked_page"
    assert decision.to_diagnostics()["expected_evidence"] == expected_evidence
