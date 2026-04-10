from __future__ import annotations

from app.services.acquisition.acquirer import AcquisitionResult
from app.services.config.platform_registry import job_platform_families
from app.services.pipeline.core import _resolve_listing_surface
from app.services.pipeline_config import JOB_PLATFORM_FAMILIES, PLATFORM_BROWSER_FIRST


def test_resolve_listing_surface_prefers_effective_surface_from_acquisition() -> None:
    acq = AcquisitionResult(
        html="<html><body><h1>Jobs</h1></body></html>",
        method="curl_cffi",
        diagnostics={"surface_effective": "job_listing", "curl_platform_family": "greenhouse"},
    )
    resolved = _resolve_listing_surface(
        surface="ecommerce_listing",
        acq=acq,
    )
    assert resolved == "job_listing"
    assert acq.diagnostics["surface_effective"] == "job_listing"


def test_resolve_listing_surface_falls_back_to_requested_surface_without_effective_override() -> None:
    resolved = _resolve_listing_surface(
        surface="ecommerce_listing",
        acq=AcquisitionResult(
            html="<html><body><h1>Open Roles</h1><p>Apply now</p></body></html>",
            method="playwright",
            diagnostics={"curl_adapter_hint": "saashr"},
        ),
    )
    assert resolved == "ecommerce_listing"


def test_job_platform_families_are_derived_from_platform_registry() -> None:
    assert JOB_PLATFORM_FAMILIES == frozenset({*job_platform_families(), "generic_jobs"})


def test_browser_first_platforms_are_registry_backed_job_platforms() -> None:
    registry_job_families = job_platform_families()

    assert PLATFORM_BROWSER_FIRST
    assert PLATFORM_BROWSER_FIRST <= registry_job_families

