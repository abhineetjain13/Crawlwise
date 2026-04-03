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
for canonical, aliases in REQUESTED_FIELD_ALIASES.items():
    canonical_key = _normalize_key(canonical)
    if canonical_key:
        _ALIAS_TO_CANONICAL[canonical_key] = canonical_key
    for alias in aliases:
        alias_key = _normalize_key(alias)
        if alias_key and alias_key not in _ALIAS_TO_CANONICAL:
            _ALIAS_TO_CANONICAL[alias_key] = canonical_key or canonical


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
