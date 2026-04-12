from __future__ import annotations

import json
import logging
import time
from hashlib import sha256
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from json import loads as parse_json
from pathlib import Path
from string import Template
from typing import Any

import httpx
from app.core.config import settings
from app.core.metrics import observe_llm_task_duration, record_llm_task_outcome
from app.core.redis import redis_fail_open, redis_is_enabled
from app.core.security import decrypt_secret
from app.models.crawl import CrawlRun
from app.models.llm import LLMConfig, LLMCostLog
from app.services.config.field_mappings import PROMPT_REGISTRY
from app.services.config.llm_runtime import (
    LLM_ANTHROPIC_MAX_TOKENS,
    LLM_ANTHROPIC_TEMPERATURE,
    LLM_CANDIDATE_EVIDENCE_MAX_CHARS,
    LLM_DISCOVERED_SOURCES_MAX_CHARS,
    LLM_EXISTING_VALUES_MAX_CHARS,
    LLM_GROQ_MAX_TOKENS,
    LLM_GROQ_TEMPERATURE,
    LLM_HTML_SNIPPET_MAX_CHARS,
    LLM_NVIDIA_MAX_TOKENS,
    LLM_NVIDIA_TEMPERATURE,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_ERROR_PREFIX = "Error:"
JSON_CONTENT_TYPE = "application/json"
SUPPORTED_LLM_PROVIDERS = {"groq", "anthropic", "nvidia"}
logger = logging.getLogger(__name__)
_PAGE_CLASSIFICATION_TYPES = {"listing", "detail", "challenge", "error", "unknown"}
_LLM_CACHE_KEY_PREFIX = "crawl:llm:result"
_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "data" / "knowledge_base" / "prompts"


def get_prompt_task(task_type: str) -> dict | None:
    task = PROMPT_REGISTRY.get(str(task_type or "").strip())
    return dict(task) if isinstance(task, dict) else None


def load_prompt_file(relative_path: str) -> str:
    relative_path = str(relative_path or "").strip()
    candidate = _PROMPTS_DIR / relative_path
    if not relative_path:
        return ""
    prompts_dir_resolved = _PROMPTS_DIR.resolve(strict=False)
    candidate_resolved = candidate.resolve(strict=False)
    try:
        candidate_resolved.relative_to(prompts_dir_resolved)
    except ValueError:
        return ""
    if not candidate.is_file():
        return ""
    return candidate.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Typed LLM error categories
# ---------------------------------------------------------------------------

class LLMErrorCategory(StrEnum):
    NONE = "none"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    AUTH_FAILURE = "auth_failure"
    PROVIDER_ERROR = "provider_error"
    PARSE_FAILURE = "parse_failure"
    VALIDATION_FAILURE = "validation_failure"
    CIRCUIT_OPEN = "circuit_open"
    MISSING_CONFIG = "missing_config"


def _classify_error(raw: str) -> LLMErrorCategory:
    """Classify an error string into a typed category."""
    lowered = raw.lower()
    if "circuit_open" in lowered or "circuit breaker" in lowered:
        return LLMErrorCategory.CIRCUIT_OPEN
    if "429" in raw or "rate" in lowered:
        return LLMErrorCategory.RATE_LIMITED
    if "timeout" in lowered or "timed out" in lowered:
        return LLMErrorCategory.TIMEOUT
    if "401" in raw or "403" in raw or "unauthorized" in lowered or "forbidden" in lowered:
        return LLMErrorCategory.AUTH_FAILURE
    if raw.startswith(_ERROR_PREFIX):
        return LLMErrorCategory.PROVIDER_ERROR
    return LLMErrorCategory.NONE


# ---------------------------------------------------------------------------
# Per-provider circuit breaker
# ---------------------------------------------------------------------------

_CIRCUIT_FAILURE_THRESHOLD = 5
_CIRCUIT_COOLDOWN_SECONDS = 120


@dataclass
class _CircuitState:
    consecutive_failures: int = 0
    opened_at: float | None = None
    total_failures: int = 0
    total_successes: int = 0
    last_error_category: LLMErrorCategory = LLMErrorCategory.NONE


_provider_circuits: dict[str, _CircuitState] = {}


def _get_circuit(provider: str) -> _CircuitState:
    if provider not in _provider_circuits:
        _provider_circuits[provider] = _CircuitState()
    return _provider_circuits[provider]


def _circuit_is_open(provider: str) -> bool:
    circuit = _get_circuit(provider)
    if circuit.consecutive_failures < _CIRCUIT_FAILURE_THRESHOLD:
        return False
    if circuit.opened_at is None:
        return False
    elapsed = time.monotonic() - circuit.opened_at
    if elapsed >= _CIRCUIT_COOLDOWN_SECONDS:
        logger.info("Circuit half-open for provider=%s — allowing probe request", provider)
        return False
    return True


def _record_success(provider: str) -> None:
    circuit = _get_circuit(provider)
    circuit.consecutive_failures = 0
    circuit.opened_at = None
    circuit.total_successes += 1


def _record_failure(provider: str, category: LLMErrorCategory) -> None:
    circuit = _get_circuit(provider)
    circuit.consecutive_failures += 1
    circuit.total_failures += 1
    circuit.last_error_category = category
    if (
        circuit.consecutive_failures >= _CIRCUIT_FAILURE_THRESHOLD
        and circuit.opened_at is None
    ):
        circuit.opened_at = time.monotonic()
        logger.warning(
            "Circuit OPEN for provider=%s after %d consecutive failures (last=%s)",
            provider, circuit.consecutive_failures, category,
        )


def circuit_breaker_snapshot() -> dict[str, dict]:
    """Return a snapshot of all circuit breaker states for observability."""
    return {
        provider: {
            "consecutive_failures": s.consecutive_failures,
            "total_failures": s.total_failures,
            "total_successes": s.total_successes,
            "is_open": _circuit_is_open(provider),
            "last_error_category": s.last_error_category,
        }
        for provider, s in _provider_circuits.items()
    }


@dataclass
class LLMTaskResult:
    payload: dict | list | None
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str = ""
    model: str = ""
    error_message: str = ""
    error_category: LLMErrorCategory = LLMErrorCategory.NONE


async def resolve_active_config(session: AsyncSession, task_type: str) -> LLMConfig | None:
    for candidate in [task_type, "general"]:
        result = await session.execute(
            select(LLMConfig)
            .where(LLMConfig.is_active.is_(True), LLMConfig.task_type == candidate)
            .order_by(LLMConfig.created_at.desc())
            .limit(1)
        )
        config = result.scalar_one_or_none()
        if config is not None and str(config.provider or "").strip().lower() in SUPPORTED_LLM_PROVIDERS:
            return config
    return None


async def snapshot_active_configs(
    session: AsyncSession,
    task_types: list[str] | None = None,
) -> dict[str, dict]:
    snapshot: dict[str, dict] = {}
    for task_type in task_types or ["general", "xpath_discovery", "missing_field_extraction", "field_cleanup_review", "page_classification", "schema_inference"]:
        config = await resolve_active_config(session, task_type)
        if config is not None:
            snapshot[task_type] = _serialize_config_snapshot(config)
    return snapshot


async def resolve_run_config(
    session: AsyncSession,
    *,
    run_id: int | None,
    task_type: str,
) -> dict | None:
    if run_id is not None:
        run = await session.get(CrawlRun, run_id)
        if run is not None:
            snapshot = run.settings_view.llm_config_snapshot()
            for candidate in [task_type, "general"]:
                config_snapshot = snapshot.get(candidate)
                if isinstance(config_snapshot, dict):
                    return config_snapshot
    config = await resolve_active_config(session, task_type)
    if config is None:
        return None
    return _serialize_config_snapshot(config)


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
        return _finish(LLMTaskResult(payload=None, error_message=f"No LLM config available for task {task_type}", error_category=LLMErrorCategory.MISSING_CONFIG))
    if task is None:
        return _finish(LLMTaskResult(payload=None, error_message=f"No prompt registered for task {task_type}", error_category=LLMErrorCategory.MISSING_CONFIG))

    system_prompt = load_prompt_file(str(task.get("system_file") or ""))
    user_template = load_prompt_file(str(task.get("user_file") or ""))
    if not system_prompt.strip() or not user_template.strip():
        return _finish(LLMTaskResult(payload=None, error_message=f"Prompt files missing for task {task_type}", error_category=LLMErrorCategory.MISSING_CONFIG))

    rendered_user_prompt = Template(user_template).safe_substitute({
        key: _stringify_prompt_value(value) for key, value in variables.items()
    })
    # Guard: prevent 413 Payload Too Large by truncating user prompt if it exceeds safety limits.
    # We use a conservative character-to-token ratio (4 chars = 1 token).
    # Groq's 8b/70b models often have a 6k-8k limit on some tiers.
    safe_user_prompt = _enforce_token_limit(rendered_user_prompt, limit=5600)
    provider = str(config.get("provider") or "")
    model = str(config.get("model") or "")
    response_type = str(task.get("response_type") or "object")
    cache_key = _build_llm_cache_key(
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
    cached_result = await _load_cached_llm_result(cache_key)
    if cached_result is not None:
        return _finish(cached_result)
    
    raw, input_tokens, output_tokens = await _call_provider_with_retry(
        provider=provider,
        model=model,
        api_key=_resolve_provider_api_key(
            provider=provider,
            encrypted_value=str(config.get("api_key_encrypted") or ""),
        ),
        system_prompt=system_prompt,
        user_prompt=safe_user_prompt,
    )
    if raw.startswith(_ERROR_PREFIX):
        return _finish(LLMTaskResult(
            payload=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider=provider,
            model=model,
            error_message=raw,
            error_category=_classify_error(raw),
        ))

    payload = _parse_payload(raw, response_type=response_type)
    if payload is None:
        return _finish(LLMTaskResult(
            payload=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider=provider,
            model=model,
            error_message="Error: Provider response could not be parsed as structured JSON.",
            error_category=LLMErrorCategory.PARSE_FAILURE,
        ))
    if isinstance(payload, dict) and task.get("data_key"):
        inner = payload.get(str(task["data_key"]))
        if isinstance(inner, (dict, list)):
            payload = inner
    validation_error = _validate_task_payload(task_type, payload)
    if validation_error:
        return _finish(LLMTaskResult(
            payload=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider=provider,
            model=model,
            error_message=f"Error: {validation_error}",
            error_category=LLMErrorCategory.VALIDATION_FAILURE,
        ))

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
            cost_usd=_estimate_cost_usd(
                provider,
                model,
                input_tokens,
                output_tokens,
            ),
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
    await _store_cached_llm_result(cache_key, result)
    return _finish(result)


def _build_llm_cache_key(
    *,
    task_type: str,
    domain: str,
    provider: str,
    model: str,
    response_type: str,
    data_key: str,
    system_prompt: str,
    user_prompt: str,
    variables: dict[str, Any],
) -> str:
    payload = {
        "task_type": str(task_type or "").strip(),
        "domain": str(domain or "").strip().lower(),
        "provider": str(provider or "").strip().lower(),
        "model": str(model or "").strip(),
        "response_type": str(response_type or "").strip(),
        "data_key": str(data_key or "").strip(),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "variables": _normalize_cache_value(variables),
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return f"{_LLM_CACHE_KEY_PREFIX}:{digest}"


def _normalize_cache_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_cache_value(value[key])
            for key in sorted(value)
        }
    if isinstance(value, list):
        return [_normalize_cache_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_cache_value(item) for item in value]
    if isinstance(value, set):
        normalized_items = [_normalize_cache_value(item) for item in value]
        try:
            return sorted(normalized_items)
        except TypeError:
            return sorted(normalized_items, key=str)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


async def _load_cached_llm_result(cache_key: str) -> LLMTaskResult | None:
    if not redis_is_enabled():
        return None

    async def _load(redis) -> LLMTaskResult | None:
        raw = await redis.get(cache_key)
        if not raw:
            return None
        return _deserialize_cached_llm_result(raw)

    return await redis_fail_open(
        _load,
        default=None,
        operation_name="llm_result_cache_get",
    )


def _deserialize_cached_llm_result(raw: str) -> LLMTaskResult | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return LLMTaskResult(
        payload=_coerce_cached_llm_payload(payload.get("payload")),
        input_tokens=_coerce_cached_llm_int(payload.get("input_tokens")),
        output_tokens=_coerce_cached_llm_int(payload.get("output_tokens")),
        provider=str(payload.get("provider") or ""),
        model=str(payload.get("model") or ""),
        error_message=str(payload.get("error_message") or ""),
        error_category=_coerce_cached_llm_error_category(payload.get("error_category")),
    )


def _coerce_cached_llm_payload(value: Any) -> dict | list | None:
    if isinstance(value, (dict, list)) or value is None:
        return value
    return None


def _coerce_cached_llm_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_cached_llm_error_category(value: Any) -> LLMErrorCategory:
    try:
        return LLMErrorCategory(str(value or LLMErrorCategory.NONE))
    except ValueError:
        return LLMErrorCategory.NONE


async def _store_cached_llm_result(cache_key: str, result: LLMTaskResult) -> None:
    if not redis_is_enabled():
        return
    ttl_seconds = max(1, int(settings.llm_cache_ttl_seconds or 0))

    async def _store(redis) -> bool:
        return await redis.set(
            cache_key,
            json.dumps(
                {
                    "payload": result.payload,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "provider": result.provider,
                    "model": result.model,
                    "error_message": result.error_message,
                    "error_category": str(result.error_category or LLMErrorCategory.NONE),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            ex=ttl_seconds,
        )

    await redis_fail_open(
        _store,
        default=False,
        operation_name="llm_result_cache_set",
    )


def _serialize_config_snapshot(config: LLMConfig) -> dict:
    return {
        "id": config.id,
        "provider": config.provider,
        "model": config.model,
        "api_key_encrypted": config.api_key_encrypted,
        "task_type": config.task_type,
    }


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
            "existing_values_json": _truncate_json_literal(existing_values, LLM_EXISTING_VALUES_MAX_CHARS),
            "html_snippet": _truncate_html(html_text, LLM_HTML_SNIPPET_MAX_CHARS, anchors=missing_fields),
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
            "existing_values_json": _truncate_json_literal(existing_values, LLM_EXISTING_VALUES_MAX_CHARS),
            "html_snippet": _truncate_html(html_text, LLM_HTML_SNIPPET_MAX_CHARS, anchors=missing_fields),
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
                LLM_EXISTING_VALUES_MAX_CHARS,
            ),
            "candidate_evidence_json": _truncate_json_literal(
                _safe_truncate_for_prompt(candidate_evidence),
                LLM_CANDIDATE_EVIDENCE_MAX_CHARS,
            ),
            "discovered_sources_json": _truncate_json_literal(discovered_sources, LLM_DISCOVERED_SOURCES_MAX_CHARS),
            "html_snippet": _truncate_html(
                html_text,
                LLM_HTML_SNIPPET_MAX_CHARS,
                anchors=[
                    *target_fields,
                    *[str(existing_values.get(field) or "") for field in target_fields],
                ],
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, dict) else {}), (result.error_message or None)


async def _call_provider(
    *,
    provider: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    normalized_provider = str(provider or "").strip().lower()
    if not api_key:
        return f"{_ERROR_PREFIX} Missing API key", 0, 0
    if normalized_provider not in SUPPORTED_LLM_PROVIDERS:
        return f"{_ERROR_PREFIX} Unsupported provider: {provider}", 0, 0

    dispatch = _provider_dispatch(normalized_provider)
    if dispatch is None:
        return f"{_ERROR_PREFIX} Unsupported provider: {normalized_provider}", 0, 0

    try:
        return await dispatch(api_key, model, system_prompt, user_prompt)
    except httpx.HTTPError as exc:
        return f"{_ERROR_PREFIX} {type(exc).__name__}: {exc}", 0, 0


async def _call_provider_with_retry(
    *,
    provider: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    max_retries: int = 1,
    base_delay_s: float = 0.0,
) -> tuple[str, int, int]:
    """Call provider with circuit breaker protection.

    - Rate limits (429) fail fast per architecture invariant 18.
    - Transient errors are retried up to ``max_retries``.
    - Circuit breaker trips after repeated consecutive failures and
      short-circuits calls for a cooldown period.
    """
    _ = base_delay_s
    normalized_provider = str(provider or "").strip().lower()

    if _circuit_is_open(normalized_provider):
        msg = f"{_ERROR_PREFIX} Circuit breaker open for provider {provider} (circuit_open)"
        logger.warning(msg)
        return msg, 0, 0

    last_error = ""
    for attempt in range(max(1, max_retries)):
        result, input_tokens, output_tokens = await _call_provider(
            provider=provider,
            model=model,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        if not result.startswith(_ERROR_PREFIX):
            _record_success(normalized_provider)
            return result, input_tokens, output_tokens

        category = _classify_error(result)
        _record_failure(normalized_provider, category)

        if category == LLMErrorCategory.RATE_LIMITED:
            logger.warning(
                "LLM rate limited for provider=%s model=%s; failing fast",
                provider, model,
            )
            return result, input_tokens, output_tokens

        if category == LLMErrorCategory.AUTH_FAILURE:
            return result, input_tokens, output_tokens

        last_error = result

    return last_error or f"{_ERROR_PREFIX} Provider call failed", 0, 0


def _provider_dispatch(provider: str):
    """Return the async call function for the given provider, or None."""
    return {
        "groq": _call_groq,
        "anthropic": _call_anthropic,
        "nvidia": _call_nvidia,
    }.get(provider)




async def _call_groq(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": JSON_CONTENT_TYPE,
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": LLM_GROQ_MAX_TOKENS,
                "temperature": LLM_GROQ_TEMPERATURE,
            },
        )
    if response.status_code != 200:
        return f"{_ERROR_PREFIX} HTTP {response.status_code}: {response.text[:300]}", 0, 0
    data = response.json()
    return _extract_chat_completion_payload(data)


async def _call_anthropic(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": JSON_CONTENT_TYPE,
            },
            json={
                "model": model,
                "max_tokens": LLM_ANTHROPIC_MAX_TOKENS,
                "temperature": LLM_ANTHROPIC_TEMPERATURE,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
    if response.status_code != 200:
        return f"{_ERROR_PREFIX} HTTP {response.status_code}: {response.text[:300]}", 0, 0
    data = response.json()
    content = data.get("content")
    if not isinstance(content, list):
        return f"{_ERROR_PREFIX} Unexpected anthropic response", 0, 0
    text = "\n".join(
        str(part.get("text") or "").strip()
        for part in content
        if isinstance(part, dict)
    ).strip()
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return text, int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)


async def _call_nvidia(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": JSON_CONTENT_TYPE,
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": LLM_NVIDIA_MAX_TOKENS,
                "temperature": LLM_NVIDIA_TEMPERATURE,
            },
        )
    if response.status_code != 200:
        return f"{_ERROR_PREFIX} HTTP {response.status_code}: {response.text[:300]}", 0, 0
    data = response.json()
    return _extract_chat_completion_payload(data)


def _extract_chat_completion_payload(data: dict[str, Any]) -> tuple[str, int, int]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return f"{_ERROR_PREFIX} Unexpected chat completion response", 0, 0
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    text = str(message.get("content") or "").strip()
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return text, int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)


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
    if set(payload) - allowed_keys:
        unexpected = sorted(set(payload) - allowed_keys)[0]
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
                return f"field_cleanup_review canonical['{normalized_field}'] must be an object"
            if row.get("suggested_value") in (None, "", [], {}):
                return f"field_cleanup_review canonical['{normalized_field}'].suggested_value is required"
            source = str(row.get("source") or "").strip()
            if not source:
                return f"field_cleanup_review canonical['{normalized_field}'].source is required"
            supporting_sources = row.get("supporting_sources")
            if supporting_sources is not None:
                if not isinstance(supporting_sources, list):
                    return f"field_cleanup_review canonical['{normalized_field}'].supporting_sources must be a list"
                if any(not str(item or "").strip() for item in supporting_sources):
                    return f"field_cleanup_review canonical['{normalized_field}'].supporting_sources contains an invalid source"
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
                return f"field_cleanup_review review_bucket[{index}].source is required"
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
    page_type = str(payload.get("page_type") or "").strip()
    if page_type not in _PAGE_CLASSIFICATION_TYPES:
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
    return bool(value) and len(value) <= 40 and value.replace("_", "").isalnum() and value.lower() == value and not value.startswith("_") and not value.isdigit()


def _parse_json_object(raw_text: str) -> dict | None:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        payload = parse_json(raw_text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_json_array(raw_text: str) -> list | None:
    start = raw_text.find("[")
    end = raw_text.rfind("]")
    if start == -1 or end < start:
        return None
    try:
        payload = parse_json(raw_text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, list) else None


def _truncate_html(html_text: str, limit: int, *, anchors: list[str] | None = None) -> str:
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
    snippet_budget = max(100, limit)
    window = max(180, min(800, snippet_budget // 3))
    chunks: list[str] = []
    seen_ranges: list[tuple[int, int]] = []
    for anchor in normalized_anchors:
        start_index = lowered_html.find(anchor)
        if start_index == -1:
            continue
        start = max(0, start_index - window)
        end = min(len(html_text), start_index + len(anchor) + window)
        if any(not (end <= prev_start or start >= prev_end) for prev_start, prev_end in seen_ranges):
            continue
        seen_ranges.append((start, end))
        chunks.append(html_text[start:end].strip())
        rendered = "\n...\n".join(chunks)
        if len(rendered) >= snippet_budget:
            return rendered[:snippet_budget]
        if len(chunks) >= 6:
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
            if len(cleaned) < 3 or cleaned in seen:
                continue
            seen.add(cleaned)
            terms.append(cleaned)
    return sorted(terms, key=len, reverse=True)


def _safe_truncate_for_prompt(
    value: object,
    max_str_len: int = 400,
    max_list_items: int = 5,
) -> object:
    """Recursively truncate prompt data while preserving JSON structure."""
    if isinstance(value, str):
        return value[:max_str_len] + "..." if len(value) > max_str_len else value
    if isinstance(value, list):
        truncated = [
            _safe_truncate_for_prompt(item, max_str_len=max_str_len, max_list_items=max_list_items)
            for item in value[:max_list_items]
        ]
        if len(value) > max_list_items:
            truncated.append(f"... ({len(value) - max_list_items} more items)")
        return truncated
    if isinstance(value, dict):
        return {
            str(key): _safe_truncate_for_prompt(item, max_str_len=max_str_len, max_list_items=max_list_items)
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
            candidate_rendered = json.dumps(candidate, default=str)
            if len(candidate_rendered) > limit:
                break
            trimmed[key] = item
        return json.dumps(trimmed, default=str)
    if isinstance(compact, list):
        trimmed_list: list[Any] = []
        for item in compact:
            candidate = [*trimmed_list, item]
            candidate_rendered = json.dumps(candidate, default=str)
            if len(candidate_rendered) > limit:
                break
            trimmed_list.append(item)
        return json.dumps(trimmed_list, default=str)
    return json.dumps(str(compact)[: max(0, limit - 2)], default=str)


def _enforce_token_limit(text: str, limit: int = 5600) -> str:
    """Shrink oversize prompts without slicing JSON blocks mid-token."""
    char_limit = limit * 3
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
        try:
            parsed = parse_json(stripped)
        except json.JSONDecodeError:
            pass
        else:
            return _truncate_json_literal(parsed, budget)
    if budget <= len(placeholder):
        return placeholder[:budget]
    return stripped[: budget - len(placeholder)].rstrip() + placeholder


def _compact_json_value(value: Any, *, depth: int = 0, max_depth: int = 3) -> Any:
    if value in (None, "", [], {}):
        return value
    if depth >= max_depth:
        return _compact_leaf_value(value)
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 12:
                break
            compact[str(key)] = _compact_json_value(item, depth=depth + 1, max_depth=max_depth)
        return compact
    if isinstance(value, list):
        return [_compact_json_value(item, depth=depth + 1, max_depth=max_depth) for item in value[:10]]
    return _compact_leaf_value(value)


def _compact_leaf_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped[:220] if len(stripped) > 220 else stripped
    return value


def _stringify_prompt_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


def _estimate_cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> Decimal:
    # Pricing metadata is not modeled yet; preserve usage truthfully and keep
    # cost as 0 until explicit rate tables are added.
    _ = (provider, model, input_tokens, output_tokens)
    return Decimal("0.0000")


def _resolve_provider_api_key(*, provider: str, encrypted_value: str) -> str:
    decrypted = decrypt_secret(encrypted_value) if encrypted_value else ""
    if decrypted:
        return decrypted
    return _provider_env_key(provider)


def _provider_env_key(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "groq":
        return settings.groq_api_key
    if normalized == "anthropic":
        return settings.anthropic_api_key
    if normalized == "nvidia":
        return settings.nvidia_api_key
    return ""


def llm_provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "provider": "groq",
            "label": "Groq",
            "api_key_set": bool(settings.groq_api_key),
            "recommended_models": [
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
            ],
        },
        {
            "provider": "nvidia",
            "label": "NVIDIA",
            "api_key_set": bool(settings.nvidia_api_key),
            "recommended_models": [
                "meta/llama-3.1-70b-instruct",
                "meta/llama-3.1-8b-instruct",
            ],
        },
        {
            "provider": "anthropic",
            "label": "Anthropic",
            "api_key_set": bool(settings.anthropic_api_key),
            "recommended_models": [
                "claude-3-5-haiku-latest",
                "claude-sonnet-4-20250514",
            ],
        },
    ]


async def test_provider_connection(
    *,
    provider: str,
    model: str,
    api_key: str | None = None,
) -> tuple[bool, str]:
    resolved_key = str(api_key or "").strip() or _provider_env_key(provider)
    raw, _input_tokens, _output_tokens = await _call_provider_with_retry(
        provider=provider,
        model=model,
        api_key=resolved_key,
        system_prompt="Reply with valid JSON only.",
        user_prompt='{"ok":true}',
    )
    if raw.startswith(_ERROR_PREFIX):
        return False, raw.removeprefix(f"{_ERROR_PREFIX} ").strip()
    return True, "Connection succeeded."
