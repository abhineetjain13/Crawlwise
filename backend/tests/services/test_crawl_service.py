# Tests for crawl service — integration tests with fixture HTML.
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlLog, CrawlRecord, ReviewPromotion
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.adapters.base import AdapterResult
from app.services.crawl_state import set_control_request
from app.services.crawl_service import (
    _build_field_discovery_summary,
    _build_llm_candidate_evidence,
    _merge_record_fields,
    _normalize_detail_candidate_values,
    active_jobs,
    commit_selected_fields,
    create_crawl_run,
    delete_run,
    get_run,
    kill_run,
    list_runs,
    parse_csv_urls,
    pause_run,
    process_run,
    resume_run,
)
from app.services.site_memory_service import merge_memory


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


def test_build_llm_candidate_evidence_preserves_legible_multi_source_values():
    evidence = _build_llm_candidate_evidence(
        {
            "description": [
                {"value": "<p>Sequential <strong>analog</strong> polysynth</p>", "source": "dom"},
                {"value": "Sequential analog polysynth", "source": "json_ld"},
            ],
            "polyphony": [
                {"value": "16 Voice", "source": "semantic_section"},
            ],
        },
        {"title": "Prophet Rev2", "description": "Sequential analog polysynth"},
    )

    assert evidence["title"][0]["source"] == "current_output"
    assert evidence["description"][0]["value"] == "Sequential analog polysynth"
    assert any(row["source"] == "semantic_section" for row in evidence["polyphony"])


def test_build_field_discovery_summary_includes_canonical_and_intelligence_fields():
    source_trace = _build_field_discovery_summary(
        {},
        {
            "title": [{"value": "Canonical Title", "source": "adapter"}],
            "wire_gauge": [{"value": "26 AWG", "source": "semantic_spec"}],
        },
        {"title": "Canonical Title"},
        [],
        "ecommerce_detail",
    )

    field_discovery = source_trace["field_discovery"]
    assert field_discovery["title"]["tier"] == "canonical"
    assert field_discovery["title"]["candidate_count"] == 1
    assert field_discovery["title"]["value"] == "Canonical Title"
    assert field_discovery["wire_gauge"]["tier"] == "intelligence"
    assert field_discovery["wire_gauge"]["candidate_count"] == 1
    assert field_discovery["wire_gauge"]["value"] == "26 AWG"
    assert "title" not in source_trace["field_discovery_missing"]
    assert "wire_gauge" not in source_trace["field_discovery_missing"]
    assert "price" in source_trace["field_discovery_missing"]


def test_build_field_discovery_summary_tolerates_candidate_rows_without_value_key():
    source_trace = _build_field_discovery_summary(
        {},
        {
            "title": [{"source": "adapter"}],
        },
        {},
        [],
        "ecommerce_detail",
    )

    assert source_trace["field_discovery"]["title"]["status"] == "found"
    assert source_trace["field_discovery"]["title"].get("value") is None


def test_normalize_detail_candidate_values_dedupes_primary_image_from_additional_images():
    normalized = _normalize_detail_candidate_values(
        {
            "image_url": "https://example.com/images/main.jpg",
            "additional_images": "https://example.com/images/main.jpg, https://example.com/images/alt.jpg",
        },
        url="https://example.com/product",
    )

    assert normalized["image_url"] == "https://example.com/images/main.jpg"
    assert normalized["additional_images"] == "https://example.com/images/alt.jpg"


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
async def test_create_crawl_run_normalizes_job_listing_urls_from_ecommerce_surface(
    db_session: AsyncSession, test_user
):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://www.dice.com/jobs",
        "surface": "ecommerce_listing",
    })

    assert run.surface == "job_listing"


@pytest.mark.asyncio
async def test_create_crawl_run_normalizes_job_detail_urls_from_ecommerce_surface(
    db_session: AsyncSession, test_user
):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://www.dice.com/job-detail/1c33f6c6-b536-48ed-8f3d-b6e1eddf03e1",
        "surface": "ecommerce_detail",
    })

    assert run.surface == "job_detail"


@pytest.mark.asyncio
async def test_create_crawl_run_clamps_sleep_ms_to_minimum_floor(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com",
        "surface": "ecommerce_detail",
        "settings": {"sleep_ms": 0},
    })

    assert run.settings["sleep_ms"] == 100


@pytest.mark.asyncio
async def test_create_crawl_run_coerces_max_pages_to_int(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com",
        "surface": "ecommerce_detail",
        "settings": {"max_pages": "7"},
    })

    assert run.settings["max_pages"] == 7


@pytest.mark.asyncio
async def test_create_crawl_run_keeps_advanced_mode_empty_without_explicit_traversal_and_coerces_max_scrolls(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com",
        "surface": "ecommerce_listing",
        "settings": {"advanced_enabled": True, "max_scrolls": "12"},
    })

    assert run.settings["advanced_mode"] is None
    assert run.settings["max_scrolls"] == 12


@pytest.mark.asyncio
async def test_create_crawl_run_includes_site_memory_fields(db_session: AsyncSession, test_user):
    await merge_memory(db_session, "https://example.com/products/widget", fields=["materials", "care"])

    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/products/widget",
        "surface": "ecommerce_detail",
    })

    assert "materials" in run.requested_fields
    assert "care" in run.requested_fields


@pytest.mark.asyncio
async def test_create_crawl_run_rejects_private_ip_targets(db_session: AsyncSession, test_user):
    with pytest.raises(ValueError, match="non-public IP address"):
        await create_crawl_run(db_session, test_user.id, {
            "run_type": "crawl",
            "url": "http://127.0.0.1/admin",
            "surface": "ecommerce_detail",
        })


@pytest.mark.asyncio
async def test_create_crawl_run_rejects_hostnames_that_resolve_private(db_session: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch):
    async def _resolve_private(_hostname: str, _port: int) -> list[str]:
        return ["10.0.0.8"]

    monkeypatch.setattr(
        "app.services.url_safety._resolve_host_ips",
        _resolve_private,
    )

    with pytest.raises(ValueError, match="non-public IP address"):
        await create_crawl_run(db_session, test_user.id, {
            "run_type": "crawl",
            "url": "https://internal-proxy.example",
            "surface": "ecommerce_detail",
        })


@pytest.mark.asyncio
async def test_create_crawl_run_rejects_unresolved_targets(db_session: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch):
    async def _raise_unresolved(_hostname: str, _port: int) -> list[str]:
        raise ValueError("Target host could not be resolved: broken.example")

    monkeypatch.setattr("app.services.url_safety._resolve_host_ips", _raise_unresolved)

    with pytest.raises(ValueError, match="could not be resolved"):
        await create_crawl_run(db_session, test_user.id, {
            "run_type": "crawl",
            "url": "https://broken.example",
            "surface": "ecommerce_detail",
        })


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
async def test_pause_resume_and_kill_run(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl", "url": "https://example.com", "surface": "ecommerce_detail",
    })
    run.status = "running"
    await db_session.commit()

    paused = await pause_run(db_session, run)
    assert paused.status == "running"
    assert paused.result_summary["control_requested"] == "pause"

    paused.status = "paused"
    paused.result_summary = {
        **(paused.result_summary or {}),
        "control_requested": None,
    }
    await db_session.commit()

    resumed = await resume_run(db_session, paused)
    assert resumed.status == "running"

    killed = await kill_run(db_session, resumed)
    assert killed.status == "running"
    assert killed.result_summary["control_requested"] == "kill"


@pytest.mark.asyncio
async def test_delete_run_removes_terminal_runs(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl", "url": "https://example.com", "surface": "ecommerce_detail",
    })
    run.status = "completed"
    await db_session.commit()

    await delete_run(db_session, run)

    assert await get_run(db_session, run.id) is None


@pytest.mark.asyncio
async def test_delete_run_rejects_active_runs(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl", "url": "https://example.com", "surface": "ecommerce_detail",
    })

    with pytest.raises(ValueError, match="Cannot delete run"):
        await delete_run(db_session, run)


@pytest.mark.asyncio
async def test_commit_selected_fields_normalizes_display_style_field_names(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product",
        "surface": "ecommerce_detail",
    })
    record = CrawlRecord(
        run_id=run.id,
        source_url=run.url,
        data={"title": "Widget"},
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    updated_records, updated_fields = await commit_selected_fields(
        db_session,
        run=run,
        items=[{"record_id": record.id, "field_name": "Description", "value": "Clean text"}],
    )

    refreshed = await db_session.get(CrawlRecord, record.id)
    assert updated_records == 1
    assert updated_fields == 1
    assert refreshed is not None
    assert refreshed.data["description"] == "Clean text"
    assert "Description" not in refreshed.data


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
async def test_process_run_applies_kill_during_inflight_acquire_wait(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product",
        "surface": "ecommerce_detail",
    })

    async def fake_acquire(*_args, checkpoint=None, **_kwargs):
        current = await db_session.get(type(run), run.id)
        assert current is not None
        set_control_request(current, "kill")
        await db_session.commit()
        assert checkpoint is not None
        await checkpoint()
        raise AssertionError("checkpoint should have interrupted acquire")

    with patch("app.services.crawl_service.acquire", new=fake_acquire):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "killed"
    assert run.result_summary.get("control_requested") is None


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
async def test_process_run_resumes_from_completed_urls_not_processed_urls(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "batch",
        "url": "https://example.com/1",
        "surface": "ecommerce_detail",
        "settings": {"urls": ["https://example.com/1", "https://example.com/2", "https://example.com/3"]},
    })
    run.status = "running"
    run.result_summary = {
        **(run.result_summary or {}),
        "processed_urls": 2,
        "completed_urls": 1,
        "url_verdicts": ["success"],
        "verdict_counts": {"success": 1},
    }
    await db_session.commit()

    seen_urls: list[str] = []

    async def _fake_process_single_url(**kwargs):
        seen_urls.append(kwargs["url"])
        return ([{"title": kwargs["url"]}], "success", {"method": "curl_cffi", "record_count": 1})

    with patch("app.services.crawl_service._process_single_url", side_effect=_fake_process_single_url):
        await process_run(db_session, run.id)

    assert seen_urls == ["https://example.com/2", "https://example.com/3"]


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
    """Listing page with no extractable records should be marked failed, not completed."""
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
    assert run.status == "failed"
    assert run.result_summary.get("extraction_verdict") == "listing_detection_failed"


@pytest.mark.asyncio
async def test_process_run_listing_retries_with_browser_after_weak_curl_listing(db_session: AsyncSession, test_user):
    weak_listing_html = """
    <html><body>
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"CollectionPage","mainEntity":{
        "@type":"ItemList",
        "itemListElement":[
          {"@type":"ListItem","position":1,"url":"https://example.com/p/one"},
          {"@type":"ListItem","position":2,"url":"https://example.com/p/two"}
        ]
      }}
      </script>
    </body></html>
    """
    browser_listing_html = """
    <html><body>
      <div class="product-card"><h3><a href="/p/1">Product A</a></h3><span class="price">$10</span></div>
      <div class="product-card"><h3><a href="/p/2">Product B</a></h3><span class="price">$20</span></div>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/category",
        "surface": "ecommerce_listing",
    })

    acquire_mock = AsyncMock(side_effect=[
        _make_acq(weak_listing_html, method="curl_cffi"),
        _make_acq(browser_listing_html, method="playwright"),
    ])

    with (
        patch("app.services.crawl_service.acquire", acquire_mock),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary.get("record_count") == 2
    assert acquire_mock.await_count == 2
    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    assert len(records) == 2
    assert {record.data["title"] for record in records} == {"Product A", "Product B"}


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
async def test_process_run_records_acquisition_summary_metrics(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product",
        "surface": "ecommerce_detail",
    })

    with (
        patch(
            "app.services.crawl_service.acquire",
            new_callable=AsyncMock,
            return_value=_make_acq(
                FIXTURE_HTML,
                method="playwright",
                network_payloads=[{"url": "https://api.example.com/product", "body": {"id": 1}}],
            ),
        ),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    summary = run.result_summary["acquisition_summary"]
    assert summary["methods"]["playwright"] == 1
    assert summary["browser_used_urls"] == 1
    assert summary["network_payloads_total"] == 1


def test_merge_record_fields_prefers_richer_detail_description():
    merged = _merge_record_fields(
        {"title": "Widget", "description": "Short desc"},
        {"description": "A much richer product description with more detail and context."},
    )
    assert merged["description"] == "A much richer product description with more detail and context."


@pytest.mark.asyncio
async def test_process_run_passes_max_pages_to_acquire(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/listing",
        "surface": "ecommerce_listing",
        "settings": {"advanced_mode": "paginate", "max_pages": 3},
    })

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock, return_value=_make_acq("<html><body></body></html>")) as acquire_mock,
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=AdapterResult(adapter_name="test", records=[{"title": "Item", "url": "https://example.com/item"}])),
    ):
        await process_run(db_session, run.id)

    assert acquire_mock.await_args.kwargs["max_pages"] == 3


@pytest.mark.asyncio
async def test_process_run_does_not_infer_advanced_mode_from_toggle_and_passes_max_scrolls_to_acquire(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/listing",
        "surface": "ecommerce_listing",
        "settings": {"advanced_enabled": True, "max_scrolls": 9},
    })

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock, return_value=_make_acq("<html><body></body></html>")) as acquire_mock,
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=AdapterResult(adapter_name="test", records=[{"title": "Item", "url": "https://example.com/item"}])),
    ):
        await process_run(db_session, run.id)

    assert acquire_mock.await_args.kwargs["advanced_mode"] is None
    assert acquire_mock.await_args.kwargs["max_scrolls"] == 9


@pytest.mark.asyncio
async def test_process_run_filters_detail_data_to_canonical_fields_and_routes_extras_to_review_bucket(db_session: AsyncSession, test_user):
    detail_html = """
    <html><body>
      <h1>Example Product</h1>
      <table>
        <tr><td>Wire Gauge</td><td>26 AWG</td></tr>
      </table>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product",
        "surface": "ecommerce_detail",
    })

    adapter = AdapterResult(
        adapter_name="test",
        records=[{"title": "Example Product", "price": "19.99", "wire_gauge": "26 AWG"}],
    )

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock, return_value=_make_acq(detail_html)),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=adapter),
    ):
        await process_run(db_session, run.id)

    record = (await db_session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run.id))).scalars().one()
    assert "wire_gauge" not in record.data
    assert record.discovered_data["review_bucket"][0]["key"] == "wire_gauge"
    assert record.discovered_data["review_bucket"][0]["value"] == "26 AWG"
    assert record.source_trace["manifest_trace"]["tables"][0]["rows"][0]["cells"][1]["text"] == "26 AWG"


@pytest.mark.asyncio
async def test_process_run_stores_llm_cleanup_suggestions_without_auto_promoting_fields(db_session: AsyncSession, test_user):
    detail_html = """
    <html><head>
    <meta name="description" content="Marketing description for the Prophet Rev2.">
    </head><body>
    <h1>Sequential Prophet Rev2</h1>
    <div class="description"><p>Sequential <strong>Prophet Rev2</strong> with lush analog tone.</p></div>
    <h2>Tech Specs</h2>
    <ul>
      <li>Type: Keyboard Synthesizer with Sequencer</li>
      <li>Number of Keys: 61</li>
      <li>Polyphony: 16 Voice</li>
    </ul>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Sequential Prophet Rev2", "brand": "Sequential", "sku": "REV2-16", "description": "Structured description for the Prophet Rev2."}
    </script>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/rev2",
        "surface": "ecommerce_detail",
        "settings": {"llm_enabled": True},
    })

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock, return_value=_make_acq(detail_html)),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
        patch("app.services.crawl_service.discover_xpath_candidates", new_callable=AsyncMock, return_value=([], None)),
        patch(
            "app.services.crawl_service.review_field_candidates",
            new_callable=AsyncMock,
            return_value=(
                {
                    "canonical": {
                        "description": {
                            "suggested_value": "Sequential Prophet Rev2 with lush analog tone.",
                            "source": "semantic_section",
                            "supporting_sources": ["dom", "semantic_section"],
                            "note": "Removed markup and preserved the descriptive sentence.",
                        },
                        "polyphony": {
                            "suggested_value": "16 Voice",
                            "source": "semantic_section",
                            "supporting_sources": ["semantic_section"],
                        },
                        "number_of_keys": {
                            "suggested_value": "61",
                            "source": "semantic_section",
                            "supporting_sources": ["semantic_section"],
                        },
                    },
                    "review_bucket": [
                        {
                            "key": "oscillator_count",
                            "value": 2,
                            "confidence_score": 8,
                            "source": "semantic_section",
                        }
                    ],
                },
                None,
            ),
        ),
    ):
        await process_run(db_session, run.id)

    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    assert len(records) == 1
    source_trace = records[0].source_trace or {}
    suggestions = source_trace.get("llm_cleanup_suggestions") or {}
    assert suggestions["description"]["suggested_value"] == "Sequential Prophet Rev2 with lush analog tone."
    assert suggestions["description"]["supporting_sources"] == ["dom", "semantic_section"]
    assert suggestions["polyphony"]["suggested_value"] == "16 Voice"
    assert suggestions["number_of_keys"]["suggested_value"] == "61"
    assert records[0].discovered_data["review_bucket"][0]["key"] == "oscillator_count"
    assert "polyphony" not in records[0].data
    assert "number_of_keys" not in records[0].data


@pytest.mark.asyncio
async def test_commit_selected_fields_preserves_typed_values_and_refreshes_metadata(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/rev2",
        "surface": "ecommerce_detail",
        "additional_fields": ["dimensions", "number_of_keys"],
    })
    record = CrawlRecord(
        run_id=run.id,
        source_url=run.url,
        data={"title": "Sequential Prophet Rev2"},
        raw_data={"title": "Sequential Prophet Rev2"},
        discovered_data={"requested_field_coverage": {"requested": 2, "found": 0, "missing": ["dimensions", "number_of_keys"]}},
        source_trace={
            "field_discovery": {
                "dimensions": {"status": "not_found"},
                "number_of_keys": {"status": "not_found"},
            },
            "field_discovery_missing": ["dimensions", "number_of_keys"],
            "llm_cleanup_suggestions": {
                "dimensions": {"suggested_value": {"width": "10 cm", "height": "20 cm"}, "source": "llm_cleanup", "status": "pending_review"},
            },
        },
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    updated_records, updated_fields = await commit_selected_fields(
        db_session,
        run=run,
        items=[
            {"record_id": record.id, "field_name": "dimensions", "value": {"width": "10 cm", "height": "20 cm"}},
            {"record_id": record.id, "field_name": "number_of_keys", "value": 61},
        ],
    )

    await db_session.refresh(record)
    assert updated_records == 1
    assert updated_fields == 2
    assert record.data["dimensions"] == {"width": "10 cm", "height": "20 cm"}
    assert record.data["number_of_keys"] == 61
    assert record.source_trace["field_discovery"]["dimensions"]["status"] == "found"
    assert record.source_trace["field_discovery"]["dimensions"]["sources"] == ["user_commit"]
    assert record.source_trace["field_discovery"]["number_of_keys"]["value"] == "61"
    assert record.source_trace["field_discovery_missing"] == []
    assert record.discovered_data["requested_field_coverage"] == {"requested": 2, "found": 2, "missing": []}
    assert record.source_trace["llm_cleanup_suggestions"]["dimensions"]["status"] == "accepted"


@pytest.mark.asyncio
async def test_create_crawl_run_reuses_domain_approved_fields(db_session: AsyncSession, test_user):
    seed_run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product/seed",
        "surface": "ecommerce_detail",
    })
    db_session.add(
        ReviewPromotion(
            run_id=seed_run.id,
            domain="example.com",
            surface="ecommerce_detail",
            approved_schema={"fields": ["polyphony", "number_of_keys"]},
            field_mapping={"polyphony": "polyphony", "number_of_keys": "number_of_keys"},
            selector_memory={},
        )
    )
    await db_session.commit()

    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product/rev2",
        "surface": "ecommerce_detail",
        "additional_fields": ["finish"],
    })

    assert run.requested_fields == ["polyphony", "number_of_keys", "finish"]
    assert run.settings["domain_requested_fields"] == ["polyphony", "number_of_keys"]


@pytest.mark.asyncio
async def test_process_run_skips_cleanup_llm_when_deterministic_fields_are_unambiguous(db_session: AsyncSession, test_user):
    detail_html = """
    <html><body>
    <h1>Deterministic Product Title</h1>
    <meta name="description" content="Structured detail description">
    <script type="application/ld+json">
    {"@type": "Product", "name": "Deterministic Product Title", "brand": "TestBrand", "sku": "SKU-1"}
    </script>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/deterministic",
        "surface": "ecommerce_detail",
        "settings": {"llm_enabled": True},
    })

    with (
        patch("app.services.crawl_service.acquire", new_callable=AsyncMock, return_value=_make_acq(detail_html)),
        patch("app.services.crawl_service.run_adapter", new_callable=AsyncMock, return_value=None),
        patch("app.services.crawl_service.discover_xpath_candidates", new_callable=AsyncMock, return_value=([], None)),
        patch("app.services.crawl_service.review_field_candidates", new_callable=AsyncMock) as review_mock,
    ):
        await process_run(db_session, run.id)

    review_mock.assert_not_awaited()
    record = (
        await db_session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run.id))
    ).scalar_one()
    assert record.source_trace["llm_cleanup_status"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_active_jobs(db_session: AsyncSession, test_user):
    await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl", "url": "https://example.com", "surface": "ecommerce_detail",
    })
    jobs = await active_jobs(db_session)
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"
