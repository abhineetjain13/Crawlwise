# Tests for auth service behavior.
from __future__ import annotations

import pytest
from app.core.security import verify_password
from app.services.auth_service import (
    BOOTSTRAP_ADMIN_ONCE,
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    authenticate_user,
    bootstrap_admin_user,
    create_user,
    ensure_default_admin,
)
from sqlalchemy.ext.asyncio import AsyncSession


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
    assert authenticated_user.token_version == 0


@pytest.mark.asyncio
async def test_authenticate_user_rejects_inactive_user(db_session: AsyncSession):
    user = await create_user(db_session, "inactive@example.com", "password123")
    user.is_active = False
    await db_session.commit()

    authenticated = await authenticate_user(db_session, user.email, "password123")

    assert authenticated is None


@pytest.mark.asyncio
async def test_ensure_default_admin_creates_and_authenticates_admin(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(DEFAULT_ADMIN_EMAIL, "admin@example.com")
    monkeypatch.setenv(DEFAULT_ADMIN_PASSWORD, "StrongerAdmin#123")

    user = await ensure_default_admin(db_session)

    assert user.email == "admin@example.com"
    assert user.role == "admin"
    authenticated = await authenticate_user(db_session, "admin@example.com", "StrongerAdmin#123")
    assert authenticated is not None


@pytest.mark.asyncio
async def test_ensure_default_admin_does_not_reset_existing_password(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(DEFAULT_ADMIN_EMAIL, "admin@example.com")
    monkeypatch.setenv(DEFAULT_ADMIN_PASSWORD, "StrongerAdmin#123")
    user = await create_user(db_session, "admin@example.com", "ExistingPass#123", role="admin")
    original_hash = user.hashed_password

    ensured = await ensure_default_admin(db_session)

    assert ensured.id == user.id
    assert ensured.hashed_password == original_hash
    assert verify_password("ExistingPass#123", ensured.hashed_password)


@pytest.mark.asyncio
async def test_bootstrap_admin_user_skips_when_toggle_is_disabled(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv(BOOTSTRAP_ADMIN_ONCE, raising=False)
    monkeypatch.setattr(
        bootstrap_admin_user.__globals__["settings"],
        "bootstrap_admin_once",
        False,
    )
    monkeypatch.setenv(DEFAULT_ADMIN_EMAIL, "admin@example.com")
    monkeypatch.setenv(DEFAULT_ADMIN_PASSWORD, "StrongerAdmin#123")

    user = await bootstrap_admin_user(db_session)

    assert user is None


@pytest.mark.asyncio
async def test_bootstrap_admin_user_can_promote_existing_user_when_enabled(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(BOOTSTRAP_ADMIN_ONCE, "true")
    monkeypatch.setenv(DEFAULT_ADMIN_EMAIL, "admin@example.com")
    monkeypatch.setenv(DEFAULT_ADMIN_PASSWORD, "StrongerAdmin#123")
    user = await create_user(db_session, "admin@example.com", "ExistingPass#123", role="user")
    user.is_active = False
    await db_session.commit()

    bootstrapped = await bootstrap_admin_user(db_session)

    assert bootstrapped is not None
    assert bootstrapped.id == user.id
    assert bootstrapped.role == "admin"
    assert bootstrapped.is_active is True
    assert verify_password("ExistingPass#123", bootstrapped.hashed_password)


def test_ensure_default_admin_rejects_weak_password(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DEFAULT_ADMIN_EMAIL, "admin@example.com")
    monkeypatch.setenv(DEFAULT_ADMIN_PASSWORD, "weakpass")

    with pytest.raises(RuntimeError, match="DEFAULT_ADMIN_PASSWORD must include"):
        ensure_default_admin.__globals__["_load_default_admin_credentials"]()


def test_load_default_admin_credentials_strips_password_whitespace(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(DEFAULT_ADMIN_EMAIL, "admin@example.com")
    monkeypatch.setenv(DEFAULT_ADMIN_PASSWORD, "  StrongerAdmin#123  ")

    email, password = ensure_default_admin.__globals__["_load_default_admin_credentials"]()

    assert email == "admin@example.com"
    assert password == "StrongerAdmin#123"
