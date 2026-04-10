from __future__ import annotations

import pytest
from app.services.schema_service import (
    is_valid_schema_field_name,
    load_resolved_schema,
    persist_resolved_schema,
    resolve_schema,
)
from sqlalchemy.ext.asyncio import AsyncSession


def test_is_valid_schema_field_name_rejects_invalid_names():
    assert is_valid_schema_field_name("materials") is True
    assert is_valid_schema_field_name("team_size") is True
    assert is_valid_schema_field_name("_hidden") is False
    assert is_valid_schema_field_name("123") is False
    assert is_valid_schema_field_name("field__name") is False
    assert is_valid_schema_field_name("Field Name") is False


@pytest.mark.asyncio
async def test_load_resolved_schema_keeps_explicit_fields_without_cross_run_persistence(
    db_session: AsyncSession,
):
    resolved = await load_resolved_schema(
        db_session,
        "ecommerce_detail",
        "example.com",
        explicit_fields=["finish"],
    )

    assert "finish" in resolved.fields
    assert resolved.domain == "example.com"

    persisted = await persist_resolved_schema(db_session, resolved)
    reloaded = await load_resolved_schema(db_session, "ecommerce_detail", "example.com")

    assert "finish" not in reloaded.fields
    assert persisted.source == "static"


@pytest.mark.asyncio
async def test_resolve_schema_remains_static_for_detail_sample_record(
    db_session: AsyncSession,
):
    resolved = await resolve_schema(
        db_session,
        "ecommerce_detail",
        "example.com",
        sample_record={"title": "Chair", "price": "10", "wire_gauge": "26 AWG"},
    )

    assert resolved.source == "static"
    assert "wire_gauge" not in resolved.fields


@pytest.mark.asyncio
async def test_resolve_schema_remains_static_for_job_sample_record(
    db_session: AsyncSession,
):
    resolved = await resolve_schema(
        db_session,
        "job_detail",
        "example.com",
        sample_record={"title": "Engineer", "category": "FULL_TIME", "requisition_id": "1234"},
    )

    assert resolved.source == "static"
    assert resolved.fields == [
        "title",
        "company",
        "location",
        "salary",
        "job_type",
        "posted_date",
        "apply_url",
        "description",
        "requirements",
        "responsibilities",
        "qualifications",
        "benefits",
        "skills",
        "remote",
    ]


@pytest.mark.asyncio
async def test_resolve_schema_ignores_llm_flag_and_returns_static_without_sample_record(
    db_session: AsyncSession,
):
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
