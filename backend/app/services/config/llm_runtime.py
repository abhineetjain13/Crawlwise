from __future__ import annotations

from pydantic_settings import BaseSettings

from app.services.config.runtime_settings import _settings_config


class LLMRuntimeSettings(BaseSettings):
    model_config = _settings_config(env_prefix="CRAWLER_LLM_")

    html_snippet_max_chars: int = 12000
    existing_values_max_chars: int = 2400
    candidate_evidence_max_chars: int = 16000
    discovered_sources_max_chars: int = 15000
    clean_candidate_text_limit: int = 1200
    groq_max_tokens: int = 1200
    groq_temperature: float = 0.1
    anthropic_max_tokens: int = 3000
    anthropic_temperature: float = 0.1
    nvidia_max_tokens: int = 1200
    nvidia_temperature: float = 0.1


llm_runtime_settings = LLMRuntimeSettings()

LLM_HTML_SNIPPET_MAX_CHARS = llm_runtime_settings.html_snippet_max_chars
LLM_EXISTING_VALUES_MAX_CHARS = llm_runtime_settings.existing_values_max_chars
LLM_CANDIDATE_EVIDENCE_MAX_CHARS = (
    llm_runtime_settings.candidate_evidence_max_chars
)
LLM_DISCOVERED_SOURCES_MAX_CHARS = (
    llm_runtime_settings.discovered_sources_max_chars
)
LLM_CLEAN_CANDIDATE_TEXT_LIMIT = llm_runtime_settings.clean_candidate_text_limit
LLM_GROQ_MAX_TOKENS = llm_runtime_settings.groq_max_tokens
LLM_GROQ_TEMPERATURE = llm_runtime_settings.groq_temperature
LLM_ANTHROPIC_MAX_TOKENS = llm_runtime_settings.anthropic_max_tokens
LLM_ANTHROPIC_TEMPERATURE = llm_runtime_settings.anthropic_temperature
LLM_NVIDIA_MAX_TOKENS = llm_runtime_settings.nvidia_max_tokens
LLM_NVIDIA_TEMPERATURE = llm_runtime_settings.nvidia_temperature
