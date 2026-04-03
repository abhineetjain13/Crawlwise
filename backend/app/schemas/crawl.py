# Crawl request and response schemas.
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="after")
    def _clean_for_display(self) -> "CrawlRecordResponse":
        """Strip empty/null fields from data and raw noise from discovered_data.

        The ``data`` dict should only expose populated logical fields.
        ``discovered_data`` strips raw manifest containers that are useful
        internally but are noise for the JSON/CSS view — review/promote is
        where users resolve field mismatches.
        """
        self.data = {
            k: v for k, v in self.data.items()
            if v not in (None, "", [], {}) and not str(k).startswith("_")
        }
        # Strip raw manifest noise from discovered_data — keep only logical metadata
        _noise_keys = {
            "adapter_data", "network_payloads", "json_ld", "microdata",
            "next_data", "tables", "_hydrated_states", "full_json_response",
        }
        self.discovered_data = {
            k: v for k, v in self.discovered_data.items()
            if k not in _noise_keys and v not in (None, "", [], {})
        }
        return self


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


class ReviewSelectorRule(BaseModel):
    id: int | None = None
    field_name: str
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None
    status: str | None = None
    confidence: float | None = None
    sample_value: str | None = None
    source: str | None = None
    is_active: bool = True


class ReviewResponse(BaseModel):
    run: CrawlRunResponse
    normalized_fields: list[str]
    discovered_fields: list[str]
    canonical_fields: list[str]
    domain_mapping: dict[str, str]
    suggested_mapping: dict[str, str]
    selector_memory: list[dict]
    selector_suggestions: dict[str, list[dict]]
    records: list[CrawlRecordResponse]


class ReviewSaveRequest(BaseModel):
    selections: list[ReviewFieldChoice]
    extra_fields: list[str] = Field(default_factory=list)


class ReviewSelectorPreviewRequest(BaseModel):
    selectors: list[ReviewSelectorRule] = Field(default_factory=list)


class ReviewSaveResponse(BaseModel):
    run_id: int
    domain: str
    surface: str
    selected_fields: list[str]
    canonical_fields: list[str]
    field_mapping: dict[str, str]


class ReviewSelectorPreviewResponse(BaseModel):
    records: list[CrawlRecordResponse]
