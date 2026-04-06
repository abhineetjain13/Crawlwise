from __future__ import annotations

from decimal import Decimal
import logging
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_secret
from app.models.llm import LLMConfig, LLMCostLog
from app.services.schema_service import (
    is_valid_schema_field_name,
    learn_schema_from_record,
    load_resolved_schema,
    persist_resolved_schema,
    resolve_schema,
)
from app.services.site_memory_service import merge_memory


def test_is_valid_schema_field_name_rejects_invalid_names():
    assert is_valid_schema_field_name("materials") is True
    assert is_valid_schema_field_name("team_size") is True
    assert is_valid_schema_field_name("_hidden") is False
    assert is_valid_schema_field_name("123") is False
    assert is_valid_schema_field_name("field__name") is False
    assert is_valid_schema_field_name("Field Name") is False


def test_learn_schema_from_record_promotes_scalar_domain_fields():
    schema = learn_schema_from_record(
        surface="ecommerce_detail",
        domain="example.com",
        baseline_fields=["title", "price"],
        sample_record={"title": "Chair", "price": "10", "materials": "Oak", "specs": {"depth": "1 in"}},
    )

    assert schema.fields == ["title", "price", "materials"]
    assert schema.new_fields == ["materials"]
    assert schema.deprecated_fields == []


@pytest.mark.asyncio
async def test_load_resolved_schema_uses_site_memory_snapshot(db_session: AsyncSession):
    await persist_resolved_schema(
        db_session,
        learn_schema_from_record(
            surface="ecommerce_detail",
            domain="example.com",
            baseline_fields=["title", "price"],
            sample_record={"title": "Chair", "price": "10", "materials": "Oak"},
        ),
    )

    resolved = await load_resolved_schema(db_session, "ecommerce_detail", "example.com", explicit_fields=["finish"])

    assert "materials" in resolved.fields
    assert "finish" in resolved.fields
    assert resolved.domain == "example.com"


@pytest.mark.asyncio
async def test_resolve_schema_learns_from_sample_record_when_memory_missing(db_session: AsyncSession):
    resolved = await resolve_schema(
        db_session,
        "ecommerce_detail",
        "example.com",
        sample_record={"title": "Chair", "price": "10", "wire_gauge": "26 AWG"},
    )

    assert resolved.source == "learned"
    assert "wire_gauge" in resolved.new_fields


@pytest.mark.asyncio
async def test_resolve_schema_falls_back_when_llm_errors(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.schema_service.run_prompt_task",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    resolved = await resolve_schema(
        db_session,
        "ecommerce_detail",
        "example.com",
        html="<html><body><h1>Chair</h1></body></html>",
        llm_enabled=True,
    )

    assert resolved.source == "static"
    assert "title" in resolved.fields


@pytest.mark.asyncio
async def test_resolve_schema_ignores_llm_error_results_without_persisting(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_run_prompt_task(_session, **kwargs):
        captured["run_id"] = kwargs["run_id"]
        return type("Result", (), {"payload": None, "error_message": "provider unavailable"})()

    monkeypatch.setattr("app.services.schema_service.run_prompt_task", fake_run_prompt_task)

    resolved = await resolve_schema(
        db_session,
        "ecommerce_detail",
        "example.com",
        run_id=55,
        html="<html><body><h1>Chair</h1></body></html>",
        llm_enabled=True,
    )

    assert captured["run_id"] == 55
    assert resolved.source == "static"
    memory_resolved = await load_resolved_schema(db_session, "ecommerce_detail", "example.com")
    assert memory_resolved.saved_at is None


@pytest.mark.asyncio
async def test_resolve_schema_ignores_empty_llm_payload_without_persisting(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.schema_service.run_prompt_task",
        AsyncMock(return_value=type("Result", (), {"payload": {}, "error_message": ""})()),
    )

    resolved = await resolve_schema(
        db_session,
        "ecommerce_detail",
        "example.com",
        run_id=56,
        html="<html><body><h1>Chair</h1></body></html>",
        llm_enabled=True,
    )

    assert resolved.source == "static"
    memory_resolved = await load_resolved_schema(db_session, "ecommerce_detail", "example.com")
    assert memory_resolved.saved_at is None


@pytest.mark.asyncio
async def test_load_resolved_schema_defaults_invalid_confidence_to_zero(db_session: AsyncSession):
    await merge_memory(
        db_session,
        "example.com",
        schemas={
            "ecommerce_detail": {
                "baseline_fields": ["title"],
                "fields": ["title", "materials"],
                "new_fields": ["materials"],
                "deprecated_fields": [],
                "source": "learned",
                "confidence": "broken",
                "saved_at": "2026-04-06T00:00:00+00:00",
            }
        },
    )

    resolved = await load_resolved_schema(db_session, "ecommerce_detail", "example.com")

    assert resolved.confidence == 0.0


@pytest.mark.asyncio
async def test_resolve_schema_logs_and_returns_fallback_when_enrichment_fails(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(
        "app.services.schema_service.run_prompt_task",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    with caplog.at_level(logging.ERROR):
        resolved = await resolve_schema(
            db_session,
            "ecommerce_detail",
            "example.com",
            html="<html><body><h1>Chair</h1></body></html>",
            llm_enabled=True,
        )

    assert resolved.source == "static"
    assert "Schema resolution enrichment failed" in caplog.text


@pytest.mark.asyncio
async def test_resolve_schema_logs_cost_with_run_id(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
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
    monkeypatch.setattr(
        "app.services.llm_runtime._call_provider_with_retry",
        AsyncMock(return_value=('{"confirmed_fields":["title"],"new_fields":["materials"],"absent_fields":[]}', 40, 12)),
    )

    resolved = await resolve_schema(
        db_session,
        "ecommerce_detail",
        "example.com",
        run_id=222,
        html="<html><body><h1>Chair</h1><section>Materials: Oak</section></body></html>",
        llm_enabled=True,
    )

    assert resolved.source == "llm_inferred"
    assert "materials" in resolved.fields
    rows = (await db_session.execute(select(LLMCostLog).where(LLMCostLog.task_type == "schema_inference"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].run_id == 222
