from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_live_health_endpoint_is_lightweight() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


@pytest.mark.asyncio
async def test_ready_health_endpoint_reports_dependency_failure(monkeypatch) -> None:
    async def db_ok() -> bool:
        return True

    async def redis_failed() -> bool:
        return False

    monkeypatch.setattr("app.main.check_database", db_ok)
    monkeypatch.setattr("app.main.check_redis", redis_failed)
    monkeypatch.setattr("app.main.check_browser_pool", lambda: True)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {
            "database": True,
            "redis": False,
            "browser_pool": True,
        },
    }
