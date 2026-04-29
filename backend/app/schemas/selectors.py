from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl, model_validator


class SelectorDomainSummaryResponse(BaseModel):
    domain: str
    surface: str
    selector_count: int
    updated_at: datetime | None = None


class SelectorRecordResponse(BaseModel):
    id: int
    domain: str
    surface: str
    field_name: str
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None
    status: str = "validated"
    sample_value: str | None = None
    source: str = "domain_memory"
    source_run_id: int | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SelectorCreateRequest(BaseModel):
    domain: str
    surface: str = "generic"
    field_name: str
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None
    status: str | None = None
    sample_value: str | None = None
    source: str | None = None
    source_run_id: int | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _require_selector(self) -> "SelectorCreateRequest":
        if not any(
            str(value or "").strip()
            for value in (self.css_selector, self.xpath, self.regex)
        ):
            raise ValueError("At least one of css_selector, xpath, or regex is required")
        return self


class SelectorUpdateRequest(BaseModel):
    field_name: str | None = None
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None
    status: str | None = None
    sample_value: str | None = None
    source: str | None = None
    source_run_id: int | None = None
    is_active: bool | None = None


class SelectorTestRequest(BaseModel):
    url: HttpUrl | str
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None

    @model_validator(mode="after")
    def _require_selector(self) -> "SelectorTestRequest":
        if not any(
            str(value or "").strip()
            for value in (self.css_selector, self.xpath, self.regex)
        ):
            raise ValueError("At least one of css_selector, xpath, or regex is required")
        return self


class SelectorTestResponse(BaseModel):
    matched_value: str | None = None
    count: int = 0
    selector_used: str | None = None


class SelectorSuggestionRecord(BaseModel):
    field_name: str | None = None
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None
    sample_value: str | None = None
    source: str | None = None


class SelectorSuggestRequest(BaseModel):
    url: HttpUrl | str
    expected_columns: list[str] = Field(default_factory=list)
    surface: str | None = None

    @model_validator(mode="after")
    def _require_expected_columns(self) -> "SelectorSuggestRequest":
        if not any(str(value or "").strip() for value in self.expected_columns):
            raise ValueError("expected_columns must contain at least one field")
        return self


class SelectorSuggestResponse(BaseModel):
    surface: str
    suggestions: dict[str, list[SelectorSuggestionRecord]]
    preview_url: str | None = None
    iframe_promoted: bool = False
