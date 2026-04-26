from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
from app.services.config.llm_runtime import SUPPORTED_LLM_PROVIDERS, llm_runtime_settings
from app.services.llm_circuit_breaker import (
    ERROR_PREFIX,
    LLMErrorCategory,
    circuit_is_open,
    classify_error,
    record_failure,
    record_success,
)
from app.services.llm_config_service import provider_env_key

JSON_CONTENT_TYPE = "application/json"


async def call_provider(
    *,
    provider: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    normalized_provider = str(provider or "").strip().lower()
    if not api_key:
        return f"{ERROR_PREFIX} Missing API key", 0, 0
    if normalized_provider not in SUPPORTED_LLM_PROVIDERS:
        return f"{ERROR_PREFIX} Unsupported provider: {provider}", 0, 0
    dispatch = _provider_dispatch(normalized_provider)
    if dispatch is None:
        return f"{ERROR_PREFIX} Unsupported provider: {normalized_provider}", 0, 0
    try:
        return await dispatch(api_key, model, system_prompt, user_prompt)
    except (httpx.HTTPError, ValueError) as exc:
        return f"{ERROR_PREFIX} {type(exc).__name__}: {exc}", 0, 0


async def call_provider_with_retry(
    *,
    provider: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    max_retries: int = llm_runtime_settings.provider_retry_max_retries,
    base_delay_s: float = llm_runtime_settings.provider_retry_base_delay_seconds,
) -> tuple[str, int, int]:
    del base_delay_s
    normalized_provider = str(provider or "").strip().lower()
    last_error = ""
    for _attempt in range(max(1, max_retries)):
        if await circuit_is_open(normalized_provider):
            message = (
                f"{ERROR_PREFIX} Circuit breaker open for provider "
                f"{provider} (circuit_open)"
            )
            return message, 0, 0
        result, input_tokens, output_tokens = await call_provider(
            provider=provider,
            model=model,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        if not result.startswith(ERROR_PREFIX):
            await record_success(normalized_provider)
            return result, input_tokens, output_tokens
        category = classify_error(result)
        await record_failure(normalized_provider, category)
        if category in {
            LLMErrorCategory.RATE_LIMITED,
            LLMErrorCategory.AUTH_FAILURE,
            LLMErrorCategory.CLIENT_ERROR,
        }:
            return result, input_tokens, output_tokens
        last_error = result
    return last_error or f"{ERROR_PREFIX} Provider call failed", 0, 0


def estimate_cost_usd(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    del provider, model, input_tokens, output_tokens
    return Decimal("0.0000")


async def test_provider_connection(
    *,
    provider: str,
    model: str,
    api_key: str | None = None,
) -> tuple[bool, str]:
    resolved_key = str(api_key or "").strip() or provider_env_key(provider)
    raw, _input_tokens, _output_tokens = await call_provider_with_retry(
        provider=provider,
        model=model,
        api_key=resolved_key,
        system_prompt="Reply with valid JSON only.",
        user_prompt='{"ok":true}',
    )
    if raw.startswith(ERROR_PREFIX):
        return False, raw.removeprefix(f"{ERROR_PREFIX} ").strip()
    return True, "Connection succeeded."


def _provider_dispatch(provider: str):
    return _PROVIDER_DISPATCH.get(provider)


async def _call_groq(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    async with httpx.AsyncClient(
        timeout=llm_runtime_settings.provider_timeout_seconds
    ) as client:
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
                "max_tokens": llm_runtime_settings.groq_max_tokens,
                "temperature": llm_runtime_settings.groq_temperature,
            },
        )
    if response.status_code != 200:
        return _http_error(response), 0, 0
    return _extract_chat_completion_payload(_safe_json_response(response))


async def _call_anthropic(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    async with httpx.AsyncClient(
        timeout=llm_runtime_settings.provider_timeout_seconds
    ) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": JSON_CONTENT_TYPE,
            },
            json={
                "model": model,
                "max_tokens": llm_runtime_settings.anthropic_max_tokens,
                "temperature": llm_runtime_settings.anthropic_temperature,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
    if response.status_code != 200:
        return _http_error(response), 0, 0
    data = _safe_json_response(response)
    content = data.get("content")
    if not isinstance(content, list):
        return f"{ERROR_PREFIX} Unexpected anthropic response", 0, 0
    text = "\n".join(
        str(part.get("text") or "").strip()
        for part in content
        if isinstance(part, dict)
    ).strip()
    usage_payload = data.get("usage")
    usage: dict[str, Any] = usage_payload if isinstance(usage_payload, dict) else {}
    return (
        text,
        int(usage.get("input_tokens", 0) or 0),
        int(usage.get("output_tokens", 0) or 0),
    )


async def _call_nvidia(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, int, int]:
    async with httpx.AsyncClient(
        timeout=llm_runtime_settings.provider_timeout_seconds
    ) as client:
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
                "max_tokens": llm_runtime_settings.nvidia_max_tokens,
                "temperature": llm_runtime_settings.nvidia_temperature,
            },
        )
    if response.status_code != 200:
        return _http_error(response), 0, 0
    return _extract_chat_completion_payload(_safe_json_response(response))


_PROVIDER_DISPATCH = {
    "groq": _call_groq,
    "anthropic": _call_anthropic,
    "nvidia": _call_nvidia,
}

if frozenset(_PROVIDER_DISPATCH) != SUPPORTED_LLM_PROVIDERS:
    raise RuntimeError(
        "SUPPORTED_LLM_PROVIDERS does not match LLM provider dispatch keys"
    )


def _http_error(response: httpx.Response) -> str:
    return (
        f"{ERROR_PREFIX} HTTP {response.status_code}: "
        f"{response.text[:llm_runtime_settings.provider_error_excerpt_chars]}"
    )


def _safe_json_response(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError(
            f"Invalid JSON from LLM provider response: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("Invalid JSON from LLM provider response: expected object")
    return data


def _extract_chat_completion_payload(data: dict[str, Any]) -> tuple[str, int, int]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return f"{ERROR_PREFIX} Unexpected chat completion response", 0, 0
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message_payload = first_choice.get("message")
    message: dict[str, Any] = (
        message_payload if isinstance(message_payload, dict) else {}
    )
    text = str(message.get("content") or "").strip()
    usage_payload = data.get("usage")
    usage: dict[str, Any] = usage_payload if isinstance(usage_payload, dict) else {}
    return (
        text,
        int(usage.get("prompt_tokens", 0) or 0),
        int(usage.get("completion_tokens", 0) or 0),
    )
