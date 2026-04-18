from __future__ import annotations

from pydantic_settings import BaseSettings

from app.services.config._module_exports import make_getattr, module_dir
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
    html_snippet_min_budget: int = 100
    html_snippet_window_min_chars: int = 180
    html_snippet_window_max_chars: int = 800
    html_snippet_max_chunks: int = 6
    html_anchor_min_length: int = 3
    schema_field_name_max_length: int = 40
    groq_max_tokens: int = 1200
    groq_temperature: float = 0.1
    anthropic_max_tokens: int = 3000
    anthropic_temperature: float = 0.1
    nvidia_max_tokens: int = 1200
    nvidia_temperature: float = 0.1


llm_runtime_settings = LLMRuntimeSettings()
_EXPORTS = {
    name: name.removeprefix("LLM_").lower()
    for name in (
        "LLM_HTML_SNIPPET_MAX_CHARS",
        "LLM_EXISTING_VALUES_MAX_CHARS",
        "LLM_CANDIDATE_EVIDENCE_MAX_CHARS",
        "LLM_DISCOVERED_SOURCES_MAX_CHARS",
        "LLM_CLEAN_CANDIDATE_TEXT_LIMIT",
        "LLM_PROVIDER_TIMEOUT_SECONDS",
        "LLM_PROVIDER_RETRY_MAX_RETRIES",
        "LLM_PROVIDER_RETRY_BASE_DELAY_SECONDS",
        "LLM_PROVIDER_ERROR_EXCERPT_CHARS",
        "LLM_CIRCUIT_FAILURE_THRESHOLD",
        "LLM_CIRCUIT_COOLDOWN_SECONDS",
        "LLM_PROMPT_TOKEN_LIMIT",
        "LLM_PROMPT_TOKEN_CHAR_MULTIPLIER",
        "LLM_PROMPT_SAFE_TRUNCATE_MAX_STR_LEN",
        "LLM_PROMPT_SAFE_TRUNCATE_MAX_LIST_ITEMS",
        "LLM_PROMPT_COMPACT_JSON_MAX_DEPTH",
        "LLM_PROMPT_COMPACT_JSON_MAX_KEYS",
        "LLM_PROMPT_COMPACT_JSON_MAX_LIST_ITEMS",
        "LLM_PROMPT_COMPACT_LEAF_STRING_MAX_CHARS",
        "LLM_HTML_SNIPPET_MIN_BUDGET",
        "LLM_HTML_SNIPPET_WINDOW_MIN_CHARS",
        "LLM_HTML_SNIPPET_WINDOW_MAX_CHARS",
        "LLM_HTML_SNIPPET_MAX_CHUNKS",
        "LLM_HTML_ANCHOR_MIN_LENGTH",
        "LLM_SCHEMA_FIELD_NAME_MAX_LENGTH",
        "LLM_GROQ_MAX_TOKENS",
        "LLM_GROQ_TEMPERATURE",
        "LLM_ANTHROPIC_MAX_TOKENS",
        "LLM_ANTHROPIC_TEMPERATURE",
        "LLM_NVIDIA_MAX_TOKENS",
        "LLM_NVIDIA_TEMPERATURE",
    )
}

__all__ = sorted([*(_EXPORTS.keys()), "LLMRuntimeSettings", "llm_runtime_settings"])

__getattr__ = make_getattr(
    attr_exports=_EXPORTS,
    settings_obj=llm_runtime_settings,
)


def __dir__() -> list[str]:
    return module_dir(globals(), __all__)
