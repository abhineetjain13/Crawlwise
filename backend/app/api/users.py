# User administration route handlers.
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_admin
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.schemas.user import UserResponse, UserUpdate
from app.services.user_service import delete_user, get_user, list_users, update_user

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=PaginatedResponse[UserResponse])
async def users(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str = "",
    is_active: bool | None = None,
    session: AsyncSession = Depends(get_db),
    _: object = Depends(require_admin),
) -> PaginatedResponse[UserResponse]:
    rows, total = await list_users(session, page, limit, search, is_active)
    return PaginatedResponse(
        items=[UserResponse.model_validate(row, from_attributes=True) for row in rows],
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )


@router.get("/{user_id}", response_model=UserResponse)
async def user_detail(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    _: object = Depends(require_admin),
) -> UserResponse:
    user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user, from_attributes=True)


@router.patch("/{user_id}", response_model=UserResponse)
async def user_patch(
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_db),
    _: object = Depends(require_admin),
) -> UserResponse:
    user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updated = await update_user(session, user, payload.model_dump(exclude_none=True))
    return UserResponse.model_validate(updated, from_attributes=True)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def user_delete(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    _: object = Depends(require_admin),
) -> None:
    user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await delete_user(session, user)
