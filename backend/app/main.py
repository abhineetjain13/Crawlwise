# FastAPI application factory and route registration.
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.api.auth import router as auth_router
from app.api.crawls import router as crawls_router
from app.api.dashboard import router as dashboard_router
from app.api.jobs import router as jobs_router
from app.api.records import router as records_router
from app.api.review import router as review_router
from app.api.users import router as users_router
from app.core.config import get_frontend_origins, settings
from app.core.migrations import apply_pending_migrations_async
from app.core.metrics import (
    check_browser_pool,
    check_database,
    check_redis,
    render_prometheus_metrics,
)
from app.core.redis import close_redis
from app.core.database import SessionLocal, dispose_engine
from app.core.telemetry import (
    configure_logging,
    generate_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.services.acquisition import (
    shutdown_browser_pool,
    validate_cookie_policy_config,
)
from app.services.auth_service import bootstrap_admin_user
from app.services.crawl_service import recover_stale_local_runs

logger = logging.getLogger("app")
configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await apply_pending_migrations_async()
    validate_cookie_policy_config()
    async with SessionLocal() as session:
        await bootstrap_admin_user(session)
        recovered = await recover_stale_local_runs(session)
        if recovered:
            logger.warning(
                "Recovered %s stale local crawl run(s) after backend restart",
                recovered,
            )
    try:
        yield
    finally:
        await shutdown_browser_pool()
        await close_redis()
        await dispose_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_frontend_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sanitize_header_value(value: str) -> str:
    return value.replace("\r", "").replace("\n", "")


@app.middleware("http")
async def correlation_middleware(request: Request, call_next) -> Response:
    request_id_header = _sanitize_header_value(settings.request_id_header).strip()
    if not request_id_header:
        request_id_header = "X-Request-ID"
    raw_correlation_id = request.headers.get(request_id_header)
    correlation_id = (
        _sanitize_header_value(raw_correlation_id)
        if raw_correlation_id is not None
        else generate_correlation_id()
    )
    if not correlation_id:
        correlation_id = generate_correlation_id()
    token = set_correlation_id(correlation_id)
    try:
        response = await call_next(request)
    finally:
        reset_correlation_id(token)
    response.headers[request_id_header] = correlation_id
    return response


@app.get("/api/health")
async def health() -> dict:
    checks = {
        "database": await check_database(),
        "redis": await check_redis(),
        "browser_pool": check_browser_pool(),
    }
    status = "healthy" if all(checks.values()) else "degraded"
    return {"status": status, "checks": checks}


@app.get("/api/metrics")
async def metrics() -> Response:
    payload, content_type = await render_prometheus_metrics()
    return Response(content=payload, media_type=content_type)


for router in [
    auth_router,
    users_router,
    dashboard_router,
    crawls_router,
    records_router,
    jobs_router,
    review_router,
]:
    app.include_router(router)
