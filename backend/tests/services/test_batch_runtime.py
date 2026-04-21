from __future__ import annotations

import asyncio

import pytest

from app.services._batch_runtime import process_run
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.crawl_crud import create_crawl_run, get_run_records
from app.services.robots_policy import (
    ROBOTS_ALLOWED,
    ROBOTS_FETCH_FAILURE,
    ROBOTS_MISSING,
    RobotsPolicyResult,
)
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
