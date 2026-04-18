from __future__ import annotations

import pytest

from app.services.adapters.base import BaseAdapter


class _FamilyAdapter(BaseAdapter):
    platform_family = "oracle_hcm"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    async def extract(self, url: str, html: str, surface: str):
        return None


@pytest.mark.asyncio
async def test_matches_platform_family_uses_shared_detector() -> None:
    adapter = _FamilyAdapter()
    html = """
    <html><body>
    <script>var CX_CONFIG = {"site": "jobs"};</script>
    </body></html>
    """

    assert await adapter.can_handle(
        "https://jobs.example.com/openings",
        html,
    )


@pytest.mark.asyncio
async def test_matches_platform_family_rejects_other_families() -> None:
    adapter = _FamilyAdapter()
    html = """
    <html><body>
    <div class="results-grid">
      <a href="/product/widget-1">Widget 1</a>
      <a href="/product/widget-2">Widget 2</a>
    </div>
    </body></html>
    """

    assert not await adapter.can_handle(
        "https://example.com/products",
        html,
    )
