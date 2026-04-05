from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SiteMemoryPayload(BaseModel):
    fields: list[str] = Field(default_factory=list)
    selectors: dict[str, list[dict]] = Field(default_factory=dict)
    source_mappings: dict[str, str] = Field(default_factory=dict)
    llm_columns: dict[str, object] = Field(default_factory=dict)


class SiteMemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    domain: str
    payload: SiteMemoryPayload
    last_crawl_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SiteMemoryUpdate(BaseModel):
    payload: SiteMemoryPayload = Field(default_factory=SiteMemoryPayload)
