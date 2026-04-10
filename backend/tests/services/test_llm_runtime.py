from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from app.core.security import encrypt_secret
from app.models.llm import LLMConfig, LLMCostLog
from app.services.llm_runtime import (
    _build_targeted_html_snippet,
    _call_groq,
    _call_provider,
    _call_provider_with_retry,
    _enforce_token_limit,
    _truncate_html,
    resolve_active_config,
    run_prompt_task,
    snapshot_active_configs,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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
    assert captured_json["temperature"] == 0.1
    assert text == '{"ok": true}'
    assert input_tokens == 5
    assert output_tokens == 7


@pytest.mark.asyncio
async def test_call_groq_uses_configured_request_params(monkeypatch):
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

    monkeypatch.setattr("app.services.llm_runtime.LLM_GROQ_MAX_TOKENS", 321)
    monkeypatch.setattr("app.services.llm_runtime.LLM_GROQ_TEMPERATURE", 0.25)

    with patch("app.services.llm_runtime.httpx.AsyncClient", return_value=DummyClient()):
        await _call_groq("test-key", "llama-test", "system", "user")

    assert captured_json["max_tokens"] == 321
    assert captured_json["temperature"] == 0.25


@pytest.mark.asyncio
async def test_call_provider_returns_error_string_on_httpx_failure():
    with patch(
        "app.services.llm_runtime._call_groq",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
    ):
        raw, input_tokens, output_tokens = await _call_provider(
            provider="groq",
            model="llama-test",
            api_key="secret",
            system_prompt="system",
            user_prompt="user",
        )

    assert raw.startswith("Error: ConnectError:")
    assert input_tokens == 0
    assert output_tokens == 0


@pytest.mark.asyncio
async def test_call_provider_with_retry_fails_fast_on_rate_limit():
    with patch(
        "app.services.llm_runtime._call_provider",
        new=AsyncMock(return_value=("Error: HTTP 429: rate limited", 0, 0)),
    ) as call_mock:
        raw, input_tokens, output_tokens = await _call_provider_with_retry(
            provider="groq",
            model="llama-test",
            api_key="secret",
            system_prompt="system",
            user_prompt="user",
            max_retries=3,
            base_delay_s=2.0,
        )

    assert raw == "Error: HTTP 429: rate limited"
    assert input_tokens == 0
    assert output_tokens == 0
    assert call_mock.await_count == 1


@pytest.mark.asyncio
async def test_call_provider_returns_explicit_error_for_supported_but_undispatched_provider():
    with patch("app.services.llm_runtime.SUPPORTED_LLM_PROVIDERS", {"groq", "future_provider"}):
        raw, input_tokens, output_tokens = await _call_provider(
            provider="future_provider",
            model="test-model",
            api_key="secret",
            system_prompt="system",
            user_prompt="user",
        )

    assert raw == "Error: Unsupported provider: future_provider"
    assert input_tokens == 0
    assert output_tokens == 0


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


def test_enforce_token_limit_preserves_json_section_validity():
    evidence = {"items": [{"title": "A" * 500}, {"title": "B" * 500}]}
    prompt = (
        "URL: https://example.com\n\n"
        "Candidate evidence by field:\n"
        f"{json.dumps(evidence)}\n\n"
        "HTML snippet:\n"
        f"<div>{'X' * 800}</div>"
    )

    truncated = _enforce_token_limit(prompt, limit=120)
    prefix = "Candidate evidence by field:\n"
    prefix_parts = truncated.split(prefix, 1)
    assert len(prefix_parts) == 2, "Expected candidate evidence prefix in truncated prompt"
    rendered_section = prefix_parts[1]
    end_marker = "\n\n[TRUNCATED DUE TO TOKEN LIMIT]"
    end = rendered_section.find(end_marker)
    assert end != -1, "Expected truncation marker after rendered JSON payload"
    rendered_json = rendered_section[:end]

    assert "[TRUNCATED DUE TO TOKEN LIMIT]" in truncated
    assert isinstance(json.loads(rendered_json), dict)


def test_truncate_html_prefers_targeted_anchor_windows():
    html = (
        "<html><body>"
        + ("<div>noise</div>" * 400)
        + "<section><h2>Materials & Care</h2><p>Merino wool outer with cotton lining.</p></section>"
        + ("<div>more-noise</div>" * 400)
        + "</body></html>"
    )

    truncated = _truncate_html(html, 320, anchors=["materials"])

    assert "Materials & Care" in truncated
    assert "Merino wool outer" in truncated
    assert len(truncated) <= 320


def test_build_targeted_html_snippet_returns_empty_without_anchor_match():
    html = "<html><body><h1>Title</h1></body></html>"

    assert _build_targeted_html_snippet(html, ["reviews"], 200) == ""
