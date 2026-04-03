# Tests for review payload construction.
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord
from app.services.crawl_service import create_crawl_run
from app.services.review.service import build_review_payload


@pytest.mark.asyncio
async def test_build_review_payload_uses_extracted_fields(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/category",
        "surface": "ecommerce_listing",
    })
    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url="https://example.com/product/1",
            data={"title": "Chair A", "price": "10"},
            raw_data={"title": "Chair A", "price": "$10", "url": "https://example.com/product/1"},
            discovered_data={"adapter_data": [], "json_ld": []},
            source_trace={"type": "listing"},
            raw_html_path=None,
        )
    )
    await db_session.commit()

    payload = await build_review_payload(db_session, run.id)

    assert payload is not None
    assert payload["normalized_fields"] == ["price", "title"]
    assert payload["discovered_fields"] == ["price", "title", "url"]


@pytest.mark.asyncio
async def test_build_review_payload_includes_selector_suggestions_for_detail_records(
    db_session: AsyncSession,
    test_user,
    tmp_path: Path,
):
    html_path = tmp_path / "detail.html"
    html_path.write_text("<html><body><h1>Chair A</h1></body></html>", encoding="utf-8")
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product/chair-a",
        "surface": "ecommerce_detail",
    })
    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url="https://example.com/product/chair-a",
            data={"title": "Chair A"},
            raw_data={"title": "Chair A"},
            discovered_data={},
            source_trace={
                "type": "detail",
                "candidates": {
                    "title": [
                        {
                            "value": "Chair A",
                            "source": "dom",
                            "xpath": "/html[1]/body[1]/h1[1]",
                            "css_selector": "h1",
                            "sample_value": "Chair A",
                        }
                    ]
                },
            },
            raw_html_path=str(html_path),
        )
    )
    await db_session.commit()

    payload = await build_review_payload(db_session, run.id)

    assert payload is not None
    assert "title" in payload["selector_suggestions"]
    assert payload["selector_suggestions"]["title"][0]["xpath"] == "/html[1]/body[1]/h1[1]"
