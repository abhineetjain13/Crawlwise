# Tests for auth service behavior.
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import authenticate_user, create_user


@pytest.mark.asyncio
async def test_create_user_hashes_password(db_session: AsyncSession):
    user = await create_user(db_session, "user@example.com", "password123")
    assert user.email == "user@example.com"
    assert user.hashed_password != "password123"
    assert user.hashed_password.startswith("$pbkdf2-sha256$")


@pytest.mark.asyncio
async def test_authenticate_user_accepts_valid_password(db_session: AsyncSession):
    user = await create_user(db_session, "user@example.com", "password123")
    authenticated = await authenticate_user(db_session, user.email, "password123")
    assert authenticated is not None
    token, authenticated_user = authenticated
    assert token
    assert authenticated_user.id == user.id
