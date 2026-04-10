"""Initialize the database with all tables."""
import asyncio

import app.models  # noqa: F401  Ensures all ORM models are registered before create_all().
from app.core.database import Base, engine


async def init_database():
    """Create all database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database initialized successfully!")


if __name__ == "__main__":
    asyncio.run(init_database())
