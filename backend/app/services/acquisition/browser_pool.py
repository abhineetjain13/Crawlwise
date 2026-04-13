from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psutil
from playwright.async_api import Error as PlaywrightError

logger = logging.getLogger(__name__)

_BROWSER_POOL_MAX_SIZE = 6
_BROWSER_POOL_IDLE_TTL_SECONDS = 300
_BROWSER_POOL_HEALTHCHECK_INTERVAL_SECONDS = 60
_BROWSER_POOL_MAX_CONTEXTS_PER_BROWSER = 4
_BROWSER_PROCESS_NAME_TOKENS = ("chrom", "firefox", "webkit")
_BROWSER_PROCESS_REGISTRY_DIR = (
    Path(tempfile.gettempdir()) / "pre-poc-ai-crawler-browser-processes"
)


@dataclass
class _PooledBrowser:
    browser: object
    last_used_monotonic: float
    process_records: tuple[str, ...] = ()
    active_contexts: int = 0


@dataclass(frozen=True)
class _BrowserProcessRecord:
    record_id: str
    owner_pid: int
    owner_create_time: float
    browser_pid: int
    browser_create_time: float


class BrowserPool:
    """Structured browser pool with LRU eviction, health probing, and context limits."""

    def __init__(self, *, pid: int) -> None:
        self.pid = pid
        self._pool: dict[str, _PooledBrowser] = {}
        self._lock = asyncio.Lock()
        self._task_lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    @property
    def pool(self) -> dict[str, _PooledBrowser]:
        return self._pool

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    @property
    def task_lock(self) -> asyncio.Lock:
        return self._task_lock

    @property
    def cleanup_task(self) -> asyncio.Task | None:
        return self._cleanup_task

    @cleanup_task.setter
    def cleanup_task(self, value: asyncio.Task | None) -> None:
        self._cleanup_task = value

    async def context_acquired(self, key: str) -> None:
        async with self._lock:
            entry = self._pool.get(key)
            if entry is not None:
                entry.active_contexts += 1

    async def context_released(self, key: str) -> None:
        async with self._lock:
            entry = self._pool.get(key)
            if entry is not None:
                entry.active_contexts = max(0, entry.active_contexts - 1)

    async def can_open_context(self, key: str) -> bool:
        async with self._lock:
            entry = self._pool.get(key)
            if entry is None:
                return True
            return (
                entry.active_contexts < _BROWSER_POOL_MAX_CONTEXTS_PER_BROWSER
            )

    def snapshot(self) -> dict[str, object]:
        return {
            "size": len(self._pool),
            "max_size": _BROWSER_POOL_MAX_SIZE,
            "max_contexts_per_browser": _BROWSER_POOL_MAX_CONTEXTS_PER_BROWSER,
            "entries": {
                key: {
                    "active_contexts": entry.active_contexts,
                    "connected": _browser_is_connected(entry.browser),
                    "idle_seconds": round(
                        time.monotonic() - entry.last_used_monotonic, 1
                    ),
                }
                for key, entry in self._pool.items()
            },
        }


_BROWSER_POOL_STATE = BrowserPool(pid=os.getpid())


def _browser_pool_state() -> BrowserPool:
    global _BROWSER_POOL_STATE
    pid = os.getpid()
    if _BROWSER_POOL_STATE.pid != pid:
        _BROWSER_POOL_STATE = BrowserPool(pid=pid)
    return _BROWSER_POOL_STATE


def _browser_pool_key(launch_profile: dict[str, str | None], proxy: str | None) -> str:
    browser_type = str(launch_profile.get("browser_type") or "chromium").strip()
    channel = str(launch_profile.get("channel") or "").strip() or "default"
    proxy_key = str(proxy or "").strip() or "direct"
    return f"{browser_type}|{channel}|{proxy_key}"


def _browser_is_connected(browser: object) -> bool:
    checker = getattr(browser, "is_connected", None)
    if not callable(checker):
        return True
    try:
        return bool(checker())
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        return False


async def _close_browser_safe(browser: object) -> None:
    try:
        await browser.close()
    except PlaywrightError:
        logger.debug("Failed to close pooled browser", exc_info=True)
    except (RuntimeError, TypeError, ValueError, AttributeError, OSError):
        logger.debug("Unexpected pooled browser close failure", exc_info=True)


def _is_browser_process_name(name: str) -> bool:
    normalized = str(name or "").strip().lower()
    return any(token in normalized for token in _BROWSER_PROCESS_NAME_TOKENS)


def _safe_process_create_time(process: psutil.Process) -> float | None:
    try:
        return float(process.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return None


def _process_matches_create_time(
    pid: int,
    expected_create_time: float,
) -> psutil.Process | None:
    try:
        process = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return None
    create_time = _safe_process_create_time(process)
    if create_time is None:
        return None
    if abs(create_time - float(expected_create_time)) > 1e-6:
        return None
    return process


def _browser_process_registry_dir() -> Path:
    _BROWSER_PROCESS_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    return _BROWSER_PROCESS_REGISTRY_DIR


def _browser_process_record_path(record_id: str) -> Path:
    return _browser_process_registry_dir() / f"{record_id}.json"


def _iter_browser_process_record_paths() -> list[Path]:
    try:
        return sorted(_browser_process_registry_dir().glob("*.json"))
    except OSError:
        return []


def _read_browser_process_record(path: Path) -> _BrowserProcessRecord | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    try:
        return _BrowserProcessRecord(
            record_id=str(payload["record_id"]),
            owner_pid=int(payload["owner_pid"]),
            owner_create_time=float(payload["owner_create_time"]),
            browser_pid=int(payload["browser_pid"]),
            browser_create_time=float(payload["browser_create_time"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _write_browser_process_record(record: _BrowserProcessRecord) -> None:
    path = _browser_process_record_path(record.record_id)
    tmp_path = path.with_suffix(".tmp")
    payload = {
        "record_id": record.record_id,
        "owner_pid": record.owner_pid,
        "owner_create_time": record.owner_create_time,
        "browser_pid": record.browser_pid,
        "browser_create_time": record.browser_create_time,
    }
    try:
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        logger.debug(
            "Failed to persist browser process record %s",
            record.record_id,
            exc_info=True,
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _delete_browser_process_record(record_id: str) -> None:
    try:
        _browser_process_record_path(record_id).unlink(missing_ok=True)
    except OSError:
        logger.debug(
            "Failed to remove browser process record %s",
            record_id,
            exc_info=True,
        )


def _collect_browser_descendant_roots(
    parent_pid: int,
    *,
    candidate_pids: set[int] | None = None,
) -> dict[int, tuple[psutil.Process, float]]:
    try:
        current = psutil.Process(parent_pid)
        descendants = current.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return {}

    browser_processes: dict[int, tuple[psutil.Process, float]] = {}
    for process in descendants:
        try:
            if not _is_browser_process_name(process.name()):
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue
        create_time = _safe_process_create_time(process)
        if create_time is None:
            continue
        if candidate_pids is not None and process.pid not in candidate_pids:
            continue
        browser_processes[process.pid] = (process, create_time)

    roots: dict[int, tuple[psutil.Process, float]] = {}
    for pid, (process, create_time) in browser_processes.items():
        ancestor: psutil.Process | None
        try:
            ancestor = process.parent()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            ancestor = None
        while ancestor is not None:
            if ancestor.pid in browser_processes:
                break
            try:
                ancestor = ancestor.parent()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
                ancestor = None
        if ancestor is None:
            roots[pid] = (process, create_time)
    return roots


def _browser_descendant_pids(parent_pid: int) -> set[int]:
    return set(_collect_browser_descendant_roots(parent_pid))


def _prune_browser_process_registry() -> None:
    for path in _iter_browser_process_record_paths():
        record = _read_browser_process_record(path)
        if record is None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        browser_process = _process_matches_create_time(
            record.browser_pid,
            record.browser_create_time,
        )
        if browser_process is None:
            _delete_browser_process_record(record.record_id)
            continue
        try:
            owner_process = _process_matches_create_time(
                record.owner_pid,
                record.owner_create_time,
            )
            if owner_process is None and not _is_browser_process_name(browser_process.name()):
                _delete_browser_process_record(record.record_id)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            _delete_browser_process_record(record.record_id)


def _register_browser_processes_for_worker(
    owner_pid: int,
    *,
    candidate_pids: set[int] | None = None,
) -> tuple[str, ...]:
    try:
        owner = psutil.Process(owner_pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return ()
    owner_create_time = _safe_process_create_time(owner)
    if owner_create_time is None:
        return ()

    record_ids: list[str] = []
    for process, browser_create_time in _collect_browser_descendant_roots(
        owner_pid,
        candidate_pids=candidate_pids,
    ).values():
        record = _BrowserProcessRecord(
            record_id=f"{owner_pid}-{process.pid}-{uuid4().hex}",
            owner_pid=owner_pid,
            owner_create_time=owner_create_time,
            browser_pid=process.pid,
            browser_create_time=browser_create_time,
        )
        _write_browser_process_record(record)
        record_ids.append(record.record_id)
    _prune_browser_process_registry()
    return tuple(record_ids)


def _kill_browser_process_tree(process: psutil.Process) -> int:
    killed = 0
    try:
        descendants = process.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        descendants = []
    for child in reversed(descendants):
        try:
            child.kill()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            pass
    try:
        process.kill()
        killed += 1
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        pass
    return killed


async def _evict_idle_or_dead_browsers() -> None:
    state = _browser_pool_state()
    now = time.monotonic()
    to_close: list[object] = []
    async with state.lock:
        stale_keys = [
            key
            for key, entry in state.pool.items()
            if (now - entry.last_used_monotonic) >= _BROWSER_POOL_IDLE_TTL_SECONDS
            or not _browser_is_connected(entry.browser)
        ]
        for key in stale_keys:
            entry = state.pool.pop(key, None)
            if entry is not None:
                to_close.append(entry.browser)
    for browser in to_close:
        await _close_browser_safe(browser)


async def _shutdown_browser_pool() -> None:
    state = _browser_pool_state()
    to_close: list[object] = []
    async with state.lock:
        for entry in state.pool.values():
            to_close.append(entry.browser)
        state.pool.clear()
    for browser in to_close:
        await _close_browser_safe(browser)


async def _browser_pool_healthcheck_loop() -> None:
    while True:
        await asyncio.sleep(_BROWSER_POOL_HEALTHCHECK_INTERVAL_SECONDS)
        try:
            await _evict_idle_or_dead_browsers()
        except Exception:
            logger.warning("Browser pool healthcheck iteration failed", exc_info=True)


def _browser_pool_healthcheck_done(task: asyncio.Task) -> None:
    state = _browser_pool_state()
    if state.cleanup_task is task:
        state.cleanup_task = None

    if task.cancelled():
        return

    exited_unexpectedly = False
    exc: BaseException | None = None
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    except BaseException as callback_exc:
        exited_unexpectedly = True
        exc = callback_exc
    else:
        exited_unexpectedly = exc is not None or not task.cancelled()

    if not exited_unexpectedly:
        return

    if exc is None:
        logger.error("Browser pool healthcheck task exited unexpectedly without an exception")
    else:
        logger.error(
            "Browser pool healthcheck task crashed; scheduling restart",
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    try:
        loop = task.get_loop()
    except RuntimeError:
        return
    if loop.is_closed():
        return

    async def _restart_if_needed_async() -> None:
        current_state = _browser_pool_state()
        async with current_state.task_lock:
            if current_state.cleanup_task is not None:
                return
            current_state.cleanup_task = loop.create_task(
                _browser_pool_healthcheck_loop(),
                name="browser-pool-healthcheck",
            )
            current_state.cleanup_task.add_done_callback(
                _browser_pool_healthcheck_done
            )
            logger.warning("Restarted browser pool healthcheck task after unexpected exit")

    loop.create_task(_restart_if_needed_async())


def _start_browser_pool_maintenance_task(
    loop: asyncio.AbstractEventLoop,
    state: BrowserPool,
) -> asyncio.Task:
    task = loop.create_task(
        _browser_pool_healthcheck_loop(),
        name="browser-pool-healthcheck",
    )
    task.add_done_callback(_browser_pool_healthcheck_done)
    state.cleanup_task = task
    return task


async def reset_browser_pool_state() -> None:
    state = _browser_pool_state()
    async with state.task_lock:
        task = state.cleanup_task
        state.cleanup_task = None
    await _shutdown_browser_pool()
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _ensure_browser_pool_maintenance_task() -> None:
    state = _browser_pool_state()
    async with state.task_lock:
        loop = asyncio.get_running_loop()
        if state.cleanup_task is None or state.cleanup_task.done():
            _start_browser_pool_maintenance_task(loop, state)


async def _acquire_browser(
    *,
    browser_type,
    launch_kwargs: dict[str, object],
    browser_pool_key: str,
    force_new: bool = False,
):
    await _ensure_browser_pool_maintenance_task()
    await _evict_idle_or_dead_browsers()
    state = _browser_pool_state()
    to_close: list[object] = []
    browser = None
    now = time.monotonic()
    known_browser_pids = _browser_descendant_pids(os.getpid())
    async with state.lock:
        if not force_new:
            pooled = state.pool.get(browser_pool_key)
            if pooled is not None and _browser_is_connected(pooled.browser):
                pooled.last_used_monotonic = now
                return pooled.browser, True
            if pooled is not None:
                to_close.append(pooled.browser)
                state.pool.pop(browser_pool_key, None)
    browser = await browser_type.launch(**launch_kwargs)
    current_browser_pids = _browser_descendant_pids(os.getpid())
    process_records = _register_browser_processes_for_worker(
        os.getpid(),
        candidate_pids=current_browser_pids - known_browser_pids,
    )
    async with state.lock:
        now = time.monotonic()
        pooled = state.pool.get(browser_pool_key)
        if (
            not force_new
            and pooled is not None
            and _browser_is_connected(pooled.browser)
        ):
            pooled.last_used_monotonic = now
            to_close.append(browser)
            browser = pooled.browser
            reused = True
        else:
            state.pool[browser_pool_key] = _PooledBrowser(
                browser=browser,
                last_used_monotonic=now,
                process_records=process_records,
            )
            reused = False
            if len(state.pool) > _BROWSER_POOL_MAX_SIZE:
                lru_key = min(
                    state.pool,
                    key=lambda key: state.pool[key].last_used_monotonic,
                )
                if lru_key != browser_pool_key:
                    entry = state.pool.pop(lru_key, None)
                    if entry is not None:
                        to_close.append(entry.browser)
    for stale_browser in to_close:
        await _close_browser_safe(stale_browser)
    return browser, reused


async def _evict_browser(browser_pool_key: str, browser) -> None:
    state = _browser_pool_state()
    async with state.lock:
        pooled = state.pool.get(browser_pool_key)
        if pooled is not None and pooled.browser is browser:
            state.pool.pop(browser_pool_key, None)
    await _close_browser_safe(browser)


def browser_pool_snapshot() -> dict[str, object]:
    return _browser_pool_state().snapshot()


def _kill_orphaned_browser_processes() -> None:
    current_pid = os.getpid()
    killed = 0
    for path in _iter_browser_process_record_paths():
        record = _read_browser_process_record(path)
        if record is None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        owner_process = _process_matches_create_time(
            record.owner_pid,
            record.owner_create_time,
        )
        if owner_process is not None and owner_process.pid == current_pid:
            continue
        if owner_process is not None:
            continue
        browser_process = _process_matches_create_time(
            record.browser_pid,
            record.browser_create_time,
        )
        if browser_process is None:
            _delete_browser_process_record(record.record_id)
            continue
        try:
            if not _is_browser_process_name(browser_process.name()):
                _delete_browser_process_record(record.record_id)
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            _delete_browser_process_record(record.record_id)
            continue
        killed += _kill_browser_process_tree(browser_process)
        _delete_browser_process_record(record.record_id)
    _prune_browser_process_registry()
    if killed:
        logger.info(
            "Killed %d orphaned browser process(es) for PID %d", killed, current_pid
        )


async def shutdown_browser_pool() -> None:
    await _shutdown_browser_pool()


def prepare_browser_pool_for_worker_process() -> None:
    global _BROWSER_POOL_STATE
    _prune_browser_process_registry()
    _kill_orphaned_browser_processes()
    _BROWSER_POOL_STATE = BrowserPool(pid=os.getpid())


def shutdown_browser_pool_sync() -> None:
    global _BROWSER_POOL_STATE
    try:
        asyncio.run(_shutdown_browser_pool())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_shutdown_browser_pool())
        except RuntimeError:
            logger.warning(
                "Async shutdown unavailable; force-killing browser child processes"
            )
            _kill_orphaned_browser_processes()
            _BROWSER_POOL_STATE = BrowserPool(pid=os.getpid())
        finally:
            loop.close()
