"""Database utility functions for handling common patterns."""

from __future__ import annotations


def escape_like_pattern(value: str) -> str:
    text = str(value or "")
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
