from __future__ import annotations

import pytest

from app.services.domain_memory_service import load_domain_memory, save_domain_memory


@pytest.mark.asyncio
async def test_domain_memory_round_trip(db_session) -> None:
    await save_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        platform="shopify",
        selectors={"title": {"css": "h1[data-test='product-title']"}},
    )
    await db_session.commit()

    loaded = await load_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )

    assert loaded is not None
    assert loaded.platform == "shopify"
    assert loaded.selectors["title"]["css"] == "h1[data-test='product-title']"
