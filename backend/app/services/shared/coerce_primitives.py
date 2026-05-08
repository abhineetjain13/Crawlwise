from __future__ import annotations

__all__ = [
    "coerce_int",
    "object_dict",
    "object_list",
    "safe_int",
    "string_list",
]

from collections.abc import Iterable


def object_list(value: object) -> list:
    return list(value) if isinstance(value, list) else []


def object_dict(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def string_list(
    value: object,
    *,
    accept_iterable: bool = False,
    strip: bool = False,
    none_as_empty: bool = False,
) -> list[str]:
    if accept_iterable:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
            return []
        items = value
    elif isinstance(value, list):
        items = value
    else:
        return []
    values = [str(item or "") if none_as_empty else str(item) for item in items]
    return [item.strip() for item in values] if strip else values


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
