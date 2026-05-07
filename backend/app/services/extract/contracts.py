from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CandidateSet",
    "ExtractionResult",
    "ExtractionWarning",
    "RawCandidate",
    "RuntimeMetrics",
]


class RawCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(min_length=1)
    value: Any
    source: str = Field(min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: str = Field(min_length=1)
    page_url: str = ""
    candidates: list[RawCandidate] = Field(default_factory=list)


class ExtractionWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    field_name: str | None = None
    severity: Literal["info", "warning", "error"] = "warning"


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: str = Field(min_length=1)
    page_url: str = ""
    record: dict[str, Any] = Field(default_factory=dict)
    candidates: CandidateSet | None = None
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RuntimeMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counters: dict[str, int] = Field(default_factory=dict)

