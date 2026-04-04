from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from string import Template
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.crawl import CrawlRun
from app.core.security import decrypt_secret
from app.models.llm import LLMConfig, LLMCostLog
from app.services.knowledge_base.store import get_prompt_task, load_prompt_file


_ERROR_PREFIX = "Error:"
JSON_CONTENT_TYPE = "application/json"
SUPPORTED_LLM_PROVIDERS = {"groq", "anthropic", "nvidia"}


@dataclass
class LLMTaskResult:
    payload: dict | list | None
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str = ""
    model: str = ""
    error_message: str = ""


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
    for task_type in task_types or ["general", "xpath_discovery", "missing_field_extraction", "field_cleanup_review"]:
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
            snapshot = (run.settings or {}).get("llm_config_snapshot")
            if isinstance(snapshot, dict):
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
    config = await resolve_run_config(session, run_id=run_id, task_type=task_type)
    task = get_prompt_task(task_type)
    if config is None:
        return LLMTaskResult(payload=None, error_message=f"No LLM config available for task {task_type}")
    if task is None:
        return LLMTaskResult(payload=None, error_message=f"No prompt registered for task {task_type}")

    system_prompt = load_prompt_file(str(task.get("system_file") or ""))
    user_template = load_prompt_file(str(task.get("user_file") or ""))
    if not system_prompt.strip() or not user_template.strip():
        return LLMTaskResult(payload=None, error_message=f"Prompt files missing for task {task_type}")

    rendered_user_prompt = Template(user_template).safe_substitute({
        key: _stringify_prompt_value(value) for key, value in variables.items()
    })
    # Guard: prevent 413 Payload Too Large by truncating user prompt if it exceeds safety limits.
    # We use a conservative character-to-token ratio (4 chars = 1 token).
    # Groq's 8b/70b models often have a 6k-8k limit on some tiers.
    safe_user_prompt = _enforce_token_limit(rendered_user_prompt, limit=5600)
    
    raw, input_tokens, output_tokens = await _call_provider(
        provider=str(config.get("provider") or ""),
        model=str(config.get("model") or ""),
        api_key=_resolve_provider_api_key(
            provider=str(config.get("provider") or ""),
            encrypted_value=str(config.get("api_key_encrypted") or ""),
        ),
        system_prompt=system_prompt,
        user_prompt=safe_user_prompt,
    )
    if raw.startswith(_ERROR_PREFIX):
        return LLMTaskResult(
            payload=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider=str(config.get("provider") or ""),
            model=str(config.get("model") or ""),
            error_message=raw,
        )

    response_type = str(task.get("response_type") or "object")
    payload = _parse_payload(raw, response_type=response_type)
    if payload is None:
        return LLMTaskResult(
            payload=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider=str(config.get("provider") or ""),
            model=str(config.get("model") or ""),
            error_message="Error: Provider response could not be parsed as structured JSON.",
        )
    if isinstance(payload, dict) and task.get("data_key"):
        inner = payload.get(str(task["data_key"]))
        if isinstance(inner, (dict, list)):
            payload = inner

    session.add(
        LLMCostLog(
            run_id=run_id,
            provider=str(config.get("provider") or ""),
            model=str(config.get("model") or ""),
            task_type=task_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_estimate_cost_usd(
                str(config.get("provider") or ""),
                str(config.get("model") or ""),
                input_tokens,
                output_tokens,
            ),
            domain=domain,
        )
    )
    await session.flush()
    return LLMTaskResult(
        payload=payload,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=str(config.get("provider") or ""),
        model=str(config.get("model") or ""),
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
            "existing_values_json": _truncate_json_literal(existing_values, 2400),
            "html_snippet": _truncate_html(html_text, 12000),
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
            "existing_values_json": _truncate_json_literal(existing_values, 2400),
            "html_snippet": _truncate_html(html_text, 12000),
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
    target_fields: list[str],
    existing_values: dict[str, object],
    candidate_evidence: dict[str, list[dict]],
    discovered_sources: dict[str, object],
) -> tuple[dict[str, dict], str | None]:
    result = await run_prompt_task(
        session,
        task_type="field_cleanup_review",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "target_fields_json": json.dumps(target_fields),
            "existing_values_json": _truncate_json_literal({field: existing_values.get(field) for field in target_fields}, 2400),
            "candidate_evidence_json": _truncate_json_literal(candidate_evidence, 16000),
            "discovered_sources_json": _truncate_json_literal(discovered_sources, 48000),
            "html_snippet": _truncate_html(html_text, 12000),
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
    try:
        if normalized_provider == "groq":
            return await _call_groq(api_key, model, system_prompt, user_prompt)
        if normalized_provider == "anthropic":
            return await _call_anthropic(api_key, model, system_prompt, user_prompt)
        if normalized_provider == "nvidia":
            return await _call_nvidia(api_key, model, system_prompt, user_prompt)
    except httpx.HTTPError as exc:
        return f"{_ERROR_PREFIX} {type(exc).__name__}: {exc}", 0, 0
    return f"{_ERROR_PREFIX} Unsupported provider: {normalized_provider}", 0, 0




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
                "max_tokens": 1200,
                "temperature": 0.1,
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
                "max_tokens": 3000,
                "temperature": 0.1,
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
                "max_tokens": 1200,
                "temperature": 0.1,
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


def _parse_json_object(raw_text: str) -> dict | None:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        payload = json.loads(raw_text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_json_array(raw_text: str) -> list | None:
    start = raw_text.find("[")
    end = raw_text.rfind("]")
    if start == -1 or end < start:
        return None
    try:
        payload = json.loads(raw_text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, list) else None


def _truncate_html(html_text: str, limit: int) -> str:
    return html_text.strip()[:limit]


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
    """Aggressively truncate text if it exceeds a character-based token estimate."""
    # Rough estimate: 4 chars per token. 5600 tokens ~ 22400 chars.
    char_limit = limit * 4
    if len(text) <= char_limit:
        return text
    return text[:char_limit] + "\n... [TRUNCATED DUE TO TOKEN LIMIT]"


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
    raw, _input_tokens, _output_tokens = await _call_provider(
        provider=provider,
        model=model,
        api_key=resolved_key,
        system_prompt="Reply with valid JSON only.",
        user_prompt='{"ok":true}',
    )
    if raw.startswith(_ERROR_PREFIX):
        return False, raw.removeprefix(f"{_ERROR_PREFIX} ").strip()
    return True, "Connection succeeded."
