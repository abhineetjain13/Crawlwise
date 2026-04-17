from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import app.services.llm_runtime as llm_runtime_module
from app.core.metrics import render_prometheus_metrics
from app.core.security import encrypt_secret
from app.models.llm import LLMConfig, LLMCostLog
from app.services.llm_runtime import (
    LLMErrorCategory,
    _call_provider_with_retry,
    load_prompt_file,
    resolve_active_config,
    run_prompt_task,
    snapshot_active_configs,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class _FakeRedis:
    def __init__(self) -> None:
        self._strings: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self._strings else 0

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        _ = ex
        if nx and key in self._strings:
            return False
        self._strings[key] = value
        return True

    async def hincrby(self, key: str, field: str, amount: int) -> int:
        bucket = self._hashes.setdefault(key, {})
        next_value = int(bucket.get(field, "0")) + int(amount)
        bucket[field] = str(next_value)
        return next_value

    async def hset(self, key: str, mapping: dict[str, object]) -> int:
        bucket = self._hashes.setdefault(key, {})
        for field, value in mapping.items():
            bucket[str(field)] = str(value)
        return len(mapping)

    async def expire(self, key: str, seconds: int) -> bool:
        _ = (key, seconds)
        return True

    async def delete(self, key: str) -> int:
        existed = key in self._strings
        self._strings.pop(key, None)
        return 1 if existed else 0

    async def eval(self, script: str, numkeys: int, *args):
        _ = (script, numkeys)
        stats_key, open_key, category, ttl_seconds, threshold, cooldown_seconds, opened_at = args
        bucket = self._hashes.setdefault(str(stats_key), {})
        total_failures = int(bucket.get("total_failures", "0")) + 1
        consecutive_failures = int(bucket.get("consecutive_failures", "0")) + 1
        bucket["total_failures"] = str(total_failures)
        bucket["consecutive_failures"] = str(consecutive_failures)
        bucket["last_error_category"] = str(category)
        bucket["opened_at_epoch"] = str(opened_at)
        await self.expire(str(stats_key), int(ttl_seconds))
        if consecutive_failures >= int(threshold):
            await self.set(str(open_key), "1", nx=True, ex=int(cooldown_seconds))
        return [total_failures, consecutive_failures]


def _seed_xpath_discovery_config(db_session: AsyncSession) -> None:
    db_session.add(
        LLMConfig(
            provider="groq",
            model="llama-xpath",
            api_key_encrypted=encrypt_secret("xpath-key"),
            task_type="xpath_discovery",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        )
    )


async def _assert_single_cost_log(
    db_session: AsyncSession,
    *,
    task_type: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    rows = (await db_session.execute(select(LLMCostLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].task_type == task_type
    assert rows[0].input_tokens == input_tokens
    assert rows[0].output_tokens == output_tokens


@pytest.mark.asyncio
async def test_resolve_active_config_prefers_task_specific(db_session: AsyncSession):
    db_session.add_all([
        LLMConfig(
            provider="groq",
            model="llama-general",
            api_key_encrypted=encrypt_secret("general-key"),
            task_type="general",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        ),
        LLMConfig(
            provider="groq",
            model="llama-xpath",
            api_key_encrypted=encrypt_secret("xpath-key"),
            task_type="xpath_discovery",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        ),
    ])
    await db_session.commit()

    config = await resolve_active_config(db_session, "xpath_discovery")

    assert config is not None
    assert config.model == "llama-xpath"


@pytest.mark.asyncio
async def test_run_prompt_task_logs_cost_usage(db_session: AsyncSession):
    _seed_xpath_discovery_config(db_session)
    await db_session.commit()

    with patch(
        "app.services.llm_runtime._call_provider",
        new=AsyncMock(return_value=('{"selectors": [{"field_name": "title", "xpath": "//h1/text()"}]}', 120, 18)),
    ):
        result = await run_prompt_task(
            db_session,
            task_type="xpath_discovery",
            run_id=7,
            domain="example.com",
            variables={
                "url": "https://example.com/product",
                "missing_fields_json": '["title"]',
                "existing_values_json": "{}",
                "html_snippet": "<html><body><h1>Title</h1></body></html>",
            },
        )

    assert isinstance(result.payload, list)
    await _assert_single_cost_log(
        db_session,
        task_type="xpath_discovery",
        input_tokens=120,
        output_tokens=18,
    )


@pytest.mark.asyncio
async def test_run_prompt_task_reuses_cached_prompt_result(db_session: AsyncSession):
    _seed_xpath_discovery_config(db_session)
    await db_session.commit()

    variables = {
        "url": "https://example.com/product",
        "missing_fields_json": '["title"]',
        "existing_values_json": "{}",
        "html_snippet": "<html><body><h1>Title</h1></body></html>",
    }
    provider_response = '{"selectors": [{"field_name": "title", "xpath": "//h1/text()"}]}'
    with patch(
        "app.services.llm_runtime._call_provider",
        new=AsyncMock(return_value=(provider_response, 120, 18)),
    ) as call_mock:
        first = await run_prompt_task(
            db_session,
            task_type="xpath_discovery",
            run_id=7,
            domain="example.com",
            variables=variables,
        )
        second = await run_prompt_task(
            db_session,
            task_type="xpath_discovery",
            run_id=7,
            domain="example.com",
            variables=variables,
        )

    assert isinstance(first.payload, list)
    assert second.payload == first.payload
    assert second.input_tokens == first.input_tokens
    assert second.output_tokens == first.output_tokens
    assert call_mock.await_count == 1
    await _assert_single_cost_log(
        db_session,
        task_type="xpath_discovery",
        input_tokens=120,
        output_tokens=18,
    )


@pytest.mark.asyncio
async def test_snapshot_active_configs_includes_page_classification(db_session: AsyncSession):
    db_session.add_all([
        LLMConfig(
            provider="groq",
            model="llama-general",
            api_key_encrypted=encrypt_secret("general-key"),
            task_type="general",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        ),
        LLMConfig(
            provider="groq",
            model="llama-page",
            api_key_encrypted=encrypt_secret("page-key"),
            task_type="page_classification",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        ),
    ])
    await db_session.commit()

    snapshot = await snapshot_active_configs(db_session)

    assert snapshot["page_classification"]["model"] == "llama-page"


@pytest.mark.asyncio
async def test_run_prompt_task_gracefully_returns_provider_connection_error(db_session: AsyncSession):
    config = LLMConfig(
        provider="groq",
        model="llama-test",
        api_key_encrypted=encrypt_secret("secret"),
        task_type="general",
        per_domain_daily_budget_usd=Decimal("5.00"),
        global_session_budget_usd=Decimal("20.00"),
        is_active=True,
    )
    db_session.add(config)
    await db_session.commit()

    with (
        patch("app.services.llm_runtime.get_prompt_task", return_value={"system_file": "x", "user_file": "y", "response_type": "object"}),
        patch("app.services.llm_runtime.load_prompt_file", side_effect=["system prompt", "user prompt"]),
        patch(
            "app.services.llm_runtime._call_provider",
            new=AsyncMock(return_value=("Error: ConnectError: [Errno 11001] getaddrinfo failed", 0, 0)),
        ),
    ):
        result = await run_prompt_task(
            db_session,
            task_type="general",
            run_id=None,
            domain="example.com",
            variables={"value": "test"},
        )

    assert result.payload is None
    assert result.error_message.startswith("Error: ConnectError:")


@pytest.mark.asyncio
async def test_run_prompt_task_rejects_invalid_xpath_selector_schema(db_session: AsyncSession):
    _seed_xpath_discovery_config(db_session)
    await db_session.commit()

    with patch(
        "app.services.llm_runtime._call_provider",
        new=AsyncMock(return_value=('{"selectors": [{"field_name": "title"}]}', 10, 2)),
    ):
        result = await run_prompt_task(
            db_session,
            task_type="xpath_discovery",
            run_id=None,
            domain="example.com",
            variables={"url": "https://example.com", "missing_fields_json": "[]", "existing_values_json": "{}", "html_snippet": "<html></html>"},
        )

    assert result.payload is None
    assert result.error_category == LLMErrorCategory.VALIDATION_FAILURE
    assert "xpath_discovery" in result.error_message


@pytest.mark.asyncio
async def test_run_prompt_task_rejects_invalid_field_cleanup_review_schema(db_session: AsyncSession):
    db_session.add(
        LLMConfig(
            provider="groq",
            model="llama-cleanup",
            api_key_encrypted=encrypt_secret("cleanup-key"),
            task_type="field_cleanup_review",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        )
    )
    await db_session.commit()

    with patch(
        "app.services.llm_runtime._call_provider",
        new=AsyncMock(return_value=('{"canonical": {"title": {"suggested_value": "Desk"}}}', 10, 2)),
    ):
        result = await run_prompt_task(
            db_session,
            task_type="field_cleanup_review",
            run_id=None,
            domain="example.com",
            variables={"url": "https://example.com", "canonical_fields_json": "[]", "target_fields_json": "[]", "existing_values_json": "{}", "candidate_evidence_json": "{}", "discovered_sources_json": "{}", "html_snippet": "<html></html>"},
        )

    assert result.payload is None
    assert result.error_category == LLMErrorCategory.VALIDATION_FAILURE
    assert "field_cleanup_review" in result.error_message


@pytest.mark.asyncio
async def test_run_prompt_task_rejects_invalid_page_classification_schema(db_session: AsyncSession):
    db_session.add(
        LLMConfig(
            provider="groq",
            model="llama-page",
            api_key_encrypted=encrypt_secret("page-key"),
            task_type="page_classification",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        )
    )
    await db_session.commit()

    with patch(
        "app.services.llm_runtime._call_provider",
        new=AsyncMock(return_value=('{"page_type": "maybe", "has_secondary_listing": "no", "wait_selector_hint": "", "reasoning": ""}', 10, 2)),
    ):
        result = await run_prompt_task(
            db_session,
            task_type="page_classification",
            run_id=None,
            domain="example.com",
            variables={"url": "https://example.com", "html_snippet": "<html></html>"},
        )

    assert result.payload is None
    assert result.error_category == LLMErrorCategory.VALIDATION_FAILURE
    assert "page_classification" in result.error_message


def test_load_prompt_file_rejects_parent_path_traversal():
    assert load_prompt_file("../secrets.txt") == ""


@pytest.mark.asyncio
async def test_run_prompt_task_rejects_invalid_schema_inference_payload(db_session: AsyncSession):
    db_session.add(
        LLMConfig(
            provider="groq",
            model="llama-schema",
            api_key_encrypted=encrypt_secret("schema-key"),
            task_type="schema_inference",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        )
    )
    await db_session.commit()

    with patch(
        "app.services.llm_runtime._call_provider",
        new=AsyncMock(return_value=('{"confirmed_fields": ["title"], "new_fields": ["Display Name"], "absent_fields": []}', 10, 2)),
    ):
        result = await run_prompt_task(
            db_session,
            task_type="schema_inference",
            run_id=None,
            domain="example.com",
            variables={"url": "https://example.com", "surface_type": "ecommerce_detail", "baseline_fields_json": "[]", "pruned_html": "<html></html>"},
        )

    assert result.payload is None
    assert result.error_category == LLMErrorCategory.VALIDATION_FAILURE
    assert "schema_inference" in result.error_message


@pytest.mark.asyncio
async def test_run_prompt_task_exports_prometheus_outcome_metrics(db_session: AsyncSession):
    db_session.add_all([
        LLMConfig(
            provider="groq",
            model="llama-xpath",
            api_key_encrypted=encrypt_secret("xpath-key"),
            task_type="xpath_discovery",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        ),
        LLMConfig(
            provider="groq",
            model="llama-schema",
            api_key_encrypted=encrypt_secret("schema-key"),
            task_type="schema_inference",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        ),
    ])
    await db_session.commit()

    with patch(
        "app.services.llm_runtime._call_provider",
        new=AsyncMock(side_effect=[
            ('{"selectors": [{"field_name": "title", "xpath": "//h1/text()"}]}', 10, 2),
            ('{"confirmed_fields": ["title"], "new_fields": ["Display Name"], "absent_fields": []}', 10, 2),
        ]),
    ):
        success = await run_prompt_task(
            db_session,
            task_type="xpath_discovery",
            run_id=None,
            domain="example.com",
            variables={
                "url": "https://example.com",
                "missing_fields_json": "[]",
                "existing_values_json": "{}",
                "html_snippet": "<html></html>",
            },
        )
        failure = await run_prompt_task(
            db_session,
            task_type="schema_inference",
            run_id=None,
            domain="example.com",
            variables={
                "url": "https://example.com",
                "surface_type": "ecommerce_detail",
                "baseline_fields_json": "[]",
                "pruned_html": "<html></html>",
            },
        )

    assert success.error_category == LLMErrorCategory.NONE
    assert failure.error_category == LLMErrorCategory.VALIDATION_FAILURE

    from app.core.metrics import _registry, generate_latest
    rendered = generate_latest(_registry).decode("utf-8") if generate_latest else ""
    assert 'llm_task_outcomes_total{error_category="none",outcome="success",provider="groq",task_type="xpath_discovery"}' in rendered
    assert 'llm_task_outcomes_total{error_category="validation_failure",outcome="error",provider="groq",task_type="schema_inference"}' in rendered
    assert "llm_task_duration_seconds_" in rendered


@pytest.mark.asyncio
async def test_call_provider_with_retry_uses_shared_circuit_state_across_workers(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()

    async def _redis_passthrough(operation, *, default, operation_name):
        _ = (default, operation_name)
        return await operation(fake_redis)

    llm_runtime_module._provider_circuits.clear()
    monkeypatch.setattr("app.services.llm_runtime.redis_is_enabled", lambda: True)
    monkeypatch.setattr("app.services.llm_runtime.redis_fail_open", _redis_passthrough)

    provider_call = AsyncMock(return_value=("Error: ConnectError: upstream unavailable", 0, 0))
    monkeypatch.setattr("app.services.llm_runtime._call_provider", provider_call)

    first_result = await _call_provider_with_retry(
        provider="groq",
        model="llama-test",
        api_key="secret",
        system_prompt="system",
        user_prompt="user",
        max_retries=5,
    )

    assert first_result[0].startswith("Error: ConnectError:")
    assert provider_call.await_count == 5

    # Simulate a separate Celery worker process with no local in-memory circuit state.
    llm_runtime_module._provider_circuits.clear()

    second_result = await _call_provider_with_retry(
        provider="groq",
        model="llama-test",
        api_key="secret",
        system_prompt="system",
        user_prompt="user",
        max_retries=5,
    )

    assert "Circuit breaker open" in second_result[0]
    assert provider_call.await_count == 5


