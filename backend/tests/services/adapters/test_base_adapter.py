from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from app.services.adapters.base import BaseAdapter


class _TestAdapter(BaseAdapter):
    async def can_handle(self, url: str, html: str) -> bool:
        return True

    async def extract(self, url: str, html: str, surface: str):
        return None


class _FakeResponse:
    status_code = 200

    def json(self):
        raise ValueError("bad json")


@pytest.mark.asyncio
async def test_request_json_with_curl_logs_decode_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _TestAdapter()
    caplog.set_level(logging.DEBUG, logger="app.services.adapters.base")

    with patch(
        "app.services.adapters.base.wait_for_host_slot",
        return_value=None,
    ):
        result = await adapter._request_json_with_curl(
            lambda *_args, **_kwargs: _FakeResponse(),
            "https://example.com/api",
        )

    assert result is None
    assert "Failed to decode adapter JSON response" in caplog.text


class _FamilyAdapter(BaseAdapter):
    platform_family = "oracle_hcm"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    async def extract(self, url: str, html: str, surface: str):
        return None


@pytest.mark.asyncio
async def test_matches_platform_family_uses_shared_detector() -> None:
    adapter = _FamilyAdapter()

    with patch(
        "app.services.adapters.base.detect_platform_family",
        return_value="oracle_hcm",
    ):
        assert await adapter.can_handle("https://example.com/jobs", "<html></html>")


@pytest.mark.asyncio
async def test_matches_platform_family_rejects_other_families() -> None:
    adapter = _FamilyAdapter()

    with patch(
        "app.services.adapters.base.detect_platform_family",
        return_value="generic_commerce",
    ):
        assert not await adapter.can_handle("https://example.com/jobs", "<html></html>")
