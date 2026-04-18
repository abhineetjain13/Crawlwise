from __future__ import annotations

from typing import Annotated

from app.core.dependencies import get_db, require_admin
from app.core.security import encrypt_secret
from app.models.llm import LLMCostLog, LLMConfig
from app.schemas.llm import (
    LLMConfigCreateRequest,
    LLMConfigResponse,
    LLMConfigUpdateRequest,
    LLMConnectionTestRequest,
    LLMConnectionTestResponse,
    LLMCostLogResponse,
    LLMProviderCatalogResponse,
)
from app.services.llm_runtime import llm_provider_catalog, test_provider_connection
from app.services.llm_config_service import SUPPORTED_LLM_PROVIDERS
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/providers")
async def llm_providers(
    _: Annotated[object, Depends(require_admin)],
) -> list[LLMProviderCatalogResponse]:
    return [
        LLMProviderCatalogResponse.model_validate(row)
        for row in llm_provider_catalog()
    ]


@router.get("/configs")
async def llm_configs(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> list[LLMConfigResponse]:
    result = await session.execute(
        select(LLMConfig).order_by(LLMConfig.task_type.asc(), LLMConfig.created_at.desc())
    )
    return [_serialize_llm_config(row) for row in result.scalars().all()]


@router.post("/configs")
async def llm_config_create(
    payload: LLMConfigCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> LLMConfigResponse:
    _validate_provider(payload.provider)
    if payload.is_active:
        await _deactivate_task_configs(session, payload.task_type)
    config = LLMConfig(
        provider=payload.provider.strip().lower(),
        model=payload.model.strip(),
        api_key_encrypted=encrypt_secret(payload.api_key.strip()) if payload.api_key else "",
        task_type=payload.task_type.strip(),
        per_domain_daily_budget_usd=payload.per_domain_daily_budget_usd,
        global_session_budget_usd=payload.global_session_budget_usd,
        is_active=payload.is_active,
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return _serialize_llm_config(config)


@router.put("/configs/{config_id}")
async def llm_config_update(
    config_id: int,
    payload: LLMConfigUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> LLMConfigResponse:
    config = await session.get(LLMConfig, config_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM config not found")
    changes = payload.model_dump(exclude_none=True)
    if "provider" in changes:
        _validate_provider(str(changes["provider"]))
    next_task_type = str(changes.get("task_type") or config.task_type).strip()
    if changes.get("is_active") is True:
        await _deactivate_task_configs(session, next_task_type, exclude_id=config.id)
    for key, value in changes.items():
        if key == "api_key":
            config.api_key_encrypted = encrypt_secret(str(value).strip()) if str(value).strip() else config.api_key_encrypted
            continue
        setattr(config, key, value)
    await session.commit()
    await session.refresh(config)
    return _serialize_llm_config(config)


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def llm_config_delete(
    config_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> None:
    config = await session.get(LLMConfig, config_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM config not found")
    await session.delete(config)
    await session.commit()


@router.post("/test-connection")
async def llm_test_connection(
    payload: LLMConnectionTestRequest,
    _: Annotated[object, Depends(require_admin)],
) -> LLMConnectionTestResponse:
    _validate_provider(payload.provider)
    ok, message = await test_provider_connection(
        provider=payload.provider,
        model=payload.model,
        api_key=payload.api_key,
    )
    return LLMConnectionTestResponse(ok=ok, message=message)


def _validate_provider(provider: str) -> None:
    normalized = str(provider or "").strip().lower()
    if normalized not in SUPPORTED_LLM_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported LLM provider: {provider}",
        )


@router.get("/cost-log")
async def llm_cost_log(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[object, Depends(require_admin)],
) -> list[LLMCostLogResponse]:
    result = await session.execute(
        select(LLMCostLog).order_by(LLMCostLog.created_at.desc(), LLMCostLog.id.desc()).limit(100)
    )
    return [
        LLMCostLogResponse.model_validate(row, from_attributes=True)
        for row in result.scalars().all()
    ]


async def _deactivate_task_configs(
    session: AsyncSession,
    task_type: str,
    *,
    exclude_id: int | None = None,
) -> None:
    result = await session.execute(select(LLMConfig).where(LLMConfig.task_type == task_type))
    for row in result.scalars().all():
        if exclude_id is not None and row.id == exclude_id:
            continue
        row.is_active = False
    await session.flush()


def _serialize_llm_config(config: LLMConfig) -> LLMConfigResponse:
    masked = ""
    if config.api_key_encrypted:
        masked = "••••••••"
    return LLMConfigResponse(
        id=config.id,
        provider=config.provider,
        model=config.model,
        api_key_masked=masked,
        api_key_set=bool(config.api_key_encrypted),
        task_type=config.task_type,
        per_domain_daily_budget_usd=config.per_domain_daily_budget_usd,
        global_session_budget_usd=config.global_session_budget_usd,
        is_active=config.is_active,
        created_at=config.created_at,
    )
