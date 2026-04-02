# Authentication and user lifecycle service.
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User


async def create_user(session: AsyncSession, email: str, password: str, role: str = "user") -> User:
    user = User(email=email.lower(), hashed_password=hash_password(password), role=role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, email: str, password: str) -> tuple[str, User] | None:
    result = await session.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return create_access_token(str(user.id)), user
