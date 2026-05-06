from __future__ import annotations

import asyncio

import pytest

from app.services._batch_runtime import process_run
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.crawl_crud import create_crawl_run, get_run_records
from app.models.crawl import CrawlRecord
from app.services.pipeline.types import URLProcessingResult
from app.services.robots_policy import (
    ROBOTS_ALLOWED,
    ROBOTS_FETCH_FAILURE,
    ROBOTS_MISSING,
    RobotsPolicyResult,
)
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession


def _detail_html() -> str:
    return """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Widget Prime",
          "description": "A deterministic widget",
          "sku": "W-100",
          "offers": {"price": "19.99", "availability": "InStock"}
        }
        </script>
      </head>
      <body><h1>Widget Prime</h1></body>
    </html>
    """


def _listing_shell_html() -> str:
    return "<html><body><h1>Empty category</h1></body></html>"


@pytest.mark.asyncio
async def test_process_run_persists_detail_records(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert run.status == "completed"
    assert run.last_heartbeat_at is not None
    assert run.result_summary["extraction_verdict"] == "success"
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"
    assert rows[0].data["price"] == "19.99"


@pytest.mark.asyncio
async def test_process_run_marks_empty_listing_as_listing_detection_failed(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_listing_shell_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "listing_detection_failed"
    assert total == 0
    assert rows == []


@pytest.mark.asyncio
async def test_process_run_tracks_failure_reason_counts(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/search?q=widget",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    async def _fake_process_single_url(*args, **kwargs):
        url = str(kwargs.get("url") or "")
        if "search" in url:
            return URLProcessingResult(
                records=[],
                verdict="empty",
                url_metrics={"record_count": 0, "failure_reason": "non_detail_seed"},
            )
        return URLProcessingResult(
            records=[],
            verdict="blocked",
            url_metrics={"record_count": 0, "failure_reason": "challenge_shell"},
        )

    monkeypatch.setattr(
        "app.services._batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.result_summary["acquisition_summary"]["failure_reasons"] == {
        "non_detail_seed": 1,
        "challenge_shell": 1,
    }


@pytest.mark.asyncio
async def test_process_run_aggregates_quality_summary_from_url_metrics(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/products/widget-prime",
                    "https://example.com/products/widget-lite",
                ],
            },
        },
    )

    async def _fake_process_single_url(*args, **kwargs):
        url = str(kwargs.get("url") or "")
        if "lite" in url:
            return URLProcessingResult(
                records=[],
                verdict="partial",
                url_metrics={
                    "record_count": 0,
                    "quality_summary": {
                        "score": 0.4,
                        "level": "low",
                        "requested_fields_total": 4,
                        "requested_fields_found_best": 2,
                        "variant_completeness": {
                            "applicable": True,
                            "complete": False,
                        },
                    },
                },
            )
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={
                "record_count": 0,
                "quality_summary": {
                    "score": 0.9,
                    "level": "high",
                    "requested_fields_total": 4,
                    "requested_fields_found_best": 4,
                    "variant_completeness": {
                        "applicable": True,
                        "complete": True,
                    },
                },
            },
        )

    monkeypatch.setattr(
        "app.services._batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.result_summary["quality_summary"] == {
        "level": "medium",
        "score": 0.65,
        "scored_urls": 2,
        "level_counts": {
            "high": 1,
            "low": 1,
        },
        "listing_incomplete_urls": 0,
        "variant_incomplete_urls": 1,
        "requested_fields_total": 4,
        "requested_fields_found_best": 4,
    }


@pytest.mark.asyncio
async def test_process_run_blocks_disallowed_url_before_acquire(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/private/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": True},
        },
    )

    async def _disallow(url: str, *, user_agent: str = "*") -> RobotsPolicyResult:
        del user_agent
        return RobotsPolicyResult(
            allowed=False,
            outcome="disallowed",
            robots_url="https://example.com/robots.txt",
        )

    async def _unexpected_acquire(request):
        raise AssertionError(f"acquire should not run for {request.url}")

    monkeypatch.setattr("app.services.pipeline.core.check_url_crawlability", _disallow)
    monkeypatch.setattr("app.services.pipeline.core.acquire", _unexpected_acquire)

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "blocked"
    assert run.result_summary["url_verdicts"] == ["blocked"]
    assert total == 0
    assert rows == []


@pytest.mark.asyncio
async def test_process_run_ignores_robots_when_disabled_in_settings(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/private/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )
    acquire_calls: list[str] = []

    async def _disallow(url: str, *, user_agent: str = "*") -> RobotsPolicyResult:
        del user_agent
        return RobotsPolicyResult(
            allowed=False,
            outcome="disallowed",
            robots_url="https://example.com/robots.txt",
        )

    async def _fake_acquire(request):
        acquire_calls.append(request.url)
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.check_url_crawlability", _disallow)
    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert acquire_calls == ["https://example.com/private/widget-prime"]
    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "success"
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"


@pytest.mark.asyncio
@pytest.mark.parametrize("robots_outcome", [ROBOTS_ALLOWED, ROBOTS_MISSING, ROBOTS_FETCH_FAILURE])
async def test_process_run_continues_when_robots_allows_or_fails_open(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    robots_outcome: str,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
        },
    )
    acquire_calls: list[str] = []

    async def _allow(url: str, *, user_agent: str = "*") -> RobotsPolicyResult:
        del user_agent
        return RobotsPolicyResult(
            allowed=True,
            outcome=robots_outcome,
            robots_url="https://example.com/robots.txt",
            error="timeout" if robots_outcome == ROBOTS_FETCH_FAILURE else None,
        )

    async def _fake_acquire(request):
        acquire_calls.append(request.url)
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.check_url_crawlability", _allow)
    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert acquire_calls == ["https://example.com/products/widget-prime"]
    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "success"
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"


@pytest.mark.asyncio
async def test_process_run_enforces_url_timeout_from_settings(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/slow-widget",
            "surface": "ecommerce_detail",
            "settings": {"url_timeout_seconds": 0.01},
        },
    )

    async def _slow_process_single_url(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.05)
        raise AssertionError("timeout should fire before this returns")

    monkeypatch.setattr(
        "app.services._batch_runtime.process_single_url",
        _slow_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "error"
    assert run.result_summary["url_verdicts"] == ["error"]


@pytest.mark.asyncio
async def test_process_run_default_timeout_includes_acquisition_slack(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/slow-widget",
            "surface": "ecommerce_detail",
        },
    )

    patch_settings(
        url_process_timeout_seconds=0.01,
        url_process_timeout_buffer_seconds=0.03,
        acquisition_attempt_timeout_seconds=0.02,
    )

    async def _slow_process_single_url(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.025)
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.services._batch_runtime.process_single_url",
        _slow_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "success"
    assert run.result_summary["url_verdicts"] == ["success"]


@pytest.mark.asyncio
async def test_process_batch_run_preserves_requested_fields_for_every_url(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "urls": [
                "https://example.com/products/widget-1",
                "https://example.com/products/widget-2",
            ],
            "surface": "ecommerce_detail",
            "requested_fields": ["materials"],
        },
    )
    captured_requested_fields: list[list[str]] = []

    async def _fake_acquire(request):
        captured_requested_fields.append(list(request.requested_fields))
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    assert captured_requested_fields == [["materials"], ["materials"]]


@pytest.mark.asyncio
async def test_process_batch_run_preserves_proxy_list_for_every_url(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "urls": [
                "https://example.com/products/widget-1",
                "https://example.com/products/widget-2",
            ],
            "surface": "ecommerce_detail",
            "settings": {
                "proxy_enabled": True,
                "proxy_list": ["http://proxy-a", "http://proxy-b"],
                "proxy_profile": {
                    "enabled": True,
                    "proxy_list": ["http://proxy-a", "http://proxy-b"],
                },
            },
        },
    )
    captured_proxy_lists: list[list[str]] = []

    async def _fake_acquire(request):
        captured_proxy_lists.append(list(request.proxy_list))
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    assert captured_proxy_lists == [
        ["http://proxy-a", "http://proxy-b"],
        ["http://proxy-a", "http://proxy-b"],
    ]


@pytest.mark.asyncio
async def test_process_batch_run_preserves_exact_requested_section_labels_for_every_url(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "urls": [
                "https://example.com/products/widget-1",
                "https://example.com/products/widget-2",
            ],
            "surface": "ecommerce_detail",
            "additional_fields": ["Features & Benefits"],
        },
    )
    captured_requested_fields: list[list[str]] = []

    async def _fake_acquire(request):
        captured_requested_fields.append(list(request.requested_fields))
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    assert captured_requested_fields == [
        ["Features & Benefits"],
        ["Features & Benefits"],
    ]


@pytest.mark.asyncio
async def test_process_run_continues_after_sqlalchemy_url_error(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/products/bad-widget",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    async def _poisoned_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        if "bad-widget" in url:
            raise PendingRollbackError("flush failed earlier")
        session = kwargs["session"]
        session.add(
            CrawlRecord(
                run_id=run.id,
                source_url=url,
                data={"title": "Widget Prime", "url": url},
                raw_data={},
                discovered_data={},
                source_trace={},
            )
        )
        await session.flush()
        return URLProcessingResult(
            records=[{"title": "Widget Prime", "url": url}],
            verdict="success",
            url_metrics={"record_count": 1},
        )

    monkeypatch.setattr(
        "app.services._batch_runtime.process_single_url",
        _poisoned_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "partial"
    assert run.result_summary["url_verdicts"] == ["error", "success"]
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"


@pytest.mark.asyncio
async def test_process_run_continues_when_failure_log_persistence_fails(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/products/bad-widget",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    async def _failing_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        if "bad-widget" in url:
            raise RuntimeError("extractor failed")
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    async def _failing_failure_log(*args, **kwargs):
        del args, kwargs
        raise PendingRollbackError("failure log flush failed")

    monkeypatch.setattr(
        "app.services._batch_runtime.process_single_url",
        _failing_process_single_url,
    )
    monkeypatch.setattr(
        "app.services._batch_runtime._persist_url_failure_log",
        _failing_failure_log,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "partial"
    assert run.result_summary["url_verdicts"] == ["error", "success"]


@pytest.mark.asyncio
async def test_process_run_records_browser_exception_diagnostics_and_continues(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/products/location-gated",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    async def _fake_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        if "location-gated" in url:
            exc = RuntimeError("location popup blocked browser")
            exc.browser_diagnostics = {
                "browser_attempted": True,
                "browser_outcome": "location_required",
                "failure_reason": "location_required",
            }
            raise exc
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.services._batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "partial"
    assert run.result_summary["url_verdicts"] == ["error", "success"]
    assert run.result_summary["acquisition_summary"]["failure_reasons"] == {
        "location_required": 1,
    }


@pytest.mark.asyncio
async def test_process_run_continues_after_generic_browser_driver_error(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/products/driver-closed",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    class BrowserDriverError(Exception):
        pass

    async def _fake_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        if "driver-closed" in url:
            exc = BrowserDriverError(
                "Page.content: Connection closed while reading from the driver"
            )
            exc.browser_diagnostics = {
                "browser_attempted": True,
                "browser_outcome": "navigation_failed",
                "failure_reason": "browser_driver_closed",
            }
            raise exc
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.services._batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "partial"
    assert run.result_summary["url_verdicts"] == ["error", "success"]
    assert run.result_summary["acquisition_summary"]["failure_reasons"] == {
        "browser_driver_closed": 1,
    }
