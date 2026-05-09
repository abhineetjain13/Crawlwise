from __future__ import annotations

import json
from json import loads as parse_json
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from app.services.config.llm_runtime import llm_runtime_settings
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)


def _require_present_value(value: Any) -> Any:
    if value in (None, "", [], {}):
        raise ValueError("must not be empty")
    return value


def _require_non_empty_text(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("must not be empty")
    return normalized


def _require_payload_key(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized or normalized.startswith("_"):
        raise ValueError("must be a non-empty field key")
    return normalized


def _require_schema_field_name(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or not _is_valid_schema_field_name(normalized):
        raise ValueError("contains an invalid field name")
    return normalized


_FieldKey = Annotated[str, AfterValidator(_require_payload_key)]
_NonEmptyText = Annotated[str, AfterValidator(_require_non_empty_text)]
_PresentValue = Annotated[Any, AfterValidator(_require_present_value)]
_SchemaFieldName = Annotated[str, AfterValidator(_require_schema_field_name)]


class _XPathSelector(TypedDict):
    field_name: _NonEmptyText
    xpath: NotRequired[str]
    css_selector: NotRequired[str]


class _CanonicalFieldReview(TypedDict):
    suggested_value: _PresentValue
    source: _NonEmptyText
    supporting_sources: NotRequired[list[_NonEmptyText]]


class _ReviewBucketItem(TypedDict):
    key: _NonEmptyText
    value: _PresentValue
    source: _NonEmptyText


class _FieldCleanupReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical: dict[_FieldKey, _CanonicalFieldReview] = Field(default_factory=dict)
    review_bucket: list[_ReviewBucketItem] = Field(default_factory=list)


class _PageClassificationPayload(TypedDict):
    page_type: Literal["listing", "detail", "challenge", "error", "unknown"]
    has_secondary_listing: bool
    wait_selector_hint: str
    reasoning: str


class _SchemaInferencePayload(TypedDict):
    confirmed_fields: list[_SchemaFieldName]
    new_fields: list[_SchemaFieldName]
    absent_fields: list[_SchemaFieldName]


class _ProductIntelligenceEnrichmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_title: str = ""
    style_name: str = ""
    model_name: str = ""
    inferred_attributes: dict[str, Any] = Field(default_factory=dict)
    suggested_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    match_explanation: str = ""
    mismatch_risks: list[str] = Field(default_factory=list)
    reason_updates: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("reason_updates")
    @classmethod
    def _validate_reason_updates(
        cls, value: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        allowed = {
            "reason_name",
            "reason_code",
            "description",
            "source",
            "timestamp",
            "conflicting_value",
            "resolution_action",
        }
        for item in value:
            unknown = set(item) - allowed
            if unknown:
                raise ValueError(
                    f"unknown reason_updates keys: {', '.join(sorted(unknown))}"
                )
        return value


class _ProductIntelligenceBrandInferencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class _DataEnrichmentSemanticPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_path: str | None = None
    color_family: str | None = None
    size_normalized: list[str] | None = None
    size_system: str | None = None
    gender_normalized: str | None = None
    materials_normalized: list[str] | None = None
    availability_normalized: str | None = None
    intent_attributes: list[str] | None = None
    audience: list[str] | None = None
    style_tags: list[str] | None = None
    ai_discovery_tags: list[str] | None = None
    suggested_bundles: list[str] | None = None


_PAYLOAD_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    "direct_record_extraction": TypeAdapter(list[dict[_FieldKey, Any]]),
    "xpath_discovery": TypeAdapter(list[_XPathSelector]),
    "missing_field_extraction": TypeAdapter(dict[_FieldKey, Any]),
    "field_cleanup_review": TypeAdapter(_FieldCleanupReviewPayload),
    "page_classification": TypeAdapter(_PageClassificationPayload),
    "schema_inference": TypeAdapter(_SchemaInferencePayload),
    "product_intelligence_enrichment": TypeAdapter(
        _ProductIntelligenceEnrichmentPayload
    ),
    "product_intelligence_brand_inference": TypeAdapter(
        _ProductIntelligenceBrandInferencePayload
    ),
    "data_enrichment_semantic": TypeAdapter(_DataEnrichmentSemanticPayload),
}


def parse_payload(raw_text: str, *, response_type: str) -> dict | list | None:
    if response_type == "array":
        return _parse_json_array(raw_text)
    return _parse_json_object(raw_text)


def validate_task_payload(
    task_type: str,
    payload: object,
) -> tuple[object, str | None]:
    adapter = _PAYLOAD_ADAPTERS.get(str(task_type or "").strip())
    if adapter is None:
        return payload, None
    try:
        validated = adapter.validate_python(payload)
    except ValidationError as exc:
        return payload, _format_validation_error(task_type, exc)
    return validated.model_dump() if isinstance(
        validated, BaseModel
    ) else validated, None


def _format_validation_error(task_type: str, exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error.get("loc", ()) if part != "root")
    detail = str(error.get("msg") or "invalid payload")
    suffix = f" at {location}" if location else ""
    return f"{task_type} payload validation failed{suffix}: {detail}"


def _is_valid_schema_field_name(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= llm_runtime_settings.schema_field_name_max_length
        and value.replace("_", "").isalnum()
        and value.lower() == value
        and not value.startswith("_")
        and not value.isdigit()
    )


def _parse_json_object(raw_text: str) -> dict | None:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        payload = parse_json(raw_text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_json_array(raw_text: str) -> list | None:
    start = raw_text.find("[")
    end = raw_text.rfind("]")
    if start == -1 or end < start:
        return None
    try:
        payload = parse_json(raw_text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, list) else None
