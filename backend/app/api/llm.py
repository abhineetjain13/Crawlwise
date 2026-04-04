# LLM configuration route handlers.
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_admin
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.schemas.llm import (
    LLMConfigCreate,
    LLMConfigResponse,
    LLMConfigUpdate,
    LLMConnectionTestRequest,
    LLMConnectionTestResponse,
    LLMCostLogResponse,
    LLMProviderCatalogItem,
)
from app.services.llm_runtime import llm_provider_catalog, test_provider_connection
from app.services.llm_service import (
    create_config,
    get_config,
    list_configs,
    list_cost_logs,
    prepare_config_create,
    prepare_config_update,
    serialize_config,
    update_config,
)

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/catalog")
async def llm_catalog(
    _: Annotated[object, Depends(require_admin)],
) -> list[LLMProviderCatalogItem]:
    return [LLMProviderCatalogItem.model_validate(item) for item in llm_provider_catalog()]


@router.get("/config")
async def llm_configs(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> list[LLMConfigResponse]:
    return [LLMConfigResponse.model_validate(serialize_config(row)) for row in await list_configs(session)]


@router.post("/config")
async def llm_config_create(
    payload: LLMConfigCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> LLMConfigResponse:
    config = await create_config(session, prepare_config_create(payload.model_dump()))
    return LLMConfigResponse.model_validate(serialize_config(config))


@router.put("/config/{config_id}")
async def llm_config_update(
    config_id: int,
    payload: LLMConfigUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> LLMConfigResponse:
    config = await get_config(session, config_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM config not found")
    updated = await update_config(session, config, prepare_config_update(payload.model_dump(exclude_none=True)))
    return LLMConfigResponse.model_validate(serialize_config(updated))


@router.post("/test")
async def llm_test_connection(
    payload: LLMConnectionTestRequest,
    _: Annotated[object, Depends(require_admin)],
) -> LLMConnectionTestResponse:
    ok, message = await test_provider_connection(
        provider=payload.provider,
        model=payload.model,
        api_key=payload.api_key,
    )
    return LLMConnectionTestResponse(ok=ok, message=message)


@router.get("/cost-log")
async def llm_cost_log(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    provider: str = "",
    task_type: str = "",
) -> PaginatedResponse[LLMCostLogResponse]:
    rows, total = await list_cost_logs(session, page, limit, provider, task_type)
    return PaginatedResponse(
        items=[LLMCostLogResponse.model_validate(row, from_attributes=True) for row in rows],
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )
