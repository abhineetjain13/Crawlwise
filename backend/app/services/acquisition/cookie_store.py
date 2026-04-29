from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import urlparse

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.crawl import DomainCookieMemory
from app.services.config.block_signatures import BLOCK_SIGNATURES
from app.services.domain_utils import normalize_domain
from app.services.field_value_core import _object_list
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


_RUN_STORAGE_STATE_CACHE: dict[str, dict[str, object]] = {}
_RUN_STORAGE_STATE_LOCK = asyncio.Lock()
_STORAGE_STATE_META_KEY = "_crawler"
_STORAGE_STATE_BROWSER_ENGINE_KEY = "browser_engine"
_DEFAULT_STORAGE_STATE_ENGINE = "chromium"
_DOMAIN_STORAGE_SCOPE_SEPARATOR = "::"
_SUPPORTED_STORAGE_STATE_ENGINES = {
    "chromium",
    "patchright",
    "real_chrome",
}
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


async def load_storage_state_for_run(
    run_id: int | None,
    *,
    browser_engine: str | None = None,
) -> dict[str, object] | None:
    normalized_run_id = _normalized_run_id(run_id)
    if normalized_run_id is None:
        return None
    validate_cookie_policy_config()
    normalized_engine = _normalized_browser_engine(browser_engine)
    for path in _storage_state_candidate_paths(
        normalized_run_id,
        browser_engine=normalized_engine,
    ):
        cache_key = str(path)
        async with _RUN_STORAGE_STATE_LOCK:
            state = _RUN_STORAGE_STATE_CACHE.get(cache_key)
            if state is None:
                state = await asyncio.to_thread(
                    _read_storage_state_file,
                    path,
                )
                if state is not None:
                    _RUN_STORAGE_STATE_CACHE[cache_key] = state
        if state is None:
            continue
        if not _storage_state_matches_browser_engine(
            state,
            browser_engine=normalized_engine,
        ):
            continue
        return _clone_storage_state(_normalize_storage_state(state))
    return None


async def load_storage_state_for_domain(
    domain: str | None,
    *,
    session: AsyncSession | None = None,
    browser_engine: str | None = None,
) -> dict[str, object] | None:
    normalized_domain = normalize_domain(domain or "")
    if not normalized_domain:
        return None
    normalized_engine = _normalized_browser_engine(browser_engine)
    if session is None:
        async with SessionLocal() as owned_session:
            return await load_storage_state_for_domain(
                normalized_domain,
                session=owned_session,
                browser_engine=normalized_engine,
            )
    result = await session.execute(
            select(DomainCookieMemory)
            .where(
                DomainCookieMemory.domain.in_(
                    _domain_storage_lookup_keys(
                        normalized_domain,
                        browser_engine=normalized_engine,
                    )
                )
            )
            .order_by(DomainCookieMemory.updated_at.desc(), DomainCookieMemory.id.desc())
    )
    rows = list(result.scalars().all())
    for row in rows:
        raw_state = row.storage_state
        if not isinstance(raw_state, Mapping):
            continue
        if not _storage_state_matches_browser_engine(
            raw_state,
            browser_engine=normalized_engine,
        ):
            continue
        normalized_state = _normalize_storage_state(raw_state)
        if not _has_reusable_storage_state(normalized_state):
            continue
        return _clone_storage_state(normalized_state)
    return None


async def export_cookie_header_for_domain(
    url: str | None,
    *,
    browser_engine: str | None = None,
    session: AsyncSession | None = None,
) -> str | None:
    state = await load_storage_state_for_domain(
        url,
        browser_engine=browser_engine,
        session=session,
    )
    if not state:
        return None
    cookie_pairs = _http_cookie_pairs_for_url(url, state)
    if not cookie_pairs:
        return None
    return "; ".join(f"{name}={value}" for name, value in cookie_pairs)


async def persist_storage_state_for_run(
    run_id: int | None,
    storage_state: Mapping[str, object] | object,
    *,
    browser_engine: str | None = None,
) -> None:
    normalized_run_id = _normalized_run_id(run_id)
    if normalized_run_id is None or not isinstance(storage_state, Mapping):
        return
    validate_cookie_policy_config()
    normalized_engine = _normalized_browser_engine(browser_engine)
    normalized_state = _normalize_storage_state_payload(
        storage_state,
        browser_engine=normalized_engine,
    )
    if not _has_reusable_storage_state(normalized_state):
        return
    path = _storage_state_path(normalized_run_id, browser_engine=normalized_engine)
    async with _RUN_STORAGE_STATE_LOCK:
        _RUN_STORAGE_STATE_CACHE[str(path)] = normalized_state
        await asyncio.to_thread(
            _write_storage_state_file,
            path,
            normalized_state,
        )


async def persist_storage_state_for_domain(
    domain: str | None,
    storage_state: Mapping[str, object] | object,
    *,
    session: AsyncSession | None = None,
    browser_engine: str | None = None,
) -> bool:
    normalized_domain = normalize_domain(domain or "")
    if not normalized_domain or not isinstance(storage_state, Mapping):
        return False
    normalized_engine = _normalized_browser_engine(browser_engine)
    storage_key = _domain_storage_key(
        normalized_domain,
        browser_engine=normalized_engine,
    )
    normalized_state = _normalize_storage_state_payload(
        storage_state,
        browser_engine=normalized_engine,
    )
    if not _has_reusable_storage_state(normalized_state):
        return False
    fingerprint = _storage_state_fingerprint(
        normalized_state,
        browser_engine=normalized_engine,
    )
    if session is None:
        async with SessionLocal() as owned_session:
            result = await owned_session.execute(
                select(DomainCookieMemory)
                .where(DomainCookieMemory.domain == storage_key)
                .order_by(DomainCookieMemory.updated_at.desc(), DomainCookieMemory.id.desc())
            )
            rows = list(result.scalars().all())
            row = next(
                (
                    candidate
                    for candidate in rows
                ),
                None,
            )
            if row is not None and str(row.state_fingerprint or "") == fingerprint:
                return False
            if row is None:
                row = DomainCookieMemory(
                    domain=storage_key,
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
            .where(DomainCookieMemory.domain == storage_key)
            .order_by(DomainCookieMemory.updated_at.desc(), DomainCookieMemory.id.desc())
    )
    rows = list(result.scalars().all())
    row = next(
        (
            candidate
            for candidate in rows
        ),
        None,
    )
    if row is not None and str(row.state_fingerprint or "") == fingerprint:
        return False
    if row is None:
        row = DomainCookieMemory(
            domain=storage_key,
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
        statement = statement.where(
            DomainCookieMemory.domain.in_(
                _domain_storage_lookup_keys(normalized_domain)
            )
        )
    rows = list((await session.execute(statement)).scalars().all())
    payload: list[dict[str, object]] = []
    for row in rows:
        normalized_state = _normalize_storage_state(row.storage_state)
        cookie_rows = _object_list(normalized_state.get("cookies"))
        origin_rows = _object_list(normalized_state.get("origins"))
        payload.append(
            {
                "id": row.id,
                "domain": _domain_from_storage_key(row.domain),
                "browser_engine": _storage_row_browser_engine(row),
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


def _storage_state_fingerprint(
    storage_state: Mapping[str, object],
    *,
    browser_engine: str | None = None,
) -> str:
    payload = json.dumps(
        _normalize_storage_state_payload(
            storage_state,
            browser_engine=browser_engine
            or _storage_state_browser_engine(storage_state),
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _storage_state_path(
    run_id: int,
    *,
    browser_engine: str | None = None,
) -> Path:
    normalized_engine = _normalized_browser_engine(browser_engine)
    if normalized_engine:
        return settings.cookie_store_dir / f"run_{run_id}__{normalized_engine}.json"
    return settings.cookie_store_dir / f"run_{run_id}.json"


def _domain_storage_key(
    domain: str,
    *,
    browser_engine: str | None = None,
) -> str:
    normalized_domain = normalize_domain(domain or "")
    normalized_engine = _normalized_browser_engine(browser_engine)
    if not normalized_domain:
        return ""
    if normalized_engine and normalized_engine != _DEFAULT_STORAGE_STATE_ENGINE:
        return (
            f"{normalized_engine}{_DOMAIN_STORAGE_SCOPE_SEPARATOR}"
            f"{normalized_domain}"
        )
    return normalized_domain


def _domain_storage_lookup_keys(
    domain: str,
    *,
    browser_engine: str | None = None,
) -> tuple[str, ...]:
    normalized_domain = normalize_domain(domain or "")
    if not normalized_domain:
        return ()
    normalized_engine = _normalized_browser_engine(browser_engine)
    if normalized_engine == _DEFAULT_STORAGE_STATE_ENGINE:
        return (normalized_domain,)
    if normalized_engine:
        return (_domain_storage_key(normalized_domain, browser_engine=normalized_engine),)
    return (
        normalized_domain,
        *(
            _domain_storage_key(normalized_domain, browser_engine=engine)
            for engine in sorted(_SUPPORTED_STORAGE_STATE_ENGINES)
            if engine != _DEFAULT_STORAGE_STATE_ENGINE
        ),
    )


def _storage_state_candidate_paths(
    run_id: int,
    *,
    browser_engine: str | None = None,
) -> tuple[Path, ...]:
    normalized_engine = _normalized_browser_engine(browser_engine)
    if normalized_engine == _DEFAULT_STORAGE_STATE_ENGINE:
        return (
            _storage_state_path(run_id, browser_engine=normalized_engine),
            _storage_state_path(run_id),
        )
    if normalized_engine:
        return (_storage_state_path(run_id, browser_engine=normalized_engine),)
    return (_storage_state_path(run_id),)


def _read_storage_state_file(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _normalize_storage_state_payload(
        payload,
        browser_engine=_storage_state_browser_engine(payload),
    )


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


def _normalize_storage_state_payload(
    storage_state: Mapping[str, object],
    *,
    browser_engine: str | None = None,
) -> dict[str, object]:
    payload = _normalize_storage_state(storage_state)
    normalized_engine = _normalized_browser_engine(browser_engine)
    if normalized_engine is None:
        normalized_engine = _storage_state_browser_engine(storage_state)
    if normalized_engine is not None:
        payload[_STORAGE_STATE_META_KEY] = {
            _STORAGE_STATE_BROWSER_ENGINE_KEY: normalized_engine,
        }
    return payload


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
    cookies_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    rows = (
        list(value)
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping))
        else _object_list(value)
    )
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        cookie: dict[str, object] = {}
        for field_name in _COOKIE_FIELDS:
            raw_value = item.get(field_name)
            if raw_value in (None, ""):
                continue
            cookie[field_name] = _sanitize_storage_state_scalar(raw_value)
        if not cookie.get("name") or not cookie.get("value"):
            continue
        # Do not learn challenge-state cookies as reusable domain memory.
        if _cookie_is_challenge_state(cookie):
            continue
        expires = cookie.get("expires")
        if isinstance(expires, (int, float)) and float(expires) > 0 and float(expires) <= now:
            continue
        key = (
            str(cookie.get("name") or "").strip().lower(),
            str(cookie.get("domain") or cookie.get("url") or "").strip().lower(),
            str(cookie.get("path") or "/").strip() or "/",
        )
        cookies_by_key[key] = cookie
    return list(cookies_by_key.values())


def _normalized_browser_engine(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in _SUPPORTED_STORAGE_STATE_ENGINES:
        return normalized
    return None


def _storage_state_browser_engine(storage_state: Mapping[str, object] | object) -> str | None:
    if not isinstance(storage_state, Mapping):
        return None
    metadata = storage_state.get(_STORAGE_STATE_META_KEY)
    if not isinstance(metadata, Mapping):
        return None
    return _normalized_browser_engine(metadata.get(_STORAGE_STATE_BROWSER_ENGINE_KEY))


def _storage_state_matches_browser_engine(
    storage_state: Mapping[str, object] | object,
    *,
    browser_engine: str | None,
) -> bool:
    normalized_engine = _normalized_browser_engine(browser_engine)
    if normalized_engine is None:
        return True
    stored_engine = _storage_state_browser_engine(storage_state)
    if stored_engine is None:
        return normalized_engine == _DEFAULT_STORAGE_STATE_ENGINE
    return stored_engine == normalized_engine


def _domain_from_storage_key(value: object) -> str:
    normalized = str(value or "").strip()
    if _DOMAIN_STORAGE_SCOPE_SEPARATOR not in normalized:
        return normalized
    engine, domain = normalized.split(_DOMAIN_STORAGE_SCOPE_SEPARATOR, 1)
    if _normalized_browser_engine(engine) is None:
        return normalized
    return domain


def _storage_key_browser_engine(value: object) -> str | None:
    normalized = str(value or "").strip()
    if _DOMAIN_STORAGE_SCOPE_SEPARATOR not in normalized:
        return None
    engine, _domain = normalized.split(_DOMAIN_STORAGE_SCOPE_SEPARATOR, 1)
    return _normalized_browser_engine(engine)


def _storage_row_browser_engine(row: DomainCookieMemory) -> str:
    return (
        _storage_state_browser_engine(row.storage_state)
        or _storage_key_browser_engine(row.domain)
        or _DEFAULT_STORAGE_STATE_ENGINE
    )


def _normalize_origins(value: object) -> list[dict[str, object]]:
    origins: list[dict[str, object]] = []
    rows = (
        list(value)
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping))
        else _object_list(value)
    )
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        origin = str(_sanitize_storage_state_scalar(item.get("origin")) or "").strip()
        if not origin:
            continue
        local_storage_rows: list[dict[str, str]] = []
        raw_entries = item.get("localStorage")
        entries = (
            list(raw_entries)
            if isinstance(raw_entries, Iterable)
            and not isinstance(raw_entries, (str, bytes, bytearray, Mapping))
            else _object_list(raw_entries)
        )
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            name = str(_sanitize_storage_state_scalar(entry.get("name")) or "").strip()
            if not name:
                continue
            # Do not replay anti-bot localStorage across future runs.
            if _local_storage_entry_is_challenge_state(entry):
                continue
            local_storage_rows.append(
                {
                    "name": name,
                    "value": str(_sanitize_storage_state_scalar(entry.get("value")) or ""),
                }
            )
        origins.append({"origin": origin, "localStorage": local_storage_rows})
    return origins


def _sanitize_storage_state_scalar(value: object) -> object:
    if isinstance(value, str):
        return value.replace("\x00", "")
    return value


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


def _http_cookie_pairs_for_url(
    url: str | None,
    storage_state: Mapping[str, object],
) -> list[tuple[str, str]]:
    host = _cookie_target_host(url)
    path = _cookie_target_path(url)
    candidates: list[tuple[int, int, str, str]] = []
    for cookie in _object_list(storage_state.get("cookies")):
        if not isinstance(cookie, Mapping):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "").strip()
        if not name or value == "":
            continue
        domain = str(cookie.get("domain") or "").strip().lower()
        cookie_path = str(cookie.get("path") or "/").strip() or "/"
        if host and domain and not _cookie_domain_matches(host, domain):
            continue
        if path and not _cookie_path_matches(path, cookie_path):
            continue
        domain_score = len(domain.lstrip("."))
        path_score = len(cookie_path)
        candidates.append((domain_score, path_score, name, value))
    selected: dict[str, tuple[int, int, str, str]] = {}
    for domain_score, path_score, name, value in candidates:
        key = name.lower()
        existing = selected.get(key)
        if existing is None or (domain_score, path_score) >= (
            existing[0],
            existing[1],
        ):
            selected[key] = (domain_score, path_score, name, value)
    return [
        (name, value)
        for _key, (_domain_score, _path_score, name, value) in selected.items()
    ]


def _cookie_target_host(url: str | None) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        return ""
    parsed = urlparse(normalized if "://" in normalized else f"//{normalized}")
    return str(parsed.hostname or "").strip().lower()


def _cookie_target_path(url: str | None) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        return "/"
    parsed = urlparse(normalized if "://" in normalized else f"//{normalized}")
    return str(parsed.path or "/").strip() or "/"


def _cookie_domain_matches(host: str, domain: str) -> bool:
    normalized_domain = domain.lstrip(".")
    return host == normalized_domain or host.endswith(f".{normalized_domain}")


def _cookie_path_matches(request_path: str, cookie_path: str) -> bool:
    normalized_request_path = str(request_path or "/").strip() or "/"
    normalized_cookie_path = str(cookie_path or "/").strip() or "/"
    if normalized_request_path == normalized_cookie_path:
        return True
    if not normalized_request_path.startswith(normalized_cookie_path):
        return False
    return normalized_cookie_path.endswith("/") or normalized_request_path[
        len(normalized_cookie_path) : len(normalized_cookie_path) + 1
    ] == "/"
