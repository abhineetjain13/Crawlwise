# Tests for review payload construction.
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRecord
from app.services.crawl_service import create_crawl_run
from app.services.review.service import build_review_payload, save_review
from app.services.site_memory_service import get_memory


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
            discovered_data={
                "review_bucket": [
                    {
                        "key": "material",
                        "value": "Oak",
                        "confidence_score": 8,
                        "source": "adapter",
                    }
                ]
            },
            source_trace={"type": "listing"},
            raw_html_path=None,
        )
    )
    await db_session.commit()

    payload = await build_review_payload(db_session, run.id)

    assert payload is not None
    assert payload["normalized_fields"] == ["price", "title"]
    assert payload["discovered_fields"] == ["material"]


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


@pytest.mark.asyncio
async def test_save_review_promotes_review_bucket_fields_into_canonical_data(
    db_session: AsyncSession,
    test_user,
):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product/chair-a",
        "surface": "ecommerce_detail",
    })
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/product/chair-a",
        data={"title": "Chair A"},
        raw_data={"title": "Chair A"},
        discovered_data={
            "review_bucket": [
                {
                    "key": "wire_gauge",
                    "value": "Oak",
                    "confidence_score": 8,
                    "source": "semantic_spec",
                }
            ]
        },
        source_trace={},
        raw_html_path=None,
    )
    db_session.add(record)
    await db_session.commit()

    await save_review(
        db_session,
        run,
        [{"source_field": "wire_gauge", "output_field": "wire_gauge", "selected": True}],
    )

    await db_session.refresh(record)
    memory = await get_memory(db_session, "example.com")
    assert record.data["wire_gauge"] == "Oak"
    assert record.discovered_data == {}
    assert memory is not None
    assert memory.payload["schemas"]["ecommerce_detail"]["new_fields"] == ["wire_gauge"]


@pytest.mark.asyncio
async def test_save_review_keeps_review_bucket_when_target_field_is_already_set(
    db_session: AsyncSession,
    test_user,
):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product/chair-a",
        "surface": "ecommerce_detail",
    })
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/product/chair-a",
        data={"title": "Chair A", "materials": "Walnut"},
        raw_data={"title": "Chair A"},
        discovered_data={
            "review_bucket": [
                {
                    "key": "material",
                    "value": "Oak",
                    "confidence_score": 8,
                    "source": "semantic_spec",
                }
            ]
        },
        source_trace={},
        raw_html_path=None,
    )
    db_session.add(record)
    await db_session.commit()

    await save_review(
        db_session,
        run,
        [{"source_field": "material", "output_field": "materials", "selected": True}],
    )

    await db_session.refresh(record)
    assert record.data["materials"] == "Walnut"
    assert record.discovered_data["review_bucket"][0]["key"] == "material"
    assert record.discovered_data["review_bucket"][0]["value"] == "Oak"
