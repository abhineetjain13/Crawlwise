from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ProductIntelligenceOptions(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    max_source_products: int = Field(
        default=10,
        ge=1,
        le=500,
        validation_alias=AliasChoices("max_source_products", "max_sources", "max_source"),
    )
    max_candidates_per_product: int = Field(
        default=2,
        ge=1,
        le=25,
        validation_alias=AliasChoices(
            "max_candidates_per_product",
            "max_urls",
            "max_url",
            "max_candidates",
        ),
    )
    search_provider: Literal["serpapi", "google_native"] = "serpapi"
    private_label_mode: Literal["include", "flag", "exclude"] = "flag"
    confidence_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    allowed_domains: list[str] = Field(default_factory=list)
    excluded_domains: list[str] = Field(default_factory=list)
    llm_enrichment_enabled: bool = False


class ProductIntelligenceSourceRecordInput(BaseModel):
    id: int | None = None
    run_id: int | None = None
    source_url: str = ""
    data: dict = Field(default_factory=dict)


class ProductIntelligenceJobCreate(BaseModel):
    source_run_id: int | None = None
    source_record_ids: list[int] = Field(default_factory=list)
    source_records: list[ProductIntelligenceSourceRecordInput] = Field(default_factory=list)
    options: ProductIntelligenceOptions = Field(default_factory=ProductIntelligenceOptions)


class ProductIntelligenceDiscoveryRequest(BaseModel):
    source_run_id: int | None = None
    source_record_ids: list[int] = Field(default_factory=list)
    source_records: list[ProductIntelligenceSourceRecordInput] = Field(default_factory=list)
    options: ProductIntelligenceOptions = Field(default_factory=ProductIntelligenceOptions)


class ProductIntelligenceReviewRequest(BaseModel):
    action: Literal["pending", "accepted", "rejected"]


class ProductIntelligenceJobResponse(BaseModel):
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


class ProductIntelligenceSourceProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    source_run_id: int | None = None
    source_record_id: int | None = None
    source_url: str
    brand: str
    normalized_brand: str
    title: str
    sku: str
    mpn: str
    gtin: str
    price: float | None = None
    currency: str
    image_url: str
    is_private_label: bool
    payload: dict
    created_at: datetime


class ProductIntelligenceCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    source_product_id: int
    candidate_crawl_run_id: int | None = None
    url: str
    domain: str
    source_type: str
    query_used: str
    search_rank: int
    status: str
    payload: dict
    created_at: datetime
    updated_at: datetime


class ProductIntelligenceMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    source_product_id: int
    candidate_id: int
    candidate_record_id: int | None = None
    score: float
    score_label: str
    review_status: str
    source_price: float | None = None
    candidate_price: float | None = None
    currency: str
    availability: str
    candidate_url: str
    candidate_domain: str
    score_reasons: dict
    llm_enrichment: dict
    created_at: datetime
    updated_at: datetime


class ProductIntelligenceJobDetailResponse(BaseModel):
    job: ProductIntelligenceJobResponse
    source_products: list[ProductIntelligenceSourceProductResponse] = Field(default_factory=list)
    candidates: list[ProductIntelligenceCandidateResponse] = Field(default_factory=list)
    matches: list[ProductIntelligenceMatchResponse] = Field(default_factory=list)


class ProductIntelligenceDiscoveredCandidateResponse(BaseModel):
    source_record_id: int | None = None
    source_run_id: int | None = None
    source_url: str = ""
    source_title: str = ""
    source_brand: str = ""
    source_price: float | None = None
    source_currency: str = ""
    source_index: int
    url: str
    domain: str
    source_type: str
    query_used: str
    search_rank: int
    payload: dict = Field(default_factory=dict)
    intelligence: dict = Field(default_factory=dict)


class ProductIntelligenceDiscoveryResponse(BaseModel):
    job_id: int
    options: dict
    source_count: int
    candidate_count: int
    search_provider: str = ""
    candidates: list[ProductIntelligenceDiscoveredCandidateResponse] = Field(default_factory=list)
