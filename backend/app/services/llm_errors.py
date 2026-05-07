from __future__ import annotations

import re
from enum import StrEnum

ERROR_PREFIX = "Error:"

__all__ = [
    "ERROR_PREFIX",
    "LLMErrorCategory",
    "classify_error",
]


class LLMErrorCategory(StrEnum):
    NONE = "none"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    AUTH_FAILURE = "auth_failure"
    CLIENT_ERROR = "client_error"
    PROVIDER_ERROR = "provider_error"
    PARSE_FAILURE = "parse_failure"
    VALIDATION_FAILURE = "validation_failure"
    CIRCUIT_OPEN = "circuit_open"
    BUDGET_EXCEEDED = "budget_exceeded"
    MISSING_CONFIG = "missing_config"


_DETERMINISTIC_CLIENT_ERROR_CODES = frozenset({
    "400", "402", "405", "406", "409", "410", "411", "413", "414",
    "415", "416", "417", "418", "421", "422", "424", "426", "428", "431",
})


def classify_error(raw: str) -> LLMErrorCategory:
    lowered = raw.lower()
    if "circuit_open" in lowered or "circuit breaker" in lowered:
        return LLMErrorCategory.CIRCUIT_OPEN
    if "429" in raw or "rate" in lowered:
        return LLMErrorCategory.RATE_LIMITED
    if "timeout" in lowered or "timed out" in lowered:
        return LLMErrorCategory.TIMEOUT
    if (
        "401" in raw
        or "403" in raw
        or "unauthorized" in lowered
        or "forbidden" in lowered
    ):
        return LLMErrorCategory.AUTH_FAILURE
    if raw.startswith(ERROR_PREFIX) and any(
        re.search(r"\b" + re.escape(code) + r"\b", raw)
        for code in _DETERMINISTIC_CLIENT_ERROR_CODES
    ):
        return LLMErrorCategory.CLIENT_ERROR
    if raw.startswith(ERROR_PREFIX):
        return LLMErrorCategory.PROVIDER_ERROR
    return LLMErrorCategory.NONE

