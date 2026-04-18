from __future__ import annotations

from decimal import Decimal

import pytest
from app.core.security import encrypt_secret
from app.models.llm import LLMConfig
from app.services.llm_runtime import (
    load_prompt_file,
    resolve_active_config,
    snapshot_active_configs,
)
from sqlalchemy.ext.asyncio import AsyncSession


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


@pytest.mark.asyncio
async def test_resolve_active_config_prefers_task_specific(db_session: AsyncSession):
    db_session.add_all(
        [
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
        ]
    )
    await db_session.commit()

    config = await resolve_active_config(db_session, "xpath_discovery")

    assert config is not None
    assert config.model == "llama-xpath"


@pytest.mark.asyncio
async def test_snapshot_active_configs_includes_page_classification(
    db_session: AsyncSession,
):
    db_session.add_all(
        [
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
        ]
    )
    await db_session.commit()

    snapshot = await snapshot_active_configs(db_session)

    assert snapshot["page_classification"]["model"] == "llama-page"


def test_load_prompt_file_rejects_parent_path_traversal():
    assert load_prompt_file("../secrets.txt") == ""
