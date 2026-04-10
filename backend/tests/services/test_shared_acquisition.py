from __future__ import annotations

import pytest
from app.services.acquisition.acquirer import AcquisitionRequest, AcquisitionResult
from app.services.shared_acquisition import acquire


@pytest.mark.asyncio
async def test_shared_acquisition_forwards_typed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, object] = {}

    async def _fake_acquire(*, request: AcquisitionRequest | None = None, **_kwargs):
        recorded["request"] = request
        return AcquisitionResult(html="<html></html>", method="curl_cffi")

    monkeypatch.setattr("app.services.shared_acquisition._acquire", _fake_acquire)

    request = AcquisitionRequest(
        run_id=7,
        url="https://example.com/listings",
        surface="ecommerce_listing",
    )
    result = await acquire(request=request)

    assert result.method == "curl_cffi"
    assert recorded["request"] == request


@pytest.mark.asyncio
async def test_shared_acquisition_requires_request_or_essential_fields() -> None:
    with pytest.raises(
        ValueError,
        match="acquire requires either request=AcquisitionRequest\\(\\.\\.\\.\\) or non-None run_id, url, and surface before calling _acquire",
    ):
        await acquire()
