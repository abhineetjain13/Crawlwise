# LLM request and response schemas.
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LLMConfigCreate(BaseModel):
    provider: str
    model: str
    api_key: str | None = None
    task_type: str
    per_domain_daily_budget_usd: Decimal
    global_session_budget_usd: Decimal


class LLMConfigUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    task_type: str | None = None
    per_domain_daily_budget_usd: Decimal | None = None
    global_session_budget_usd: Decimal | None = None
    is_active: bool | None = None


class LLMConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    model: str
    api_key_masked: str
    api_key_set: bool
    task_type: str
    per_domain_daily_budget_usd: Decimal
    global_session_budget_usd: Decimal
    is_active: bool
    created_at: datetime


class LLMCostLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    provider: str
    model: str
    task_type: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    domain: str
    created_at: datetime


class LLMProviderCatalogItem(BaseModel):
    provider: str
    label: str
    api_key_set: bool
    recommended_models: list[str]


class LLMConnectionTestRequest(BaseModel):
    provider: str
    model: str
    api_key: str | None = None


class LLMConnectionTestResponse(BaseModel):
    ok: bool
    message: str
