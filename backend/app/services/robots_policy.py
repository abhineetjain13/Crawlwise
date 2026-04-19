from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from cachetools import TTLCache

from app.core.config import settings
from app.services.pipeline.pipeline_config import PIPELINE_CONFIG

ROBOTS_ALLOWED = "allowed"
ROBOTS_DISALLOWED = "disallowed"
ROBOTS_MISSING = "missing"
ROBOTS_FETCH_FAILURE = "fetch_failure"
_ROBOTS_CACHE = TTLCache(
    maxsize=PIPELINE_CONFIG.robots_cache_size,
    ttl=PIPELINE_CONFIG.robots_cache_ttl,
)
_ROBOTS_CACHE_LOCK = RLock()
_ROBOTS_FETCH_ERRORS = (TimeoutError, URLError, OSError)


@dataclass(frozen=True, slots=True)
class RobotsPolicyResult:
    allowed: bool
    outcome: str
    robots_url: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _RobotsSnapshot:
    robots_url: str
    parser: RobotFileParser | None
    missing: bool = False
    error: str | None = None


def reset_robots_policy_cache() -> None:
    with _ROBOTS_CACHE_LOCK:
        _ROBOTS_CACHE.clear()


async def check_url_crawlability(
    url: str,
    *,
    user_agent: str = "*",
) -> RobotsPolicyResult:
    return await asyncio.to_thread(_check_url_crawlability_sync, url, user_agent)


def _check_url_crawlability_sync(url: str, user_agent: str) -> RobotsPolicyResult:
    snapshot = _load_robots_snapshot(_base_url(url))
    if snapshot.missing:
        return RobotsPolicyResult(
            allowed=True,
            outcome=ROBOTS_MISSING,
            robots_url=snapshot.robots_url,
        )
    if snapshot.error:
        return RobotsPolicyResult(
            allowed=True,
            outcome=ROBOTS_FETCH_FAILURE,
            robots_url=snapshot.robots_url,
            error=snapshot.error,
        )
    allowed = bool(snapshot.parser and snapshot.parser.can_fetch(user_agent, url))
    return RobotsPolicyResult(
        allowed=allowed,
        outcome=ROBOTS_ALLOWED if allowed else ROBOTS_DISALLOWED,
        robots_url=snapshot.robots_url,
    )


def _load_robots_snapshot(base_url: str) -> _RobotsSnapshot:
    with _ROBOTS_CACHE_LOCK:
        cached = _ROBOTS_CACHE.get(base_url)
    if cached is not None:
        return cached
    snapshot = _fetch_robots_snapshot(base_url)
    with _ROBOTS_CACHE_LOCK:
        _ROBOTS_CACHE[base_url] = snapshot
    return snapshot


def _fetch_robots_snapshot(base_url: str) -> _RobotsSnapshot:
    robots_url = f"{base_url}/robots.txt"
    request = _robots_request(robots_url)
    try:
        with urlopen(request, timeout=settings.http_timeout_seconds) as response:
            body = response.read().decode(_response_encoding(response), errors="replace")
    except HTTPError as exc:
        if exc.code in {404, 410}:
            return _RobotsSnapshot(robots_url=robots_url, parser=None, missing=True)
        if exc.code in {401, 403}:
            return _disallow_all_snapshot(robots_url)
        return _error_snapshot(robots_url, f"HTTP {exc.code}")
    except _ROBOTS_FETCH_ERRORS as exc:
        return _error_snapshot(robots_url, str(exc))

    return _parse_robots_snapshot(robots_url, body)


def _base_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL for robots policy: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _response_encoding(response) -> str:
    headers = getattr(response, "headers", None)
    if headers is not None:
        content_charset = headers.get_content_charset()
        if content_charset:
            return str(content_charset)
    return "utf-8"


def _robots_request(robots_url: str) -> Request:
    return Request(
        robots_url,
        headers={"User-Agent": PIPELINE_CONFIG.robots_fetch_user_agent},
    )


def _parse_robots_snapshot(robots_url: str, body: str) -> _RobotsSnapshot:
    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(body.splitlines())
    return _RobotsSnapshot(robots_url=robots_url, parser=parser)


def _disallow_all_snapshot(robots_url: str) -> _RobotsSnapshot:
    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(["User-agent: *", "Disallow: /"])
    return _RobotsSnapshot(robots_url=robots_url, parser=parser)


def _error_snapshot(robots_url: str, error: str) -> _RobotsSnapshot:
    return _RobotsSnapshot(
        robots_url=robots_url,
        parser=None,
        error=error,
    )
