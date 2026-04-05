# FastAPI application factory and route registration.
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.crawls import router as crawls_router
from app.api.dashboard import router as dashboard_router
from app.api.jobs import router as jobs_router
from app.api.llm import router as llm_router
from app.api.records import router as records_router
from app.api.review import router as review_router
from app.api.selectors import router as selectors_router
from app.api.site_memory import router as site_memory_router
from app.api.users import router as users_router
from app.core.config import get_frontend_origins, settings
from app.core.database import SessionLocal
from app.services.auth_service import bootstrap_admin_user


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with SessionLocal() as session:
        await bootstrap_admin_user(session)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_frontend_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


for router in [
    auth_router,
    users_router,
    dashboard_router,
    crawls_router,
    records_router,
    selectors_router,
    site_memory_router,
    llm_router,
    jobs_router,
    review_router,
]:
    app.include_router(router)
