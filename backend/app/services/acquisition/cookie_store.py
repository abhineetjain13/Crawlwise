from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Iterable, Mapping
from pathlib import Path

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.crawl import DomainCookieMemory
from app.services.config.block_signatures import BLOCK_SIGNATURES
from app.services.domain_utils import normalize_domain
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
_CHALLENGE_ELEMENT_CONFIG = BLOCK_SIGNATURES.get("challenge_elements")
if not isinstance(_CHALLENGE_ELEMENT_CONFIG, Mapping):
    _CHALLENGE_ELEMENT_CONFIG = {}
_STORAGE_STATE_SIGNATURES = _CHALLENGE_ELEMENT_CONFIG.get("storage_state")
if not isinstance(_STORAGE_STATE_SIGNATURES, Mapping):
    _STORAGE_STATE_SIGNATURES = {}
_CHALLENGE_COOKIE_NAME_PREFIXES = tuple(
    str(value or "").strip().lower()
    for value in _STORAGE_STATE_SIGNATURES.get("cookie_name_prefixes", [])
    if str(value or "").strip()
)
_CHALLENGE_COOKIE_NAME_EXACT = {
    str(value or "").strip().lower()
    for value in _STORAGE_STATE_SIGNATURES.get("cookie_name_exact", [])
    if str(value or "").strip()
}
_CHALLENGE_LOCAL_STORAGE_NAME_TOKENS = tuple(
    str(value or "").strip().lower()
    for value in _STORAGE_STATE_SIGNATURES.get("local_storage_name_tokens", [])
    if str(value or "").strip()
)
_CHALLENGE_COOKIE_VALUE_TOKENS = tuple(
    str(value or "").strip().lower()
    for value in _STORAGE_STATE_SIGNATURES.get("cookie_value_tokens", [])
    if str(value or "").strip()
)
_CHALLENGE_LOCAL_STORAGE_VALUE_TOKENS = tuple(
    str(value or "").strip().lower()
    for value in _STORAGE_STATE_SIGNATURES.get("local_storage_value_tokens", [])
    if str(value or "").strip()
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


async def load_storage_state_for_domain(
    domain: str | None,
    *,
    session: AsyncSession | None = None,
) -> dict[str, object] | None:
    normalized_domain = normalize_domain(domain or "")
    if not normalized_domain:
        return None
    if session is None:
        async with SessionLocal() as owned_session:
            return await load_storage_state_for_domain(
                normalized_domain,
                session=owned_session,
            )
    result = await session.execute(
            select(DomainCookieMemory)
            .where(DomainCookieMemory.domain == normalized_domain)
            .order_by(DomainCookieMemory.updated_at.desc(), DomainCookieMemory.id.desc())
            .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None or not isinstance(row.storage_state, Mapping):
        return None
    normalized_state = _normalize_storage_state(row.storage_state)
    if not _has_reusable_storage_state(normalized_state):
        return None
    return _clone_storage_state(normalized_state)


async def persist_storage_state_for_run(
    run_id: int | None,
    storage_state: Mapping[str, object] | object,
) -> None:
    normalized_run_id = _normalized_run_id(run_id)
    if normalized_run_id is None or not isinstance(storage_state, Mapping):
        return
    validate_cookie_policy_config()
    normalized_state = _normalize_storage_state(storage_state)
    if not _has_reusable_storage_state(normalized_state):
        return
    async with _RUN_STORAGE_STATE_LOCK:
        _RUN_STORAGE_STATE_CACHE[normalized_run_id] = normalized_state
        await asyncio.to_thread(
            _write_storage_state_file,
            _storage_state_path(normalized_run_id),
            normalized_state,
        )


async def persist_storage_state_for_domain(
    domain: str | None,
    storage_state: Mapping[str, object] | object,
    *,
    session: AsyncSession | None = None,
) -> bool:
    normalized_domain = normalize_domain(domain or "")
    if not normalized_domain or not isinstance(storage_state, Mapping):
        return False
    normalized_state = _normalize_storage_state(storage_state)
    if not _has_reusable_storage_state(normalized_state):
        return False
    fingerprint = _storage_state_fingerprint(normalized_state)
    if session is None:
        async with SessionLocal() as owned_session:
            result = await owned_session.execute(
                select(DomainCookieMemory)
                .where(DomainCookieMemory.domain == normalized_domain)
                .order_by(DomainCookieMemory.updated_at.desc(), DomainCookieMemory.id.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row is not None and str(row.state_fingerprint or "") == fingerprint:
                return False
            if row is None:
                row = DomainCookieMemory(
                    domain=normalized_domain,
                    storage_state=normalized_state,
                    state_fingerprint=fingerprint,
                )
                owned_session.add(row)
            else:
                row.storage_state = normalized_state
                row.state_fingerprint = fingerprint
            await owned_session.commit()
            return True
    result = await session.execute(
            select(DomainCookieMemory)
            .where(DomainCookieMemory.domain == normalized_domain)
            .order_by(DomainCookieMemory.updated_at.desc(), DomainCookieMemory.id.desc())
            .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is not None and str(row.state_fingerprint or "") == fingerprint:
        return False
    if row is None:
        row = DomainCookieMemory(
            domain=normalized_domain,
            storage_state=normalized_state,
            state_fingerprint=fingerprint,
        )
        session.add(row)
    else:
        row.storage_state = normalized_state
        row.state_fingerprint = fingerprint
    await session.flush()
    return True


async def list_domain_cookie_memory(
    domain: str | None = None,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, object]]:
    normalized_domain = normalize_domain(domain or "") if domain else ""
    if session is None:
        async with SessionLocal() as owned_session:
            return await list_domain_cookie_memory(
                domain,
                session=owned_session,
            )
    statement = select(DomainCookieMemory).order_by(
            DomainCookieMemory.domain.asc(),
            DomainCookieMemory.updated_at.desc(),
            DomainCookieMemory.id.desc(),
    )
    if normalized_domain:
        statement = statement.where(DomainCookieMemory.domain == normalized_domain)
    rows = list((await session.execute(statement)).scalars().all())
    payload: list[dict[str, object]] = []
    for row in rows:
        normalized_state = _normalize_storage_state(row.storage_state)
        cookie_rows = _object_list(normalized_state.get("cookies"))
        origin_rows = _object_list(normalized_state.get("origins"))
        payload.append(
            {
                "id": row.id,
                "domain": row.domain,
                "cookie_count": len(cookie_rows),
                "origin_count": len(origin_rows),
                "updated_at": row.updated_at,
            }
        )
    return payload


def _normalized_run_id(run_id: int | None) -> int | None:
    if run_id is None:
        return None
    try:
        return int(run_id)
    except (TypeError, ValueError):
        return None


def _storage_state_fingerprint(storage_state: Mapping[str, object]) -> str:
    payload = json.dumps(
        _normalize_storage_state(storage_state),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def _object_list(value: object) -> list[object]:
    if value is None or isinstance(value, (str, bytes, bytearray, Mapping)):
        return []
    if not isinstance(value, Iterable):
        return []
    return list(value)


def _has_reusable_storage_state(storage_state: Mapping[str, object]) -> bool:
    if _object_list(storage_state.get("cookies")):
        return True
    for origin in _object_list(storage_state.get("origins")):
        if not isinstance(origin, Mapping):
            continue
        if _object_list(origin.get("localStorage")):
            return True
    return False


def _normalize_cookies(value: object) -> list[dict[str, object]]:
    now = time.time()
    cookies: list[dict[str, object]] = []
    for item in _object_list(value):
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
        # Do not learn challenge-state cookies as reusable domain memory.
        if _cookie_is_challenge_state(cookie):
            continue
        expires = cookie.get("expires")
        if isinstance(expires, (int, float)) and float(expires) > 0 and float(expires) <= now:
            continue
        cookies.append(cookie)
    return cookies


def _normalize_origins(value: object) -> list[dict[str, object]]:
    origins: list[dict[str, object]] = []
    for item in _object_list(value):
        if not isinstance(item, Mapping):
            continue
        origin = str(item.get("origin") or "").strip()
        if not origin:
            continue
        local_storage_rows: list[dict[str, str]] = []
        for entry in _object_list(item.get("localStorage")):
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            # Do not replay anti-bot localStorage across future runs.
            if _local_storage_entry_is_challenge_state(entry):
                continue
            local_storage_rows.append(
                {
                    "name": name,
                    "value": str(entry.get("value") or ""),
                }
            )
        origins.append({"origin": origin, "localStorage": local_storage_rows})
    return origins


def _cookie_name_is_challenge_state(value: object) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    if lowered in _CHALLENGE_COOKIE_NAME_EXACT:
        return True
    return any(lowered.startswith(prefix) for prefix in _CHALLENGE_COOKIE_NAME_PREFIXES)


def _cookie_is_challenge_state(cookie: Mapping[str, object]) -> bool:
    if _cookie_name_is_challenge_state(cookie.get("name")):
        return True
    value = str(cookie.get("value") or "").strip().lower()
    if not value:
        return False
    return any(token in value for token in _CHALLENGE_COOKIE_VALUE_TOKENS)


def _local_storage_name_is_challenge_state(value: object) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in _CHALLENGE_LOCAL_STORAGE_NAME_TOKENS)


def _local_storage_entry_is_challenge_state(entry: Mapping[str, object]) -> bool:
    if _local_storage_name_is_challenge_state(entry.get("name")):
        return True
    value = str(entry.get("value") or "").strip().lower()
    if not value:
        return False
    return any(token in value for token in _CHALLENGE_LOCAL_STORAGE_VALUE_TOKENS)


def _clone_storage_state(
    storage_state: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if storage_state is None:
        return None
    cookies = _object_list(storage_state.get("cookies"))
    origins = _object_list(storage_state.get("origins"))
    return {
        "cookies": [dict(cookie) for cookie in cookies if isinstance(cookie, Mapping)],
        "origins": [
            {
                "origin": str(origin.get("origin") or ""),
                "localStorage": [
                    {
                        "name": str(entry.get("name") or ""),
                        "value": str(entry.get("value") or ""),
                    }
                    for entry in _object_list(origin.get("localStorage"))
                    if isinstance(entry, Mapping)
                ],
            }
            for origin in origins
            if isinstance(origin, Mapping)
        ],
    }
