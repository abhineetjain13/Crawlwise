from __future__ import annotations

import json
import time
from string import Template
from typing import Any

from app.core.metrics import observe_llm_task_duration, record_llm_task_outcome
from app.services.config.llm_runtime import (
    PARSE_PROVIDER_JSON_ERROR,
    llm_runtime_settings,
)
from app.services.llm_budget import reserve_run_llm_call
from app.services.llm_cache import (
    build_llm_cache_key,
    load_cached_llm_result,
    store_cached_llm_result,
)
from app.services.llm_config_service import (
    get_prompt_task,
    load_prompt_file,
    resolve_provider_api_key,
    resolve_run_config,
)
from app.services.llm_cost_logging import record_llm_cost_log
from app.services.llm_errors import ERROR_PREFIX, LLMErrorCategory, classify_error
from app.services.llm_payloads import parse_payload, validate_task_payload
from app.services.llm_prompt_rendering import (
    enforce_token_limit,
    extract_structured_data,
    safe_truncate_for_prompt,
    stringify_prompt_value,
    truncate_html,
    truncate_json_literal,
)
from app.services.llm_provider_client import call_provider_with_retry
from app.services.llm_types import LLMTaskResult
from sqlalchemy.ext.asyncio import AsyncSession


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
        {key: stringify_prompt_value(value) for key, value in variables.items()}
    )
    safe_user_prompt = enforce_token_limit(rendered_user_prompt)
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

    if not await reserve_run_llm_call(run_id):
        return _finish(
            LLMTaskResult(
                payload=None,
                provider=provider,
                model=model,
                error_message=(
                    "Error: LLM call budget exceeded for crawl run "
                    f"{run_id}; max={llm_runtime_settings.llm_max_calls_per_run}"
                ),
                error_category=LLMErrorCategory.BUDGET_EXCEEDED,
            )
        )

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
        error_category = classify_error(raw)
        await _record_cost(
            session,
            run_id=run_id,
            task_type=task_type,
            domain=domain,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_message=raw,
            error_category=error_category,
        )
        return _finish(
            LLMTaskResult(
                payload=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider=provider,
                model=model,
                error_message=raw,
                error_category=error_category,
            )
        )

    payload: object = parse_payload(raw, response_type=response_type)
    if payload is None:
        error_message = PARSE_PROVIDER_JSON_ERROR
        await _record_cost(
            session,
            run_id=run_id,
            task_type=task_type,
            domain=domain,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_message=error_message,
            error_category=LLMErrorCategory.PARSE_FAILURE,
        )
        return _finish(
            LLMTaskResult(
                payload=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider=provider,
                model=model,
                error_message=error_message,
                error_category=LLMErrorCategory.PARSE_FAILURE,
            )
        )

    if isinstance(payload, dict) and task.get("data_key"):
        inner = payload.get(str(task["data_key"]))
        if isinstance(inner, (dict, list)):
            payload = inner
    payload, validation_error = validate_task_payload(task_type, payload)
    if validation_error is not None:
        error_message = f"Error: {validation_error}"
        await _record_cost(
            session,
            run_id=run_id,
            task_type=task_type,
            domain=domain,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_message=error_message,
            error_category=LLMErrorCategory.VALIDATION_FAILURE,
        )
        return _finish(
            LLMTaskResult(
                payload=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider=provider,
                model=model,
                error_message=error_message,
                error_category=LLMErrorCategory.VALIDATION_FAILURE,
            )
        )

    await _record_cost(
        session,
        run_id=run_id,
        task_type=task_type,
        domain=domain,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    normalized_payload = payload if isinstance(payload, (dict, list)) else None
    result = LLMTaskResult(
        payload=normalized_payload,
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
    structured_data = extract_structured_data(html_text)
    structured_data_json = truncate_json_literal(
        structured_data,
        llm_runtime_settings.existing_values_max_chars * 2,
    )
    result = await run_prompt_task(
        session,
        task_type="xpath_discovery",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "missing_fields_json": json.dumps(missing_fields),
            "existing_values_json": truncate_json_literal(
                existing_values,
                llm_runtime_settings.existing_values_max_chars,
            ),
            "structured_data_json": structured_data_json,
            "html_snippet": truncate_html(
                html_text,
                llm_runtime_settings.html_snippet_max_chars,
                anchors=missing_fields,
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, list) else []), (
        result.error_message or None
    )


async def extract_records_directly(
    session: AsyncSession,
    *,
    run_id: int,
    domain: str,
    url: str,
    surface: str,
    html_text: str,
    requested_fields: list[str] | None,
    existing_records: list[dict[str, object]] | None,
) -> tuple[list[dict[str, object]], str | None]:
    result = await run_prompt_task(
        session,
        task_type="direct_record_extraction",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "surface": surface,
            "requested_fields_json": json.dumps(list(requested_fields or [])),
            "existing_records_json": truncate_json_literal(
                safe_truncate_for_prompt(list(existing_records or [])),
                llm_runtime_settings.candidate_evidence_max_chars,
            ),
            "html_snippet": truncate_html(
                html_text,
                llm_runtime_settings.html_snippet_max_chars,
                anchors=list(requested_fields or []),
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, list) else []), (
        result.error_message or None
    )


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
            "existing_values_json": truncate_json_literal(
                existing_values,
                llm_runtime_settings.existing_values_max_chars,
            ),
            "html_snippet": truncate_html(
                html_text,
                llm_runtime_settings.html_snippet_max_chars,
                anchors=missing_fields,
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, dict) else {}), (
        result.error_message or None
    )


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
            "existing_values_json": truncate_json_literal(
                {field: existing_values.get(field) for field in target_fields},
                llm_runtime_settings.existing_values_max_chars,
            ),
            "candidate_evidence_json": truncate_json_literal(
                safe_truncate_for_prompt(candidate_evidence),
                llm_runtime_settings.candidate_evidence_max_chars,
            ),
            "discovered_sources_json": truncate_json_literal(
                discovered_sources,
                llm_runtime_settings.discovered_sources_max_chars,
            ),
            "html_snippet": truncate_html(
                html_text,
                llm_runtime_settings.html_snippet_max_chars,
                anchors=[
                    *target_fields,
                    *[str(existing_values.get(field) or "") for field in target_fields],
                ],
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, dict) else {}), (
        result.error_message or None
    )


async def _record_cost(
    session: AsyncSession,
    *,
    run_id: int | None,
    task_type: str,
    domain: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    error_message: str = "",
    error_category: LLMErrorCategory = LLMErrorCategory.NONE,
) -> None:
    await record_llm_cost_log(
        session,
        run_id=run_id,
        task_type=task_type,
        domain=domain,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error_message=error_message,
        error_category=error_category,
    )
