from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.site_memory import SiteMemoryResponse, SiteMemoryUpdate
from app.services.site_memory_service import clear_all_memory, delete_memory, get_memory, list_memory, save_memory

router = APIRouter(prefix="/api/site-memory", tags=["site-memory"])


@router.get("")
async def site_memory_list(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> list[SiteMemoryResponse]:
    rows = await list_memory(session)
    return [SiteMemoryResponse.model_validate(row, from_attributes=True) for row in rows]


@router.get("/{domain}")
async def site_memory_get(
    domain: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> SiteMemoryResponse:
    row = await get_memory(session, domain)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site memory not found")
    return SiteMemoryResponse.model_validate(row, from_attributes=True)


@router.put("/{domain}")
async def site_memory_put(
    domain: str,
    payload: SiteMemoryUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> SiteMemoryResponse:
    row = await save_memory(
        session,
        domain,
        fields=payload.payload.fields,
        selectors=payload.payload.selectors,
        source_mappings=payload.payload.source_mappings,
        llm_columns=payload.payload.llm_columns,
    )
    return SiteMemoryResponse.model_validate(row, from_attributes=True)


@router.delete("/{domain}")
async def site_memory_delete(
    domain: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    deleted = await delete_memory(session, domain)
    return {"deleted": deleted}


@router.delete("")
async def site_memory_clear_all(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict:
    deleted = await clear_all_memory(session)
    return {"deleted": deleted}
