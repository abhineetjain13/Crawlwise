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
from app.core.redis import close_redis
from app.core.database import SessionLocal
from app.core.telemetry import (
    generate_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.services.acquisition.browser_client import shutdown_browser_pool
from app.services.acquisition.cookie_store import validate_cookie_policy_config
from app.services.auth_service import bootstrap_admin_user

logger = logging.getLogger("app")

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_cookie_policy_config()
    async with SessionLocal() as session:
        await bootstrap_admin_user(session)
    try:
        yield
    finally:
        await shutdown_browser_pool()
        await close_redis()


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
