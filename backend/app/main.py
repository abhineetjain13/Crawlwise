# FastAPI application factory and route registration.
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
logger = logging.getLogger("app")

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

from app.api.auth import router as auth_router
from app.api.crawls import router as crawls_router
from app.api.dashboard import router as dashboard_router
from app.api.jobs import router as jobs_router
from app.api.records import router as records_router
from app.api.review import router as review_router
from app.api.users import router as users_router
from app.core.config import get_frontend_origins, settings
from app.core.database import SessionLocal, ensure_sqlite_queue_lease_columns
from app.core.telemetry import (
    generate_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.services.auth_service import bootstrap_admin_user
from app.services.acquisition.browser_client import shutdown_browser_pool
from app.services.workers import CrawlWorkerLoop, QueueLeaseConfig, default_worker_id, recover_stale_leases


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker = CrawlWorkerLoop(
        config=QueueLeaseConfig(worker_id=default_worker_id())
    )
    started = False
    async with SessionLocal() as session:
        await ensure_sqlite_queue_lease_columns(session)
        await bootstrap_admin_user(session)
        await recover_stale_inflight_runs(session)
    try:
        await worker.start()
        started = True
        yield
    finally:
        if started:
            await worker.stop()
        await shutdown_browser_pool()


async def recover_stale_inflight_runs(session) -> list[int]:
    recovered_ids = await recover_stale_leases(session)
    if recovered_ids:
        logger.warning(
            "Recovered %d stale leased run(s) on startup: %s",
            len(recovered_ids),
            recovered_ids,
        )
    return recovered_ids


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_frontend_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next) -> Response:
    request_id_header = settings.request_id_header
    correlation_id = request.headers.get(request_id_header) or generate_correlation_id()
    token = set_correlation_id(correlation_id)
    try:
        response = await call_next(request)
    finally:
        reset_correlation_id(token)
    response.headers[request_id_header] = correlation_id
    return response


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


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
