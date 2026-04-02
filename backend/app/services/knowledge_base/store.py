# File-backed knowledge-base access.
from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge_base"
SCHEMA_FILE = BASE_DIR / "canonical_schemas.json"
MAPPING_FILE = BASE_DIR / "field_mappings.json"
SELECTOR_FILE = BASE_DIR / "selector_defaults.json"
PROMPT_FILE = BASE_DIR / "prompt_registry.json"


def _load_json(path: Path, fallback: dict | list) -> dict | list:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_canonical_schemas() -> dict[str, list[str]]:
    return dict(_load_json(SCHEMA_FILE, {}))


def get_canonical_fields(surface: str) -> list[str]:
    return load_canonical_schemas().get(surface, [])


def load_field_mappings() -> dict[str, dict[str, dict[str, str]]]:
    return dict(_load_json(MAPPING_FILE, {}))


def get_domain_mapping(domain: str, surface: str) -> dict[str, str]:
    mappings = load_field_mappings()
    return mappings.get(domain, {}).get(surface, {})


def save_domain_mapping(domain: str, surface: str, mapping: dict[str, str]) -> None:
    mappings = load_field_mappings()
    domain_rows = mappings.setdefault(domain, {})
    current = domain_rows.setdefault(surface, {})
    current.update(mapping)
    _write_json(MAPPING_FILE, mappings)


def load_selector_defaults() -> dict[str, dict[str, list[dict]]]:
    return dict(_load_json(SELECTOR_FILE, {}))


def get_selector_defaults(domain: str, field_name: str) -> list[dict]:
    domain_rows = load_selector_defaults().get(domain, {})
    return list(domain_rows.get(field_name, []))


def save_selector_defaults(domain: str, field_name: str, values: list[dict]) -> None:
    payload = load_selector_defaults()
    payload.setdefault(domain, {})[field_name] = values
    _write_json(SELECTOR_FILE, payload)
