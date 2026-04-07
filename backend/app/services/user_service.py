# User administration service.
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def list_users(
    session: AsyncSession,
    page: int,
    limit: int,
    search: str = "",
    is_active: bool | None = None,
) -> tuple[list[User], int]:
    """Retrieve a paginated list of users with optional search and active-status filtering.
    Parameters:
        - session (AsyncSession): The async database session used to execute queries.
        - page (int): The page number to retrieve.
        - limit (int): The maximum number of users to return per page.
        - search (str): Optional search text to match against user email.
        - is_active (bool | None): Optional filter for user active status.
    Returns:
        - tuple[list[User], int]: A tuple containing the list of users for the requested page and the total matching user count."""
    query = select(User)
    count_query = select(func.count()).select_from(User)
    if search:
        pattern = f"%{search.lower()}%"
        query = query.where(func.lower(User.email).like(pattern))
        count_query = count_query.where(func.lower(User.email).like(pattern))
    if is_active is not None:
        query = query.where(User.is_active == is_active)
        count_query = count_query.where(User.is_active == is_active)
    total = int((await session.execute(count_query)).scalar() or 0)
    result = await session.execute(
        query.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit)
    )
    return list(result.scalars().all()), total


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def update_user(session: AsyncSession, user: User, payload: dict) -> User:
    """Update a user record and revoke sessions if critical fields change.
    Parameters:
        - session (AsyncSession): Active database session used to persist changes.
        - user (User): The user instance to update.
        - payload (dict): Dictionary of fields and values to apply to the user.
    Returns:
        - User: The updated and refreshed user instance."""
    should_revoke_sessions = False
    for key, value in payload.items():
        if key in {"is_active", "role"} and getattr(user, key) != value:
            should_revoke_sessions = True
        setattr(user, key, value)
    if should_revoke_sessions:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(token_version=func.coalesce(User.token_version, 0) + 1)
        )
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.commit()
