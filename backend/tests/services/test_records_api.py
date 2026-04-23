from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.crawl import CrawlRecord
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.crawl_crud import create_crawl_run, get_run_records as real_get_run_records
from app.services.crawl_state import CrawlStatus, update_run_status


@pytest.fixture
async def records_api_client(db_session, test_user):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_records_api_retries_empty_first_read_when_run_summary_expects_rows(
    records_api_client: AsyncClient,
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
            "settings": {},
        },
    )
    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url="https://example.com/products/widget",
            url_identity_key="widget-1",
            data={"title": "Widget Prime"},
            raw_data={"title": "Widget Prime"},
            discovered_data={},
            source_trace={},
            raw_html_path=None,
        )
    )
    update_run_status(run, CrawlStatus.RUNNING)
    update_run_status(run, CrawlStatus.COMPLETED)
    run.update_summary(record_count=1, extraction_verdict="success")
    await db_session.commit()

    call_count = 0

    async def _fake_get_run_records(session, run_id: int, page: int, limit: int):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [], 0
        return await real_get_run_records(session, run_id, page, limit)

    @asynccontextmanager
    async def _fake_session_local():
        yield db_session

    monkeypatch.setattr("app.api.records.get_run_records", _fake_get_run_records)
    monkeypatch.setattr("app.api.records.SessionLocal", _fake_session_local)
    monkeypatch.setattr(crawler_runtime_settings, "records_read_retry_attempts", 1)
    monkeypatch.setattr(crawler_runtime_settings, "records_read_retry_delay_ms", 0)

    response = await records_api_client.get(
        f"/api/crawls/{run.id}/records",
        params={"page": 1, "limit": 100},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["data"]["title"] == "Widget Prime"
    assert call_count == 2
