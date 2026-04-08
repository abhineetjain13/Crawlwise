from __future__ import annotations

import pytest

from app.services.acquisition.acquirer import AcquisitionResult
from app.services.pipeline.core import _resolve_listing_surface


@pytest.mark.parametrize("requested_surface", ["ecommerce_listing", "job_listing"])
def test_resolve_listing_surface_preserves_user_requested_surface(requested_surface: str) -> None:
    resolved = _resolve_listing_surface(
        surface=requested_surface,
        url="https://example.com/jobs",
        html="<html><body><h1>Jobs</h1></body></html>",
        acq=AcquisitionResult(html="<html><body><h1>Jobs</h1></body></html>", method="curl_cffi"),
    )
    assert resolved == requested_surface


def test_resolve_listing_surface_does_not_mutate_ecommerce_listing_when_page_looks_job_like() -> None:
    requested = "ecommerce_listing"
    resolved = _resolve_listing_surface(
        surface=requested,
        url="https://example.com/careers",
        html="<html><body><h1>Open Roles</h1><p>Apply now</p></body></html>",
        acq=AcquisitionResult(
            html="<html><body><h1>Open Roles</h1><p>Apply now</p></body></html>",
            method="playwright",
        ),
    )
    assert resolved == requested

