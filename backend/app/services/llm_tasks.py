from __future__ import annotations

import json
import time
from json import loads as parse_json
from string import Template
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from app.core.metrics import observe_llm_task_duration, record_llm_task_outcome
from app.models.crawl import CrawlRun
from app.models.llm import LLMCostLog
from app.services.config.llm_runtime import llm_runtime_settings
from app.services.llm_cache import (
    build_llm_cache_key,
    load_cached_llm_result,
    store_cached_llm_result,
)
from app.services.llm_circuit_breaker import ERROR_PREFIX, LLMErrorCategory, classify_error
from app.services.llm_config_service import (
    get_prompt_task,
    load_prompt_file,
    resolve_provider_api_key,
    resolve_run_config,
)
from app.services.llm_provider_client import call_provider_with_retry, estimate_cost_usd
from app.services.llm_types import LLMTaskResult
from app.services.record_export_service import render_markdown_block
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

_PROMPT_JSON_REPARSE_MAX_CHARS = 16_384


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
    xpath: _NonEmptyText


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


_PAYLOAD_ADAPTERS = {
    "xpath_discovery": TypeAdapter(list[_XPathSelector]),
    "missing_field_extraction": TypeAdapter(dict[_FieldKey, Any]),
    "field_cleanup_review": TypeAdapter(_FieldCleanupReviewPayload),
    "page_classification": TypeAdapter(_PageClassificationPayload),
    "schema_inference": TypeAdapter(_SchemaInferencePayload),
}


async def run_prompt_task(
    session: AsyncSession,
    *,
    task_type: str,
    run_id: int | None,
    domain: str,
    variables: dict[str, Any],
) -> LLMTaskResult:
    started_at = time.monotonic()

    def _finish(result: LLMTaskResult) -> LLMTaskResult:
        provider_label = str(result.provider or "unknown")
        outcome = "success" if not result.error_message else "error"
        record_llm_task_outcome(
            task_type=task_type,
            provider=provider_label,
            outcome=outcome,
            error_category=str(result.error_category or LLMErrorCategory.NONE),
        )
        observe_llm_task_duration(
            task_type=task_type,
            provider=provider_label,
            outcome=outcome,
            seconds=time.monotonic() - started_at,
        )
        return result

    config = await resolve_run_config(session, run_id=run_id, task_type=task_type)
    task = get_prompt_task(task_type)
    if config is None:
        return _finish(
            LLMTaskResult(
                payload=None,
                error_message=f"No LLM config available for task {task_type}",
                error_category=LLMErrorCategory.MISSING_CONFIG,
            )
        )
    if task is None:
        return _finish(
            LLMTaskResult(
                payload=None,
                error_message=f"No prompt registered for task {task_type}",
                error_category=LLMErrorCategory.MISSING_CONFIG,
            )
        )

    system_prompt = load_prompt_file(str(task.get("system_file") or ""))
    user_template = load_prompt_file(str(task.get("user_file") or ""))
    if not system_prompt.strip() or not user_template.strip():
        return _finish(
            LLMTaskResult(
                payload=None,
                error_message=f"Prompt files missing for task {task_type}",
                error_category=LLMErrorCategory.MISSING_CONFIG,
            )
        )

    rendered_user_prompt = Template(user_template).safe_substitute(
        {key: _stringify_prompt_value(value) for key, value in variables.items()}
    )
    safe_user_prompt = _enforce_token_limit(rendered_user_prompt)
    provider = str(config.get("provider") or "")
    model = str(config.get("model") or "")
    response_type = str(task.get("response_type") or "object")
    cache_key = build_llm_cache_key(
        task_type=task_type,
        domain=domain,
        provider=provider,
        model=model,
        response_type=response_type,
        data_key=str(task.get("data_key") or ""),
        system_prompt=system_prompt,
        user_prompt=safe_user_prompt,
        variables=variables,
    )
    cached_result = await load_cached_llm_result(cache_key)
    if cached_result is not None:
        return _finish(cached_result)

    raw, input_tokens, output_tokens = await call_provider_with_retry(
        provider=provider,
        model=model,
        api_key=resolve_provider_api_key(
            provider=provider,
            encrypted_value=str(config.get("api_key_encrypted") or ""),
        ),
        system_prompt=system_prompt,
        user_prompt=safe_user_prompt,
    )
    if raw.startswith(ERROR_PREFIX):
        return _finish(
            LLMTaskResult(
                payload=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider=provider,
                model=model,
                error_message=raw,
                error_category=classify_error(raw),
            )
        )

    payload = _parse_payload(raw, response_type=response_type)
    if payload is None:
        return _finish(
            LLMTaskResult(
                payload=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider=provider,
                model=model,
                error_message=(
                    "Error: Provider response could not be parsed as structured JSON."
                ),
                error_category=LLMErrorCategory.PARSE_FAILURE,
            )
        )

    if isinstance(payload, dict) and task.get("data_key"):
        inner = payload.get(str(task["data_key"]))
        if isinstance(inner, (dict, list)):
            payload = inner
    payload, validation_error = _validate_task_payload(task_type, payload)
    if validation_error is not None:
        return _finish(
            LLMTaskResult(
                payload=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider=provider,
                model=model,
                error_message=f"Error: {validation_error}",
                error_category=LLMErrorCategory.VALIDATION_FAILURE,
            )
        )

    persisted_run_id = run_id
    if run_id is not None:
        existing_run = await session.get(CrawlRun, run_id)
        if existing_run is None:
            persisted_run_id = None
    session.add(
        LLMCostLog(
            run_id=persisted_run_id,
            provider=provider,
            model=model,
            task_type=task_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost_usd(provider, model, input_tokens, output_tokens),
            domain=domain,
        )
    )
    await session.flush()
    result = LLMTaskResult(
        payload=payload,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=provider,
        model=model,
    )
    await store_cached_llm_result(cache_key, result)
    return _finish(result)


async def discover_xpath_candidates(
    session: AsyncSession,
    *,
    run_id: int,
    domain: str,
    url: str,
    html_text: str,
    missing_fields: list[str],
    existing_values: dict[str, object],
) -> tuple[list[dict], str | None]:
    result = await run_prompt_task(
        session,
        task_type="xpath_discovery",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "missing_fields_json": json.dumps(missing_fields),
            "existing_values_json": _truncate_json_literal(
                existing_values,
                llm_runtime_settings.existing_values_max_chars,
            ),
            "html_snippet": _truncate_html(
                html_text,
                llm_runtime_settings.html_snippet_max_chars,
                anchors=missing_fields,
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, list) else []), (result.error_message or None)


async def extract_missing_fields(
    session: AsyncSession,
    *,
    run_id: int,
    domain: str,
    url: str,
    html_text: str,
    missing_fields: list[str],
    existing_values: dict[str, object],
) -> tuple[dict[str, object], str | None]:
    result = await run_prompt_task(
        session,
        task_type="missing_field_extraction",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "missing_fields_json": json.dumps(missing_fields),
            "existing_values_json": _truncate_json_literal(
                existing_values,
                llm_runtime_settings.existing_values_max_chars,
            ),
            "html_snippet": _truncate_html(
                html_text,
                llm_runtime_settings.html_snippet_max_chars,
                anchors=missing_fields,
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, dict) else {}), (result.error_message or None)


async def review_field_candidates(
    session: AsyncSession,
    *,
    run_id: int,
    domain: str,
    url: str,
    html_text: str,
    canonical_fields: list[str],
    target_fields: list[str],
    existing_values: dict[str, object],
    candidate_evidence: dict[str, list[dict]],
    discovered_sources: dict[str, object],
) -> tuple[dict[str, object], str | None]:
    result = await run_prompt_task(
        session,
        task_type="field_cleanup_review",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "canonical_fields_json": json.dumps(canonical_fields),
            "target_fields_json": json.dumps(target_fields),
            "existing_values_json": _truncate_json_literal(
                {field: existing_values.get(field) for field in target_fields},
                llm_runtime_settings.existing_values_max_chars,
            ),
            "candidate_evidence_json": _truncate_json_literal(
                _safe_truncate_for_prompt(candidate_evidence),
                llm_runtime_settings.candidate_evidence_max_chars,
            ),
            "discovered_sources_json": _truncate_json_literal(
                discovered_sources,
                llm_runtime_settings.discovered_sources_max_chars,
            ),
            "html_snippet": _truncate_html(
                html_text,
                llm_runtime_settings.html_snippet_max_chars,
                anchors=[
                    *target_fields,
                    *[
                        str(existing_values.get(field) or "")
                        for field in target_fields
                    ],
                ],
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, dict) else {}), (result.error_message or None)


def _parse_payload(raw_text: str, *, response_type: str) -> dict | list | None:
    if response_type == "array":
        return _parse_json_array(raw_text)
    return _parse_json_object(raw_text)


def _validate_task_payload(
    task_type: str,
    payload: object,
) -> tuple[dict | list | object, str | None]:
    adapter = _PAYLOAD_ADAPTERS.get(str(task_type or "").strip())
    if adapter is None:
        return payload, None
    try:
        validated = adapter.validate_python(payload)
    except ValidationError as exc:
        return payload, _format_validation_error(task_type, exc)
    return validated.model_dump() if isinstance(validated, BaseModel) else validated, None


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


def _truncate_html(
    html_text: str,
    limit: int,
    *,
    anchors: list[str] | None = None,
) -> str:
    if limit <= 0:
        return ""
    rendered = render_markdown_block(html_text).strip()
    if len(rendered) <= limit:
        return rendered
    focused = _focus_markdown_context(rendered, anchors or [])
    return (focused or rendered)[:limit]


def _focus_markdown_context(markdown_text: str, anchors: list[str]) -> str:
    normalized_anchors = _normalize_html_anchor_terms(anchors)
    if not normalized_anchors:
        return ""
    focused_lines: list[str] = []
    seen: set[str] = set()
    previous_line = ""
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if not any(anchor in lowered for anchor in normalized_anchors):
            previous_line = line
            continue
        if previous_line and previous_line not in seen:
            focused_lines.append(previous_line)
            seen.add(previous_line)
        if line not in seen:
            focused_lines.append(line)
            seen.add(line)
        previous_line = line
    return "\n".join(focused_lines)


def _normalize_html_anchor_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value or "").strip().lower()
        if not raw:
            continue
        for candidate in {
            raw,
            raw.replace("_", " "),
            raw.replace("&", "and"),
        }:
            cleaned = " ".join(candidate.split())
            if (
                len(cleaned) < llm_runtime_settings.html_anchor_min_length
                or cleaned in seen
            ):
                continue
            seen.add(cleaned)
            terms.append(cleaned)
    return sorted(terms, key=len, reverse=True)


def _safe_truncate_for_prompt(
    value: object,
    max_str_len: int = llm_runtime_settings.prompt_safe_truncate_max_str_len,
    max_list_items: int = llm_runtime_settings.prompt_safe_truncate_max_list_items,
) -> object:
    if isinstance(value, str):
        return value[:max_str_len] + "..." if len(value) > max_str_len else value
    if isinstance(value, list):
        truncated = [
            _safe_truncate_for_prompt(
                item,
                max_str_len=max_str_len,
                max_list_items=max_list_items,
            )
            for item in value[:max_list_items]
        ]
        if len(value) > max_list_items:
            truncated.append(f"... ({len(value) - max_list_items} more items)")
        return truncated
    if isinstance(value, dict):
        return {
            str(key): _safe_truncate_for_prompt(
                item,
                max_str_len=max_str_len,
                max_list_items=max_list_items,
            )
            for key, item in value.items()
        }
    return value


def _truncate_json_literal(value: Any, limit: int) -> str:
    compact = _compact_json_value(value)
    rendered = json.dumps(compact, default=str)
    if len(rendered) <= limit:
        return rendered
    if isinstance(compact, dict):
        trimmed: dict[str, Any] = {}
        for key, item in compact.items():
            candidate = {**trimmed, key: item}
            if len(json.dumps(candidate, default=str)) > limit:
                break
            trimmed[key] = item
        return json.dumps(trimmed, default=str)
    if isinstance(compact, list):
        trimmed_list: list[Any] = []
        for item in compact:
            candidate = [*trimmed_list, item]
            if len(json.dumps(candidate, default=str)) > limit:
                break
            trimmed_list.append(item)
        return json.dumps(trimmed_list, default=str)
    return json.dumps(str(compact)[: max(0, limit - 2)], default=str)


def _enforce_token_limit(
    text: str,
    limit: int = llm_runtime_settings.prompt_token_limit,
) -> str:
    char_limit = limit * llm_runtime_settings.prompt_token_char_multiplier
    if len(text) <= char_limit:
        return text
    suffix = "\n\n[TRUNCATED DUE TO TOKEN LIMIT]"
    budget = max(0, char_limit - len(suffix))
    sections = text.split("\n\n")
    kept: list[str] = []
    used = 0
    for section in sections:
        separator = 0 if not kept else 2
        section_len = len(section)
        if used + separator + section_len <= budget:
            kept.append(section)
            used += separator + section_len
            continue
        remaining = budget - used - separator
        if remaining > 0:
            trimmed = _trim_prompt_section(section, remaining)
            if trimmed:
                kept.append(trimmed)
        break
    if not kept:
        return suffix.strip()
    return "\n\n".join(kept) + suffix


def _trim_prompt_section(section: str, budget: int) -> str:
    if budget <= 0:
        return ""
    placeholder = "[TRUNCATED]"
    if len(section) <= budget:
        return section
    if "\n" not in section:
        return section[:budget]
    header, body = section.split("\n", 1)
    preserved_header = header[:budget]
    if len(preserved_header) >= budget:
        return preserved_header
    remainder_budget = budget - len(preserved_header) - 1
    if remainder_budget <= 0:
        return preserved_header
    trimmed_body = _trim_prompt_section_body(body, remainder_budget, placeholder)
    if not trimmed_body:
        return preserved_header
    return f"{preserved_header}\n{trimmed_body}"


def _trim_prompt_section_body(body: str, budget: int, placeholder: str) -> str:
    if budget <= 0:
        return ""
    stripped = body.strip()
    if len(stripped) <= budget:
        return stripped
    if stripped.startswith(("{", "[")):
        if len(stripped) <= _PROMPT_JSON_REPARSE_MAX_CHARS:
            try:
                parsed = parse_json(stripped)
            except json.JSONDecodeError:
                return _truncate_structured_text(stripped, budget, placeholder)
            else:
                return _truncate_json_literal(parsed, budget)
        return _truncate_structured_text(stripped, budget, placeholder)
    if budget <= len(placeholder):
        return placeholder[:budget]
    return stripped[: budget - len(placeholder)].rstrip() + placeholder


def _truncate_structured_text(text: str, budget: int, placeholder: str) -> str:
    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text
    if "\n" in text:
        framed = _truncate_structured_lines(text, budget, placeholder)
        if framed:
            return framed
    if budget <= len(placeholder):
        return placeholder[:budget]
    closing = ""
    if text.startswith("{") and budget > len(placeholder) + 1:
        closing = "}"
    elif text.startswith("[") and budget > len(placeholder) + 1:
        closing = "]"
    head_budget = budget - len(placeholder) - len(closing)
    if head_budget <= 0:
        return (placeholder + closing)[:budget]
    return text[:head_budget].rstrip() + placeholder + closing


def _truncate_structured_lines(text: str, budget: int, placeholder: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    closing = ""
    if text.startswith("{") and text.rstrip().endswith("}"):
        closing = "}"
    elif text.startswith("[") and text.rstrip().endswith("]"):
        closing = "]"
    suffix = f"\n{placeholder}{closing}" if closing else f"\n{placeholder}"
    if len(lines[0]) + len(suffix) > budget:
        return ""
    kept = [lines[0]]
    used = len(lines[0])
    for line in lines[1:]:
        next_used = used + 1 + len(line)
        if next_used + len(suffix) > budget:
            break
        kept.append(line)
        used = next_used
    if len(kept) == len(lines):
        return "\n".join(kept)
    return "\n".join(kept) + suffix


def _compact_json_value(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = llm_runtime_settings.prompt_compact_json_max_depth,
) -> Any:
    if value in (None, "", [], {}):
        return value
    if depth >= max_depth:
        return _compact_leaf_value(value)
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= llm_runtime_settings.prompt_compact_json_max_keys:
                break
            compact[str(key)] = _compact_json_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
            )
        return compact
    if isinstance(value, list):
        return [
            _compact_json_value(item, depth=depth + 1, max_depth=max_depth)
            for item in value[
                : llm_runtime_settings.prompt_compact_json_max_list_items
            ]
        ]
    return _compact_leaf_value(value)


def _compact_leaf_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) > llm_runtime_settings.prompt_compact_leaf_string_max_chars:
            return stripped[
                : llm_runtime_settings.prompt_compact_leaf_string_max_chars
            ]
        return stripped
    return value


def _stringify_prompt_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)
