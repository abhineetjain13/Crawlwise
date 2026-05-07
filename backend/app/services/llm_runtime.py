"""Public facade for LLM runtime calls and exported LLM contracts."""

from __future__ import annotations

from app.services.llm_circuit_breaker import circuit_breaker_snapshot
from app.services.llm_config_service import llm_provider_catalog
from app.services.llm_errors import ERROR_PREFIX, LLMErrorCategory, classify_error
from app.services.llm_provider_client import test_provider_connection
from app.services.llm_tasks import (
    discover_xpath_candidates,
    extract_records_directly,
    extract_missing_fields,
    review_field_candidates,
    run_prompt_task,
)
from app.services.llm_types import LLMTaskResult

__all__ = [
    "ERROR_PREFIX",
    "LLMErrorCategory",
    "LLMTaskResult",
    "classify_error",
    "circuit_breaker_snapshot",
    "discover_xpath_candidates",
    "extract_records_directly",
    "extract_missing_fields",
    "llm_provider_catalog",
    "review_field_candidates",
    "run_prompt_task",
    "test_provider_connection",
]
