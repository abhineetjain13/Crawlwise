from __future__ import annotations

import json

import pytest

from app.models.crawl import CrawlRecord
from app.services.crawl_crud import create_crawl_run
from app.services import record_export_service
from app.services.extraction_runtime import extract_records
from app.services.record_export_service import (
    stream_export_artifacts_json,
    stream_export_csv,
    stream_export_json,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _collect_chunks(stream) -> str:
    chunks: list[str] = []
    async for chunk in stream:
        chunks.append(chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_export_streams_serialize_clean_record_data(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
        },
    )
    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url=run.url,
            data={
                "title": "Widget Prime",
                "price": "19.99",
                "_source": "dom",
                "page_markdown": "# internal",
                "empty_field": "",
            },
            raw_data={},
            discovered_data={},
            source_trace={},
        )
    )
    await db_session.commit()

    exported_json = await _collect_chunks(stream_export_json(db_session, run.id))
    exported_csv = await _collect_chunks(stream_export_csv(db_session, run.id))
    json_rows = json.loads(exported_json)

    assert json_rows == [{"price": "19.99", "title": "Widget Prime"}]
    assert "_source" not in exported_csv
    assert "page_markdown" not in exported_csv
    assert "Widget Prime" in exported_csv


@pytest.mark.asyncio
async def test_export_streamers_preserve_order_across_paged_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        CrawlRecord(
            id=1,
            run_id=7,
            source_url="https://example.com/a",
            data={"title": "A"},
            raw_data={},
            discovered_data={},
            source_trace={},
        ),
        CrawlRecord(
            id=2,
            run_id=7,
            source_url="https://example.com/b",
            data={"title": "B"},
            raw_data={},
            discovered_data={},
            source_trace={},
        ),
        CrawlRecord(
            id=3,
            run_id=7,
            source_url="https://example.com/c",
            data={"title": "C"},
            raw_data={},
            discovered_data={},
            source_trace={},
        ),
    ]

    async def _fake_get_run_records(session, run_id, page, page_size):
        del session, page_size
        assert run_id == 7
        pages = {
            1: (rows[:2], 3),
            2: (rows[2:], 3),
        }
        return pages.get(page, ([], 3))

    monkeypatch.setattr(record_export_service, "get_run_records", _fake_get_run_records)
    monkeypatch.setattr(record_export_service, "MAX_RECORD_PAGE_SIZE", 2)

    exported_json = await _collect_chunks(stream_export_json(None, 7))
    exported_csv = await _collect_chunks(stream_export_csv(None, 7))
    exported_artifacts = await _collect_chunks(stream_export_artifacts_json(None, 7))

    json_rows = json.loads(exported_json)
    artifact_rows = json.loads(exported_artifacts)

    assert [row["title"] for row in json_rows] == ["A", "B", "C"]
    assert exported_csv.index("A") < exported_csv.index("B") < exported_csv.index("C")
    assert [row["source_url"] for row in artifact_rows] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]


def test_export_image_dedupe_preserves_comma_containing_urls() -> None:
    sanitized = record_export_service._sanitize_markdown_export_data(
        {
            "image_url": "https://cdn.example.com/images/widget-1.jpg",
            "additional_images": [
                "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-2.jpg",
                "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-3.jpg",
            ],
        }
    )

    assert sanitized["additional_images"] == (
        "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-2.jpg, "
        "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-3.jpg"
    )


def test_export_image_dedupe_handles_legacy_string_values() -> None:
    sanitized = record_export_service._sanitize_markdown_export_data(
        {
            "image_url": "https://cdn.example.com/images/widget-1.jpg",
            "additional_images": (
                "https://cdn.example.com/images/widget-1.jpg, "
                "https://cdn.example.com/images/widget-2.jpg"
            ),
        }
    )

    assert sanitized["additional_images"] == "https://cdn.example.com/images/widget-2.jpg"


def test_record_to_markdown_includes_page_context_from_raw_data() -> None:
    row = CrawlRecord(
        id=1,
        run_id=7,
        source_url="https://example.com/products/widget",
        data={"title": "Widget Prime", "price": "19.99"},
        raw_data={"page_markdown": "Widget Prime\n\nVisible links:\n- View specs -> /specs"},
        discovered_data={},
        source_trace={},
    )

    markdown = record_export_service.record_to_markdown(row)

    assert "## Page Context" not in markdown
    assert "Visible links:" in markdown
    assert "Widget Prime" in markdown


def test_record_to_markdown_keeps_listing_source_and_record_url_distinct() -> None:
    row = CrawlRecord(
        id=2,
        run_id=7,
        source_url="https://example.com/collections/widgets",
        data={
            "title": "Widget Prime",
            "url": "https://example.com/products/widget-prime",
            "price": "19.99",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )

    markdown = record_export_service.record_to_markdown(row)

    assert "Source: <https://example.com/collections/widgets>" in markdown
    assert "Record URL: <https://example.com/products/widget-prime>" in markdown


def test_clean_export_data_keeps_variant_payloads_but_hides_internal_markdown() -> None:
    cleaned = record_export_service.clean_export_data(
        {
            "title": "Widget Prime",
            "variants": [{"sku": "W-1", "color": "Black"}],
            "variant_axes": {"color": ["Black"]},
            "selected_variant": {"sku": "W-1", "color": "Black"},
            "page_markdown": "# internal",
            "_source": "dom",
        }
    )

    assert cleaned == {
        "title": "Widget Prime",
        "variants": [{"sku": "W-1", "color": "Black"}],
        "variant_axes": {"color": ["Black"]},
        "selected_variant": {"sku": "W-1", "color": "Black"},
    }


def test_listing_adapter_records_use_shared_surface_normalization() -> None:
    rows = extract_records(
        "<html><body></body></html>",
        "https://www.glossier.com/en-in/collections/makeup",
        "ecommerce_listing",
        max_records=5,
        adapter_records=[
            {
                "title": "Boy Brow",
                "brand": "Glossier",
                "url": "https://www.glossier.com/en-in/products/boy-brow",
                "image_url": "https://cdn.example.com/boy-brow-1.jpg",
                "additional_images": [
                    "https://cdn.example.com/boy-brow-2.jpg",
                ],
                "price": "2400",
                "availability": "in_stock",
                "description": "<p>Inspired by the flexible formula of mustache pomade.</p>",
                "variants": [
                    {"sku": "BBR-378-00-00", "title": "Dark Brown"},
                ],
                "variant_axes": {"shade": ["Dark Brown"]},
                "selected_variant": {"sku": "BBR-378-00-00"},
                "_source": "shopify_adapter",
            }
        ],
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["title"] == "Boy Brow"
    assert record["description"] == "Inspired by the flexible formula of mustache pomade."
    assert record["_source"] == "shopify_adapter"
    assert "additional_images" not in record
    assert "variants" not in record
    assert "variant_axes" not in record
    assert "selected_variant" not in record
