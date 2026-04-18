from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


def _decode_export_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    value_type = value.get("__type__")
    if value_type == "list":
        return [_decode_export_value(item) for item in value.get("items", [])]
    if value_type == "tuple":
        return tuple(_decode_export_value(item) for item in value.get("items", []))
    if value_type == "set":
        return {_decode_export_value(item) for item in value.get("items", [])}
    if value_type == "frozenset":
        return frozenset(
            _decode_export_value(item) for item in value.get("items", [])
        )
    if value_type == "dict":
        return {
            _decode_export_value(item["key"]): _decode_export_value(item["value"])
            for item in value.get("items", [])
        }
    if value_type == "pattern":
        return re.compile(
            str(value.get("pattern", "")),
            int(value.get("flags", 0) or 0),
        )
    return {key: _decode_export_value(item) for key, item in value.items()}


@lru_cache(maxsize=None)
def load_export_data(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Export payload at {path} must be a JSON object")
    return {
        str(name): _decode_export_value(value)
        for name, value in payload.items()
    }
