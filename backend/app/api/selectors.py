from __future__ import annotations

from typing import Annotated

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.selectors import (
    SelectorCreateRequest,
    SelectorRecordResponse,
    SelectorSuggestRequest,
    SelectorSuggestResponse,
    SelectorTestRequest,
    SelectorTestResponse,
    SelectorUpdateRequest,
)
from app.services.selectors_runtime import (
    build_preview_html,
    create_selector_record,
    delete_domain_selector_records,
    delete_selector_record,
    fetch_selector_document,
    list_selector_records,
    suggest_selectors,
    test_selector,
    update_selector_record,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/selectors", tags=["selectors"])


@router.get("")
async def selectors_list(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    domain: str = "",
    surface: str = "generic",
) -> list[SelectorRecordResponse]:
    return [
        SelectorRecordResponse.model_validate(row)
        for row in await list_selector_records(
            session,
            domain=domain,
            surface=surface,
        )
    ]


@router.post("")
async def selectors_create(
    payload: SelectorCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorRecordResponse:
    record = await create_selector_record(
        session,
        domain=payload.domain,
        surface=payload.surface,
        payload=payload.model_dump(),
    )
    return SelectorRecordResponse.model_validate(record)


@router.put("/{selector_id}")
async def selectors_update(
    selector_id: int,
    payload: SelectorUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorRecordResponse:
    record = await update_selector_record(
        session,
        selector_id=selector_id,
        payload=payload.model_dump(exclude_none=True),
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selector not found")
    return SelectorRecordResponse.model_validate(record)


@router.delete("/{selector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def selectors_delete(
    selector_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Response:
    deleted = await delete_selector_record(session, selector_id=selector_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selector not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/domain/{domain}")
async def selectors_delete_domain(
    domain: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    surface: str | None = Query(default=None),
) -> dict[str, int]:
    deleted = await delete_domain_selector_records(
        session,
        domain=domain,
        surface=surface,
    )
    return {"deleted": deleted}


@router.post("/suggest")
async def selectors_suggest(
    payload: SelectorSuggestRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorSuggestResponse:
    result = await suggest_selectors(
        session,
        url=str(payload.url),
        expected_columns=list(payload.expected_columns or []),
        surface=payload.surface,
    )
    return SelectorSuggestResponse.model_validate(result)


@router.post("/test")
async def selectors_test(
    payload: SelectorTestRequest,
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorTestResponse:
    result = await test_selector(
        url=str(payload.url),
        css_selector=payload.css_selector,
        xpath=payload.xpath,
        regex=payload.regex,
    )
    return SelectorTestResponse.model_validate(result)


@router.get("/preview-html", response_class=HTMLResponse)
async def selectors_preview_html(
    _: Annotated[User, Depends(get_current_user)],
    url: str = Query(...),
) -> HTMLResponse:
    document = await fetch_selector_document(url)
    return HTMLResponse(
        content=build_preview_html(
            source_url=str(document["url"]),
            html=str(document["html"]),
        )
    )
