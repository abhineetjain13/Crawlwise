"""Database utility functions for handling common patterns."""
from __future__ import annotations

import asyncio
import random
from typing import TypeVar, Callable, Awaitable

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.runtime_metrics import incr


T = TypeVar('T')

# Global lock for serializing writes on SQLite to avoid "database is locked" and data loss
# during concurrent updates to the same row (since FOR UPDATE is not supported in SQLite).
sqlite_write_lock = asyncio.Lock()


def escape_like_pattern(value: str) -> str:
    text = str(value or "")
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _is_retryable_sqlite_lock_error(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return (
        "database is locked" in message
        or "database table is locked" in message
        or "database schema is locked" in message
        or ("sqlite" in message and "locked" in message)
    )


async def with_retry(
    session: AsyncSession,
    operation: Callable[[AsyncSession], Awaitable[T]],
    *,
    max_retries: int = 5,
    base_delay_ms: int = 50,
    max_delay_ms: int = 2000,
) -> T:
    """Execute a database operation with exponential backoff retry for lock errors.
    
    This function retries the entire unit-of-work (operation + commit) to ensure
    that session state is not lost on failed commits. SQLAlchemy invalidates session
    state on commit failure, so retrying only the commit would lose pending changes.
    
    Args:
        session: The database session to use
        operation: Async function that performs database operations and returns a result
        max_retries: Maximum number of retry attempts (default: 5)
        base_delay_ms: Base delay in milliseconds for exponential backoff (default: 50)
        max_delay_ms: Maximum delay in milliseconds (default: 2000)
        
    Returns:
        The result returned by the operation function
        
    Raises:
        OperationalError: If the error is not a lock error or max retries exceeded
        
    Example:
        async def create_user(session: AsyncSession) -> User:
            user = User(name="Alice")
            session.add(user)
            return user
            
        user = await with_retry(session, create_user)
    """
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    for attempt in range(max_retries):
        try:
            result = await operation(session)
            await session.commit()
            return result
        except OperationalError as exc:
            if not _is_retryable_sqlite_lock_error(exc):
                raise
            incr("db_lock_errors_total")
            if attempt == max_retries - 1:
                raise
            incr("db_lock_retries_total")
            # Rollback to clean up session state before retry
            await session.rollback()
            # Exponential backoff with jitter to reduce collision probability
            delay_ms = min(base_delay_ms * (2 ** attempt), max_delay_ms)
            jitter_ms = random.randint(0, delay_ms // 4)
            await asyncio.sleep((delay_ms + jitter_ms) / 1000)
    
    # This should never be reached due to the raise in the loop, but for type safety
    raise RuntimeError("Retry loop exited unexpectedly")




