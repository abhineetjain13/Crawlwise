from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from cachetools import TTLCache
import httpx

from app.core.config import settings
from app.services.config.runtime_settings import crawler_runtime_settings

ROBOTS_ALLOWED = "allowed"
ROBOTS_DISALLOWED = "disallowed"
ROBOTS_MISSING = "missing"
ROBOTS_FETCH_FAILURE = "fetch_failure"
_ROBOTS_CACHE: TTLCache[str, "_RobotsSnapshot"] = TTLCache(
    maxsize=crawler_runtime_settings.robots_cache_size,
    ttl=crawler_runtime_settings.robots_cache_ttl,
)
_ROBOTS_CACHE_LOCK: asyncio.Lock | None = None
_ROBOTS_INFLIGHT_FETCHES: dict[str, asyncio.Task["_RobotsSnapshot"]] | None = None
_ROBOTS_FETCH_TASKS: set[asyncio.Task["_RobotsSnapshot"]] | None = None


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


_INIT_LOCK = threading.Lock()

def _get_lock() -> asyncio.Lock:
    global _ROBOTS_CACHE_LOCK
    if _ROBOTS_CACHE_LOCK is None:
        with _INIT_LOCK:
            if _ROBOTS_CACHE_LOCK is None:
                _ROBOTS_CACHE_LOCK = asyncio.Lock()
    return _ROBOTS_CACHE_LOCK


def _get_inflight() -> dict[str, asyncio.Task["_RobotsSnapshot"]]:
    global _ROBOTS_INFLIGHT_FETCHES
    if _ROBOTS_INFLIGHT_FETCHES is None:
        with _INIT_LOCK:
            if _ROBOTS_INFLIGHT_FETCHES is None:
                _ROBOTS_INFLIGHT_FETCHES = {}
    return _ROBOTS_INFLIGHT_FETCHES


def _get_tracked_tasks() -> set[asyncio.Task["_RobotsSnapshot"]]:
    global _ROBOTS_FETCH_TASKS
    if _ROBOTS_FETCH_TASKS is None:
        with _INIT_LOCK:
            if _ROBOTS_FETCH_TASKS is None:
                _ROBOTS_FETCH_TASKS = set()
    return _ROBOTS_FETCH_TASKS


def _track_fetch_task(task: asyncio.Task["_RobotsSnapshot"]) -> asyncio.Task["_RobotsSnapshot"]:
    tracked = _get_tracked_tasks()
    tracked.add(task)
    task.add_done_callback(lambda finished: tracked.discard(finished))
    return task


async def reset_robots_policy_cache() -> None:
    async with _get_lock():
        inflight = _get_inflight()
        tasks = list(inflight.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        inflight.clear()
        _ROBOTS_CACHE.clear()


async def shutdown_robots_policy() -> None:
    tracked_tasks = list(_get_tracked_tasks())
    for task in tracked_tasks:
        task.cancel()
    if tracked_tasks:
        await asyncio.gather(*tracked_tasks, return_exceptions=True)
    _get_tracked_tasks().clear()
    await reset_robots_policy_cache()


async def check_url_crawlability(
    url: str,
    *,
    user_agent: str = "*",
) -> RobotsPolicyResult:
    snapshot = await _load_robots_snapshot(_base_url(url))
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


async def _load_robots_snapshot(base_url: str) -> _RobotsSnapshot:
    async with _get_lock():
        cached = _ROBOTS_CACHE.get(base_url)
        if cached is not None:
            return cached
        inflight = _get_inflight()
        fetch_task = inflight.get(base_url)
        if fetch_task is None:
            fetch_task = _track_fetch_task(
                asyncio.create_task(_fetch_robots_snapshot(base_url))
            )
            inflight[base_url] = fetch_task
    try:
        snapshot = await fetch_task
    finally:
        async with _get_lock():
            inflight = _get_inflight()
            if inflight.get(base_url) is fetch_task:
                inflight.pop(base_url, None)
    async with _get_lock():
        cached = _ROBOTS_CACHE.get(base_url)
        if cached is not None:
            return cached
        _ROBOTS_CACHE[base_url] = snapshot
        return snapshot


async def _fetch_robots_snapshot(base_url: str) -> _RobotsSnapshot:
    robots_url = f"{base_url}/robots.txt"
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": crawler_runtime_settings.robots_fetch_user_agent},
        ) as client:
            response = await client.get(robots_url)
    except httpx.RequestError as exc:
        return _error_snapshot(robots_url, str(exc))

    if response.status_code in {404, 410}:
        return _RobotsSnapshot(robots_url=robots_url, parser=None, missing=True)
    if response.status_code in {401, 403}:
        return _disallow_all_snapshot(robots_url)
    if response.status_code >= 400:
        return _error_snapshot(robots_url, f"HTTP {response.status_code}")
    return _parse_robots_snapshot(robots_url, response.text)


def _base_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL for robots policy: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


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
