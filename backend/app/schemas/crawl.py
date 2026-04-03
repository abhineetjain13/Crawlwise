# Crawl request and response schemas.
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CrawlCreate(BaseModel):
    run_type: str  # "crawl", "batch", "csv"
    url: str | None = None
    urls: list[str] = Field(default_factory=list)
    surface: str  # "ecommerce_listing", "ecommerce_detail", "job_listing", "job_detail", "automobile_listing", "automobile_detail", "tabular"
    settings: dict = Field(default_factory=dict)
    # settings can include: page_type, proxy_list, advanced_mode, max_pages, max_records, sleep_ms, csv_content
    additional_fields: list[str] = Field(default_factory=list)


class CrawlRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    run_type: str
    url: str
    status: str
    surface: str
    settings: dict
    requested_fields: list[str]
    result_summary: dict
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class CrawlRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    source_url: str
    data: dict
    raw_data: dict
    discovered_data: dict
    source_trace: dict
    raw_html_path: str | None
    created_at: datetime


class DashboardResponse(BaseModel):
    total_runs: int
    active_runs: int
    total_records: int
    recent_runs: list[CrawlRunResponse]
    top_domains: list[dict]
    success_rate: float


class ReviewFieldChoice(BaseModel):
    source_field: str
    output_field: str
    selected: bool = True


class ReviewResponse(BaseModel):
    run: CrawlRunResponse
    normalized_fields: list[str]
    discovered_fields: list[str]
    canonical_fields: list[str]
    domain_mapping: dict[str, str]
    suggested_mapping: dict[str, str]
    selector_memory: list[dict]
    records: list[CrawlRecordResponse]


class ReviewSaveRequest(BaseModel):
    selections: list[ReviewFieldChoice]
    extra_fields: list[str] = Field(default_factory=list)


class ReviewSaveResponse(BaseModel):
    run_id: int
    domain: str
    surface: str
    selected_fields: list[str]
    canonical_fields: list[str]
    field_mapping: dict[str, str]
