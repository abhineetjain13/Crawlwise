# Crawl request and response schemas.
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Literal
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator
from app.schemas.selectors import SelectorRecordResponse

_DISPLAY_HIDDEN_RECORD_FIELDS = {"page_markdown", "table_markdown", "record_type"}


class CrawlCreate(BaseModel):
    run_type: str  # "crawl", "batch", "csv"
    url: str | None = None
    urls: list[str] = Field(default_factory=list)
    surface: str  # "ecommerce_listing", "ecommerce_detail", "job_listing", "job_detail", "automobile_listing", "automobile_detail", "tabular"
    settings: dict = Field(default_factory=dict)
    # settings may include traversal controls; backend preserves user-selected controls.
    requested_fields: list[str] = Field(default_factory=list)
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
    def _sanitize_settings(self) -> CrawlRunResponse:
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
    review_bucket: list[UnverifiedAttribute] = Field(default_factory=list)
    provenance_available: bool = False
    raw_html_path: str | None = None
    created_at: datetime


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


class ReviewResponse(BaseModel):
    run: CrawlRunResponse
    normalized_fields: list[str]
    discovered_fields: list[str]
    canonical_fields: list[str]
    domain_mapping: dict[str, str]
    suggested_mapping: dict[str, str]
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


class DomainRecipeRequestedCoverage(BaseModel):
    requested: list[str] = Field(default_factory=list)
    found: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class DomainRecipeSelectorCandidate(BaseModel):
    candidate_key: str
    field_name: str
    selector_kind: str
    selector_value: str
    selector_source: str
    sample_value: str | None = None
    source_record_ids: list[int] = Field(default_factory=list)
    source_run_id: int | None = None
    saved_selector_id: int | None = None
    already_saved: bool = False
    final_field_source: str | None = None


class DomainRecipeAffordanceCandidates(BaseModel):
    accordions: list[str] = Field(default_factory=list)
    tabs: list[str] = Field(default_factory=list)
    carousels: list[str] = Field(default_factory=list)
    shadow_hosts: list[str] = Field(default_factory=list)
    iframe_promotion: str | None = None
    browser_required: bool = False


class DomainRecipeAcquisitionEvidence(BaseModel):
    actual_fetch_method: str | None = None
    browser_used: bool = False
    browser_reason: str | None = None
    acquisition_summary: dict = Field(default_factory=dict)
    cookie_memory_available: bool = False


class DomainRecipeFieldFeedback(BaseModel):
    action: str
    source_kind: str
    source_value: str | None = None
    source_run_id: int | None = None
    created_at: datetime


class DomainRecipeFieldLearningItem(BaseModel):
    field_name: str
    value: Any
    source_labels: list[str] = Field(default_factory=list)
    selector_kind: str | None = None
    selector_value: str | None = None
    source_record_ids: list[int] = Field(default_factory=list)
    feedback: DomainRecipeFieldFeedback | None = None


class DomainFieldFeedbackRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    surface: str
    field_name: str
    action: Literal["keep", "reject"]
    source_kind: str
    source_value: str | None = None
    source_run_id: int | None = None
    selector_kind: str | None = None
    selector_value: str | None = None
    source_record_ids: list[int] = Field(default_factory=list)
    created_at: datetime


class DomainRunFetchProfile(BaseModel):
    fetch_mode: Literal["auto", "http_only", "browser_only", "http_then_browser"] = "auto"
    extraction_source: Literal[
        "raw_html",
        "rendered_dom",
        "rendered_dom_visual",
        "network_payload_first",
    ] = "raw_html"
    js_mode: Literal["auto", "enabled", "disabled"] = "auto"
    include_iframes: bool = False
    traversal_mode: Literal[
        "auto",
        "scroll",
        "load_more",
        "view_all",
        "paginate",
    ] | None = None
    request_delay_ms: int = Field(default=100, ge=0, le=60_000)
    max_pages: int = Field(default=5, ge=1, le=100)
    max_scrolls: int = Field(default=8, ge=0, le=100)


class DomainRunLocalityProfile(BaseModel):
    geo_country: str = "auto"
    language_hint: str | None = None
    currency_hint: str | None = None


class DomainRunDiagnosticsProfile(BaseModel):
    capture_html: bool = True
    capture_screenshot: bool = False
    capture_network: str = "off"
    capture_response_headers: bool = True
    capture_browser_diagnostics: bool = True


class DomainRunProfilePayload(BaseModel):
    version: int = 1
    fetch_profile: DomainRunFetchProfile = Field(default_factory=DomainRunFetchProfile)
    locality_profile: DomainRunLocalityProfile = Field(default_factory=DomainRunLocalityProfile)
    diagnostics_profile: DomainRunDiagnosticsProfile = Field(default_factory=DomainRunDiagnosticsProfile)
    source_run_id: int | None = None
    saved_at: datetime | None = None


class DomainRecipeResponse(BaseModel):
    run_id: int
    domain: str
    surface: str
    requested_field_coverage: DomainRecipeRequestedCoverage
    acquisition_evidence: DomainRecipeAcquisitionEvidence = Field(default_factory=DomainRecipeAcquisitionEvidence)
    field_learning: list[DomainRecipeFieldLearningItem] = Field(default_factory=list)
    selector_candidates: list[DomainRecipeSelectorCandidate] = Field(default_factory=list)
    affordance_candidates: DomainRecipeAffordanceCandidates = Field(default_factory=DomainRecipeAffordanceCandidates)
    saved_selectors: list[SelectorRecordResponse] = Field(default_factory=list)
    saved_run_profile: DomainRunProfilePayload | None = None


class DomainRunProfileLookupResponse(BaseModel):
    domain: str
    surface: str
    saved_run_profile: DomainRunProfilePayload | None = None


class DomainRunProfileRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    surface: str
    profile: DomainRunProfilePayload
    created_at: datetime
    updated_at: datetime


class DomainCookieMemoryRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    cookie_count: int
    origin_count: int
    updated_at: datetime


class DomainRecipeSelectorPromotionItem(BaseModel):
    candidate_key: str
    field_name: str
    selector_kind: str
    selector_value: str
    sample_value: str | None = None


class DomainRecipePromoteSelectorsRequest(BaseModel):
    selectors: list[DomainRecipeSelectorPromotionItem] = Field(default_factory=list)


class DomainRecipeSaveRunProfileRequest(BaseModel):
    profile: DomainRunProfilePayload


class DomainRecipeFieldActionRequest(BaseModel):
    field_name: str
    action: Literal["keep", "reject"]
    selector_kind: str | None = None
    selector_value: str | None = None
    source_record_ids: list[int] = Field(default_factory=list)


class LLMCommitItem(FieldCommitItem):
    pass


class LLMCommitRequest(FieldCommitRequest):
    pass


class LLMCommitResponse(FieldCommitResponse):
    pass


class UnverifiedAttribute(BaseModel):
    key: str
    value: Any
    source: str


class CrawlRecordProvenanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    source_url: str
    raw_data: dict
    discovered_data: dict
    source_trace: dict
    manifest_trace: dict = Field(default_factory=dict)
    raw_html_path: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _expand_provenance(self) -> CrawlRecordProvenanceResponse:
        self.raw_data = self.raw_data if isinstance(self.raw_data, dict) else {}
        self.discovered_data = (
            self.discovered_data if isinstance(self.discovered_data, dict) else {}
        )
        self.source_trace = (
            self.source_trace if isinstance(self.source_trace, dict) else {}
        )
        self.manifest_trace = _extract_manifest_trace(
            self.source_trace, self.discovered_data
        )
        self.source_trace = {
            key: value
            for key, value in self.source_trace.items()
            if key not in _SOURCE_TRACE_EXCLUDE_KEYS and value not in (None, "", [], {})
        }
        return self


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
        sanitized[normalized_key] = _sanitize_setting_value(
            normalized_lookup, raw_value
        )
    return sanitized


def _sanitize_setting_value(key: str, value: object) -> object:
    if key in {"proxy_list", "proxies"} and isinstance(value, list):
        return [_sanitize_proxy_item(item) for item in value]
    if key == "proxy" and isinstance(value, str):
        return _mask_proxy_url(value)
    if isinstance(value, dict):
        return _sanitize_crawl_settings(value)
    if isinstance(value, list):
        return [
            _sanitize_crawl_settings(item) if isinstance(item, dict) else item
            for item in value
        ]
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
            if key.lower() in {"url", "proxy", "proxy_url", "server"} and isinstance(
                sanitized[key], str
            ):
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


_LEGACY_MANIFEST_KEYS = {
    "adapter_data",
    "network_payloads",
    "json_ld",
    "microdata",
    "next_data",
    "_hydrated_states",
    "embedded_json",
    "open_graph",
    "tables",
    "full_json_response",
    "json_record_keys",
    "content_type",
}
_LEGACY_REVIEW_KEYS = {
    "semantic",
    "specifications",
    "promoted_fields",
    "discovered_fields",
}
_DISCOVERED_DATA_EXCLUDE_KEYS = (
    _LEGACY_MANIFEST_KEYS | _LEGACY_REVIEW_KEYS | {"review_bucket", "manifest_trace"}
)
_SOURCE_TRACE_EXCLUDE_KEYS = {"manifest_trace"}


def _extract_manifest_trace(
    source_trace: object, discovered_data: object
) -> dict[str, Any]:
    trace = source_trace if isinstance(source_trace, dict) else {}
    discovered = discovered_data if isinstance(discovered_data, dict) else {}
    manifest_trace = trace.get("manifest_trace")
    if isinstance(manifest_trace, dict):
        return {
            key: value
            for key, value in manifest_trace.items()
            if value not in (None, "", [], {})
        }
    legacy_manifest = {
        key: value
        for key, value in discovered.items()
        if key in _LEGACY_MANIFEST_KEYS and value not in (None, "", [], {})
    }
    return legacy_manifest


def _normalize_review_bucket(
    value: object, *, fallback: object | None = None
) -> list[UnverifiedAttribute]:
    rows: list[UnverifiedAttribute] = []
    seen: set[tuple[str, str]] = set()
    raw_rows = value if isinstance(value, list) else []
    for raw_row in raw_rows:
        _append_review_bucket_row(rows, seen, raw_row)
    if rows:
        return rows
    fallback_dict = fallback if isinstance(fallback, dict) else {}
    for key in ("discovered_fields", "specifications", "promoted_fields"):
        payload = fallback_dict.get(key)
        if not isinstance(payload, dict):
            continue
        for field_name, field_value in payload.items():
            _append_review_bucket_row(
                rows,
                seen,
                {
                    "key": field_name,
                    "value": field_value,
                    "source": key,
                }
            )
    return rows


def _normalize_review_bucket_row(value: object) -> UnverifiedAttribute | None:
    if not isinstance(value, dict):
        return None
    key = str(value.get("key") or "").strip()
    if not key or key.startswith("_"):
        return None
    raw_value = value.get("value")
    if raw_value in (None, "", [], {}):
        return None
    source = str(value.get("source") or "review_bucket").strip() or "review_bucket"
    return UnverifiedAttribute(
        key=key,
        value=raw_value,
        source=source,
    )


def _append_review_bucket_row(
    rows: list[UnverifiedAttribute],
    seen: set[tuple[str, str]],
    value: object,
) -> None:
    normalized = _normalize_review_bucket_row(value)
    if normalized is None:
        return
    dedupe_key = (
        normalized.key,
        _stable_review_value_fingerprint(normalized.value),
    )
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    rows.append(normalized)


def _stable_review_value_fingerprint(value: object) -> str:
    if isinstance(value, str):
        return " ".join(value.split()).strip().casefold()
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value).strip().casefold()


def serialize_crawl_record_response(value: object) -> CrawlRecordResponse:
    record = CrawlRecordResponse.model_validate(value, from_attributes=True)
    manifest_trace = _extract_manifest_trace(record.source_trace, record.discovered_data)
    record.data = {
        key: item
        for key, item in record.data.items()
        if (
            item not in (None, "", [], {})
            and not str(key).startswith("_")
            and str(key) not in _DISPLAY_HIDDEN_RECORD_FIELDS
        )
    }
    record.review_bucket = _normalize_review_bucket(
        (record.discovered_data or {}).get("review_bucket"),
        fallback=record.discovered_data,
    )
    record.discovered_data = {
        key: item
        for key, item in record.discovered_data.items()
        if key not in _DISCOVERED_DATA_EXCLUDE_KEYS and item not in (None, "", [], {})
    }
    record.source_trace = {
        key: item
        for key, item in record.source_trace.items()
        if key not in _SOURCE_TRACE_EXCLUDE_KEYS and item not in (None, "", [], {})
    }
    record.provenance_available = bool(manifest_trace)
    return record


def serialize_crawl_record_responses(
    values: Iterable[object],
) -> list[CrawlRecordResponse]:
    return [serialize_crawl_record_response(value) for value in values]
