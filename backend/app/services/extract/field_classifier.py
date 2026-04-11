from __future__ import annotations

import re

from app.services.config.extraction_rules import (
    CANDIDATE_DYNAMIC_FIELD_NAME_HARD_REJECTS,
    CANDIDATE_DYNAMIC_FIELD_NAME_PATTERN,
    DYNAMIC_FIELD_NAME_DROP_TOKENS,
    DYNAMIC_FIELD_NAME_MAX_TOKENS,
    DYNAMIC_FIELD_NAME_SCHEMA_NOISE_REGEXES,
    DYNAMIC_FIELD_NAME_TICKERLIKE_BLOCKLIST,
    JSONLD_NON_PRODUCT_BLOCK_TYPES,
    JSONLD_TYPE_NOISE,
    PRODUCT_IDENTITY_FIELDS,
)
from app.services.config.field_mappings import get_surface_field_aliases

# ---------------------------------------------------------------------------
# Module-level constants (only used by functions in this module)
# ---------------------------------------------------------------------------

_DYNAMIC_FIELD_NAME_MAX_TOKENS = DYNAMIC_FIELD_NAME_MAX_TOKENS
_DYNAMIC_VARIANT_VALUE_FIELDS = frozenset(
    {"style", "styles", "xs", "s", "m", "l", "xl", "xxl", "xxxl", "onesize", "one_size"}
)
_PACK_STYLE_DYNAMIC_RE = re.compile(r"^pack_\d+$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Inline helper (avoids circular import with service.py)
# ---------------------------------------------------------------------------

def _normalized_candidate_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


# ---------------------------------------------------------------------------
# Moved functions
# ---------------------------------------------------------------------------

def _dynamic_field_name_is_schema_slug_noise(normalized: str) -> bool:
    """Analytics / embedding / vendor keys (elp158, e150d_en, …)."""
    if normalized in DYNAMIC_FIELD_NAME_TICKERLIKE_BLOCKLIST:
        return True
    for pattern in DYNAMIC_FIELD_NAME_SCHEMA_NOISE_REGEXES:
        if pattern.search(normalized):
            return True
    return False


def _dynamic_value_is_bare_ticker_symbol(value: object) -> bool:
    """Drop dynamic rows whose value is only a ticker-like token (e.g. XRP)."""
    text = _normalized_candidate_text(value)
    if not text or len(text) > 6:
        return False
    if not re.fullmatch(r"[A-Za-z]{3,5}", text):
        return False
    return text.lower() in DYNAMIC_FIELD_NAME_TICKERLIKE_BLOCKLIST


def _dynamic_field_name_is_valid(normalized: str) -> bool:
    """Reject field names that are noise: single chars, sentence-like, or JSON-LD types."""
    if len(normalized) <= 1 or len(normalized) > 60:
        return False
    if not re.fullmatch(CANDIDATE_DYNAMIC_FIELD_NAME_PATTERN, normalized):
        return False
    if normalized in JSONLD_TYPE_NOISE:
        return False
    if normalized in _DYNAMIC_VARIANT_VALUE_FIELDS or _PACK_STYLE_DYNAMIC_RE.fullmatch(
        normalized
    ):
        return False
    if _dynamic_field_name_is_schema_slug_noise(normalized):
        return False
    tokens = [token for token in normalized.split("_") if token]
    if len(tokens) > _DYNAMIC_FIELD_NAME_MAX_TOKENS:
        return False
    dropped_tokens = sum(
        1 for token in tokens if token in DYNAMIC_FIELD_NAME_DROP_TOKENS
    )
    if dropped_tokens >= 2 and dropped_tokens >= len(tokens) - 1:
        return False
    # 5+ underscores suggests a sentence heading, not a spec label
    if normalized.count("_") >= 5:
        return False
    return True


def _field_name_preference(field_name: str, *, target_fields: set[str]) -> int:
    tokens = [token for token in str(field_name or "").split("_") if token]
    score = 100 if field_name in target_fields else 0
    score += max(0, 20 - len(tokens))
    if re.match(r"^\d", field_name):
        score -= 30
    if "price" in tokens and len(tokens) > 2:
        score -= 20
    if len(tokens) > _DYNAMIC_FIELD_NAME_MAX_TOKENS:
        score -= 30
    score -= sum(5 for token in tokens if token in DYNAMIC_FIELD_NAME_DROP_TOKENS)
    return score


def _dynamic_field_name_is_noisy(field_name: str) -> bool:
    normalized = str(field_name or "").strip().lower()
    if not normalized:
        return True
    if re.match(r"^\d", normalized):
        return True
    tokens = [token for token in normalized.split("_") if token]
    if not tokens:
        return True
    if len(tokens) > _DYNAMIC_FIELD_NAME_MAX_TOKENS:
        return True
    noise_hits = sum(1 for token in tokens if token in DYNAMIC_FIELD_NAME_DROP_TOKENS)
    if noise_hits >= 2:
        return True
    if "price" in tokens and len(tokens) > 2:
        return True
    if _dynamic_field_name_is_schema_slug_noise(normalized):
        return True
    if normalized in CANDIDATE_DYNAMIC_FIELD_NAME_HARD_REJECTS:
        return True
    return False


def _should_skip_jsonld_block(payload: dict, field_name: str) -> bool:
    """Skip non-product JSON-LD blocks for product-identity fields."""
    if field_name not in PRODUCT_IDENTITY_FIELDS:
        return False
    raw_types = payload.get("@type")
    if raw_types is None:
        type_names: list[object] = []
    elif isinstance(raw_types, str):
        type_names = [raw_types]
    elif isinstance(raw_types, (list, tuple)):
        type_names = list(raw_types)
    else:
        type_names = [raw_types]
    lowered_types = [
        str(type_name or "").lower()
        for type_name in type_names
        if str(type_name or "").strip()
    ]
    return any(
        type_name in JSONLD_NON_PRODUCT_BLOCK_TYPES for type_name in lowered_types
    )


def _field_alias_tokens(field_name: str, *, surface: str = "") -> set[str]:
    aliases = [field_name, *get_surface_field_aliases(surface).get(field_name, [])]
    return {token for alias in aliases if (token := _normalized_field_token(alias))}


def _normalized_field_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
