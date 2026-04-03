# Host memory for acquisition retry policy.
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings
from app.services.pipeline_config import STEALTH_PREFER_TTL_HOURS

logger = logging.getLogger(__name__)


_CACHE: dict[str, dict[str, object]] = {}
_CACHE_PATH: Path | None = None


def host_key(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.netloc or parsed.path or "").lower().strip()


def host_prefers_stealth(url: str) -> bool:
    record = _load().get(host_key(url))
    if not record:
        return False
    preferred_until = _as_float(record.get("preferred_stealth_until"))
    return preferred_until > time.time()


def remember_stealth_host(url: str, ttl_hours: int | None = None, reason: str = "blocked") -> None:
    ttl = ttl_hours if ttl_hours is not None else STEALTH_PREFER_TTL_HOURS
    now = time.time()
    _load()[host_key(url)] = {
        "preferred_stealth_until": now + max(0, ttl) * 3600,
        "reason": reason,
        "updated_at": now,
    }
    _save()


def clear_stealth_host(url: str) -> None:
    key = host_key(url)
    if key in _load():
        _CACHE.pop(key, None)
        _save()


def reset_host_memory() -> None:
    _CACHE.clear()
    global _CACHE_PATH
    _CACHE_PATH = None
    path = _memory_path()
    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.debug("Failed to remove host memory file at %s", path, exc_info=True)


def snapshot_host_memory() -> dict[str, dict[str, object]]:
    return {key: dict(value) for key, value in _load().items()}


def _memory_path() -> Path:
    return Path(settings.artifacts_dir) / "acquisition_memory" / "host_preferences.json"


def _load() -> dict[str, dict[str, object]]:
    global _CACHE_PATH
    path = _memory_path()
    if _CACHE_PATH != path:
        _CACHE.clear()
        _CACHE_PATH = path
    if _CACHE:
        return _CACHE
    if not path.exists():
        return _CACHE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Failed to parse host memory file at %s", path, exc_info=True)
        return _CACHE
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, dict):
                _CACHE[key] = value
    return _CACHE


def _save() -> None:
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(_CACHE, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        logger.debug("Failed to save host memory to %s", path, exc_info=True)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            logger.debug("Failed to clean up temp file %s", tmp_path, exc_info=True)


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
