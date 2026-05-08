from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.models.crawl import CrawlRecord
from app.services.config.public_record_policy import (
    PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS,
)
from app.services.db_utils import mapping_or_empty
from app.services.field_value_core import object_list as _object_list
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EXPORT_RECORD_VERSION = "1"


class FieldProvenance(BaseModel):
    status: str = "found"
    value: Any = None
    sources: list[str] = Field(default_factory=list)
    selector_trace: dict[str, Any] | None = None

    @field_validator("sources", mode="before")
    @classmethod
    def _sources(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("field provenance sources must be a list")
        return [str(item) for item in value if str(item or "").strip()]


class AcquisitionTrace(BaseModel):
    method: str = ""
    status_code: int | None = None
    final_url: str = ""
    blocked: bool = False
    adapter_name: str | None = None
    adapter_source_type: str | None = None
    network_payload_count: int = 0
    browser_diagnostics: dict[str, Any] = Field(default_factory=dict)


class ExtractionTrace(BaseModel):
    source: str = "extraction"
    confidence: dict[str, Any] = Field(default_factory=dict)
    self_heal: dict[str, Any] = Field(default_factory=dict)
    field_repair: dict[str, Any] = Field(default_factory=dict)
    manifest_trace: dict[str, Any] = Field(default_factory=dict)
    review_bucket: list[dict[str, Any]] = Field(default_factory=list)
    semantic: dict[str, Any] = Field(default_factory=dict)
    rejected_public_fields: dict[str, Any] = Field(default_factory=dict)


class ExportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = EXPORT_RECORD_VERSION
    source_url: str
    data: dict[str, Any] = Field(default_factory=dict)
    acquisition: AcquisitionTrace = Field(default_factory=AcquisitionTrace)
    extraction: ExtractionTrace = Field(default_factory=ExtractionTrace)
    field_discovery: dict[str, FieldProvenance] = Field(default_factory=dict)

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: str) -> str:
        text = str(value or "").strip()
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute http(s) URL")
        return text

    @model_validator(mode="after")
    def _record_url_identity(self) -> "ExportRecord":
        record_url = self.data.get("url")
        if record_url in (None, ""):
            return self
        parsed = urlparse(str(record_url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("record url must be an absolute http(s) URL")
        return self


def build_source_trace(
    acquisition_result,
    record: dict[str, object],
    *,
    data: dict[str, object],
) -> dict[str, object]:
    field_discovery: dict[str, object] = {}
    field_sources = mapping_or_empty(record.get("_field_sources"))
    selector_traces = mapping_or_empty(record.get("_selector_traces"))
    rejected_public_fields = mapping_or_empty(record.get("_rejected_public_fields"))
    for key, value in record.items():
        if str(key).startswith("_"):
            continue
        discovery: dict[str, object] = {
            "status": "found",
            "value": value,
            "sources": _string_list(
                field_sources.get(str(key), [str(record.get("_source") or "extraction")])
            ),
        }
        selector_trace = selector_traces.get(str(key))
        if isinstance(selector_trace, dict):
            discovery["selector_trace"] = {
                **dict(selector_trace),
                "survived_to_final_record": True,
            }
        field_discovery[str(key)] = discovery
    trace = {
        "acquisition": {
            "method": acquisition_result.method,
            "status_code": acquisition_result.status_code,
            "final_url": acquisition_result.final_url,
            "blocked": acquisition_result.blocked,
            "adapter_name": acquisition_result.adapter_name,
            "adapter_source_type": acquisition_result.adapter_source_type,
            "network_payload_count": len(list(acquisition_result.network_payloads or [])),
            "browser_diagnostics": mapping_or_empty(acquisition_result.browser_diagnostics),
        },
        "extraction": {
            "source": str(record.get("_source") or "extraction"),
            "confidence": mapping_or_empty(record.get("_confidence")),
            "self_heal": mapping_or_empty(record.get("_self_heal")),
            "field_repair": mapping_or_empty(record.get("_field_repair")),
            "manifest_trace": mapping_or_empty(record.get("_manifest_trace")),
            "review_bucket": _object_list(record.get("_review_bucket")),
            "semantic": mapping_or_empty(record.get("_semantic")),
            "rejected_public_fields": rejected_public_fields,
        },
        "field_discovery": field_discovery,
    }
    ExportRecord.model_validate(
        {
            "source_url": str(record.get("source_url") or acquisition_result.final_url),
            "data": clean_export_data(data),
            **trace,
        }
    )
    return trace


def export_record_from_row(row: CrawlRecord) -> ExportRecord:
    source_trace = row.source_trace if isinstance(row.source_trace, dict) else {}
    return ExportRecord.model_validate(
        {
            "source_url": row.source_url,
            "data": clean_export_data(row.data if isinstance(row.data, dict) else {}),
            "acquisition": source_trace.get("acquisition") or {},
            "extraction": source_trace.get("extraction") or {},
            "field_discovery": source_trace.get("field_discovery") or {},
        }
    )


def clean_export_data(data: dict) -> dict:
    """Strip empty/null values and internal keys from export data."""
    return {
        k: v
        for k, v in data.items()
        if (
            v not in (None, "", [], {})
            and not str(k).strip().startswith("_")
            and str(k).strip().lower() not in PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS
        )
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
