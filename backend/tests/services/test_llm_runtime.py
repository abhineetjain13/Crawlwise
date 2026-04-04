from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_secret
from app.models.llm import LLMConfig, LLMCostLog
from app.services.llm_runtime import _call_groq, _call_provider, resolve_active_config, run_prompt_task


@pytest.mark.asyncio
async def test_resolve_active_config_prefers_task_specific(db_session: AsyncSession):
    db_session.add_all([
        LLMConfig(
            provider="openai",
            model="gpt-general",
            api_key_encrypted=encrypt_secret("general-key"),
            task_type="general",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        ),
        LLMConfig(
            provider="openai",
            model="gpt-xpath",
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
    assert config.model == "gpt-xpath"


@pytest.mark.asyncio
async def test_run_prompt_task_logs_cost_usage(db_session: AsyncSession):
    db_session.add(
        LLMConfig(
            provider="openai",
            model="gpt-xpath",
            api_key_encrypted=encrypt_secret("xpath-key"),
            task_type="xpath_discovery",
            per_domain_daily_budget_usd=Decimal("1.00"),
            global_session_budget_usd=Decimal("5.00"),
            is_active=True,
        )
    )
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
    rows = (await db_session.execute(select(LLMCostLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].task_type == "xpath_discovery"
    assert rows[0].input_tokens == 120
    assert rows[0].output_tokens == 18


@pytest.mark.asyncio
async def test_call_groq_sets_max_tokens():
    captured_json: dict = {}

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7},
            }

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, _url, *, headers, json):
            _ = headers
            captured_json.update(json)
            return DummyResponse()

    with patch("app.services.llm_runtime.httpx.AsyncClient", return_value=DummyClient()):
        text, input_tokens, output_tokens = await _call_groq(
            "test-key",
            "llama-test",
            "system",
            "user",
        )

    assert captured_json["max_tokens"] == 1200
    assert text == '{"ok": true}'
    assert input_tokens == 5
    assert output_tokens == 7


@pytest.mark.asyncio
async def test_call_provider_returns_error_string_on_httpx_failure():
    with patch(
        "app.services.llm_runtime._call_openai",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
    ):
        raw, input_tokens, output_tokens = await _call_provider(
            provider="openai",
            model="gpt-test",
            api_key="secret",
            system_prompt="system",
            user_prompt="user",
        )

    assert raw.startswith("Error: ConnectError:")
    assert input_tokens == 0
    assert output_tokens == 0


@pytest.mark.asyncio
async def test_run_prompt_task_gracefully_returns_provider_connection_error(db_session: AsyncSession):
    config = LLMConfig(
        provider="openai",
        model="gpt-test",
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
