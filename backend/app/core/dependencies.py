# FastAPI dependency helpers.
from __future__ import annotations

from app.core.database import get_session
from app.core.security import decode_access_token
from app.models.user import User
from fastapi import Cookie, Depends, Header, HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db(
    session: AsyncSession = Depends(get_session),  # noqa: B008 - FastAPI injects dependencies via parameter defaults.
) -> AsyncSession:
    return session


async def get_current_user(
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),  # noqa: B008 - FastAPI dependency injection requires Depends defaults.
) -> User:
    token = access_token
    if not token and authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            token = credentials.strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
        token_version = int(payload.get("ver", 0))
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    user_token_version = user.token_version if user.token_version is not None else 0
    if user_token_version != token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return user


async def require_admin(
    user: User = Depends(get_current_user),  # noqa: B008 - FastAPI dependency injection requires Depends defaults.
) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
