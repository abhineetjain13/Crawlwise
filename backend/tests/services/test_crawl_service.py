# Tests for crawl service — integration tests with fixture HTML.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun
from app.services.crawl_service import (
    active_jobs,
    cancel_run,
    create_crawl_run,
    get_run,
    list_runs,
    parse_csv_urls,
    process_run,
)


# --- CSV parsing ---

def test_parse_csv_urls_basic():
    csv = "url\nhttps://example.com/1\nhttps://example.com/2\n"
    urls = parse_csv_urls(csv)
    assert urls == ["https://example.com/1", "https://example.com/2"]


def test_parse_csv_urls_no_header():
    csv = "https://example.com/1\nhttps://example.com/2\n"
    urls = parse_csv_urls(csv)
    assert urls == ["https://example.com/1", "https://example.com/2"]


def test_parse_csv_urls_with_header():
    csv = "URL,Name\nhttps://example.com/1,Product 1\nhttps://example.com/2,Product 2\n"
    urls = parse_csv_urls(csv)
    assert urls == ["https://example.com/1", "https://example.com/2"]


def test_parse_csv_urls_empty():
    assert parse_csv_urls("") == []
    assert parse_csv_urls("header\nnot-a-url\n") == []


# --- CRUD ---

@pytest.mark.asyncio
async def test_create_crawl_run(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com",
        "surface": "ecommerce_detail",
    })
    assert run.id is not None
    assert run.status == "pending"
    assert run.url == "https://example.com"


@pytest.mark.asyncio
async def test_list_runs_with_filters(db_session: AsyncSession, test_user):
    await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl", "url": "https://a.com", "surface": "ecommerce_detail",
    })
    await create_crawl_run(db_session, test_user.id, {
        "run_type": "batch", "url": "https://b.com", "surface": "ecommerce_listing",
    })
    # Filter by run_type
    runs, total = await list_runs(db_session, 1, 20, run_type="crawl")
    assert total == 1
    assert runs[0].run_type == "crawl"


@pytest.mark.asyncio
async def test_cancel_run(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl", "url": "https://example.com", "surface": "ecommerce_detail",
    })
    updated = await cancel_run(db_session, run)
    assert updated.status == "cancelled"


# --- Pipeline ---

FIXTURE_HTML = """
<html><body>
<h1>Test Product</h1>
<span itemprop="price" content="29.99">$29.99</span>
<meta name="description" content="A great product for testing">
<script type="application/ld+json">
{"@type": "Product", "name": "JSON-LD Product", "brand": "TestBrand", "sku": "SKU123"}
</script>
</body></html>
"""


@pytest.mark.asyncio
async def test_process_run_single_url(db_session: AsyncSession, test_user):
    """Full pipeline test for a single detail page."""
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product",
        "surface": "ecommerce_detail",
    })

    with (
        patch("app.services.crawl_service.acquire_html", new_callable=AsyncMock,
              return_value=(FIXTURE_HTML, "curl_cffi", "/tmp/artifact.html", [])),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary["record_count"] >= 1

    # Check records
    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    assert len(records) >= 1
    assert "title" in records[0].data


@pytest.mark.asyncio
async def test_process_run_error_handling(db_session: AsyncSession, test_user):
    """Pipeline errors should mark run as failed, not leave it running."""
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/fail",
        "surface": "ecommerce_detail",
    })

    with patch("app.services.crawl_service.acquire_html", new_callable=AsyncMock,
               side_effect=ConnectionError("Network unreachable")):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "failed"
    assert "ConnectionError" in run.result_summary.get("error", "")


@pytest.mark.asyncio
async def test_process_run_batch(db_session: AsyncSession, test_user):
    """Batch crawl processes multiple URLs."""
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "batch",
        "url": "https://example.com/1",
        "surface": "ecommerce_detail",
        "settings": {"urls": ["https://example.com/1", "https://example.com/2"]},
    })

    with (
        patch("app.services.crawl_service.acquire_html", new_callable=AsyncMock,
              return_value=(FIXTURE_HTML, "curl_cffi", "/tmp/artifact.html", [])),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary["record_count"] >= 2


@pytest.mark.asyncio
async def test_process_run_listing_page(db_session: AsyncSession, test_user):
    """Listing page should extract multiple records from cards."""
    listing_html = """
    <html><body>
    <div class="product-card"><h3><a href="/p/1">Product A</a></h3><span class="price">$10</span></div>
    <div class="product-card"><h3><a href="/p/2">Product B</a></h3><span class="price">$20</span></div>
    <div class="product-card"><h3><a href="/p/3">Product C</a></h3><span class="price">$30</span></div>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/category",
        "surface": "ecommerce_listing",
    })

    with (
        patch("app.services.crawl_service.acquire_html", new_callable=AsyncMock,
              return_value=(listing_html, "curl_cffi", "/tmp/artifact.html", [])),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    assert len(records) == 3


@pytest.mark.asyncio
async def test_process_run_blocked_page(db_session: AsyncSession, test_user):
    """Blocked/empty page should not produce valid records."""
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/blocked",
        "surface": "ecommerce_detail",
    })

    with (
        patch("app.services.crawl_service.acquire_html", new_callable=AsyncMock,
              return_value=("", "curl_cffi", "/tmp/artifact.html", [])),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    # Should have a record with blocked status
    assert len(records) == 1
    assert records[0].data.get("_status") == "blocked"


@pytest.mark.asyncio
async def test_active_jobs(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl", "url": "https://example.com", "surface": "ecommerce_detail",
    })
    jobs = await active_jobs(db_session)
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"
