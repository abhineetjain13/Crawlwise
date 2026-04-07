from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum


class CrawlStatus(StrEnum):
    """Enum representing the lifecycle and terminal states of a crawl job.
    Parameters:
        - None: This enum does not accept initialization parameters; it defines fixed string status values.
    Processing Logic:
        - Provides a standardized set of crawl states for tracking job progress.
        - Includes both active states and terminal failure states.
        - Uses string-backed values for easy serialization and comparison.
    """
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    KILLED = "killed"
    CLAIMED = "claimed"
    FAILED = "failed"
    PROXY_EXHAUSTED = "proxy_exhausted"


TERMINAL_STATUSES = {
    CrawlStatus.COMPLETED,
    CrawlStatus.KILLED,
    CrawlStatus.FAILED,
    CrawlStatus.PROXY_EXHAUSTED,
}
ACTIVE_STATUSES = {
    CrawlStatus.PENDING,
    CrawlStatus.CLAIMED,
    CrawlStatus.RUNNING,
    CrawlStatus.PAUSED,
}
WORKER_PICKUP_STATUSES = {
    CrawlStatus.PENDING,
}
CONTROL_REQUEST_KEY = "control_requested"
CONTROL_REQUEST_PAUSE = "pause"
CONTROL_REQUEST_KILL = "kill"

_LEGACY_STATUS_MAP = {
    "cancelled": CrawlStatus.KILLED,
    "degraded": CrawlStatus.FAILED,
}
_ALLOWED_TRANSITIONS = {
    CrawlStatus.PENDING: {CrawlStatus.CLAIMED, CrawlStatus.RUNNING, CrawlStatus.KILLED},
    CrawlStatus.CLAIMED: {CrawlStatus.RUNNING, CrawlStatus.KILLED, CrawlStatus.FAILED},
    CrawlStatus.RUNNING: {CrawlStatus.PAUSED, CrawlStatus.COMPLETED, CrawlStatus.KILLED, CrawlStatus.FAILED, CrawlStatus.PROXY_EXHAUSTED},
    CrawlStatus.PAUSED: {CrawlStatus.RUNNING, CrawlStatus.KILLED},
    CrawlStatus.COMPLETED: set(),
    CrawlStatus.KILLED: set(),
    CrawlStatus.FAILED: set(),
    CrawlStatus.PROXY_EXHAUSTED: set(),
}


def normalize_status(value: str | CrawlStatus) -> CrawlStatus:
    if isinstance(value, CrawlStatus):
        return value
    legacy = _LEGACY_STATUS_MAP.get(str(value).strip().lower())
    if legacy is not None:
        return legacy
    return CrawlStatus(str(value).strip().lower())


def transition_status(current: str | CrawlStatus, target: str | CrawlStatus) -> CrawlStatus:
    """Transition a crawl status from the current state to a valid target state.
    Parameters:
        - current (str | CrawlStatus): The current crawl status.
        - target (str | CrawlStatus): The desired target crawl status.
    Returns:
        - CrawlStatus: The normalized target status after validating the transition."""
    current_status = normalize_status(current)
    target_status = normalize_status(target)
    if current_status == target_status:
        return target_status
    if target_status not in _ALLOWED_TRANSITIONS[current_status]:
        raise ValueError(f"Invalid crawl status transition: {current_status} -> {target_status}")
    return target_status


def update_run_status(run, target: str | CrawlStatus) -> CrawlStatus:
    previous_status = str(run.status)
    next_status = transition_status(run.status, target)
    run.status = next_status.value
    if next_status in TERMINAL_STATUSES and (next_status.value != previous_status or run.completed_at is None):
        run.completed_at = datetime.now(UTC)
    return next_status


def get_control_request(run) -> str | None:
    result_summary = dict(run.result_summary or {})
    value = result_summary.get(CONTROL_REQUEST_KEY)
    return str(value).strip().lower() if value else None


def set_control_request(run, request: str | None) -> None:
    result_summary = dict(run.result_summary or {})
    if request:
        result_summary[CONTROL_REQUEST_KEY] = request
    else:
        result_summary.pop(CONTROL_REQUEST_KEY, None)
    run.result_summary = result_summary
