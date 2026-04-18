from __future__ import annotations

from dataclasses import dataclass

from app.services.llm_circuit_breaker import LLMErrorCategory


@dataclass
class LLMTaskResult:
    payload: dict | list | None
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str = ""
    model: str = ""
    error_message: str = ""
    error_category: LLMErrorCategory = LLMErrorCategory.NONE
