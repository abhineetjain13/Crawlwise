from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DataEnrichmentOptions(BaseModel):
    max_source_records: int = Field(default=500, ge=1, le=500)
    llm_enabled: bool = False


class DataEnrichmentSourceRecordInput(BaseModel):
    id: int | None = None
    run_id: int | None = None
    source_url: str = ""
    data: dict = Field(default_factory=dict)


class DataEnrichmentJobCreate(BaseModel):
    source_run_id: int | None = None
    source_record_ids: list[int] = Field(default_factory=list)
    source_records: list[DataEnrichmentSourceRecordInput] = Field(default_factory=list)
    options: DataEnrichmentOptions = Field(default_factory=DataEnrichmentOptions)


class DataEnrichmentJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    source_run_id: int | None = None
    status: str
    options: dict
    summary: dict
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class EnrichedProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    source_run_id: int | None = None
    source_record_id: int | None = None
    source_url: str
    status: str
    price_normalized: dict | None = None
    color_family: str | None = None
    size_normalized: list | None = None
    size_system: str | None = None
    gender_normalized: str | None = None
    materials_normalized: list | None = None
    availability_normalized: str | None = None
    seo_keywords: list | None = None
    category_path: str | None = None
    intent_attributes: list | None = None
    audience: list | None = None
    style_tags: list | None = None
    ai_discovery_tags: list | None = None
    suggested_bundles: list | None = None
    diagnostics: dict
    created_at: datetime
    updated_at: datetime


class DataEnrichmentJobDetailResponse(BaseModel):
    job: DataEnrichmentJobResponse
    enriched_products: list[EnrichedProductResponse] = Field(default_factory=list)
