from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from typing import Any

from app.core.config import settings
from app.core.redis import redis_fail_open, redis_is_enabled
from app.services.llm_circuit_breaker import LLMErrorCategory
from app.services.llm_types import LLMTaskResult

_LLM_CACHE_KEY_PREFIX = "crawl:llm:result"


def build_llm_cache_key(
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
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"{_LLM_CACHE_KEY_PREFIX}:{digest}"


def _normalize_cache_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_cache_value(value[key]) for key in sorted(value)}
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


async def load_cached_llm_result(cache_key: str) -> LLMTaskResult | None:
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
        payload=_coerce_cached_payload(payload.get("payload")),
        input_tokens=_coerce_cached_int(payload.get("input_tokens")),
        output_tokens=_coerce_cached_int(payload.get("output_tokens")),
        provider=str(payload.get("provider") or ""),
        model=str(payload.get("model") or ""),
        error_message=str(payload.get("error_message") or ""),
        error_category=_coerce_cached_error_category(payload.get("error_category")),
    )


def _coerce_cached_payload(value: Any) -> dict | list | None:
    if isinstance(value, (dict, list)) or value is None:
        return value
    return None


def _coerce_cached_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_cached_error_category(value: Any) -> LLMErrorCategory:
    try:
        return LLMErrorCategory(str(value or LLMErrorCategory.NONE))
    except ValueError:
        return LLMErrorCategory.NONE


async def store_cached_llm_result(cache_key: str, result: LLMTaskResult) -> None:
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
                    "error_category": str(
                        result.error_category or LLMErrorCategory.NONE
                    ),
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
