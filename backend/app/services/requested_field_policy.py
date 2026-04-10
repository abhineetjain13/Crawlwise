from __future__ import annotations

import re

from app.services.pipeline_config import REQUESTED_FIELD_ALIASES

_CAMEL_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")
_NON_FIELD_RE = re.compile(r"[^a-z0-9.]+")


def _normalize_key(value: str | None) -> str:
    text = " ".join(str(value or "").split()).strip().lower()
    if not text:
        return ""
    text = text.replace("&", " ")
    text = _CAMEL_BOUNDARY_RE.sub("_", text)
    text = _NON_FIELD_RE.sub("_", text)
    text = re.sub(r"_+", "_", text).strip("_.")
    return text


_ALIAS_TO_CANONICAL: dict[str, str] = {}
NORMALIZED_REQUESTED_FIELD_ALIASES: dict[str, list[str]] = {}
for canonical, aliases in REQUESTED_FIELD_ALIASES.items():
    canonical_key = _normalize_key(canonical)
    if canonical_key:
        _ALIAS_TO_CANONICAL[canonical_key] = canonical_key
    normalized_aliases: list[str] = []
    for alias in aliases:
        alias_key = _normalize_key(alias)
        if alias_key and alias_key not in _ALIAS_TO_CANONICAL:
            _ALIAS_TO_CANONICAL[alias_key] = canonical_key or canonical
        if alias_key and alias_key not in normalized_aliases:
            normalized_aliases.append(alias_key)
    if canonical_key:
        alias_terms = [canonical_key, *normalized_aliases]
        deduped_alias_terms: list[str] = []
        seen_terms: set[str] = set()
        for term in alias_terms:
            if not term or term in seen_terms:
                continue
            seen_terms.add(term)
            deduped_alias_terms.append(term)
        NORMALIZED_REQUESTED_FIELD_ALIASES[canonical_key] = deduped_alias_terms


def normalize_requested_field(value: str | None) -> str:
    text = _normalize_key(value)
    if not text:
        return ""
    if text.startswith("sections."):
        text = text.split(".", 1)[1]
    return _ALIAS_TO_CANONICAL.get(text, text)


def expand_requested_fields(values: list[str] | None) -> list[str]:
    expanded: list[str] = []
    for value in values or []:
        normalized = normalize_requested_field(value)
        if normalized and normalized not in expanded:
            expanded.append(normalized)
    return expanded


def requested_field_alias_map() -> dict[str, str]:
    return dict(_ALIAS_TO_CANONICAL)


def requested_field_terms(value: str | None) -> list[str]:
    normalized = normalize_requested_field(value)
    if not normalized:
        return []
    raw_terms = [normalized, *NORMALIZED_REQUESTED_FIELD_ALIASES.get(normalized, [])]
    terms: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        cleaned = " ".join(str(term or "").replace("_", " ").split()).strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        terms.append(cleaned)
    return sorted(terms, key=len, reverse=True)
