# File-backed knowledge-base access.
from __future__ import annotations

import asyncio
import json
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge_base"
SCHEMA_FILE = BASE_DIR / "canonical_schemas.json"
MAPPING_FILE = BASE_DIR / "field_mappings.json"
SELECTOR_FILE = BASE_DIR / "selector_defaults.json"
PROMPT_FILE = BASE_DIR / "prompt_registry.json"
PROMPTS_DIR = BASE_DIR / "prompts"

logger = logging.getLogger(__name__)


@dataclass
class _KnowledgeBaseCache:
    canonical_schemas: dict[str, list[str]] = field(default_factory=dict)
    field_mappings: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    selector_defaults: dict[str, dict[str, list[dict]]] = field(default_factory=dict)
    prompt_registry: dict[str, dict] = field(default_factory=dict)
    prompt_files: dict[str, str] = field(default_factory=dict)


def _load_json(path: Path, fallback: dict | list) -> dict | list:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_prompt_files() -> dict[str, str]:
    if not PROMPTS_DIR.exists():
        return {}
    prompt_files: dict[str, str] = {}
    for path in PROMPTS_DIR.rglob("*"):
        if not path.is_file():
            continue
        prompt_files[path.relative_to(PROMPTS_DIR).as_posix()] = path.read_text(encoding="utf-8")
    return prompt_files


def load_selector_defaults_from_disk() -> dict[str, dict[str, list[dict]]]:
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


def _build_cache() -> _KnowledgeBaseCache:
    return _KnowledgeBaseCache(
        canonical_schemas=dict(_load_json(SCHEMA_FILE, {})),
        field_mappings=dict(_load_json(MAPPING_FILE, {})),
        selector_defaults=load_selector_defaults_from_disk(),
        prompt_registry=dict(_load_json(PROMPT_FILE, {})),
        prompt_files=_load_prompt_files(),
    )


async def _persist_json(path: Path, payload: dict | list) -> None:
    snapshot = deepcopy(payload)
    try:
        await asyncio.to_thread(_write_json, path, snapshot)
    except Exception:
        logger.exception("Failed to persist knowledge-base payload", extra={"path": str(path)})
        raise


def load_canonical_schemas() -> dict[str, list[str]]:
    return deepcopy(_CACHE.canonical_schemas)


def get_canonical_fields(surface: str) -> list[str]:
    return list(_CACHE.canonical_schemas.get(surface, []))


async def save_canonical_fields(surface: str, fields: list[str]) -> list[str]:
    async with _CACHE_LOCK:
        existing = list(_CACHE.canonical_schemas.get(surface, []))
        merged: list[str] = []
        seen: set[str] = set()
        for field in [*existing, *fields]:
            value = str(field or "").strip()
            if not value or value in seen:
                continue
            merged.append(value)
            seen.add(value)
        next_schemas = deepcopy(_CACHE.canonical_schemas)
        next_schemas[surface] = merged
        await _persist_json(SCHEMA_FILE, next_schemas)
        _CACHE.canonical_schemas = next_schemas
        return merged


def load_field_mappings() -> dict[str, dict[str, dict[str, str]]]:
    return deepcopy(_CACHE.field_mappings)


def get_domain_mapping(domain: str, surface: str) -> dict[str, str]:
    return dict(_CACHE.field_mappings.get(domain, {}).get(surface, {}))


async def save_domain_mapping(domain: str, surface: str, mapping: dict[str, str]) -> None:
    async with _CACHE_LOCK:
        next_mappings = deepcopy(_CACHE.field_mappings)
        domain_rows = next_mappings.setdefault(domain, {})
        current = domain_rows.setdefault(surface, {})
        current.update(mapping)
        await _persist_json(MAPPING_FILE, next_mappings)
        _CACHE.field_mappings = next_mappings


def load_selector_defaults() -> dict[str, dict[str, list[dict]]]:
    return deepcopy(_CACHE.selector_defaults)


def get_selector_defaults(domain: str, field_name: str) -> list[dict]:
    domain_rows = _CACHE.selector_defaults.get(domain, {})
    return [dict(row) for row in domain_rows.get(field_name, [])]


async def save_selector_defaults(domain: str, field_name: str, values: list[dict]) -> None:
    async with _CACHE_LOCK:
        next_defaults = deepcopy(_CACHE.selector_defaults)
        next_defaults.setdefault(domain, {})[field_name] = [
            row for row in (_normalize_selector_row(value) for value in values)
            if row
        ]
        await _persist_json(SELECTOR_FILE, next_defaults)
        _CACHE.selector_defaults = next_defaults


def load_prompt_registry() -> dict[str, dict]:
    return deepcopy(_CACHE.prompt_registry)


def get_prompt_task(task_type: str) -> dict | None:
    task = _CACHE.prompt_registry.get(task_type)
    return deepcopy(task) if isinstance(task, dict) else None


def load_prompt_file(relative_path: str) -> str:
    return str(_CACHE.prompt_files.get(relative_path, ""))


async def reset_learned_state() -> None:
    async with _CACHE_LOCK:
        empty_mappings: dict[str, dict[str, dict[str, str]]] = {}
        empty_defaults: dict[str, dict[str, list[dict]]] = {}
        await _persist_json(MAPPING_FILE, empty_mappings)
        await _persist_json(SELECTOR_FILE, empty_defaults)
        _CACHE.field_mappings = empty_mappings
        _CACHE.selector_defaults = empty_defaults


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
        "sample_value": str(value.get("sample_value") or "").strip() or None,
        "source": str(value.get("source") or "knowledge_base"),
    }


_CACHE = _build_cache()
_CACHE_LOCK = asyncio.Lock()
