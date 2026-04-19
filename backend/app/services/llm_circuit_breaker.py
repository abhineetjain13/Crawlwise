from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import StrEnum

from app.core.redis import redis_fail_open, redis_is_enabled
from app.services.config.llm_runtime import llm_runtime_settings

ERROR_PREFIX = "Error:"
logger = logging.getLogger(__name__)

_LLM_CIRCUIT_KEY_PREFIX = "crawl:llm:circuit"
DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 5
_RECORD_LLM_FAILURE_LUA = """
local stats_key = KEYS[1]
local open_key = KEYS[2]
local category = ARGV[1]
local stats_ttl = tonumber(ARGV[2])
local failure_threshold = tonumber(ARGV[3])
local cooldown_seconds = tonumber(ARGV[4])
local opened_at = ARGV[5]

local consecutive_failures = redis.call('HINCRBY', stats_key, 'consecutive_failures', 1)
redis.call('HINCRBY', stats_key, 'total_failures', 1)
redis.call('HSET', stats_key, 'last_error_category', category)
redis.call('EXPIRE', stats_key, stats_ttl)

local opened_now = 0
if consecutive_failures >= failure_threshold then
    local set_result = redis.call('SET', open_key, opened_at, 'NX', 'EX', cooldown_seconds)
    if set_result then
        redis.call('HSET', stats_key, 'opened_at_epoch', opened_at)
        opened_now = 1
    end
end

return {consecutive_failures, opened_now}
"""


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


def classify_error(raw: str) -> LLMErrorCategory:
    lowered = raw.lower()
    if "circuit_open" in lowered or "circuit breaker" in lowered:
        return LLMErrorCategory.CIRCUIT_OPEN
    if "429" in raw or "rate" in lowered:
        return LLMErrorCategory.RATE_LIMITED
    if "timeout" in lowered or "timed out" in lowered:
        return LLMErrorCategory.TIMEOUT
    if (
        "401" in raw
        or "403" in raw
        or "unauthorized" in lowered
        or "forbidden" in lowered
    ):
        return LLMErrorCategory.AUTH_FAILURE
    if raw.startswith(ERROR_PREFIX):
        return LLMErrorCategory.PROVIDER_ERROR
    return LLMErrorCategory.NONE


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


def _local_circuit_is_open(provider: str) -> bool:
    circuit = _get_circuit(provider)
    failure_threshold = _resolved_failure_threshold()
    if failure_threshold is None:
        return False
    if circuit.consecutive_failures < failure_threshold:
        return False
    if circuit.opened_at is None:
        return False
    elapsed = time.monotonic() - circuit.opened_at
    if elapsed >= llm_runtime_settings.circuit_cooldown_seconds:
        logger.info(
            "Circuit half-open for provider=%s; allowing probe request",
            provider,
        )
        return False
    return True


def _record_local_success(provider: str) -> None:
    circuit = _get_circuit(provider)
    circuit.consecutive_failures = 0
    circuit.opened_at = None
    circuit.last_error_category = LLMErrorCategory.NONE
    circuit.total_successes += 1


def _record_local_failure(provider: str, category: LLMErrorCategory) -> None:
    circuit = _get_circuit(provider)
    circuit.consecutive_failures += 1
    circuit.total_failures += 1
    circuit.last_error_category = category
    failure_threshold = _resolved_failure_threshold()
    if (
        failure_threshold is not None
        and circuit.consecutive_failures >= failure_threshold
        and circuit.opened_at is None
    ):
        circuit.opened_at = time.monotonic()
        logger.warning(
            "Circuit open for provider=%s after %d consecutive failures (last=%s)",
            provider,
            circuit.consecutive_failures,
            category,
        )


def _shared_circuit_stats_key(provider: str) -> str:
    return f"{_LLM_CIRCUIT_KEY_PREFIX}:{provider}:stats"


def _shared_circuit_open_key(provider: str) -> str:
    return f"{_LLM_CIRCUIT_KEY_PREFIX}:{provider}:open"


def _shared_circuit_stats_ttl_seconds() -> int:
    return max(300, int(llm_runtime_settings.circuit_cooldown_seconds or 0) * 10)


def _resolved_failure_threshold() -> int | None:
    raw_threshold = getattr(
        llm_runtime_settings,
        "circuit_failure_threshold",
        DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
    )
    if raw_threshold is None:
        raw_threshold = DEFAULT_CIRCUIT_FAILURE_THRESHOLD
    try:
        return max(1, int(raw_threshold))
    except (TypeError, ValueError):
        return None


async def circuit_is_open(provider: str) -> bool:
    local_default = _local_circuit_is_open(provider)
    if not redis_is_enabled():
        return local_default

    async def _check(redis) -> bool:
        return bool(await redis.exists(_shared_circuit_open_key(provider)))

    return await redis_fail_open(
        _check,
        default=local_default,
        operation_name=f"llm_circuit_check:{provider}",
    )


async def record_success(provider: str) -> None:
    _record_local_success(provider)
    if not redis_is_enabled():
        return

    async def _update(redis) -> None:
        stats_key = _shared_circuit_stats_key(provider)
        await redis.hincrby(stats_key, "total_successes", 1)
        await redis.hset(
            stats_key,
            mapping={
                "consecutive_failures": 0,
                "opened_at_epoch": "",
                "last_error_category": str(LLMErrorCategory.NONE),
            },
        )
        await redis.expire(stats_key, _shared_circuit_stats_ttl_seconds())
        await redis.delete(_shared_circuit_open_key(provider))

    await redis_fail_open(
        _update,
        default=None,
        operation_name=f"llm_circuit_success:{provider}",
    )


async def record_failure(provider: str, category: LLMErrorCategory) -> None:
    _record_local_failure(provider, category)
    if not redis_is_enabled():
        return

    async def _update(redis) -> None:
        stats_key = _shared_circuit_stats_key(provider)
        opened_at = f"{time.time():.6f}"
        await redis.eval(
            _RECORD_LLM_FAILURE_LUA,
            2,
            stats_key,
            _shared_circuit_open_key(provider),
            str(category),
            _shared_circuit_stats_ttl_seconds(),
            _resolved_failure_threshold() or 1,
            max(1, int(llm_runtime_settings.circuit_cooldown_seconds or 0)),
            opened_at,
        )

    await redis_fail_open(
        _update,
        default=None,
        operation_name=f"llm_circuit_failure:{provider}",
    )


def circuit_breaker_snapshot() -> dict[str, dict]:
    return {
        provider: {
            "consecutive_failures": state.consecutive_failures,
            "total_failures": state.total_failures,
            "total_successes": state.total_successes,
            "is_open": _local_circuit_is_open(provider),
            "last_error_category": state.last_error_category,
        }
        for provider, state in _provider_circuits.items()
    }
