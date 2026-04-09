# Host memory for acquisition retry policy.
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings
from app.services.pipeline_config import STEALTH_MIN_TTL_HOURS, STEALTH_PREFER_TTL_HOURS

logger = logging.getLogger(__name__)


_STEALTH_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_PATH: Path | None = None
_LOCK = threading.Lock()
def host_key(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.netloc or parsed.path or "").lower().strip()


def host_prefers_stealth(url: str) -> bool:
    key = host_key(url)
    with _LOCK:
        record = _load().get(key)
    if record is None:
        return False
    _reason, expires_at = record
    return expires_at > time.time()


def remember_stealth_host(
    url: str, ttl_hours: int | None = None, reason: str = "blocked"
) -> None:
    ttl = ttl_hours if ttl_hours is not None else STEALTH_PREFER_TTL_HOURS
    ttl = max(STEALTH_MIN_TTL_HOURS, int(ttl))
    expires_at = time.time() + ttl * 3600
    with _LOCK:
        _load()[host_key(url)] = (reason, expires_at)
        _save()


def clear_stealth_host(url: str) -> None:
    key = host_key(url)
    with _LOCK:
        cache = _load()
        if key in cache:
            cache.pop(key, None)
            _save()


def reset_host_memory() -> None:
    with _LOCK:
        _STEALTH_CACHE.clear()
        global _CACHE_PATH
        path = _memory_path()
        _CACHE_PATH = path
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to remove host memory file at %s", path, exc_info=True)


def snapshot_host_memory() -> dict[str, dict[str, object]]:
    with _LOCK:
        return {
            key: {"reason": reason, "preferred_stealth_until": expires_at}
            for key, (reason, expires_at) in _load().items()
        }


def _memory_path() -> Path:
    return Path(settings.artifacts_dir) / "acquisition_memory" / "host_preferences.json"


def _load() -> dict[str, tuple[str, float]]:
    global _CACHE_PATH
    path = _memory_path()
    if _CACHE_PATH != path:
        _STEALTH_CACHE.clear()
        _CACHE_PATH = path
    if _STEALTH_CACHE:
        return _STEALTH_CACHE
    if not path.exists():
        return _STEALTH_CACHE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        logger.debug("Failed to parse host memory file at %s", path, exc_info=True)
        return _STEALTH_CACHE
    if not isinstance(payload, dict):
        return _STEALTH_CACHE
    now = time.time()
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        expires_at = _as_float(value.get("preferred_stealth_until"))
        if expires_at <= now:
            continue
        reason = str(value.get("reason") or "blocked").strip() or "blocked"
        _STEALTH_CACHE[key] = (reason, expires_at)
    return _STEALTH_CACHE


def _save() -> None:
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    payload = {
        key: {"reason": reason, "preferred_stealth_until": expires_at}
        for key, (reason, expires_at) in _STEALTH_CACHE.items()
        if expires_at > time.time()
    }
    try:
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        tmp_path.replace(path)
    except OSError:
        logger.debug("Failed to save host memory to %s", path, exc_info=True)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to clean up temp file %s", tmp_path, exc_info=True)


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
