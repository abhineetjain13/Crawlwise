from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from string import Template
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret
from app.models.llm import LLMConfig, LLMCostLog
from app.services.knowledge_base.store import get_prompt_task, load_prompt_file


_ERROR_PREFIX = "Error:"


@dataclass
class LLMTaskResult:
    payload: dict | list | None
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str = ""
    model: str = ""


async def resolve_active_config(session: AsyncSession, task_type: str) -> LLMConfig | None:
    for candidate in [task_type, "general"]:
        result = await session.execute(
            select(LLMConfig)
            .where(LLMConfig.is_active.is_(True), LLMConfig.task_type == candidate)
            .order_by(LLMConfig.created_at.desc())
            .limit(1)
        )
        config = result.scalar_one_or_none()
        if config is not None:
            return config
    return None


async def run_prompt_task(
    session: AsyncSession,
    *,
    task_type: str,
    run_id: int | None,
    domain: str,
    variables: dict[str, Any],
) -> LLMTaskResult:
    config = await resolve_active_config(session, task_type)
    task = get_prompt_task(task_type)
    if config is None or task is None:
        return LLMTaskResult(payload=None)

    system_prompt = load_prompt_file(str(task.get("system_file") or ""))
    user_template = load_prompt_file(str(task.get("user_file") or ""))
    if not system_prompt.strip() or not user_template.strip():
        return LLMTaskResult(payload=None)

    rendered_user_prompt = Template(user_template).safe_substitute({
        key: _stringify_prompt_value(value) for key, value in variables.items()
    })
    raw, input_tokens, output_tokens = await _call_provider(
        provider=config.provider,
        model=config.model,
        api_key=decrypt_secret(config.api_key_encrypted),
        system_prompt=system_prompt,
        user_prompt=rendered_user_prompt,
    )
    if raw.startswith(_ERROR_PREFIX):
        return LLMTaskResult(
            payload=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider=config.provider,
            model=config.model,
        )

    response_type = str(task.get("response_type") or "object")
    payload = _parse_payload(raw, response_type=response_type)
    if isinstance(payload, dict) and task.get("data_key"):
        inner = payload.get(str(task["data_key"]))
        if isinstance(inner, (dict, list)):
            payload = inner

    session.add(
        LLMCostLog(
            run_id=run_id,
            provider=config.provider,
            model=config.model,
            task_type=task_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_estimate_cost_usd(config.provider, config.model, input_tokens, output_tokens),
            domain=domain,
        )
    )
    await session.commit()
    return LLMTaskResult(
        payload=payload,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=config.provider,
        model=config.model,
    )


async def discover_xpath_candidates(
    session: AsyncSession,
    *,
    run_id: int,
    domain: str,
    url: str,
    html_text: str,
    missing_fields: list[str],
    existing_values: dict[str, object],
) -> list[dict]:
    result = await run_prompt_task(
        session,
        task_type="xpath_discovery",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "missing_fields_json": json.dumps(missing_fields),
            "existing_values_json": json.dumps(existing_values, default=str),
            "html_snippet": _truncate_html(html_text, 18000),
        },
    )
    payload = result.payload
    return payload if isinstance(payload, list) else []


async def extract_missing_fields(
    session: AsyncSession,
    *,
    run_id: int,
    domain: str,
    url: str,
    html_text: str,
    missing_fields: list[str],
    existing_values: dict[str, object],
) -> dict[str, object]:
    result = await run_prompt_task(
        session,
        task_type="missing_field_extraction",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "missing_fields_json": json.dumps(missing_fields),
            "existing_values_json": json.dumps(existing_values, default=str),
            "html_snippet": _truncate_html(html_text, 18000),
        },
    )
    payload = result.payload
    return payload if isinstance(payload, dict) else {}


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
    if normalized_provider == "openai":
        return await _call_openai(api_key, model, system_prompt, user_prompt)
    if normalized_provider == "groq":
        return await _call_groq(api_key, model, system_prompt, user_prompt)
    if normalized_provider == "anthropic":
        return await _call_anthropic(api_key, model, system_prompt, user_prompt)
    return f"{_ERROR_PREFIX} Unsupported provider: {provider}", 0, 0


async def _call_openai(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
                ],
                "max_output_tokens": 1200,
            },
        )
    if response.status_code != 200:
        return f"{_ERROR_PREFIX} HTTP {response.status_code}: {response.text[:300]}", 0, 0
    data = response.json()
    text = str(data.get("output_text") or "").strip()
    if not text:
        output = data.get("output")
        if isinstance(output, list):
            fragments: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        fragments.append(part["text"])
            text = "\n".join(fragments).strip()
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return text, int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)


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
                "Content-Type": "application/json",
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
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1200,
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


def _stringify_prompt_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


def _estimate_cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> Decimal:
    # Pricing metadata is not modeled yet; preserve usage truthfully and keep
    # cost as 0 until explicit rate tables are added.
    _ = (provider, model, input_tokens, output_tokens)
    return Decimal("0.0000")
