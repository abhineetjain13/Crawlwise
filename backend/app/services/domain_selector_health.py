from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CRITICAL_FIELDS_BY_SURFACE",
    "SelectorHealthSnapshot",
]

CRITICAL_FIELDS_BY_SURFACE: dict[str, tuple[str, ...]] = {
    "ecommerce_detail": ("title", "price", "url"),
    "ecommerce_listing": ("title", "url"),
    "job_detail": ("title", "company", "url"),
    "job_listing": ("title", "url"),
    "automobile_detail": ("title", "price", "url"),
    "automobile_listing": ("title", "url"),
    "table": ("url",),
}


class SelectorHealthSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = ""
    surface: str = ""
    field_name: str = ""
    selector: str = ""
    hit_count: int = Field(default=0, ge=0)
    miss_count: int = Field(default=0, ge=0)
    last_hit_at: datetime | None = None
    last_miss_at: datetime | None = None
    stale: bool = False
    critical: bool = False
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

