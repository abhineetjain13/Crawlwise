from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.security import decrypt_secret
from app.models.crawl import CrawlRun
from app.models.llm import LLMConfig
from app.services.config.field_mappings import PROMPT_REGISTRY
from app.services.config.llm_runtime import SUPPORTED_LLM_PROVIDERS
from app.services.config.product_intelligence import PRODUCT_INTELLIGENCE_PROMPT_REGISTRY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "data" / "prompts"
_LEGACY_PROMPTS_DIR = (
    Path(__file__).resolve().parents[1] / "data" / "knowledge_base" / "prompts"
)


def get_prompt_task(task_type: str) -> dict | None:
    normalized = str(task_type or "").strip()
    task = PRODUCT_INTELLIGENCE_PROMPT_REGISTRY.get(normalized) or PROMPT_REGISTRY.get(normalized)
    return dict(task) if isinstance(task, dict) else None


def load_prompt_file(relative_path: str) -> str:
    text = str(relative_path or "").strip()
    if not text:
        return ""
    for prompts_dir in (_PROMPTS_DIR, _LEGACY_PROMPTS_DIR):
        candidate = prompts_dir / text
        prompts_dir_resolved = prompts_dir.resolve(strict=False)
        candidate_resolved = candidate.resolve(strict=False)
        try:
            candidate_resolved.relative_to(prompts_dir_resolved)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return ""


def serialize_config_snapshot(config: LLMConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "provider": config.provider,
        "model": config.model,
        "api_key_encrypted": config.api_key_encrypted,
        "task_type": config.task_type,
    }


async def resolve_active_config(
    session: AsyncSession,
    task_type: str,
) -> LLMConfig | None:
    for candidate in [task_type, "general"]:
        result = await session.execute(
            select(LLMConfig)
            .where(LLMConfig.is_active.is_(True), LLMConfig.task_type == candidate)
            .order_by(LLMConfig.created_at.desc())
            .limit(1)
        )
        config = result.scalar_one_or_none()
        if (
            config is not None
            and str(config.provider or "").strip().lower() in SUPPORTED_LLM_PROVIDERS
        ):
            return config
    return None


async def snapshot_active_configs(
    session: AsyncSession,
    task_types: list[str] | None = None,
) -> dict[str, dict]:
    snapshot: dict[str, dict] = {}
    for task_type in task_types or [
        "general",
        "direct_record_extraction",
        "xpath_discovery",
        "missing_field_extraction",
        "field_cleanup_review",
        "page_classification",
        "schema_inference",
        "product_intelligence_enrichment",
        "product_intelligence_brand_inference",
    ]:
        config = await resolve_active_config(session, task_type)
        if config is not None:
            snapshot[task_type] = serialize_config_snapshot(config)
    return snapshot


async def resolve_run_config(
    session: AsyncSession,
    *,
    run_id: int | None,
    task_type: str,
) -> dict[str, Any] | None:
    if run_id is not None:
        run = await session.get(CrawlRun, run_id)
        if run is not None:
            snapshot = run.settings_view.llm_config_snapshot()
            for candidate in [task_type, "general"]:
                config_snapshot = snapshot.get(candidate)
                if isinstance(config_snapshot, dict):
                    return config_snapshot
    config = await resolve_active_config(session, task_type)
    if config is None:
        return None
    return serialize_config_snapshot(config)


def provider_env_key(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "groq":
        return settings.groq_api_key
    if normalized == "anthropic":
        return settings.anthropic_api_key
    if normalized == "nvidia":
        return settings.nvidia_api_key
    return ""


def resolve_provider_api_key(*, provider: str, encrypted_value: str) -> str:
    decrypted = decrypt_secret(encrypted_value) if encrypted_value else ""
    if decrypted:
        return decrypted
    return provider_env_key(provider)


def llm_provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "provider": "groq",
            "label": "Groq",
            "api_key_set": bool(settings.groq_api_key),
            "recommended_models": [
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
            ],
        },
        {
            "provider": "nvidia",
            "label": "NVIDIA",
            "api_key_set": bool(settings.nvidia_api_key),
            "recommended_models": [
                "meta/llama-3.1-70b-instruct",
                "meta/llama-3.1-8b-instruct",
            ],
        },
        {
            "provider": "anthropic",
            "label": "Anthropic",
            "api_key_set": bool(settings.anthropic_api_key),
            "recommended_models": [
                "claude-3-5-haiku-latest",
                "claude-sonnet-4-20250514",
            ],
        },
    ]
