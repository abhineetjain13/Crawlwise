# Alembic migration helpers for startup and local initialization flows.
from __future__ import annotations

import asyncio
import logging

from alembic import command
from alembic.config import Config

from app.core.config import BASE_DIR, settings

logger = logging.getLogger("app.core.migrations")
_ALEMBIC_INI_PATH = BASE_DIR / "alembic.ini"
_ALEMBIC_SCRIPT_PATH = BASE_DIR / "alembic"


def build_alembic_config() -> Config:
    config = Config(str(_ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(_ALEMBIC_SCRIPT_PATH))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config

def apply_pending_migrations() -> None:
    config = build_alembic_config()
    logger.info("Applying database migrations to head")
    command.upgrade(config, "head")


async def apply_pending_migrations_async() -> None:
    await asyncio.to_thread(apply_pending_migrations)
