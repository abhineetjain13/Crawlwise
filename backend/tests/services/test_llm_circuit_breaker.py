from __future__ import annotations

import pytest

from app.services import llm_circuit_breaker


def test_record_local_failure_uses_default_threshold_when_setting_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_circuit_breaker._provider_circuits.clear()
    monkeypatch.setattr(
        llm_circuit_breaker.llm_runtime_settings,
        "circuit_failure_threshold",
        None,
    )

    default_threshold = type(
        llm_circuit_breaker.llm_runtime_settings
    ).model_fields["circuit_failure_threshold"].default

    for _ in range(default_threshold):
        llm_circuit_breaker._record_local_failure(
            "openai",
            llm_circuit_breaker.LLMErrorCategory.TIMEOUT,
        )

    circuit = llm_circuit_breaker._get_circuit("openai")
    assert circuit.opened_at is not None


@pytest.mark.asyncio
async def test_record_failure_normalizes_none_threshold_for_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_circuit_breaker._provider_circuits.clear()
    monkeypatch.setattr(
        llm_circuit_breaker.llm_runtime_settings,
        "circuit_failure_threshold",
        None,
    )
    monkeypatch.setattr(llm_circuit_breaker, "redis_is_enabled", lambda: True)

    seen_args: list[object] = []

    class _FakeRedis:
        async def eval(self, *args) -> None:
            seen_args.extend(args)

    async def _fake_redis_fail_open(operation, *, default, operation_name):
        del default, operation_name
        return await operation(_FakeRedis())

    monkeypatch.setattr(
        llm_circuit_breaker,
        "redis_fail_open",
        _fake_redis_fail_open,
    )

    await llm_circuit_breaker.record_failure(
        "openai",
        llm_circuit_breaker.LLMErrorCategory.TIMEOUT,
    )

    assert seen_args[6] == type(
        llm_circuit_breaker.llm_runtime_settings
    ).model_fields["circuit_failure_threshold"].default


def test_classify_error_uses_whole_status_code_matches() -> None:
    assert (
        llm_circuit_breaker.classify_error("Error: upstream returned 400 bad request")
        == llm_circuit_breaker.LLMErrorCategory.CLIENT_ERROR
    )
    assert (
        llm_circuit_breaker.classify_error("Error: provider code 14003")
        == llm_circuit_breaker.LLMErrorCategory.PROVIDER_ERROR
    )
