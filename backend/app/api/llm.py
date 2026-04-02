# LLM configuration route handlers.
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.schemas.llm import LLMConfigCreate, LLMConfigResponse, LLMConfigUpdate, LLMCostLogResponse
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


@router.get("/config", response_model=list[LLMConfigResponse])
async def llm_configs(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[LLMConfigResponse]:
    return [LLMConfigResponse.model_validate(serialize_config(row)) for row in await list_configs(session)]


@router.post("/config", response_model=LLMConfigResponse)
async def llm_config_create(
    payload: LLMConfigCreate,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> LLMConfigResponse:
    config = await create_config(session, prepare_config_create(payload.model_dump()))
    return LLMConfigResponse.model_validate(serialize_config(config))


@router.put("/config/{config_id}", response_model=LLMConfigResponse)
async def llm_config_update(
    config_id: int,
    payload: LLMConfigUpdate,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> LLMConfigResponse:
    config = await get_config(session, config_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM config not found")
    updated = await update_config(session, config, prepare_config_update(payload.model_dump(exclude_none=True)))
    return LLMConfigResponse.model_validate(serialize_config(updated))


@router.get("/cost-log", response_model=PaginatedResponse[LLMCostLogResponse])
async def llm_cost_log(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    provider: str = "",
    task_type: str = "",
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PaginatedResponse[LLMCostLogResponse]:
    rows, total = await list_cost_logs(session, page, limit, provider, task_type)
    return PaginatedResponse(
        items=[LLMCostLogResponse.model_validate(row, from_attributes=True) for row in rows],
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )
