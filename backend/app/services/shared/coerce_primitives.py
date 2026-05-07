from __future__ import annotations

__all__ = [
    "coerce_int",
    "object_dict",
    "object_list",
    "safe_int",
]


def object_list(value: object) -> list:
    return list(value) if isinstance(value, list) else []


def object_dict(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def safe_int(value: object, *, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return default


def coerce_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default

