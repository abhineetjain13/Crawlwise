from __future__ import annotations

import json
import re
import argparse
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

EXPORT_PROVENANCE_KEY = "_export_provenance"
EXPORT_PROVENANCE_GENERATOR = "app.services.config._export_data"


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
    _validate_export_provenance(path, payload)
    return {
        str(name): _decode_export_value(value)
        for name, value in payload.items()
        if str(name) != EXPORT_PROVENANCE_KEY
    }


def _validate_export_provenance(path: str, payload: dict[str, Any]) -> None:
    provenance = payload.get(EXPORT_PROVENANCE_KEY)
    if not isinstance(provenance, dict):
        raise ValueError(f"Export payload at {path} must define {EXPORT_PROVENANCE_KEY}")
    generator = str(provenance.get("generator") or "").strip()
    if generator != EXPORT_PROVENANCE_GENERATOR:
        raise ValueError(
            f"Export payload at {path} has unsupported generator {generator!r}"
        )


def validate_export_file(path: Path) -> None:
    load_export_data.cache_clear()
    load_export_data(str(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate static config export payload provenance."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="exports.json files to validate; defaults to app/services/config/*.exports.json",
    )
    args = parser.parse_args(argv)
    paths = args.paths or sorted(Path(__file__).parent.glob("*.exports.json"))
    for path in paths:
        try:
            validate_export_file(path)
        except ValueError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
