# Selector request and response schemas.
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SelectorCreate(BaseModel):
    domain: str
    field_name: str
    selector: str
    selector_type: str


class SelectorUpdate(BaseModel):
    field_name: str | None = None
    selector: str | None = None
    selector_type: str | None = None
    is_active: bool | None = None


class SelectorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    field_name: str
    selector: str
    selector_type: str
    source: str
    last_validated_at: datetime | None
    is_active: bool
    created_at: datetime


class SelectorSuggestRequest(BaseModel):
    url: str
    expected_columns: list[str] = Field(default_factory=list)


class SelectorTestRequest(BaseModel):
    url: str
    selector: str
    selector_type: str


class SelectorTestResponse(BaseModel):
    matched_value: str | None
    count: int
