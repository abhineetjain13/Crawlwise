from __future__ import annotations

from app.core.redis import redis_fail_open
from app.services.config.llm_runtime import llm_runtime_settings

_LLM_RUN_CALL_BUDGET_KEY_PREFIX = "crawl:llm:run_calls"


async def reserve_run_llm_call(run_id: int | None) -> bool:
    if run_id is None:
        return True
    max_calls = int(llm_runtime_settings.llm_max_calls_per_run)
    if max_calls < 1:
        return False

    async def _reserve(redis) -> bool:
        key = f"{_LLM_RUN_CALL_BUDGET_KEY_PREFIX}:{int(run_id)}"
        count = int(await redis.incr(key))
        if count == 1:
            await redis.expire(
                key,
                int(llm_runtime_settings.llm_call_budget_ttl_seconds),
            )
        return count <= max_calls

    return await redis_fail_open(
        _reserve,
        default=False,
        operation_name="llm_run_call_budget",
    )
