from __future__ import annotations

from pydantic_settings import BaseSettings

from app.services.config.runtime_settings import _settings_config


class LLMRuntimeSettings(BaseSettings):
    """LLM_* exports strip the LLM_ prefix before resolving settings attributes."""

    model_config = _settings_config(env_prefix="CRAWLER_LLM_")

    html_snippet_max_chars: int = 12000
    existing_values_max_chars: int = 2400
    candidate_evidence_max_chars: int = 16000
    discovered_sources_max_chars: int = 15000
    clean_candidate_text_limit: int = 1200
    provider_timeout_seconds: float = 30.0
    provider_retry_max_retries: int = 1
    provider_retry_base_delay_seconds: float = 0.0
    provider_error_excerpt_chars: int = 300
    circuit_failure_threshold: int = 5
    circuit_cooldown_seconds: int = 120
    prompt_token_limit: int = 5600
    prompt_token_char_multiplier: int = 3
    prompt_safe_truncate_max_str_len: int = 400
    prompt_safe_truncate_max_list_items: int = 5
    prompt_compact_json_max_depth: int = 3
    prompt_compact_json_max_keys: int = 12
    prompt_compact_json_max_list_items: int = 10
    prompt_compact_leaf_string_max_chars: int = 220
    html_anchor_min_length: int = 3
    schema_field_name_max_length: int = 40
    groq_max_tokens: int = 1200
    groq_temperature: float = 0.1
    anthropic_max_tokens: int = 3000
    anthropic_temperature: float = 0.1
    nvidia_max_tokens: int = 1200
    nvidia_temperature: float = 0.1


llm_runtime_settings = LLMRuntimeSettings()

__all__ = ["LLMRuntimeSettings", "llm_runtime_settings"]
