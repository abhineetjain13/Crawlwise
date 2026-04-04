# LLM request and response schemas.
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

SUPPORTED_LLM_PROVIDERS = {"groq", "anthropic", "nvidia"}


class LLMConfigCreate(BaseModel):
    provider: str
    model: str
    api_key: str | None = None
    task_type: str
    per_domain_daily_budget_usd: Decimal
    global_session_budget_usd: Decimal

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in SUPPORTED_LLM_PROVIDERS:
            raise ValueError(f"Unsupported provider: {value}")
        return normalized


class LLMConfigUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    task_type: str | None = None
    per_domain_daily_budget_usd: Decimal | None = None
    global_session_budget_usd: Decimal | None = None
    is_active: bool | None = None

    @field_validator("provider")
    @classmethod
    def _validate_optional_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value or "").strip().lower()
        if normalized not in SUPPORTED_LLM_PROVIDERS:
            raise ValueError(f"Unsupported provider: {value}")
        return normalized


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
    run_id: int | None = None
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

    @field_validator("provider")
    @classmethod
    def _validate_connection_provider(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in SUPPORTED_LLM_PROVIDERS:
            raise ValueError(f"Unsupported provider: {value}")
        return normalized


class LLMConnectionTestResponse(BaseModel):
    ok: bool
    message: str
