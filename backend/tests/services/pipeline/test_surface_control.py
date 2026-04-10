from __future__ import annotations

import pytest

from app.services.acquisition.acquirer import AcquisitionResult
from app.services.pipeline.core import _reclassify_surface_if_job, _resolve_listing_surface


@pytest.mark.parametrize("requested_surface, expected_surface", [("ecommerce_listing", "job_listing"), ("job_listing", "job_listing")])
def test_resolve_listing_surface_prefers_effective_surface_from_diagnostics(
    requested_surface: str, expected_surface: str
) -> None:
    resolved = _resolve_listing_surface(
        surface=requested_surface,
        url="https://example.com/jobs",
        html="<html><body><h1>Jobs</h1></body></html>",
        acq=AcquisitionResult(
            html="<html><body><h1>Jobs</h1></body></html>",
            method="curl_cffi",
            diagnostics={"surface_effective": "job_listing", "curl_platform_family": "greenhouse"},
        ),
    )
    assert resolved == expected_surface


def test_resolve_listing_surface_uses_adapter_hint_when_diagnostics_are_job_like() -> None:
    requested = "ecommerce_listing"
    resolved = _resolve_listing_surface(
        surface=requested,
        url="https://example.com/careers",
        html="<html><body><h1>Open Roles</h1><p>Apply now</p></body></html>",
        acq=AcquisitionResult(
            html="<html><body><h1>Open Roles</h1><p>Apply now</p></body></html>",
            method="playwright",
            diagnostics={"curl_adapter_hint": "saashr"},
        ),
    )
    assert resolved == "job_listing"


def test_reclassify_surface_if_job_remaps_conflicting_requested_surface() -> None:
    acq = AcquisitionResult(
        html="<html><body><h1>Open Roles</h1></body></html>",
        method="playwright",
        diagnostics={"platform_family": "greenhouse", "confidence": "high"},
    )

    assert _reclassify_surface_if_job("ecommerce_listing", acq) == "job_listing"

