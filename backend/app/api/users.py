# User administration route handlers.
from __future__ import annotations

from typing import Annotated

from app.core.dependencies import get_db, require_admin
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.schemas.user import UserResponse, UserUpdate
from app.services.user_service import delete_user, get_user, list_users, update_user
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/users", tags=["users"])

USER_NOT_FOUND_DETAIL = "User not found"


@router.get("")
async def users(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str = "",
    is_active: bool | None = None,
) -> PaginatedResponse[UserResponse]:
    rows, total = await list_users(session, page, limit, search, is_active)
    return PaginatedResponse(
        items=[UserResponse.model_validate(row, from_attributes=True) for row in rows],
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )


@router.get("/{user_id}")
async def user_detail(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> UserResponse:
    user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=USER_NOT_FOUND_DETAIL)
    return UserResponse.model_validate(user, from_attributes=True)


@router.patch("/{user_id}")
async def user_patch(
    user_id: int,
    payload: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> UserResponse:
    user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=USER_NOT_FOUND_DETAIL)
    updated = await update_user(session, user, payload.model_dump(exclude_none=True))
    return UserResponse.model_validate(updated, from_attributes=True)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def user_delete(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> None:
    user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=USER_NOT_FOUND_DETAIL)
    await delete_user(session, user)
