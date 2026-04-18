from __future__ import annotations

import pytest

from app.models.llm import LLMCostLog
from app.services import llm_runtime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_run_prompt_task_returns_validated_payload(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_run_config(session, *, run_id, task_type):
        del session, run_id, task_type
        return {"provider": "groq", "model": "llama", "api_key_encrypted": ""}

    def fake_get_prompt_task(task_type: str):
        assert task_type == "missing_field_extraction"
        return {
            "system_file": "system.txt",
            "user_file": "user.txt",
            "response_type": "object",
        }

    def fake_load_prompt_file(_path: str) -> str:
        return "Return JSON."

    async def fake_call_provider_with_retry(**_kwargs):
        return '{"materials":"Cotton blend"}', 12, 8

    async def fake_load_cached_llm_result(_cache_key: str):
        return None

    stored_keys: list[str] = []

    async def fake_store_cached_llm_result(cache_key: str, result) -> None:
        stored_keys.append(cache_key)
        assert result.payload == {"materials": "Cotton blend"}

    monkeypatch.setattr("app.services.llm_tasks.resolve_run_config", fake_resolve_run_config)
    monkeypatch.setattr("app.services.llm_tasks.get_prompt_task", fake_get_prompt_task)
    monkeypatch.setattr("app.services.llm_tasks.load_prompt_file", fake_load_prompt_file)
    monkeypatch.setattr(
        "app.services.llm_tasks.call_provider_with_retry",
        fake_call_provider_with_retry,
    )
    monkeypatch.setattr(
        "app.services.llm_tasks.load_cached_llm_result",
        fake_load_cached_llm_result,
    )
    monkeypatch.setattr(
        "app.services.llm_tasks.store_cached_llm_result",
        fake_store_cached_llm_result,
    )

    result = await llm_runtime.run_prompt_task(
        db_session,
        task_type="missing_field_extraction",
        run_id=None,
        domain="example.com",
        variables={"missing_fields_json": "[]"},
    )

    cost_logs = list(
        (
            await db_session.execute(select(LLMCostLog).order_by(LLMCostLog.id.asc()))
        ).scalars()
    )

    assert result.payload == {"materials": "Cotton blend"}
    assert result.error_message == ""
    assert len(cost_logs) == 1
    assert cost_logs[0].task_type == "missing_field_extraction"
    assert stored_keys


@pytest.mark.asyncio
async def test_run_prompt_task_returns_typed_provider_failure(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_run_config(session, *, run_id, task_type):
        del session, run_id, task_type
        return {"provider": "groq", "model": "llama", "api_key_encrypted": ""}

    def fake_get_prompt_task(task_type: str):
        assert task_type == "missing_field_extraction"
        return {
            "system_file": "system.txt",
            "user_file": "user.txt",
            "response_type": "object",
        }

    def fake_load_prompt_file(_path: str) -> str:
        return "Return JSON."

    async def fake_call_provider_with_retry(**_kwargs):
        return "Error: HTTP 429: rate limited", 0, 0

    async def fake_load_cached_llm_result(_cache_key: str):
        return None

    async def fake_store_cached_llm_result(_cache_key: str, _result) -> None:
        raise AssertionError("provider failures must not be cached as success")

    monkeypatch.setattr("app.services.llm_tasks.resolve_run_config", fake_resolve_run_config)
    monkeypatch.setattr("app.services.llm_tasks.get_prompt_task", fake_get_prompt_task)
    monkeypatch.setattr("app.services.llm_tasks.load_prompt_file", fake_load_prompt_file)
    monkeypatch.setattr(
        "app.services.llm_tasks.call_provider_with_retry",
        fake_call_provider_with_retry,
    )
    monkeypatch.setattr(
        "app.services.llm_tasks.load_cached_llm_result",
        fake_load_cached_llm_result,
    )
    monkeypatch.setattr(
        "app.services.llm_tasks.store_cached_llm_result",
        fake_store_cached_llm_result,
    )

    result = await llm_runtime.run_prompt_task(
        db_session,
        task_type="missing_field_extraction",
        run_id=None,
        domain="example.com",
        variables={"missing_fields_json": "[]"},
    )

    cost_logs = list(
        (
            await db_session.execute(select(LLMCostLog).order_by(LLMCostLog.id.asc()))
        ).scalars()
    )

    assert result.payload is None
    assert result.error_category == llm_runtime.LLMErrorCategory.RATE_LIMITED
    assert "rate limited" in result.error_message.lower()
    assert cost_logs == []
