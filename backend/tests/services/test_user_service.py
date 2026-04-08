from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.user_service import list_users


@pytest.mark.asyncio
async def test_list_users_search_treats_like_wildcards_as_literals(
    db_session: AsyncSession,
):
    literal_user = User(
        email="qa_100%real@example.com",
        hashed_password="x",
        role="admin",
        is_active=True,
    )
    other_user = User(
        email="qa-100-real@example.com",
        hashed_password="x",
        role="admin",
        is_active=True,
    )
    db_session.add_all([literal_user, other_user])
    await db_session.commit()

    rows, total = await list_users(db_session, page=1, limit=20, search="100%real")

    assert total == 1
    assert len(rows) == 1
    assert rows[0].email == "qa_100%real@example.com"
