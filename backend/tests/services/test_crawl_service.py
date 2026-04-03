# Tests for crawl service — integration tests with fixture HTML.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.adapters.base import AdapterResult
from app.services.crawl_service import (
    active_jobs,
    cancel_run,
    create_crawl_run,
    get_run,
    list_runs,
    parse_csv_urls,
    process_run,
)


def _make_acq(html: str = "", **kwargs) -> AcquisitionResult:
    """Helper to build an AcquisitionResult for test mocks."""
    return AcquisitionResult(
        html=html,
        json_data=kwargs.get("json_data"),
        content_type=kwargs.get("content_type", "html"),
        method=kwargs.get("method", "curl_cffi"),
        artifact_path=kwargs.get("artifact_path", "/tmp/artifact.html"),
        network_payloads=kwargs.get("network_payloads", []),
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
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock,
              return_value=_make_acq(FIXTURE_HTML)),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary["record_count"] >= 1
    assert run.result_summary["current_stage"] == "PUBLISH"
    assert run.result_summary["current_url"] == "https://example.com/product"

    # Check records
    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    assert len(records) >= 1
    assert "title" in records[0].data
    logs = (await db_session.execute(
        select(CrawlLog).where(CrawlLog.run_id == run.id)
    )).scalars().all()
    assert any("[UNIFY]" in log.message for log in logs)


@pytest.mark.asyncio
async def test_process_run_error_handling(db_session: AsyncSession, test_user):
    """Pipeline errors should mark run as failed, not leave it running."""
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/fail",
        "surface": "ecommerce_detail",
    })

    with patch("app.services.crawl_service.acquire", new_callable=AsyncMock,
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
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock,
              return_value=_make_acq(FIXTURE_HTML)),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary["record_count"] >= 2
    assert run.result_summary["processed_urls"] == 2
    assert run.result_summary["completed_urls"] == 2
    assert run.result_summary["remaining_urls"] == 0


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
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock,
              return_value=_make_acq(listing_html)),
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
    """Blocked/empty page should not produce valid records and should mark as failed."""
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/blocked",
        "surface": "ecommerce_detail",
    })

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock,
              return_value=_make_acq("")),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    # Blocked pages now mark the run as failed, not completed
    assert run.status == "failed"
    assert run.result_summary.get("extraction_verdict") == "blocked"
    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    # Should have a record with blocked status
    assert len(records) == 1
    assert records[0].data.get("_status") == "blocked"


@pytest.mark.asyncio
async def test_process_run_challenge_page(db_session: AsyncSession, test_user):
    """Challenge/anti-bot page should be detected and marked as blocked."""
    challenge_html = """
    <html><head><title>Robot or human?</title></head>
    <body>
    <div>Please verify you are a human</div>
    <div class="px-captcha">Complete the security check</div>
    <script src="perimeterx.js"></script>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/challenge",
        "surface": "ecommerce_detail",
    })

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock,
              return_value=_make_acq(challenge_html)),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "failed"
    assert run.result_summary.get("extraction_verdict") == "blocked"


@pytest.mark.asyncio
async def test_process_run_blocked_shopify_listing_recovers_via_public_endpoint(db_session: AsyncSession, test_user):
    challenge_html = """
    <html><head><title>Just a moment...</title></head>
    <body>
    <div>Checking your browser before accessing the site</div>
    <div class="cf-challenge"></div>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://store.com/collections/maternity-dresses",
        "surface": "ecommerce_listing",
    })

    recovered = AdapterResult(
        records=[
            {
                "title": "Recovered Dress",
                "brand": "BrandX",
                "price": "89.00",
                "url": "https://store.com/products/recovered-dress",
            }
        ],
        source_type="shopify_adapter_recovery",
        confidence=0.95,
        adapter_name="shopify",
    )

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock,
              return_value=_make_acq(challenge_html)),
        patch("app.services.crawl_service.try_blocked_adapter_recovery", new_callable=AsyncMock,
              return_value=recovered),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary.get("record_count") == 1
    assert run.result_summary.get("extraction_verdict") == "success"
    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    assert len(records) == 1
    assert records[0].data["title"] == "Recovered Dress"


@pytest.mark.asyncio
async def test_process_run_json_api(db_session: AsyncSession, test_user):
    """JSON API response should be extracted via the JSON path."""
    json_payload = {
        "jobs": [
            {"title": "Engineer", "company_name": "Acme", "url": "/jobs/1"},
            {"title": "Designer", "company_name": "Beta", "url": "/jobs/2"},
        ]
    }
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://api.example.com/jobs",
        "surface": "job_listing",
    })

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock,
              return_value=_make_acq("", json_data=json_payload, content_type="json")),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary["record_count"] == 2
    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    assert len(records) == 2
    titles = {r.data["title"] for r in records}
    assert "Engineer" in titles
    assert "Designer" in titles


@pytest.mark.asyncio
async def test_process_run_listing_no_records_fails(db_session: AsyncSession, test_user):
    """Listing page with no extractable records should be marked degraded, not completed."""
    empty_listing_html = """
    <html><body>
    <h1>Products</h1>
    <p>No products found matching your criteria.</p>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/empty-category",
        "surface": "ecommerce_listing",
    })

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock,
              return_value=_make_acq(empty_listing_html)),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    # Should NOT be "completed" — listing extraction failed
    assert run.status == "degraded"
    assert run.result_summary.get("extraction_verdict") == "listing_detection_failed"


@pytest.mark.asyncio
async def test_extraction_verdict_in_summary(db_session: AsyncSession, test_user):
    """Successful runs should have extraction_verdict=success in result_summary."""
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product",
        "surface": "ecommerce_detail",
    })

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock,
              return_value=_make_acq(FIXTURE_HTML)),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert "extraction_verdict" in run.result_summary
    assert run.result_summary["extraction_verdict"] in ("success", "partial")


@pytest.mark.asyncio
async def test_active_jobs(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl", "url": "https://example.com", "surface": "ecommerce_detail",
    })
    jobs = await active_jobs(db_session)
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"
