"""Initialize the database with all tables."""
import asyncio
from app.core.database import engine, Base
from app.models.crawl import CrawlRun, CrawlRecord, CrawlLog
from app.models.user import User


async def init_database():
    """Create all database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database initialized successfully!")


if __name__ == "__main__":
    asyncio.run(init_database())
