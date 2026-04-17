# Tests for crawl service — integration tests with fixture HTML.
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app.core.telemetry import reset_correlation_id, set_correlation_id
from app.models.crawl import CrawlRecord
from app.services.crawl_service import (
    kill_run,
    pause_run,
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class _MissingRunRef:
    id = -999999

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
async def test_create_crawl_run_requires_explicit_surface(
    db_session: AsyncSession, test_user
):
    with pytest.raises(ValueError, match="surface is required"):
        await create_crawl_run(db_session, test_user.id, {
            "run_type": "crawl",
            "url": "https://example.com",
        })


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
async def test_active_jobs(db_session: AsyncSession, test_user):
    await create_crawl_run(db_session, test_user.id, {
        "run_type": "crawl", "url": "https://example.com", "surface": "ecommerce_detail",
    })
    jobs = await active_jobs(db_session)
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"


