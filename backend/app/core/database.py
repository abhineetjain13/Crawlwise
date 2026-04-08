# Async database engine and session factory.
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


is_sqlite = settings.database_url.startswith("sqlite")
engine_kwargs = {
    "future": True,
    "connect_args": {"timeout": 120, "check_same_thread": False} if is_sqlite else {},
    # Reduce echo for better performance in production
    "echo": False,
}
if not is_sqlite:
    # QueuePool tuning only applies to non-SQLite engines.
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10
engine = create_async_engine(settings.database_url, **engine_kwargs)
SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
    # Autoflush can cause extra queries and lock contention
    autoflush=False,
)


if is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(connection, _record) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=120000")  # 120 seconds
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
            cursor.execute("PRAGMA temp_store=MEMORY")
            # Reduce lock contention
            cursor.execute("PRAGMA wal_autocheckpoint=1000")
        finally:
            cursor.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def ensure_sqlite_queue_lease_columns(session: AsyncSession) -> None:
    if not is_sqlite:
        return
    tables = await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='crawl_runs'")
    )
    if tables.first() is None:
        return
    table_info = await session.execute(text("PRAGMA table_info(crawl_runs)"))
    existing_columns = {str(row[1]) for row in table_info.fetchall()}

    statements: list[str] = []
    if "queue_owner" not in existing_columns:
        statements.append("ALTER TABLE crawl_runs ADD COLUMN queue_owner VARCHAR(64)")
    if "lease_expires_at" not in existing_columns:
        statements.append("ALTER TABLE crawl_runs ADD COLUMN lease_expires_at DATETIME")
    if "last_heartbeat_at" not in existing_columns:
        statements.append("ALTER TABLE crawl_runs ADD COLUMN last_heartbeat_at DATETIME")
    if "claim_count" not in existing_columns:
        statements.append("ALTER TABLE crawl_runs ADD COLUMN claim_count INTEGER DEFAULT 0")
    if "last_claimed_at" not in existing_columns:
        statements.append("ALTER TABLE crawl_runs ADD COLUMN last_claimed_at DATETIME")

    schema_changed = False
    for stmt in statements:
        await session.execute(text(stmt))
        schema_changed = True

    index_info = await session.execute(text("PRAGMA index_list(crawl_runs)"))
    existing_indexes = {str(row[1]) for row in index_info.fetchall()}
    missing_indexes = []
    if "ix_crawl_runs_queue_owner" not in existing_indexes:
        missing_indexes.append(
            "CREATE INDEX IF NOT EXISTS ix_crawl_runs_queue_owner "
            "ON crawl_runs (queue_owner)"
        )
    if "ix_crawl_runs_lease_expires_at" not in existing_indexes:
        missing_indexes.append(
            "CREATE INDEX IF NOT EXISTS ix_crawl_runs_lease_expires_at "
            "ON crawl_runs (lease_expires_at)"
        )
    for stmt in missing_indexes:
        await session.execute(text(stmt))

    index_changed = bool(missing_indexes)
    if schema_changed or index_changed:
        await session.commit()
