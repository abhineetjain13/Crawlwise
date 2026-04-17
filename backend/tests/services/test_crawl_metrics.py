from __future__ import annotations

from app.services.acquisition.acquirer import AcquisitionResult
from app.services.publish import build_url_metrics


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
