from __future__ import annotations

from types import SimpleNamespace

from app.services.publish.metrics import build_url_metrics


def test_build_url_metrics_promotes_traversal_diagnostics() -> None:
    acquisition_result = SimpleNamespace(
        method="browser",
        status_code=200,
        blocked=False,
        final_url="https://example.com/listing?page=2",
        network_payloads=[{"url": "https://example.com/api/listing"}],
        adapter_name=None,
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
        },
    )

    metrics = build_url_metrics(acquisition_result, requested_fields=["title"])

    assert metrics["traversal_attempted"] is True
    assert metrics["traversal_succeeded"] is True
    assert metrics["traversal_fell_back"] is False
    assert metrics["traversal_mode_used"] == "paginate"
    assert metrics["pages_collected"] == 2
    assert metrics["pages_scrolled"] == 1
    assert metrics["network_payload_count"] == 1
