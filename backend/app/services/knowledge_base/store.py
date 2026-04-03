# File-backed knowledge-base access.
from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge_base"
SCHEMA_FILE = BASE_DIR / "canonical_schemas.json"
MAPPING_FILE = BASE_DIR / "field_mappings.json"
SELECTOR_FILE = BASE_DIR / "selector_defaults.json"
PROMPT_FILE = BASE_DIR / "prompt_registry.json"
PROMPTS_DIR = BASE_DIR / "prompts"


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


def save_canonical_fields(surface: str, fields: list[str]) -> list[str]:
    schemas = load_canonical_schemas()
    existing = schemas.setdefault(surface, [])
    merged: list[str] = []
    seen: set[str] = set()
    for field in [*existing, *fields]:
        value = str(field or "").strip()
        if not value or value in seen:
            continue
        merged.append(value)
        seen.add(value)
    schemas[surface] = merged
    _write_json(SCHEMA_FILE, schemas)
    return merged


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
    raw = dict(_load_json(SELECTOR_FILE, {}))
    normalized: dict[str, dict[str, list[dict]]] = {}
    for domain, domain_rows in raw.items():
        if not isinstance(domain_rows, dict):
            continue
        normalized[domain] = {}
        for field_name, rows in domain_rows.items():
            if not isinstance(rows, list):
                continue
            normalized_rows = [_normalize_selector_row(row) for row in rows]
            normalized[domain][field_name] = [row for row in normalized_rows if row]
    return normalized


def get_selector_defaults(domain: str, field_name: str) -> list[dict]:
    domain_rows = load_selector_defaults().get(domain, {})
    return list(domain_rows.get(field_name, []))


def save_selector_defaults(domain: str, field_name: str, values: list[dict]) -> None:
    payload = load_selector_defaults()
    payload.setdefault(domain, {})[field_name] = [
        row for row in (_normalize_selector_row(value) for value in values)
        if row
    ]
    _write_json(SELECTOR_FILE, payload)


def load_prompt_registry() -> dict[str, dict]:
    return dict(_load_json(PROMPT_FILE, {}))


def get_prompt_task(task_type: str) -> dict | None:
    registry = load_prompt_registry()
    task = registry.get(task_type)
    return task if isinstance(task, dict) else None


def load_prompt_file(relative_path: str) -> str:
    path = PROMPTS_DIR / relative_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def reset_learned_state() -> None:
    _write_json(MAPPING_FILE, {})
    _write_json(SELECTOR_FILE, {})


def _normalize_selector_row(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    css_selector = str(value.get("css_selector") or "").strip() or None
    xpath = str(value.get("xpath") or "").strip() or None
    regex = str(value.get("regex") or "").strip() or None
    legacy_selector = str(value.get("selector") or "").strip()
    legacy_type = str(value.get("selector_type") or "").strip().lower()
    if legacy_selector:
        if legacy_type == "xpath" and not xpath:
            xpath = legacy_selector
        elif legacy_type == "regex" and not regex:
            regex = legacy_selector
        elif not css_selector:
            css_selector = legacy_selector
    if not any([css_selector, xpath, regex]):
        return None
    return {
        "xpath": xpath,
        "css_selector": css_selector,
        "regex": regex,
        "status": str(value.get("status") or "validated"),
        "confidence": value.get("confidence"),
        "sample_value": str(value.get("sample_value") or "").strip() or None,
        "source": str(value.get("source") or "knowledge_base"),
    }
