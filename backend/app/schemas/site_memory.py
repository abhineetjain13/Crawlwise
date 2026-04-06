from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SiteSchemaSnapshot(BaseModel):
    baseline_fields: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    new_fields: list[str] = Field(default_factory=list)
    deprecated_fields: list[str] = Field(default_factory=list)
    source: str = "static"
    confidence: float = 0.0
    saved_at: datetime | None = None


class SiteMemoryPayload(BaseModel):
    fields: list[str] = Field(default_factory=list)
    schemas: dict[str, SiteSchemaSnapshot] = Field(default_factory=dict)
    selectors: dict[str, list[dict]] = Field(default_factory=dict)
    selector_suggestions: dict[str, list[dict]] = Field(default_factory=dict)
    source_mappings: dict[str, str] = Field(default_factory=dict)
    llm_columns: dict[str, object] = Field(default_factory=dict)
    acquisition: dict[str, object] = Field(default_factory=dict)


class SiteMemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    domain: str
    payload: SiteMemoryPayload
    last_crawl_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SiteMemoryUpdate(BaseModel):
    payload: SiteMemoryPayload = Field(default_factory=SiteMemoryPayload)
