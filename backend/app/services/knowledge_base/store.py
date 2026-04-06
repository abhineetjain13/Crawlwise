from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from app.services.config.field_mappings import CANONICAL_SCHEMAS, PROMPT_REGISTRY

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge_base" / "prompts"


@dataclass
class _KnowledgeBaseCache:
    canonical_schemas: dict[str, list[str]] = field(default_factory=lambda: deepcopy(CANONICAL_SCHEMAS))
    field_mappings: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    selector_defaults: dict[str, dict[str, list[dict]]] = field(default_factory=dict)
    prompt_registry: dict[str, dict] = field(default_factory=lambda: deepcopy(PROMPT_REGISTRY))
    prompt_files: dict[str, str] = field(default_factory=dict)


def _load_prompt_files() -> dict[str, str]:
    if not PROMPTS_DIR.exists():
        return {}
    prompt_files: dict[str, str] = {}
    for path in PROMPTS_DIR.rglob("*"):
        if path.is_file():
            prompt_files[path.relative_to(PROMPTS_DIR).as_posix()] = path.read_text(encoding="utf-8")
    return prompt_files


def _build_cache() -> _KnowledgeBaseCache:
    cache = _KnowledgeBaseCache()
    cache.prompt_files = _load_prompt_files()
    return cache


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
        _CACHE.canonical_schemas[surface] = merged
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
        _CACHE.field_mappings = next_mappings


def load_selector_defaults() -> dict[str, dict[str, list[dict]]]:
    return deepcopy(_CACHE.selector_defaults)


def get_selector_defaults(domain: str, field_name: str) -> list[dict]:
    domain_rows = _CACHE.selector_defaults.get(domain, {})
    return [dict(row) for row in domain_rows.get(field_name, [])]


async def save_selector_defaults(domain: str, field_name: str, values: list[dict]) -> None:
    async with _CACHE_LOCK:
        next_defaults = deepcopy(_CACHE.selector_defaults)
        domain_rows = next_defaults.setdefault(domain, {})
        normalized_rows = [row for row in (_normalize_selector_row(value) for value in values) if row]
        if normalized_rows:
            domain_rows[field_name] = normalized_rows
        else:
            domain_rows.pop(field_name, None)
        if not domain_rows:
            next_defaults.pop(domain, None)
        _CACHE.selector_defaults = next_defaults


async def save_domain_selector_defaults(domain: str, values_by_field: dict[str, list[dict]]) -> None:
    async with _CACHE_LOCK:
        next_defaults = deepcopy(_CACHE.selector_defaults)
        normalized_domain_rows: dict[str, list[dict]] = {}
        for field_name, values in values_by_field.items():
            normalized_rows = [row for row in (_normalize_selector_row(value) for value in values) if row]
            if normalized_rows:
                normalized_domain_rows[field_name] = normalized_rows
        if normalized_domain_rows:
            next_defaults[domain] = normalized_domain_rows
        else:
            next_defaults.pop(domain, None)
        _CACHE.selector_defaults = next_defaults


async def clear_selector_defaults() -> None:
    async with _CACHE_LOCK:
        _CACHE.selector_defaults = {}


def load_prompt_registry() -> dict[str, dict]:
    return deepcopy(_CACHE.prompt_registry)


def get_prompt_task(task_type: str) -> dict | None:
    task = _CACHE.prompt_registry.get(task_type)
    return deepcopy(task) if isinstance(task, dict) else None


def load_prompt_file(relative_path: str) -> str:
    return str(_CACHE.prompt_files.get(relative_path, ""))


async def reset_learned_state() -> None:
    async with _CACHE_LOCK:
        _CACHE.field_mappings = {}
        _CACHE.selector_defaults = {}


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
