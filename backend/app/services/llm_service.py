# LLM configuration and cost-log service.
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret, encrypt_secret
from app.models.llm import LLMConfig, LLMCostLog


def mask_key(value: str) -> str:
    tail = value[-4:] if len(value) >= 4 else value
    return f"sk-****{tail}"


async def list_configs(session: AsyncSession) -> list[LLMConfig]:
    result = await session.execute(select(LLMConfig).order_by(LLMConfig.created_at.desc()))
    return list(result.scalars().all())


async def create_config(session: AsyncSession, payload: dict) -> LLMConfig:
    if payload.get("is_active", True):
        await _deactivate_task_configs(session, str(payload.get("task_type") or ""))
    config = LLMConfig(**payload)
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


async def update_config(session: AsyncSession, config: LLMConfig, payload: dict) -> LLMConfig:
    next_task_type = str(payload.get("task_type") or config.task_type)
    next_is_active = bool(payload.get("is_active", config.is_active))
    if next_is_active:
        await _deactivate_task_configs(session, next_task_type, keep_id=config.id)
    for key, value in payload.items():
        setattr(config, key, value)
    await session.commit()
    await session.refresh(config)
    return config


async def get_config(session: AsyncSession, config_id: int) -> LLMConfig | None:
    return await session.get(LLMConfig, config_id)


async def list_cost_logs(
    session: AsyncSession,
    page: int,
    limit: int,
    provider: str = "",
    task_type: str = "",
) -> tuple[list[LLMCostLog], int]:
    query = select(LLMCostLog)
    count_query = select(func.count()).select_from(LLMCostLog)
    if provider:
        query = query.where(LLMCostLog.provider == provider)
        count_query = count_query.where(LLMCostLog.provider == provider)
    if task_type:
        query = query.where(LLMCostLog.task_type == task_type)
        count_query = count_query.where(LLMCostLog.task_type == task_type)
    total = int((await session.execute(count_query)).scalar() or 0)
    result = await session.execute(
        query.order_by(LLMCostLog.created_at.desc()).offset((page - 1) * limit).limit(limit)
    )
    return list(result.scalars().all()), total


def serialize_config(config: LLMConfig) -> dict:
    decrypted = decrypt_secret(config.api_key_encrypted) if config.api_key_encrypted else ""
    return {
        "id": config.id,
        "provider": config.provider,
        "model": config.model,
        "api_key_masked": mask_key(decrypted) if decrypted else "Not configured",
        "api_key_set": bool(decrypted),
        "task_type": config.task_type,
        "per_domain_daily_budget_usd": config.per_domain_daily_budget_usd,
        "global_session_budget_usd": config.global_session_budget_usd,
        "is_active": config.is_active,
        "created_at": config.created_at,
    }


def prepare_config_create(payload: dict) -> dict:
    api_key = str(payload.pop("api_key", "") or "")
    return {**payload, "api_key_encrypted": encrypt_secret(api_key) if api_key else ""}


def prepare_config_update(payload: dict) -> dict:
    update = {key: value for key, value in payload.items() if value is not None and key != "api_key"}
    if payload.get("api_key"):
        update["api_key_encrypted"] = encrypt_secret(payload["api_key"])
    return update


async def _deactivate_task_configs(session: AsyncSession, task_type: str, *, keep_id: int | None = None) -> None:
    if not task_type:
        return
    result = await session.execute(select(LLMConfig).where(LLMConfig.task_type == task_type, LLMConfig.is_active.is_(True)))
    for row in result.scalars().all():
        if keep_id is not None and row.id == keep_id:
            continue
        row.is_active = False
