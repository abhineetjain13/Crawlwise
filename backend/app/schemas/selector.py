# Selector request and response schemas.
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _require_selector_value(
    css_selector: str | None,
    xpath: str | None,
    regex: str | None,
) -> None:
    if any(str(value or "").strip() for value in (css_selector, xpath, regex)):
        return
    raise ValueError("At least one of css_selector, xpath, or regex is required")


class SelectorCreate(BaseModel):
    domain: str
    field_name: str
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None
    status: str | None = "validated"
    sample_value: str | None = None
    source: str | None = "manual"
    source_run_id: int | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def check_at_least_one(self) -> "SelectorCreate":
        _require_selector_value(self.css_selector, self.xpath, self.regex)
        return self


class SelectorUpdate(BaseModel):
    field_name: str | None = None
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None
    status: str | None = None
    sample_value: str | None = None
    source: str | None = None
    source_run_id: int | None = None
    is_active: bool | None = None


class SelectorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    field_name: str
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None
    status: str
    sample_value: str | None = None
    source: str
    source_run_id: int | None = None
    last_validated_at: datetime | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SelectorSuggestRequest(BaseModel):
    url: str
    expected_columns: list[str] = Field(default_factory=list)


class SelectorTestRequest(BaseModel):
    url: str
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None

    @model_validator(mode="after")
    def check_at_least_one(self) -> "SelectorTestRequest":
        _require_selector_value(self.css_selector, self.xpath, self.regex)
        return self


class SelectorTestResponse(BaseModel):
    matched_value: str | None = None
    count: int
    selector_used: str | None = None
