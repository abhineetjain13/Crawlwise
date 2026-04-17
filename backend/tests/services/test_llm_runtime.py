import math
import math
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from app.core.metrics import render_prometheus_metrics
from app.core.security import encrypt_secret
from app.models.llm import LLMConfig, LLMCostLog
from app.services.llm_runtime import (
    _build_targeted_html_snippet,
    _build_llm_cache_key,
    _call_groq,
    _call_provider,
    _call_provider_with_retry,
    _classify_error,
    _get_circuit,
    _enforce_token_limit,
    _truncate_html,
    LLMErrorCategory,
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
async def test_run_prompt_task_reuses_cached_prompt_result(db_session: AsyncSession):
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
    rows = (await db_session.execute(select(LLMCostLog))).scalars().all()
    assert len(rows) == 1


def test_build_llm_cache_key_is_deterministic_for_equivalent_variables():
    key_a = _build_llm_cache_key(
        task_type="xpath_discovery",
        domain="Example.com",
        provider="groq",
        model="llama-test",
        response_type="object",
        data_key="",
        system_prompt="system",
        user_prompt="user",
        variables={"b": [2, 1], "a": {"y": 2, "x": 1}},
    )
    key_b = _build_llm_cache_key(
        task_type="xpath_discovery",
        domain="example.com",
        provider="groq",
        model="llama-test",
        response_type="object",
        data_key="",
        system_prompt="system",
        user_prompt="user",
        variables={"a": {"x": 1, "y": 2}, "b": [2, 1]},
    )

    assert key_a == key_b


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

    assert math.isclose(captured_json["temperature"], 0.1, rel_tol=1e-09, abs_tol=1e-09)
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
    assert math.isclose(captured_json["temperature"], 0.25, rel_tol=1e-09, abs_tol=1e-09)


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
async def test_call_provider_with_retry_marks_open_circuit_errors():
    import time

    circuit = _get_circuit("groq")
    circuit.consecutive_failures = 5
    circuit.opened_at = time.monotonic()

    try:
        raw, input_tokens, output_tokens = await _call_provider_with_retry(
            provider="groq",
            model="llama-test",
            api_key="secret",
            system_prompt="system",
            user_prompt="user",
        )
    finally:
        circuit.consecutive_failures = 0
        circuit.opened_at = 0.0

    assert "circuit_open" in raw
    assert _classify_error(raw) == LLMErrorCategory.CIRCUIT_OPEN
    assert input_tokens == 0
    assert output_tokens == 0


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


@pytest.mark.asyncio
async def test_run_prompt_task_rejects_invalid_xpath_selector_schema(db_session: AsyncSession):
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

    payload, _content_type = await render_prometheus_metrics()
    rendered = payload.decode("utf-8")
    assert 'llm_task_outcomes_total{error_category="none",outcome="success",provider="groq",task_type="xpath_discovery"}' in rendered
    assert 'llm_task_outcomes_total{error_category="validation_failure",outcome="error",provider="groq",task_type="schema_inference"}' in rendered
    assert "llm_task_duration_seconds_" in rendered


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