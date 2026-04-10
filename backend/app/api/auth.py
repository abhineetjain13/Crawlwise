# Authentication route handlers.
from __future__ import annotations

from typing import Annotated

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.user import AuthResponse, UserCreate, UserResponse
from app.services.auth_service import authenticate_user, create_user
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
async def register(
    payload: UserCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    if not settings.registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled. Enable REGISTRATION_ENABLED for multi-tenant deployments.",
        )
    existing = await session.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    user = await create_user(session, payload.email, payload.password)
    return UserResponse.model_validate(user, from_attributes=True)


@router.post("/login")
async def login(
    payload: UserCreate,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthResponse:
    authenticated = await authenticate_user(session, payload.email, payload.password)
    if authenticated is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token, user = authenticated
    response.set_cookie("access_token", token, httponly=True, samesite="lax")
    return AuthResponse(
        access_token=token,
        user=UserResponse.model_validate(user, from_attributes=True),
    )


@router.get("/me")
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse.model_validate(user, from_attributes=True)
