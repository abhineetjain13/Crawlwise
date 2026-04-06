from __future__ import annotations

import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.schema_service import (
    is_valid_schema_field_name,
    learn_schema_from_record,
    load_resolved_schema,
    persist_resolved_schema,
    resolve_schema,
)


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
async def test_load_resolved_schema_keeps_explicit_fields_without_cross_run_persistence(db_session: AsyncSession):
    await persist_resolved_schema(
        db_session,
        learn_schema_from_record(
            surface="ecommerce_detail",
            domain="example.com",
            baseline_fields=["title", "price"],
            sample_record={"title": "Chair", "price": "10", "wire_gauge": "26 AWG"},
        ),
    )

    resolved = await load_resolved_schema(db_session, "ecommerce_detail", "example.com", explicit_fields=["finish"])

    assert "wire_gauge" not in resolved.fields
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


def test_learn_schema_from_record_normalizes_record_keys_for_deprecated_detection():
    schema = learn_schema_from_record(
        surface="job_detail",
        domain="example.com",
        baseline_fields=["user_name", "title"],
        sample_record={"userName": "Alice", "title": "Engineer"},
    )

    assert schema.deprecated_fields == []


def test_learn_schema_from_record_does_not_expand_job_surface_from_sample_record():
    schema = learn_schema_from_record(
        surface="job_detail",
        domain="example.com",
        baseline_fields=["title", "company", "location", "salary"],
        sample_record={
            "title": "Engineer",
            "currency": "USD",
            "image_url": "https://example.com/job.jpg",
            "additional_images": "https://example.com/job-2.jpg",
            "category": "FULL_TIME",
            "color": "Blue",
            "sku": "ABC-123",
            "requisition_id": "1234",
        },
    )

    assert schema.fields == ["title", "company", "location", "salary"]
    assert schema.new_fields == []


@pytest.mark.asyncio
async def test_resolve_schema_does_not_learn_job_surface_from_sample_record(db_session: AsyncSession):
    resolved = await resolve_schema(
        db_session,
        "job_detail",
        "example.com",
        sample_record={"title": "Engineer", "category": "FULL_TIME", "requisition_id": "1234"},
    )

    assert resolved.source == "static"
    assert resolved.fields == ["title", "company", "location", "salary", "job_type", "posted_date", "apply_url", "description", "requirements", "responsibilities", "qualifications", "benefits", "skills", "remote"]


@pytest.mark.asyncio
async def test_resolve_schema_ignores_llm_flag_and_returns_static_without_sample_record(db_session: AsyncSession):
    with pytest.warns(DeprecationWarning, match="LLM-based schema inference is no longer supported"):
        resolved = await resolve_schema(
            db_session,
            "ecommerce_detail",
            "example.com",
            run_id=55,
            html="<html><body><h1>Chair</h1></body></html>",
            url="https://example.com/product",
            llm_enabled=True,
        )

    assert resolved.source == "static"
    assert "title" in resolved.fields
    assert resolved.saved_at is None


@pytest.mark.asyncio
async def test_resolve_schema_logs_and_returns_fallback_when_learning_fails(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(
        "app.services.schema_service.learn_schema_from_record",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with caplog.at_level(logging.ERROR):
        resolved = await resolve_schema(
            db_session,
            "ecommerce_detail",
            "example.com",
            sample_record={"title": "Chair", "price": "10"},
        )

    assert resolved.source == "static"
    assert "Schema resolution enrichment failed" in caplog.text
