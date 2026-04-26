from __future__ import annotations

from types import SimpleNamespace

from app.services.publish.metadata import _stringify_value, refresh_record_commit_metadata
from app.services.publish.metrics import build_url_metrics, diagnostics_indicate_block


def test_build_url_metrics_promotes_traversal_diagnostics() -> None:
    acquisition_result = SimpleNamespace(
        method="browser",
        status_code=200,
        blocked=False,
        final_url="https://example.com/listing?page=2",
        network_payloads=[{"url": "https://example.com/api/listing"}],
        adapter_name=None,
        platform_family="shopify",
        browser_diagnostics={
            "navigation_strategy": "domcontentloaded",
            "network_payload_count": 1,
            "malformed_network_payloads": 0,
            "requested_traversal_mode": "auto",
            "selected_traversal_mode": "paginate",
            "traversal_activated": True,
            "traversal_stop_reason": "next_page_not_found",
            "traversal_iterations": 1,
            "scroll_iterations": 0,
            "load_more_clicks": 0,
            "pages_advanced": 1,
            "traversal_progress_events": 1,
            "traversal_fallback_used": True,
            "traversal_fallback_recovered": True,
            "traversal_fallback_record_count": 58,
            "browser_engine": "real_chrome",
            "browser_profile": "real_chrome_native",
            "browser_launch_mode": "headful",
            "browser_headless": False,
            "browser_native_context": True,
            "browser_stealth_enabled": False,
        },
    )

    metrics = build_url_metrics(acquisition_result, requested_fields=["title"])

    assert metrics["traversal_attempted"] is True
    assert metrics["traversal_succeeded"] is True
    assert metrics["traversal_fell_back"] is False
    assert metrics["traversal_fallback_used"] is True
    assert metrics["traversal_fallback_recovered"] is True
    assert metrics["traversal_fallback_record_count"] == 58
    assert metrics["traversal_mode_used"] == "paginate"
    assert metrics["pages_collected"] == 2
    assert metrics["pages_scrolled"] == 1
    assert metrics["network_payload_count"] == 1
    assert metrics["platform_family"] == "shopify"
    assert metrics["browser_fetch_method"] == "browser:real_chrome"
    assert metrics["browser_engine"] == "real_chrome"
    assert metrics["browser_profile"] == "real_chrome_native"
    assert metrics["browser_launch_mode"] == "headful"
    assert metrics["browser_headless"] is False
    assert metrics["browser_native_context"] is True
    assert metrics["browser_stealth_enabled"] is False


def test_build_url_metrics_keeps_failed_browser_attempts_when_final_method_is_http() -> None:
    acquisition_result = SimpleNamespace(
        method="curl_cffi",
        status_code=200,
        blocked=False,
        final_url="https://example.com/category/widgets",
        network_payloads=[],
        adapter_name=None,
        platform_family=None,
        browser_diagnostics={
            "browser_attempted": True,
            "browser_reason": "empty-extraction retry",
            "browser_outcome": "navigation_failed",
            "html_bytes": 49,
            "phase_timings_ms": {"navigation": 1200},
        },
    )

    metrics = build_url_metrics(acquisition_result, requested_fields=["title"])

    assert metrics["browser_used"] is False
    assert metrics["browser_attempted"] is True
    assert metrics["browser_reason"] == "empty-extraction retry"
    assert metrics["browser_outcome"] == "navigation_failed"
    assert metrics["html_bytes"] == 49
    assert metrics["browser_phase_timings_ms"] == {"navigation": 1200}


def test_build_url_metrics_keeps_platform_family_separate_from_adapter_name() -> None:
    acquisition_result = SimpleNamespace(
        method="test",
        status_code=200,
        blocked=False,
        final_url="https://example.com/products/widget-prime",
        network_payloads=[],
        adapter_name=None,
        platform_family="shopify",
        browser_diagnostics={},
    )

    metrics = build_url_metrics(acquisition_result, requested_fields=["title"])

    assert metrics["adapter_name"] is None
    assert metrics["platform_family"] == "shopify"


def test_diagnostics_indicate_block_preserves_ready_usable_content_despite_provider_evidence() -> None:
    diagnostics = {
        "browser_outcome": "usable_content",
        "challenge_evidence": ["provider:cloudflare"],
        "challenge_provider_hits": ["cloudflare"],
        "readiness_probes": [{"is_ready": True}],
    }

    assert diagnostics_indicate_block(diagnostics) is False


def test_diagnostics_indicate_block_preserves_ready_usable_content_despite_challenge_iframe() -> None:
    diagnostics = {
        "browser_outcome": "usable_content",
        "challenge_evidence": [
            "provider:akamai",
            "challenge_element:captcha_titled_iframe",
        ],
        "challenge_provider_hits": ["akamai"],
        "challenge_element_hits": ["captcha_titled_iframe"],
        "readiness_probes": [{"is_ready": True}],
    }

    assert diagnostics_indicate_block(diagnostics) is False


def test_diagnostics_indicate_block_flags_usable_content_with_strong_challenge_evidence() -> None:
    diagnostics = {
        "browser_outcome": "usable_content",
        "challenge_evidence": [
            "strong:captcha",
            "provider:cloudflare",
        ],
        "challenge_provider_hits": ["cloudflare"],
    }

    assert diagnostics_indicate_block(diagnostics) is True


def test_diagnostics_indicate_block_keeps_strong_challenge_over_ready_probe() -> None:
    diagnostics = {
        "browser_outcome": "usable_content",
        "challenge_evidence": [
            "strong:captcha",
            "provider:cloudflare",
        ],
        "challenge_provider_hits": ["cloudflare"],
        "readiness_probes": [{"is_ready": True}],
    }

    assert diagnostics_indicate_block(diagnostics) is True


def test_stringify_value_preserves_falsy_scalars() -> None:
    assert _stringify_value(0) == "0"
    assert _stringify_value(False) == "False"
    assert _stringify_value(0.0) == "0.0"
    assert _stringify_value(None) == ""


def test_refresh_record_commit_metadata_filters_empty_requested_fields() -> None:
    record = SimpleNamespace(source_trace={}, discovered_data={})
    run = SimpleNamespace(requested_fields=["title", "", None, "  "])

    refresh_record_commit_metadata(
        record,
        run=run,
        field_name="title",
        value="Widget Prime",
    )

    assert record.discovered_data["requested_field_coverage"] == {
        "requested": 1,
        "found": 1,
        "missing": [],
    }
