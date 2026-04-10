# Authentication and user lifecycle service.
from __future__ import annotations

import os
import re

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_ADMIN_EMAIL = "DEFAULT_ADMIN_EMAIL"
DEFAULT_ADMIN_PASSWORD = "DEFAULT_ADMIN_PASSWORD"
BOOTSTRAP_ADMIN_ONCE = "BOOTSTRAP_ADMIN_ONCE"


def _env_flag(name: str) -> bool:
    if name == BOOTSTRAP_ADMIN_ONCE:
        return bool(settings.bootstrap_admin_once)
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _validate_default_admin_password(password: str) -> None:
    issues: list[str] = []
    if len(password) < 12:
        issues.append("at least 12 characters")
    if not re.search(r"[A-Z]", password):
        issues.append("an uppercase letter")
    if not re.search(r"[a-z]", password):
        issues.append("a lowercase letter")
    if not re.search(r"\d", password):
        issues.append("a digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        issues.append("a special character")
    if issues:
        raise RuntimeError(
            f"{DEFAULT_ADMIN_PASSWORD} must include " + ", ".join(issues) + "."
        )


def _load_default_admin_credentials() -> tuple[str, str]:
    email = str(settings.default_admin_email or "").strip().lower()
    password = str(settings.default_admin_password or "")
    if not email:
        raise RuntimeError(f"{DEFAULT_ADMIN_EMAIL} is required for admin bootstrap.")
    if not password:
        raise RuntimeError(f"{DEFAULT_ADMIN_PASSWORD} is required for admin bootstrap.")
    _validate_default_admin_password(password)
    return email, password


async def create_user(session: AsyncSession, email: str, password: str, role: str = "user") -> User:
    user = User(email=email.lower(), hashed_password=hash_password(password), role=role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def ensure_default_admin(session: AsyncSession) -> User:
    email, password = _load_default_admin_credentials()
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        return await create_user(session, email, password, role="admin")
    changed = False
    if user.role != "admin":
        user.role = "admin"
        changed = True
    if not user.is_active:
        user.is_active = True
        changed = True
    if changed:
        await session.commit()
        await session.refresh(user)
    return user


async def bootstrap_admin_user(session: AsyncSession) -> User | None:
    if not _env_flag(BOOTSTRAP_ADMIN_ONCE):
        return None

    email, password = _load_default_admin_credentials()
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        return await create_user(session, email, password, role="admin")

    changed = False
    if user.role != "admin":
        user.role = "admin"
        changed = True
    if not user.is_active:
        user.is_active = True
        changed = True
    if changed:
        await session.commit()
        await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, email: str, password: str) -> tuple[str, User] | None:
    result = await session.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        return None
    return create_access_token(str(user.id), token_version=user.token_version), user
