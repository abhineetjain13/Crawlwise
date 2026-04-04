# Crawl request and response schemas.
from __future__ import annotations

from datetime import datetime
from urllib.parse import SplitResult, urlsplit, urlunsplit

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
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def _sanitize_settings(self) -> "CrawlRunResponse":
        self.settings = _sanitize_crawl_settings(self.settings)
        return self


class CrawlRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    source_url: str
    data: dict
    raw_data: dict
    discovered_data: dict
    source_trace: dict
    raw_html_path: str | None = None
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


class FieldCommitItem(BaseModel):
    record_id: int
    field_name: str
    value: object


class FieldCommitRequest(BaseModel):
    items: list[FieldCommitItem] = Field(default_factory=list)


class FieldCommitResponse(BaseModel):
    run_id: int
    updated_records: int
    updated_fields: int


class LLMCommitItem(FieldCommitItem):
    pass


class LLMCommitRequest(FieldCommitRequest):
    pass


class LLMCommitResponse(FieldCommitResponse):
    pass


_SENSITIVE_SETTING_KEYS = {
    "api_key",
    "api_key_encrypted",
    "authorization",
    "proxy_password",
}
_SENSITIVE_PROXY_KEYS = {
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
}


def _sanitize_crawl_settings(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    sanitized: dict[str, object] = {}
    for key, raw_value in value.items():
        normalized_key = str(key or "").strip()
        normalized_lookup = normalized_key.lower()
        if normalized_lookup in _SENSITIVE_SETTING_KEYS:
            continue
        sanitized[normalized_key] = _sanitize_setting_value(normalized_lookup, raw_value)
    return sanitized


def _sanitize_setting_value(key: str, value: object) -> object:
    if key in {"proxy_list", "proxies"} and isinstance(value, list):
        return [_sanitize_proxy_item(item) for item in value]
    if key == "proxy" and isinstance(value, str):
        return _mask_proxy_url(value)
    if isinstance(value, dict):
        return _sanitize_crawl_settings(value)
    if isinstance(value, list):
        return [_sanitize_crawl_settings(item) if isinstance(item, dict) else item for item in value]
    return value


def _sanitize_proxy_item(value: object) -> object:
    if isinstance(value, str):
        return _mask_proxy_url(value)
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, raw_value in value.items():
            normalized_key = str(key or "").strip()
            if normalized_key.lower() in _SENSITIVE_PROXY_KEYS:
                continue
            sanitized[normalized_key] = raw_value
        for key in list(sanitized.keys()):
            if key.lower() in {"url", "proxy", "proxy_url", "server"} and isinstance(sanitized[key], str):
                sanitized[key] = _mask_proxy_url(sanitized[key])
        return sanitized
    return value


def _mask_proxy_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    if not parsed.username and not parsed.password:
        return raw
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    masked_netloc = f"***:***@{host}" if host else "***:***"
    rebuilt = SplitResult(
        scheme=parsed.scheme,
        netloc=masked_netloc,
        path=parsed.path,
        query=parsed.query,
        fragment=parsed.fragment,
    )
    return urlunsplit(rebuilt)
