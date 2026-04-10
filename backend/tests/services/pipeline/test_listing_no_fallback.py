from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.acquisition.acquirer import AcquisitionResult
from app.services.pipeline.core import VERDICT_LISTING_FAILED, _extract_listing


@pytest.mark.asyncio
async def test_extract_listing_zero_records_returns_failure_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    save_mock = AsyncMock()
    monkeypatch.setattr("app.services.pipeline.core.extract_listing_records", lambda **_: [])
    monkeypatch.setattr("app.services.pipeline.core._listing_acquisition_blocked", lambda *_: False)
    monkeypatch.setattr("app.services.pipeline.core._looks_like_loading_listing_shell", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("app.services.pipeline.core._save_listing_records", save_mock)

    records, verdict, metrics = await _extract_listing(
        session=SimpleNamespace(),
        run=SimpleNamespace(id=999),
        url="https://example.com/category",
        html="<html><body><h1>No items</h1></body></html>",
        acq=AcquisitionResult(html="<html><body><h1>No items</h1></body></html>", method="curl_cffi"),
        adapter_result=None,
        adapter_records=[],
        additional_fields=[],
        surface="ecommerce_listing",
        max_records=20,
        url_metrics={},
        update_run_state=False,
        persist_logs=False,
    )

    assert records == []
    assert verdict == VERDICT_LISTING_FAILED
    assert metrics["listing_surface_used"] == "ecommerce_listing"
    save_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_listing_downgrades_sparse_job_payload_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_listing_records",
        lambda **_: [{"title": "Quality Inspector I - 2nd shift", "url": "https://example.com/jobs/1"}],
    )
    monkeypatch.setattr("app.services.pipeline.core._save_listing_records", AsyncMock(return_value=[{"title": "Quality Inspector I - 2nd shift", "url": "https://example.com/jobs/1"}]))

    records, verdict, metrics = await _extract_listing(
        session=SimpleNamespace(flush=AsyncMock()),
        run=SimpleNamespace(id=1001),
        url="https://recruiting.ultipro.com/jobboard",
        html="<html><body></body></html>",
        acq=AcquisitionResult(
            html="<html><body></body></html>",
            method="playwright",
            network_payloads=[{"url": "https://recruiting.ultipro.com/api/jobs", "body": {"opportunities": [{"Id": "abc"}]}}],
        ),
        adapter_result=None,
        adapter_records=[],
        additional_fields=[],
        surface="job_listing",
        max_records=20,
        url_metrics={},
        update_run_state=False,
        persist_logs=False,
    )

    assert records == [{"title": "Quality Inspector I - 2nd shift", "url": "https://example.com/jobs/1"}]
    assert verdict == "partial"
    assert "job_payload_missing_context" in metrics["listing_quality_flags"]

