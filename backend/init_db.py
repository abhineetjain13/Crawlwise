"""Initialize the database by applying Alembic migrations."""
import asyncio

from app.core.migrations import apply_pending_migrations_async


async def init_database():
    """Upgrade the configured database to the latest schema revision."""
    await apply_pending_migrations_async()
    print("Database migrations applied successfully!")


if __name__ == "__main__":
    asyncio.run(init_database())
