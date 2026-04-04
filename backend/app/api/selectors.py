# Selector tool route handlers.
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_admin
from app.models.selector import Selector
from app.models.user import User
from app.schemas.selector import (
    SelectorCreate,
    SelectorResponse,
    SelectorSuggestRequest,
    SelectorTestRequest,
    SelectorTestResponse,
    SelectorUpdate,
)
from app.services.selector_service import (
    clear_all_selectors,
    create_selector,
    delete_selectors_for_domain,
    delete_selector,
    list_selectors,
    suggest_selectors,
    test_selector,
    update_selector,
)

router = APIRouter(prefix="/api/selectors", tags=["selectors"])


@router.post("/suggest")
async def selectors_suggest(
    payload: SelectorSuggestRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    return {"suggestions": await suggest_selectors(session, payload.url, payload.expected_columns)}


@router.post("/test")
async def selectors_test(
    payload: SelectorTestRequest,
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorTestResponse:
    matched_value, count, selector_used = await test_selector(
        payload.url,
        css_selector=payload.css_selector,
        xpath=payload.xpath,
        regex=payload.regex,
    )
    return SelectorTestResponse(matched_value=matched_value, count=count, selector_used=selector_used)


@router.get("")
async def selectors_list(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    domain: Annotated[str, Query()] = "",
) -> list[SelectorResponse]:
    rows = await list_selectors(session, domain)
    return [SelectorResponse.model_validate(row, from_attributes=True) for row in rows]


@router.post("")
async def selectors_create(
    payload: SelectorCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorResponse:
    try:
        selector = await create_selector(session, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SelectorResponse.model_validate(selector, from_attributes=True)


@router.delete("/clear-all")
async def selectors_clear_all(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict:
    deleted = await clear_all_selectors(session)
    return {"deleted": deleted}


@router.put("/{selector_id}")
async def selectors_put(
    selector_id: int,
    payload: SelectorUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorResponse:
    result = await session.execute(select(Selector).where(Selector.id == selector_id))
    selector = result.scalar_one_or_none()
    if selector is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selector not found")
    try:
        updated = await update_selector(session, selector, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SelectorResponse.model_validate(updated, from_attributes=True)


@router.delete("/{selector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def selectors_delete(
    selector_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> None:
    await delete_selector(session, selector_id)


@router.delete("/domain/{domain}")
async def selectors_delete_domain(
    domain: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    deleted = await delete_selectors_for_domain(session, domain)
    return {"deleted": deleted}
