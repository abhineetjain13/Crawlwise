# FastAPI application factory and route registration.
from __future__ import annotations

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
from app.api.users import router as users_router
from app.core.config import settings

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
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
    llm_router,
    jobs_router,
    review_router,
]:
    app.include_router(router)
