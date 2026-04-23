from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from pathlib import Path

from app.core.config import settings

def validate_cookie_policy_config() -> None:
    if settings.cookie_store_dir.exists() and not settings.cookie_store_dir.is_dir():
        raise ValueError(
            f"cookie_store_dir must be a directory: {settings.cookie_store_dir}"
        )
    settings.cookie_store_dir.mkdir(parents=True, exist_ok=True)
    if not settings.cookie_store_dir.is_dir():
        raise ValueError(
            f"cookie_store_dir must be a directory: {settings.cookie_store_dir}"
        )


_RUN_STORAGE_STATE_CACHE: dict[int, dict[str, object]] = {}
_RUN_STORAGE_STATE_LOCK = asyncio.Lock()
_COOKIE_FIELDS = (
    "name",
    "value",
    "domain",
    "path",
    "expires",
    "httpOnly",
    "secure",
    "sameSite",
    "url",
)


async def clear_cookie_store_cache() -> None:
    async with _RUN_STORAGE_STATE_LOCK:
        _RUN_STORAGE_STATE_CACHE.clear()


async def load_storage_state_for_run(run_id: int | None) -> dict[str, object] | None:
    normalized_run_id = _normalized_run_id(run_id)
    if normalized_run_id is None:
        return None
    validate_cookie_policy_config()
    async with _RUN_STORAGE_STATE_LOCK:
        state = _RUN_STORAGE_STATE_CACHE.get(normalized_run_id)
        if state is None:
            state = await asyncio.to_thread(
                _read_storage_state_file,
                _storage_state_path(normalized_run_id),
            )
            if state is not None:
                _RUN_STORAGE_STATE_CACHE[normalized_run_id] = state
    return _clone_storage_state(state)


async def persist_storage_state_for_run(
    run_id: int | None,
    storage_state: Mapping[str, object] | object,
) -> None:
    normalized_run_id = _normalized_run_id(run_id)
    if normalized_run_id is None or not isinstance(storage_state, Mapping):
        return
    validate_cookie_policy_config()
    normalized_state = _normalize_storage_state(storage_state)
    if not normalized_state["cookies"] and not normalized_state["origins"]:
        return
    async with _RUN_STORAGE_STATE_LOCK:
        _RUN_STORAGE_STATE_CACHE[normalized_run_id] = normalized_state
        await asyncio.to_thread(
            _write_storage_state_file,
            _storage_state_path(normalized_run_id),
            normalized_state,
        )


def _normalized_run_id(run_id: int | None) -> int | None:
    if run_id is None:
        return None
    try:
        return int(run_id)
    except (TypeError, ValueError):
        return None


def _storage_state_path(run_id: int) -> Path:
    return settings.cookie_store_dir / f"run_{run_id}.json"


def _read_storage_state_file(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _normalize_storage_state(payload)


def _write_storage_state_file(path: Path, storage_state: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(storage_state, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _normalize_storage_state(storage_state: Mapping[str, object]) -> dict[str, object]:
    return {
        "cookies": _normalize_cookies(storage_state.get("cookies")),
        "origins": _normalize_origins(storage_state.get("origins")),
    }


def _normalize_cookies(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    now = time.time()
    cookies: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        cookie: dict[str, object] = {}
        for field_name in _COOKIE_FIELDS:
            raw_value = item.get(field_name)
            if raw_value in (None, ""):
                continue
            cookie[field_name] = raw_value
        if not cookie.get("name") or not cookie.get("value"):
            continue
        expires = cookie.get("expires")
        if isinstance(expires, (int, float)) and float(expires) > 0 and float(expires) <= now:
            continue
        cookies.append(cookie)
    return cookies


def _normalize_origins(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    origins: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        origin = str(item.get("origin") or "").strip()
        if not origin:
            continue
        local_storage_rows: list[dict[str, str]] = []
        for entry in item.get("localStorage") or []:
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            local_storage_rows.append(
                {
                    "name": name,
                    "value": str(entry.get("value") or ""),
                }
            )
        origins.append({"origin": origin, "localStorage": local_storage_rows})
    return origins


def _clone_storage_state(
    storage_state: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if storage_state is None:
        return None
    return {
        "cookies": [dict(cookie) for cookie in list(storage_state.get("cookies") or [])],
        "origins": [
            {
                "origin": str(origin.get("origin") or ""),
                "localStorage": [
                    {
                        "name": str(entry.get("name") or ""),
                        "value": str(entry.get("value") or ""),
                    }
                    for entry in list(origin.get("localStorage") or [])
                    if isinstance(entry, Mapping)
                ],
            }
            for origin in list(storage_state.get("origins") or [])
            if isinstance(origin, Mapping)
        ],
    }
