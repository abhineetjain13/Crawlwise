from __future__ import annotations

import json
import time
from json import loads as parse_json
from string import Template
from typing import Any

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
from sqlalchemy.ext.asyncio import AsyncSession

_PAGE_CLASSIFICATION_TYPES = {"listing", "detail", "challenge", "error", "unknown"}
_PROMPT_JSON_REPARSE_MAX_CHARS = 16_384


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
    validation_error = _validate_task_payload(task_type, payload)
    if validation_error:
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


def _validate_task_payload(task_type: str, payload: object) -> str | None:
    validators = {
        "xpath_discovery": _validate_xpath_discovery_payload,
        "missing_field_extraction": _validate_missing_field_extraction_payload,
        "field_cleanup_review": _validate_field_cleanup_review_payload,
        "page_classification": _validate_page_classification_payload,
        "schema_inference": _validate_schema_inference_payload,
    }
    validator = validators.get(str(task_type or "").strip())
    if validator is None:
        return None
    return validator(payload)


def _validate_xpath_discovery_payload(payload: object) -> str | None:
    if not isinstance(payload, list):
        return "xpath_discovery payload must be a list of selector objects"
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            return f"xpath_discovery selectors[{index}] must be an object"
        field_name = str(row.get("field_name") or "").strip()
        xpath = str(row.get("xpath") or "").strip()
        if not field_name:
            return f"xpath_discovery selectors[{index}].field_name is required"
        if not xpath:
            return f"xpath_discovery selectors[{index}].xpath is required"
    return None


def _validate_missing_field_extraction_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return "missing_field_extraction payload must be an object"
    for key in payload:
        normalized_key = str(key or "").strip()
        if not normalized_key or normalized_key.startswith("_"):
            return "missing_field_extraction payload contains an invalid field key"
    return None


def _validate_field_cleanup_review_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return "field_cleanup_review payload must be an object"
    allowed_keys = {"canonical", "review_bucket"}
    unexpected_keys = set(payload) - allowed_keys
    if unexpected_keys:
        unexpected = sorted(unexpected_keys)[0]
        return f"field_cleanup_review payload has unexpected key '{unexpected}'"
    canonical = payload.get("canonical", {})
    if canonical not in ({}, None) and not isinstance(canonical, dict):
        return "field_cleanup_review canonical must be an object"
    if isinstance(canonical, dict):
        for field_name, row in canonical.items():
            normalized_field = str(field_name or "").strip()
            if not normalized_field or normalized_field.startswith("_"):
                return "field_cleanup_review canonical contains an invalid field key"
            if not isinstance(row, dict):
                return (
                    f"field_cleanup_review canonical['{normalized_field}'] "
                    "must be an object"
                )
            if row.get("suggested_value") in (None, "", [], {}):
                return (
                    f"field_cleanup_review canonical['{normalized_field}']."
                    "suggested_value is required"
                )
            source = str(row.get("source") or "").strip()
            if not source:
                return (
                    f"field_cleanup_review canonical['{normalized_field}']."
                    "source is required"
                )
            supporting_sources = row.get("supporting_sources")
            if supporting_sources is None:
                continue
            if not isinstance(supporting_sources, list):
                return (
                    f"field_cleanup_review canonical['{normalized_field}']."
                    "supporting_sources must be a list"
                )
            if any(not str(item or "").strip() for item in supporting_sources):
                return (
                    f"field_cleanup_review canonical['{normalized_field}']."
                    "supporting_sources contains an invalid source"
                )
    review_bucket = payload.get("review_bucket", [])
    if review_bucket not in (None, []) and not isinstance(review_bucket, list):
        return "field_cleanup_review review_bucket must be a list"
    if isinstance(review_bucket, list):
        for index, row in enumerate(review_bucket):
            if not isinstance(row, dict):
                return f"field_cleanup_review review_bucket[{index}] must be an object"
            key = str(row.get("key") or "").strip()
            source = str(row.get("source") or "").strip()
            if not key:
                return f"field_cleanup_review review_bucket[{index}].key is required"
            if row.get("value") in (None, "", [], {}):
                return f"field_cleanup_review review_bucket[{index}].value is required"
            if not source:
                return (
                    f"field_cleanup_review review_bucket[{index}].source is required"
                )
    return None


def _validate_page_classification_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return "page_classification payload must be an object"
    required_keys = {
        "page_type",
        "has_secondary_listing",
        "wait_selector_hint",
        "reasoning",
    }
    missing_keys = sorted(required_keys - set(payload))
    if missing_keys:
        return f"page_classification payload missing key '{missing_keys[0]}'"
    if str(payload.get("page_type") or "").strip() not in _PAGE_CLASSIFICATION_TYPES:
        return "page_classification page_type is invalid"
    if not isinstance(payload.get("has_secondary_listing"), bool):
        return "page_classification has_secondary_listing must be a boolean"
    if not isinstance(payload.get("wait_selector_hint"), str):
        return "page_classification wait_selector_hint must be a string"
    if not isinstance(payload.get("reasoning"), str):
        return "page_classification reasoning must be a string"
    return None


def _validate_schema_inference_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return "schema_inference payload must be an object"
    required_keys = {"confirmed_fields", "new_fields", "absent_fields"}
    missing_keys = sorted(required_keys - set(payload))
    if missing_keys:
        return f"schema_inference payload missing key '{missing_keys[0]}'"
    for key in sorted(required_keys):
        value = payload.get(key)
        if not isinstance(value, list):
            return f"schema_inference {key} must be a list"
        for field_name in value:
            normalized = str(field_name or "").strip()
            if not normalized or not _is_valid_schema_field_name(normalized):
                return f"schema_inference {key} contains an invalid field name"
    return None


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
    text = html_text.strip()
    if len(text) <= limit:
        return text
    targeted = _build_targeted_html_snippet(text, anchors or [], limit)
    return targeted[:limit] if targeted else text[:limit]


def _build_targeted_html_snippet(html_text: str, anchors: list[str], limit: int) -> str:
    if limit <= 0:
        return ""
    normalized_anchors = _normalize_html_anchor_terms(anchors)
    if not normalized_anchors:
        return ""
    lowered_html = html_text.lower()
    snippet_budget = max(llm_runtime_settings.html_snippet_min_budget, limit)
    window = max(
        llm_runtime_settings.html_snippet_window_min_chars,
        min(
            llm_runtime_settings.html_snippet_window_max_chars,
            snippet_budget // llm_runtime_settings.prompt_token_char_multiplier,
        ),
    )
    chunks: list[str] = []
    seen_ranges: list[tuple[int, int]] = []
    for anchor in normalized_anchors:
        start_index = lowered_html.find(anchor)
        if start_index == -1:
            continue
        start = max(0, start_index - window)
        end = min(len(html_text), start_index + len(anchor) + window)
        if any(
            not (end <= prev_start or start >= prev_end)
            for prev_start, prev_end in seen_ranges
        ):
            continue
        seen_ranges.append((start, end))
        chunks.append(html_text[start:end].strip())
        rendered = "\n...\n".join(chunks)
        if len(rendered) >= snippet_budget:
            return rendered[:snippet_budget]
        if len(chunks) >= llm_runtime_settings.html_snippet_max_chunks:
            break
    return "\n...\n".join(chunks)[:snippet_budget]


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
                pass
            else:
                return _truncate_json_literal(parsed, budget)
        return _truncate_json_text_literal(stripped, budget, placeholder)
    if budget <= len(placeholder):
        return placeholder[:budget]
    return stripped[: budget - len(placeholder)].rstrip() + placeholder


def _truncate_json_text_literal(text: str, budget: int, placeholder: str) -> str:
    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text
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
