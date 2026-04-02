# User administration service.
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def list_users(
    session: AsyncSession,
    page: int,
    limit: int,
    search: str = "",
    is_active: bool | None = None,
) -> tuple[list[User], int]:
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
    for key, value in payload.items():
        setattr(user, key, value)
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.commit()
