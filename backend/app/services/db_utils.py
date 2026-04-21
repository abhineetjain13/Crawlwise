"""Database utility functions for handling common patterns."""

from __future__ import annotations

from collections.abc import Mapping


def escape_like_pattern(value: str) -> str:
    text = str(value or "")
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def mapping_or_empty(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}
