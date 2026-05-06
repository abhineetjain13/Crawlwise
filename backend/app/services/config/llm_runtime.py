"""Runtime LLM settings exports.

This module exports ``LLMRuntimeSettings``, ``SUPPORTED_LLM_PROVIDERS``, and the
``llm_runtime_settings`` instance. Older derived ``LLM_*`` constants were removed.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings

from app.services.config.runtime_settings import _settings_config

SUPPORTED_LLM_PROVIDERS = frozenset({"groq", "anthropic", "nvidia", "aws"})
PARSE_PROVIDER_JSON_ERROR = (
    "Error: Provider response could not be parsed as structured JSON."
)
DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD = {
    "groq/llama-3.3-70b-versatile": [0.59, 0.79],
    "anthropic/claude-3-5-haiku-latest": [0.8, 4.0],
    "nvidia/meta/llama-3.1-70b-instruct": [0.35, 0.4],
    "aws/amazon.nova-lite-v1:0": [0.06, 0.24],
    "aws/amazon.nova-pro-v1:0": [0.8, 3.2],
}


def _parse_provider_model_and_rates(
    key: object,
    value: object,
    *,
    require_supported_provider: bool,
) -> tuple[tuple[str, str], tuple[Decimal, Decimal]] | None:
    provider, separator, model = str(key or "").partition("/")
    normalized_provider = provider.strip().lower()
    if not separator:
        return None
    if (
        require_supported_provider
        and normalized_provider not in SUPPORTED_LLM_PROVIDERS
    ):
        return None
    rates: Any = value
    if not isinstance(rates, (list, tuple)) or len(rates) != 2:
        return None
    try:
        input_rate = Decimal(str(rates[0]))
        output_rate = Decimal(str(rates[1]))
    except (InvalidOperation, ValueError):
        return None
    if input_rate < 0 or output_rate < 0:
        return None
    return (normalized_provider, model.strip().lower()), (input_rate, output_rate)


class LLMRuntimeSettings(BaseSettings):
    """Runtime LLM settings loaded from ``CRAWLER_LLM_`` environment variables."""

    model_config = _settings_config(env_prefix="CRAWLER_LLM_")

    html_snippet_max_chars: int = 40000
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
    prompt_json_reparse_max_chars: int = 16384
    prompt_token_char_multiplier: int = 3
    prompt_safe_truncate_max_str_len: int = 400
    prompt_safe_truncate_max_list_items: int = 5
    prompt_compact_json_max_depth: int = 3
    prompt_compact_json_max_keys: int = 12
    prompt_compact_json_max_list_items: int = 10
    prompt_compact_leaf_string_max_chars: int = 220
    html_anchor_min_length: int = 3
    schema_field_name_max_length: int = 40
    html_prune_stripped_tags: str = "script,style,svg,noscript,iframe,nav,footer,header,aside,form,button,input,select,textarea"
    html_prune_preserved_script_types: str = "application/ld+json,application/json"
    html_prune_preserved_attrs: str = "id,class,data-testid,data-test,data-qa,data-sku,data-product-id,data-price,data-availability,itemprop,itemtype,itemscope,itemref,aria-label,aria-labelledby,role,name,type,content,property,href,src,alt,title,value,data-component,data-section,data-field"
    html_prune_preserved_script_ids: str = "__NEXT_DATA__"
    html_prune_strip_attr_prefixes: str = "on,data-"
    html_prune_preserved_data_attr_prefixes: str = (
        "data-test,data-qa,data-sku,data-product-id,data-price,"
        "data-availability,data-component,data-section,data-field"
    )
    groq_chat_completions_url: str = "https://api.groq.com/openai/v1/chat/completions"
    groq_max_tokens: int = 1200
    groq_temperature: float = 0.1
    anthropic_messages_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_max_tokens: int = 3000
    anthropic_temperature: float = 0.1
    nvidia_chat_completions_url: str = (
        "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    nvidia_max_tokens: int = 1200
    nvidia_temperature: float = 0.1
    aws_max_tokens: int = 4096
    aws_temperature: float = 0.1
    # AWS Bedrock calls go through the local LiteLLM-compatible proxy.
    aws_proxy_url: str = "http://localhost:4000/v1/chat/completions"
    token_pricing_json: str = Field(
        default=json.dumps(DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD),
        description=(
            "JSON map of 'provider/model' to [input_per_million, output_per_million] USD."
        ),
    )

    def get_token_pricing(self) -> dict[tuple[str, str], tuple[Decimal, Decimal]]:
        """Return (provider, model) -> (input_per_million, output_per_million)."""
        try:
            raw = json.loads(self.token_pricing_json or "{}")
        except json.JSONDecodeError:
            raw = DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD
        if not isinstance(raw, dict):
            raw = DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD

        pricing: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
        for key, value in raw.items():
            parsed = _parse_provider_model_and_rates(
                key,
                value,
                require_supported_provider=True,
            )
            if parsed:
                pricing[parsed[0]] = parsed[1]
        if not pricing and raw is not DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD:
            for key, value in DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD.items():
                parsed = _parse_provider_model_and_rates(
                    key,
                    value,
                    require_supported_provider=False,
                )
                if parsed:
                    pricing[parsed[0]] = parsed[1]
        return pricing


llm_runtime_settings = LLMRuntimeSettings()
LLM_TOKEN_PRICING_PER_MILLION_USD = llm_runtime_settings.get_token_pricing()

__all__ = [
    "DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD",
    "LLMRuntimeSettings",
    "LLM_TOKEN_PRICING_PER_MILLION_USD",
    "PARSE_PROVIDER_JSON_ERROR",
    "SUPPORTED_LLM_PROVIDERS",
    "llm_runtime_settings",
]
