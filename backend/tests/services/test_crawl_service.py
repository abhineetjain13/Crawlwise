# Tests for crawl service — integration tests with fixture HTML.
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app.core.security import hash_password
from app.core.telemetry import reset_correlation_id, set_correlation_id
from app.models.crawl import CrawlLog, CrawlRecord
from app.models.user import User
from app.services.acquisition.acquirer import AcquisitionRequest, AcquisitionResult
from app.services.adapters.base import AdapterResult
from app.services.crawl_service import (
    kill_run,
    pause_run,
    process_run,
    resume_run,
)
from app.services.crawl_crud import (
    active_jobs,
    commit_selected_fields,
    create_crawl_run,
    delete_run,
    get_run,
    list_runs,
)
from app.services.crawl_utils import parse_csv_urls
from app.services.pipeline.core import STAGE_SAVE
from app.services.extract.candidate_processing import sanitize_field_value
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.services._duplication_helpers import (
    adapter_result,
    food_processor_listing_html,
    html_page,
    job_card,
    product_card,
)


class _MissingRunRef:
    id = -999999


def _make_acq(html: str = "", **kwargs) -> AcquisitionResult:
    """Helper to build an AcquisitionResult for test mocks."""
    return AcquisitionResult(
        html=html,
        json_data=kwargs.get("json_data"),
        content_type=kwargs.get("content_type", "html"),
        method=kwargs.get("method", "curl_cffi"),
        artifact_path=kwargs.get("artifact_path", "/tmp/artifact.html"),
        network_payloads=kwargs.get("network_payloads", []),
        diagnostics=kwargs.get("diagnostics", {}),
    )


async def _process_run_with_acquisition(
    db_session: AsyncSession,
    run,
    acquisition: AcquisitionResult,
    *,
    adapter: AdapterResult | None = None,
) -> None:
    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock, return_value=acquisition),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=adapter),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)


async def _get_run_records(db_session: AsyncSession, run_id: int):
    return (
        await db_session.execute(
            select(CrawlRecord).where(CrawlRecord.run_id == run_id).order_by(CrawlRecord.id.asc())
        )
    ).scalars().all()


def _elementor_job_card(*, href: str, title: str, excerpt: str) -> str:
    return (
        '<article class="elementor-post elementor-grid-item post type-post status-publish category-jobs">'
        '<div class="elementor-post__text">'
        f'<h3 class="elementor-post__title"><a href="{href}">{title}</a></h3>'
        f'<div class="elementor-post__excerpt"><p>{excerpt}</p></div>'
        "</div></article>"
    )


def _elementor_jobs_html(*cards: tuple[str, str, str]) -> str:
    return html_page(
        "<main>",
        *(_elementor_job_card(href=href, title=title, excerpt=excerpt) for href, title, excerpt in cards),
        "</main>",
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
async def test_create_crawl_run_sets_correlation_id_from_request_context(
    db_session: AsyncSession, test_user
):
    token = set_correlation_id("req-test-correlation")
    try:
        run = await create_crawl_run(db_session, test_user.id, {
            "run_type": "crawl",
            "url": "https://example.com",
            "surface": "ecommerce_detail",
        })
    finally:
        reset_correlation_id(token)

    assert run.result_summary["correlation_id"] == "req-test-correlation"


@pytest.mark.asyncio
async def test_create_crawl_run_preserves_user_requested_listing_surface_for_job_urls(
    db_session: AsyncSession, test_user
):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://www.dice.com/jobs",
        "surface": "ecommerce_listing",
    })

    assert run.surface == "ecommerce_listing"


@pytest.mark.asyncio
async def test_create_crawl_run_preserves_user_requested_detail_surface_for_job_urls(
    db_session: AsyncSession, test_user
):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://www.dice.com/job-detail/1c33f6c6-b536-48ed-8f3d-b6e1eddf03e1",
        "surface": "ecommerce_detail",
    })

    assert run.surface == "ecommerce_detail"


@pytest.mark.asyncio
async def test_create_crawl_run_preserves_requested_surface_for_hash_routes(
    db_session: AsyncSession, test_user
):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://practicesoftwaretesting.com/#/product/01HB",
        "surface": "ecommerce_listing",
    })

    assert run.surface == "ecommerce_listing"


@pytest.mark.asyncio
async def test_create_crawl_run_unescapes_html_entity_urls(
    db_session: AsyncSession, test_user
):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=tenant&amp;ccId=19000101_000001&amp;type=MP",
        "surface": "job_listing",
    })

    assert run.url == "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=tenant&ccId=19000101_000001&type=MP"


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
async def test_create_crawl_run_preserves_advanced_mode_contract_and_coerces_max_scrolls(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com",
        "surface": "ecommerce_listing",
        "settings": {"max_scrolls": "12", "advanced_enabled": True, "advanced_mode": "paginate"},
    })

    assert run.settings["traversal_mode"] == "paginate"
    assert run.settings["advanced_enabled"] is True
    assert run.settings["advanced_mode"] == "paginate"
    assert run.settings["max_scrolls"] == 12


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
async def test_list_runs_url_search_treats_wildcards_as_literals(db_session: AsyncSession, test_user):
    await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product_100%real",
            "surface": "ecommerce_detail",
        },
    )
    await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product-100-real",
            "surface": "ecommerce_detail",
        },
    )

    runs, total = await list_runs(db_session, 1, 20, url_search="100%real")
    assert total == 1
    assert len(runs) == 1
    assert runs[0].url.endswith("product_100%real")


@pytest.mark.asyncio
async def test_pause_resume_and_kill_run(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("app.services.crawl_service.settings.celery_dispatch_enabled", True)
    monkeypatch.setattr(
        "app.services.crawl_service.settings.legacy_inprocess_runner_enabled", False
    )
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl", "url": "https://example.com", "surface": "ecommerce_detail",
    })
    run.status = "running"
    run.result_summary = {"celery_task_id": "task-running"}
    await db_session.commit()

    with (
        patch("app.services.crawl_service.process_run_task.app.control.revoke") as revoke_mock,
        patch("app.services.crawl_service.process_run_task.apply_async") as apply_async_mock,
        patch("app.services.crawl_service._log", new_callable=AsyncMock),
    ):
        paused = await pause_run(db_session, run)
        assert paused.status == "paused"
        assert paused.result_summary.get("celery_task_id") is None
        revoke_mock.assert_called_once_with("task-running", terminate=True)

        paused.result_summary = {}
        await db_session.commit()

        resumed = await resume_run(db_session, paused)
        assert resumed.status == "running"
        assert resumed.result_summary.get("celery_task_id")
        apply_async_mock.assert_called_once()

        next_task_id = resumed.result_summary["celery_task_id"]
        killed = await kill_run(db_session, resumed)
        assert killed.status == "killed"
        assert killed.result_summary.get("celery_task_id") is None
        assert revoke_mock.call_args_list[-1].kwargs == {
            "terminate": True,
        }
        assert revoke_mock.call_args_list[-1].args == (next_task_id,)


@pytest.mark.asyncio
@pytest.mark.parametrize("op", [pause_run, resume_run, kill_run])
async def test_control_ops_raise_run_not_found_for_missing_run_reference(
    db_session: AsyncSession, op
):
    with pytest.raises(ValueError, match="Run not found"):
        await op(db_session, _MissingRunRef())


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

    await _process_run_with_acquisition(db_session, run, _make_acq(FIXTURE_HTML))
    assert run.status == "completed"
    assert run.result_summary["record_count"] >= 1
    assert run.result_summary["current_stage"] == STAGE_SAVE
    assert run.result_summary["current_url"] == "https://example.com/product"

    # Check records
    records = await _get_run_records(db_session, run.id)
    assert len(records) >= 1
    assert "title" in records[0].data
    logs = (await db_session.execute(
        select(CrawlLog).where(CrawlLog.run_id == run.id)
    )).scalars().all()
    assert any("[SAVE]" in log.message for log in logs)


@pytest.mark.asyncio
async def test_process_run_applies_kill_during_inflight_acquire_wait(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product",
        "surface": "ecommerce_detail",
    })
    run.status = "running"
    run.result_summary = {"celery_task_id": "task-inflight"}
    await db_session.commit()

    with (
        patch("app.services.crawl_service.process_run_task.app.control.revoke") as revoke_mock,
        patch("app.services.crawl_service._log", new_callable=AsyncMock),
    ):
        killed = await kill_run(db_session, run)

    assert killed.status == "killed"
    revoke_mock.assert_called_once_with("task-inflight", terminate=True)


@pytest.mark.asyncio
async def test_process_run_error_handling(db_session: AsyncSession, test_user):
    """Pipeline errors should mark run as failed, not leave it running."""
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/fail",
        "surface": "ecommerce_detail",
    })

    with patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
               side_effect=ConnectionError("Network unreachable")):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "failed"
    assert "ConnectionError" in run.result_summary.get("error", "")


@pytest.mark.asyncio
async def test_process_run_honors_per_url_timeout_setting(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/slow",
        "surface": "ecommerce_detail",
        "settings": {"url_timeout_seconds": 0.01},
    })

    async def _slow_process_single_url(**_kwargs):
        await asyncio.sleep(0.2)
        return [], "empty", {}

    with patch("app.services._batch_runtime._process_single_url", side_effect=_slow_process_single_url):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "failed"
    assert "timed out" in str(run.result_summary.get("error", "")).lower()



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
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
              return_value=_make_acq(FIXTURE_HTML)),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
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

    with patch("app.services._batch_runtime._process_single_url", side_effect=_fake_process_single_url):
        await process_run(db_session, run.id)

    assert seen_urls == ["https://example.com/2", "https://example.com/3"]


@pytest.mark.asyncio
async def test_process_run_multi_run_concurrency_keeps_status_and_summary_consistent(
    db_session: AsyncSession,
):
    assert db_session.bind is not None
    session_factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    user = User(
        email="concurrency@example.com",
        hashed_password=hash_password("password123"),
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    run_a = await create_crawl_run(
        db_session,
        user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/listing-a",
            "surface": "ecommerce_listing",
        },
    )
    run_b = await create_crawl_run(
        db_session,
        user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/listing-b",
            "surface": "ecommerce_listing",
        },
    )
    run_ids = [run_a.id, run_b.id]

    async def _run_one(run_id: int) -> None:
        async with session_factory() as session:
            await process_run(session, run_id)

    with (
        patch(
            "app.services.pipeline.core.acquire",
            new_callable=AsyncMock,
            return_value=_make_acq(
                "<html><body><div class='product-card'><a href='/p/1'>One</a><span class='price'>$10</span></div>"
                "<div class='product-card'><a href='/p/2'>Two</a><span class='price'>$20</span></div></body></html>",
                method="curl_cffi",
            ),
        ),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await asyncio.gather(*[_run_one(run_id) for run_id in run_ids])

    async with session_factory() as verify_session:
        for run_id in run_ids:
            run = await get_run(verify_session, run_id)
            assert run is not None
            assert run.status == "completed"
            summary = dict(run.result_summary or {})
            assert summary.get("extraction_verdict") in {"success", "partial"}
            assert int(summary.get("record_count", 0) or 0) >= 1


@pytest.mark.asyncio
async def test_process_run_listing_page(db_session: AsyncSession, test_user):
    """Listing page should extract multiple records from cards."""
    listing_html = html_page(
        product_card(href="/p/1", title="Product A", price="$10"),
        product_card(href="/p/2", title="Product B", price="$20"),
        product_card(href="/p/3", title="Product C", price="$30"),
    )
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/category",
        "surface": "ecommerce_listing",
    })

    await _process_run_with_acquisition(db_session, run, _make_acq(listing_html))
    assert run.status == "completed"
    records = await _get_run_records(db_session, run.id)
    assert len(records) == 3


@pytest.mark.asyncio
async def test_process_run_listing_merges_sparse_adapter_rows_with_richer_dom_records(
    db_session: AsyncSession, test_user
):
    listing_html = html_page(
        job_card(
            href="https://example.com/jobs/164066",
            title="Medical Surgical Registered Nurse / RN",
            company="Emory Univ Hosp-Midtown",
            location="Atlanta, GA, 30308",
            salary="$52/hr",
        ),
        job_card(
            href="https://example.com/jobs/164065",
            title="Cardiovascular Step Down Registered Nurse / RN",
            company="Emory Univ Hosp-Midtown",
            location="Atlanta, GA, 30308",
        ),
    )
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/jobs",
        "surface": "job_listing",
    })

    adapter = adapter_result(
        "icims",
        [
            {
                "title": "Medical Surgical Registered Nurse / RN",
                "url": "https://example.com/jobs/164066",
                "job_id": "164066",
                "department": "Nursing",
            },
            {
                "title": "Cardiovascular Step Down Registered Nurse / RN",
                "url": "https://example.com/jobs/164065",
                "job_id": "164065",
                "department": "Nursing",
            },
        ],
    )

    await _process_run_with_acquisition(db_session, run, _make_acq(listing_html), adapter=adapter)

    records = await _get_run_records(db_session, run.id)
    assert len(records) == 2
    assert records[0].data["company"] == "Emory Univ Hosp-Midtown"
    assert records[0].data["location"] == "Atlanta, GA, 30308"
    assert records[0].data["salary"] == "$52/hr"
    assert records[0].data["job_id"] == "164066"
    assert "adapter" in records[0].source_trace["source"]
    assert "listing_card" in records[0].source_trace["source"]


@pytest.mark.asyncio
async def test_process_run_job_listing_sanitizes_adapter_media_and_noisy_description(
    db_session: AsyncSession, test_user
):
    listing_html = html_page(
        job_card(
            href="https://example.com/jobs/164066",
            title="Medical Surgical Registered Nurse / RN",
            company="Emory Univ Hosp-Midtown",
            location="Atlanta, GA, 30308",
        ),
        job_card(
            href="https://example.com/jobs/164065",
            title="Cardiovascular Step Down Registered Nurse / RN",
            company="Emory Univ Hosp-Midtown",
            location="Atlanta, GA, 30308",
        ),
    )
    noisy_description = (
        "Be inspired. Be rewarded. Belong. At Emory Healthcare. "
        "This role includes clinical care, patient flow, collaboration, compliance, internal marketing copy, "
        "benefits language, culture statements, and repeated hiring copy that should not leak into listing summaries."
    )
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/jobs",
        "surface": "job_listing",
    })

    adapter = adapter_result(
        "icims",
        [
            {
                "title": "Medical Surgical Registered Nurse / RN",
                "url": "https://example.com/jobs/164066",
                "job_id": "164066",
                "department": "Nursing",
                "description": noisy_description,
                "image_url": "https://example.com/assets/start.svg",
                "additional_images": "https://example.com/assets/shift.svg",
            },
            {
                "title": "Cardiovascular Step Down Registered Nurse / RN",
                "url": "https://example.com/jobs/164065",
                "job_id": "164065",
                "department": "Nursing",
                "description": noisy_description,
                "image_url": "https://example.com/assets/start.svg",
                "additional_images": "https://example.com/assets/shift.svg",
            },
        ],
    )

    await _process_run_with_acquisition(db_session, run, _make_acq(listing_html), adapter=adapter)

    records = await _get_run_records(db_session, run.id)
    assert len(records) == 2
    assert "image_url" not in records[0].data
    assert "additional_images" not in records[0].data
    assert records[0].data["description"] == "Be inspired. Be rewarded. Belong. At Emory Healthcare."


@pytest.mark.asyncio
async def test_process_run_blocked_page(db_session: AsyncSession, test_user):
    """Blocked/empty page should not produce valid records and should mark as failed."""
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/blocked",
        "surface": "ecommerce_detail",
    })

    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
              return_value=_make_acq("")),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
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
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
              return_value=_make_acq(challenge_html)),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
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
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
              return_value=_make_acq(challenge_html)),
        patch("app.services.pipeline.core.try_blocked_adapter_recovery", new_callable=AsyncMock,
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
async def test_process_run_blocked_jibe_listing_recovers_via_public_endpoint(db_session: AsyncSession, test_user):
    challenge_html = """
    <html><head><title>403 Forbidden</title></head>
    <body><h1>403 Forbidden</h1></body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://www.foxrccareers.com/foxrc-careers-home/jobs?keywords=Dough%20Bird",
        "surface": "job_listing",
    })

    recovered = AdapterResult(
        records=[
            {
                "title": "Dishwasher",
                "company": "Doughbird",
                "job_id": "5920",
                "url": "https://www.foxrccareers.com/jobs/5920?lang=en-us",
                "apply_url": "https://apply.example.com/jobs/5920",
            }
        ],
        source_type="jibe_adapter_recovery",
        adapter_name="jibe",
    )

    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
              return_value=_make_acq(challenge_html)),
        patch("app.services.pipeline.core.try_blocked_adapter_recovery", new_callable=AsyncMock,
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
    assert records[0].data["title"] == "Dishwasher"


@pytest.mark.asyncio
async def test_process_run_blocked_oracle_hcm_listing_recovers_via_public_endpoint(db_session: AsyncSession, test_user):
    challenge_html = """
    <html><head><title>403 Forbidden</title></head>
    <body><h1>403 Forbidden</h1></body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?mode=location",
        "surface": "job_listing",
    })

    recovered = AdapterResult(
        records=[
            {
                "title": "Server",
                "company": "Brookdale Senior Living Inc.",
                "job_id": "25019248",
                "url": "https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/25019248/",
                "apply_url": "https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/25019248/",
            }
        ],
        source_type="oracle_hcm_adapter_recovery",
        adapter_name="oracle_hcm",
    )

    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
              return_value=_make_acq(challenge_html)),
        patch("app.services.pipeline.core.try_blocked_adapter_recovery", new_callable=AsyncMock,
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
    assert records[0].data["title"] == "Server"


@pytest.mark.asyncio
async def test_process_run_listing_browser_retry_blocked_marks_run_blocked(db_session: AsyncSession, test_user):
    curl_shell_html = """
    <html><head><title>Gear | Reverb</title></head>
    <body><div>Marketplace shell</div></body></html>
    """
    blocked_browser_html = """
    <html><head><title>Just a moment...</title></head>
    <body><div class="cf-browser-verification">Checking your browser before accessing the site</div></body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://www.reverb.com/marketplace?product_type=electric-guitars",
        "surface": "ecommerce_listing",
    })

    with (
        patch(
            "app.services.pipeline.core.acquire",
            new_callable=AsyncMock,
            side_effect=[
                _make_acq(curl_shell_html, method="curl_cffi"),
                _make_acq(
                    blocked_browser_html,
                    method="playwright",
                    diagnostics={
                        "browser_attempted": True,
                        "browser_blocked": True,
                        "browser_diagnostics": {"blocked": True},
                    },
                ),
            ],
        ),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "failed"
    assert run.result_summary.get("extraction_verdict") == "blocked"


@pytest.mark.asyncio
async def test_process_run_listing_blocked_curl_recovers_with_browser_first_retry(
    db_session: AsyncSession, test_user
):
    blocked_curl_html = """
    <html><head><title>Just a moment...</title></head>
    <body><div class="cf-browser-verification">Checking your browser before accessing the site</div></body></html>
    """
    browser_listing_html = html_page(
        product_card(href="/p/1", title="Product A", price="$10"),
        product_card(href="/p/2", title="Product B", price="$20"),
    )
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://reverb.com/marketplace?product_type=electric-guitars",
        "surface": "ecommerce_listing",
    })

    acquire_mock = AsyncMock(side_effect=[
        _make_acq(blocked_curl_html, method="curl_cffi"),
        _make_acq(browser_listing_html, method="playwright"),
    ])

    with (
        patch("app.services.pipeline.core.acquire", acquire_mock),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary.get("record_count") == 2
    assert acquire_mock.await_count == 2


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
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
              return_value=_make_acq("", json_data=json_payload, content_type="json")),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
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
async def test_process_run_json_api_listing_keeps_domain_specific_fields_without_schema_trace(
    db_session: AsyncSession, test_user
):
    json_payload = {
        "products": [
            {"title": "Widget", "price": 12.5, "brand": "Acme", "warrantyInformation": "1 year"},
            {"title": "Thing", "price": 8.0, "brand": "Acme", "warrantyInformation": "2 years"},
        ]
    }
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://dummyjson.example/products",
        "surface": "ecommerce_listing",
    })

    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
              return_value=_make_acq("", json_data=json_payload, content_type="json")),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id).order_by(CrawlRecord.id.asc())
    )).scalars().all()
    assert len(records) == 2
    assert records[0].data["warranty_information"] == "1 year"
    assert "schema_resolution" not in records[0].source_trace


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
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
              return_value=_make_acq(empty_listing_html)),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    # Should NOT be "completed" — listing extraction failed
    assert run.status == "failed"
    assert run.result_summary.get("extraction_verdict") == "listing_detection_failed"


@pytest.mark.asyncio
async def test_process_run_listing_legible_page_with_zero_items_fails_without_fallback_record(db_session: AsyncSession, test_user):
    blog_listing_html = """
    <html><head>
      <title>Workblades Blogs</title>
      <meta name="description" content="Updates from the team on abrasive tooling and grinding services.">
    </head><body>
      <main>
        <h1>Blogs</h1>
        <ul class="breadcrumbs">
          <li><a href="https://example.com">Home</a></li>
          <li><a href="https://example.com/products">Products</a></li>
        </ul>
        <section class="news">
          <div class="news__list">
            <div class="news__list__item">
              <h4 class="news__list__item__content__title">
                <a href="https://example.com/blogs/centreless-grinding-training">Centreless Grinding Training</a>
              </h4>
              <p>At Workblades &amp; Formers, we have spent decades helping operators understand setup, dressing, and process control for centreless grinding.</p>
            </div>
            <div class="news__list__item">
              <h4 class="news__list__item__content__title">
                <a href="https://example.com/blogs/workrest-blades">Why We Engineer Workrest Blades</a>
              </h4>
              <p>Workrest blades influence stability, finish, and throughput, so we document geometry choices and setup tradeoffs in detail.</p>
            </div>
          </div>
        </section>
      </main>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/blogs",
        "surface": "ecommerce_listing",
    })

    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock, return_value=_make_acq(blog_listing_html)),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "failed"
    assert run.result_summary.get("extraction_verdict") == "listing_detection_failed"
    assert run.result_summary.get("record_count") == 0

    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    assert records == []


@pytest.mark.asyncio
async def test_process_run_job_listing_elementor_cards_capture_multiple_rows(db_session: AsyncSession, test_user):
    jobs_html = _elementor_jobs_html(
        (
            "https://example.com/jobs/executive-assistant",
            "Executive Assistant",
            "Purpose: The Executive Assistant provides high-level administrative support.",
        ),
        (
            "https://example.com/jobs/associate",
            "Associate",
            "The Associate supports sourcing, diligence, and portfolio work.",
        ),
        (
            "https://example.com/jobs/vice-president",
            "Vice President",
            "The Vice President leads execution across search and portfolio initiatives.",
        ),
    )
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/jobs",
        "surface": "job_listing",
    })

    await _process_run_with_acquisition(db_session, run, _make_acq(jobs_html))
    assert run.status == "completed"
    assert run.result_summary.get("record_count") == 3
    assert run.result_summary.get("extraction_verdict") in {"success", "partial"}

    records = await _get_run_records(db_session, run.id)
    assert len(records) == 3
    assert records[0].data["title"] == "Executive Assistant"
    assert records[0].data["url"] == "https://example.com/jobs/executive-assistant"
    assert records[0].data["apply_url"] == "https://example.com/jobs/executive-assistant"


@pytest.mark.asyncio
async def test_process_run_job_like_ecommerce_listing_uses_job_extractor(db_session: AsyncSession, test_user):
    jobs_html = _elementor_jobs_html(
        (
            "https://example.com/jobs/executive-assistant",
            "Executive Assistant",
            "Purpose: The Executive Assistant provides high-level administrative support.",
        ),
        (
            "https://example.com/jobs/associate",
            "Associate",
            "The Associate supports sourcing, diligence, and portfolio work.",
        ),
    )
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/jobs",
        "surface": "ecommerce_listing",
    })

    await _process_run_with_acquisition(db_session, run, _make_acq(jobs_html))
    assert run.status == "failed"
    assert run.result_summary.get("extraction_verdict") == "listing_detection_failed"

    records = await _get_run_records(db_session, run.id)
    assert len(records) == 0


@pytest.mark.asyncio
async def test_process_run_job_like_listing_retries_browser_instead_of_page_fallback(db_session: AsyncSession, test_user):
    weak_jobs_html = """
    <html><body>
      <main>
        <h1>Search jobs</h1>
        <form><input name="search"><input name="location"></form>
      </main>
    </body></html>
    """
    browser_jobs_html = """
    <html><body>
      <main>
        <ul>
          <li><h2><a href="https://example.com/careers/1">Warehouse Associate</a></h2><p>Ellabell, GA</p></li>
          <li><h2><a href="https://example.com/careers/2">Buyer</a></h2><p>Lancaster, PA</p></li>
        </ul>
      </main>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/careers",
        "surface": "ecommerce_listing",
    })

    acquire_mock = AsyncMock(side_effect=[
        _make_acq(weak_jobs_html, method="curl_cffi"),
        _make_acq(browser_jobs_html, method="playwright"),
    ])

    with (
        patch("app.services.pipeline.core.acquire", acquire_mock),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "failed"
    assert run.result_summary.get("extraction_verdict") == "listing_detection_failed"
    assert acquire_mock.await_count == 2

    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id).order_by(CrawlRecord.id.asc())
    )).scalars().all()
    assert len(records) == 0


@pytest.mark.asyncio
async def test_process_run_listing_skips_duplicate_browser_retry_after_failed_browser_attempt(
    db_session: AsyncSession, test_user
):
    weak_listing_html = """
    <html><body>
      <main>
        <h1>Hair Stylers</h1>
        <p>Compare the range.</p>
      </main>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/category",
        "surface": "ecommerce_listing",
    })

    acquire_mock = AsyncMock(return_value=_make_acq(
        weak_listing_html,
        method="curl_cffi",
        diagnostics={
            "browser_attempted": True,
            "browser_failed": True,
        },
    ))

    with (
        patch("app.services.pipeline.core.acquire", acquire_mock),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "failed"
    assert run.result_summary.get("extraction_verdict") == "listing_detection_failed"
    assert acquire_mock.await_count == 1


@pytest.mark.asyncio
async def test_process_run_listing_promotes_same_host_child_listing_before_browser_retry(
    db_session: AsyncSession, test_user
):
    parent_listing_html = """
    <html><body>
      <main>
        <a href="/countertop-appliances/food-processors/food-processor-and-chopper-products">Food Processors</a>
        <a href="/countertop-appliances/food-processors/parts">Food Processor Parts</a>
        <a href="/countertop-appliances/food-processors/accessories">Food Processor Accessories</a>
        <a href="/countertop-appliances/food-processors/processors">Shop All Food Processors</a>
      </main>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/countertop-appliances/food-processors/food-processor-and-chopper-products.html",
        "surface": "ecommerce_listing",
    })

    acquire_mock = AsyncMock(side_effect=[
        _make_acq(parent_listing_html, method="curl_cffi"),
        _make_acq(food_processor_listing_html(), method="curl_cffi"),
    ])

    with (
        patch("app.services.pipeline.core.acquire", acquire_mock),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary.get("record_count") == 2
    assert acquire_mock.await_count == 2
    first_request = acquire_mock.await_args_list[0].kwargs["request"]
    second_request = acquire_mock.await_args_list[1].kwargs["request"]
    assert isinstance(first_request, AcquisitionRequest)
    assert isinstance(second_request, AcquisitionRequest)
    assert second_request.url == "https://example.com/countertop-appliances/food-processors/processors"
    assert second_request.traversal_mode is None

    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id).order_by(CrawlRecord.id.asc())
    )).scalars().all()
    assert len(records) == 2
    assert records[0].data["title"] == "13-Cup Food Processor"
    assert records[0].source_trace["method"] == "curl_cffi"


@pytest.mark.asyncio
async def test_process_run_listing_promotes_child_listing_when_initial_records_are_category_tiles(
    db_session: AsyncSession, test_user
):
    parent_listing_html = """
    <html><body>
      <div class="swiper-slide">
        <a href="/countertop-appliances/food-processors/processors">
          <img alt="Food Processors Icon" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==" />
        </a>
      </div>
      <div class="swiper-slide">
        <a href="/countertop-appliances/food-processors/parts">
          <img alt="Food Processor Parts 2x" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==" />
        </a>
      </div>
      <div class="swiper-slide">
        <a href="/countertop-appliances/food-processors/accessories">
          <img alt="Food Processor Accessories 1x" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==" />
        </a>
      </div>
      <a href="/countertop-appliances/food-processors/processors">Shop All Food Processors</a>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/countertop-appliances/food-processors/food-processor-and-chopper-products.html",
        "surface": "ecommerce_listing",
    })

    acquire_mock = AsyncMock(side_effect=[
        _make_acq(parent_listing_html, method="curl_cffi"),
        _make_acq(food_processor_listing_html(), method="curl_cffi"),
    ])

    with (
        patch("app.services.pipeline.core.acquire", acquire_mock),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary.get("record_count") == 2
    assert acquire_mock.await_count == 2
    second_request = acquire_mock.await_args_list[1].kwargs["request"]
    assert second_request.url == "https://example.com/countertop-appliances/food-processors/processors"


@pytest.mark.asyncio
async def test_process_run_loading_shell_listing_retries_browser_and_skips_inline_junk(
    db_session: AsyncSession, test_user
):
    curl_shell_html = """
    <html><body>
      <script type="application/json">
        {
          "items": [
            {"title": "Premier Delivery", "url": "/premier-delivery"},
            {"title": "Karen Millen App", "url": "/app"},
            {"title": "Gift Cards", "url": "/gift-cards"}
          ]
        }
      </script>
      <div data-test-id="content-grid">
        <div class="product-card-skeleton animate-pulse"></div>
        <div class="product-card-skeleton animate-pulse"></div>
        <div class="product-card-skeleton animate-pulse"></div>
        <div class="product-card-skeleton animate-pulse"></div>
      </div>
    </body></html>
    """
    browser_listing_html = html_page(
        product_card(
            href="/products/linen-blazer",
            title="Linen Blazer",
            price="$219",
            image_src="https://example.com/img/linen-blazer.jpg",
        ),
        product_card(
            href="/products/wool-coat",
            title="Wool Coat",
            price="$349",
            image_src="https://example.com/img/wool-coat.jpg",
        ),
    )
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/categories/womens-coats-jackets",
        "surface": "ecommerce_listing",
    })

    acquire_mock = AsyncMock(side_effect=[
        _make_acq(curl_shell_html, method="curl_cffi"),
        _make_acq(browser_listing_html, method="playwright"),
    ])

    with (
        patch("app.services.pipeline.core.acquire", acquire_mock),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary.get("record_count") == 2
    assert acquire_mock.await_count == 2

    records = await _get_run_records(db_session, run.id)
    assert len(records) == 2
    assert [record.data["title"] for record in records] == ["Linen Blazer", "Wool Coat"]
    assert all(record.source_trace["type"] == "listing" for record in records)
    assert all(record.source_trace["source"] == "listing_card" for record in records)
    assert all(record.source_trace["method"] == "playwright" for record in records)


@pytest.mark.asyncio
async def test_process_run_reclassifies_detail_html_even_when_requested_surface_is_listing(
    db_session: AsyncSession, test_user
):
    detail_html = """
    <html><body>
      <main>
        <h1>Precision Screwdriver</h1>
        <div class="product-meta">
          <span class="price">$19.99</span>
          <span class="sku">PSD-19</span>
        </div>
        <button>Add to cart</button>
      </main>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/item?id=123",
        "surface": "ecommerce_listing",
    })

    adapter = AdapterResult(
        adapter_name="test",
        records=[{"title": "Precision Screwdriver", "price": "$19.99", "sku": "PSD-19"}],
    )

    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock, return_value=_make_acq(detail_html)),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=adapter),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary.get("record_count") == 1

    record = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().one()
    assert record.data["title"] == "Precision Screwdriver"


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
        patch("app.services.pipeline.core.acquire", acquire_mock),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary.get("record_count") == 2
    assert acquire_mock.await_count == 2
    first_request = acquire_mock.await_args_list[0].kwargs["request"]
    second_request = acquire_mock.await_args_list[1].kwargs["request"]
    assert isinstance(first_request, AcquisitionRequest)
    assert isinstance(second_request, AcquisitionRequest)
    assert first_request.traversal_mode is None
    assert second_request.traversal_mode is None
    records = (await db_session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )).scalars().all()
    assert len(records) == 2
    assert {record.data["title"] for record in records} == {"Product A", "Product B"}


@pytest.mark.asyncio
async def test_process_run_job_listing_retries_browser_after_title_url_only_curl_records(db_session: AsyncSession, test_user):
    weak_listing_html = """
    <html><body>
      <ul>
        <li><a href="https://example.com/jobs/1">Platform Engineer</a></li>
        <li><a href="https://example.com/jobs/2">Data Engineer</a></li>
      </ul>
    </body></html>
    """
    browser_listing_html = """
    <html><body>
      <div class="job-card">
        <a href="https://example.com/jobs/1">
          <h3>Platform Engineer</h3>
          <span class="company">Acme</span>
          <span class="location">Remote</span>
        </a>
      </div>
      <div class="job-card">
        <a href="https://example.com/jobs/2">
          <h3>Data Engineer</h3>
          <span class="company">Acme</span>
          <span class="location">Austin, TX</span>
        </a>
      </div>
    </body></html>
    """
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/jobs",
        "surface": "job_listing",
    })

    acquire_mock = AsyncMock(side_effect=[
        _make_acq(weak_listing_html, method="curl_cffi"),
        _make_acq(browser_listing_html, method="playwright"),
    ])

    with (
        patch("app.services.pipeline.core.acquire", acquire_mock),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.result_summary.get("record_count") == 2
    assert acquire_mock.await_count == 2


@pytest.mark.asyncio
async def test_extraction_verdict_in_summary(db_session: AsyncSession, test_user):
    """Successful runs should have extraction_verdict=success in result_summary."""
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/product",
        "surface": "ecommerce_detail",
    })

    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock,
              return_value=_make_acq(FIXTURE_HTML)),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
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
            "app.services.pipeline.core.acquire",
            new_callable=AsyncMock,
            return_value=_make_acq(
                FIXTURE_HTML,
                method="playwright",
                network_payloads=[{"url": "https://api.example.com/product", "body": {"id": 1}}],
            ),
        ),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
    ):
        await process_run(db_session, run.id)

    await db_session.refresh(run)
    summary = run.result_summary["acquisition_summary"]
    assert summary["methods"]["playwright"] == 1
    assert summary["browser_used_urls"] == 1
    assert summary["network_payloads_total"] == 1


@pytest.mark.asyncio
async def test_process_run_marks_failed_when_single_url_processing_times_out(
    db_session: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/slow",
        "surface": "ecommerce_detail",
    })

    async def _slow_process_single_url(**_kwargs):
        await asyncio.sleep(0.05)
        return ([], "empty", {})

    monkeypatch.setattr(
        "app.services._batch_runtime.URL_PROCESS_TIMEOUT_SECONDS",
        0.001,
    )
    with (
        patch("app.services._batch_runtime._process_single_url", side_effect=_slow_process_single_url),
        patch("app.services._batch_runtime._mark_run_failed", new_callable=AsyncMock) as mark_failed_mock,
    ):
        await process_run(db_session, run.id)

    mark_failed_mock.assert_awaited_once()
    error_message = mark_failed_mock.await_args.args[2]
    assert "timed out" in error_message.lower()


def test_sanitize_field_value_drops_polluted_title_phrase():
    assert sanitize_field_value("title", "Cookie Preferences") is None


def test_sanitize_field_value_keeps_valid_brand_text():
    assert sanitize_field_value("brand", "Nike") == "Nike"


@pytest.mark.asyncio
async def test_process_run_passes_max_pages_to_acquire(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/listing",
        "surface": "ecommerce_listing",
        "settings": {"traversal_mode": "paginate", "max_pages": 3},
    })

    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock, return_value=_make_acq("<html><body></body></html>")) as acquire_mock,
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=AdapterResult(adapter_name="test", records=[{"title": "Item", "url": "https://example.com/item"}])),
    ):
        await process_run(db_session, run.id)

    request = acquire_mock.await_args.kwargs["request"]
    assert isinstance(request, AcquisitionRequest)
    assert request.max_pages == 3


@pytest.mark.asyncio
async def test_process_run_does_not_infer_traversal_mode_from_unrelated_toggle_and_passes_max_scrolls_to_acquire(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://example.com/listing",
        "surface": "ecommerce_listing",
        "settings": {"max_scrolls": 9},
    })

    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock, return_value=_make_acq("<html><body></body></html>")) as acquire_mock,
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=AdapterResult(adapter_name="test", records=[{"title": "Item", "url": "https://example.com/item"}])),
    ):
        await process_run(db_session, run.id)

    request = acquire_mock.await_args.kwargs["request"]
    assert isinstance(request, AcquisitionRequest)
    assert request.traversal_mode is None
    assert request.max_scrolls == 9


@pytest.mark.asyncio
async def test_process_run_normalizes_html_escaped_target_url_before_acquire(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=tenant&amp;ccId=19000101_000001&amp;type=MP",
        "surface": "job_listing",
    })

    with (
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock, return_value=_make_acq("<html><body></body></html>")) as acquire_mock,
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=AdapterResult(adapter_name="test", records=[{"title": "Item", "url": "https://example.com/item", "location": "Lancaster"}])),
    ):
        await process_run(db_session, run.id)

    request = acquire_mock.await_args.kwargs["request"]
    assert isinstance(request, AcquisitionRequest)
    assert request.url == "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=tenant&ccId=19000101_000001&type=MP"


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
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock, return_value=_make_acq(detail_html)),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=adapter),
    ):
        await process_run(db_session, run.id)

    record = (await db_session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run.id))).scalars().one()
    assert "wire_gauge" not in record.data
    review_bucket = record.discovered_data.get("review_bucket") or []
    assert any(
        row.get("key") == "wire_gauge" and row.get("value") == "26 AWG"
        for row in review_bucket
    )
    assert record.source_trace["manifest_trace"]["tables"][0]["rows"][0]["cells"][1]["text"] == "26 AWG"
    assert record.source_trace["schema_resolution"]["resolved_fields"]


@pytest.mark.asyncio
async def test_process_run_drops_commerce_leakage_from_job_listing_records(db_session: AsyncSession, test_user):
    run = await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl",
        "url": "https://careers.clarkassociatesinc.biz/",
        "surface": "job_listing",
    })

    adapter = AdapterResult(
        adapter_name="test",
        records=[{
            "title": "1st Shift Outbound Material Handler-$20.00/Hr. (4 weeks PTO)",
            "company": "WebstaurantStore",
            "location": "Savannah, GA",
            "salary": "$20.00/Hr.",
            "currency": "USD",
            "price": "$20.00/Hr.",
            "url": "https://careers.clarkassociatesinc.biz/careerdetail/?id=100709",
        }],
    )

    with (
        patch(
            "app.services.pipeline.core.acquire",
            new_callable=AsyncMock,
            return_value=_make_acq(
                "<html><body><main><p>Job listings</p><p>"
                + ("Open roles available. " * 40)
                + "</p></main></body></html>"
            ),
        ),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=adapter),
    ):
        await process_run(db_session, run.id)

    record = (await db_session.execute(select(CrawlRecord).where(CrawlRecord.run_id == run.id))).scalars().one()
    assert record.data["salary"] == "$20.00/Hr."
    assert "currency" not in record.data
    assert "price" not in record.data
    review_bucket = record.discovered_data.get("review_bucket") or []
    assert all(row.get("key") != "currency" for row in review_bucket)
    assert all(row.get("key") != "price" for row in review_bucket)


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
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock, return_value=_make_acq(detail_html)),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
        patch("app.services.pipeline.core.discover_xpath_candidates", new_callable=AsyncMock, return_value=([], None)),
        patch(
            "app.services.pipeline.core.review_field_candidates",
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
    assert suggestions == {}
    assert records[0].discovered_data.get("review_bucket") in (None, [])
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
        patch("app.services.pipeline.core.acquire", new_callable=AsyncMock, return_value=_make_acq(detail_html)),
        patch("app.services.pipeline.core.run_adapter", new_callable=AsyncMock, return_value=None),
        patch("app.services.pipeline.core.discover_xpath_candidates", new_callable=AsyncMock, return_value=([], None)),
        patch("app.services.pipeline.core.review_field_candidates", new_callable=AsyncMock) as review_mock,
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


