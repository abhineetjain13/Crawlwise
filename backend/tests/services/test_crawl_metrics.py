from __future__ import annotations

from app.services.acquisition.acquirer import AcquisitionResult
from app.services.publish import build_url_metrics, finalize_url_metrics


def test_build_url_metrics_surfaces_surface_warning_signals() -> None:
    result = AcquisitionResult(
        html="<html></html>",
        method="playwright",
        diagnostics={
            "invalid_surface_page": False,
            "soft_404_page": True,
            "surface_selection_warnings": [
                {
                    "warning": "surface_selection_may_be_low_confidence",
                    "signals": ["soft_404_title", "soft_404_heading"],
                }
            ],
        },
    )

    metrics = build_url_metrics(result, requested_fields=[])

    assert metrics["soft_404_page"] is True
    assert metrics["surface_warning_signals"] == [
        "soft_404_heading",
        "soft_404_title",
    ]


def test_finalize_url_metrics_persists_quality_level_and_score() -> None:
    metrics = finalize_url_metrics(
        {
            "listing_quality": "meaningful",
            "listing_completeness": {"applicable": True, "complete": False},
        },
        records=[
            {"title": "Example Tee", "url": "https://example.com/p/tee", "price": "99"},
        ],
        requested_fields=["title", "url", "price", "brand"],
    )

    quality_summary = metrics["quality_summary"]

    assert quality_summary["score"] == 0.45
    assert quality_summary["level"] == "low"
    assert quality_summary["requested_fields_total"] == 4
    assert quality_summary["requested_fields_found_best"] == 3
