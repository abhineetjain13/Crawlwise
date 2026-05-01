# Alembic migration helpers for startup and local initialization flows.
from __future__ import annotations

import asyncio
import logging

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import BASE_DIR, settings
from app.models import Base

logger = logging.getLogger("app.core.migrations")
_ALEMBIC_INI_PATH = BASE_DIR / "alembic.ini"
_ALEMBIC_SCRIPT_PATH = BASE_DIR / "alembic"
_APP_TABLES = frozenset(
    {"users", "crawl_runs", "crawl_records", "crawl_logs", "review_promotions"}
)
_QUEUE_LEASE_BASELINE = "20260406_0007"
_CRAWL_RECORDS_INDEX_BASELINE = "20260410_0009"
_DATA_ENRICHMENT_BASELINE = "20260426_0018"


def build_alembic_config() -> Config:
    config = Config(str(_ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(_ALEMBIC_SCRIPT_PATH))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


async def _resolve_legacy_start_revision() -> str | None:
    engine = create_async_engine(settings.database_url, future=True, echo=False)
    try:
        async with engine.begin() as connection:
            return await connection.run_sync(_resolve_legacy_start_revision_sync)
    finally:
        await engine.dispose()


def _resolve_legacy_start_revision_sync(connection) -> str | None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "alembic_version" in tables:
        return None
    if not (_APP_TABLES & tables):
        return None

    # Legacy local databases were created via metadata.create_all() without an
    # alembic_version row. Ensure missing tables exist, then stamp the nearest
    # known baseline before applying later additive migrations.
    Base.metadata.create_all(bind=connection, checkfirst=True)
    inspector = inspect(connection)

    crawl_runs_columns = {
        column["name"] for column in inspector.get_columns("crawl_runs")
    }
    crawl_records_columns = {
        column["name"] for column in inspector.get_columns("crawl_records")
    }

    if "queue_owner" not in crawl_runs_columns:
        return _QUEUE_LEASE_BASELINE
    if "url_identity_key" not in crawl_records_columns:
        return _CRAWL_RECORDS_INDEX_BASELINE
    if {"enrichment_status", "enriched_at"} - crawl_records_columns:
        return _DATA_ENRICHMENT_BASELINE
    return "head"


def apply_pending_migrations() -> None:
    config = build_alembic_config()
    legacy_start_revision = asyncio.run(_resolve_legacy_start_revision())
    if legacy_start_revision is None:
        logger.info("Applying database migrations to head")
        command.upgrade(config, "head")
        return

    if legacy_start_revision == "head":
        logger.warning(
            "Stamping unmanaged legacy database at head before serving requests"
        )
        command.stamp(config, "head")
        return

    logger.warning(
        "Stamping unmanaged legacy database at %s before upgrading to head",
        legacy_start_revision,
    )
    command.stamp(config, legacy_start_revision)
    command.upgrade(config, "head")


async def apply_pending_migrations_async() -> None:
    await asyncio.to_thread(apply_pending_migrations)
