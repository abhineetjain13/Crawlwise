from __future__ import annotations

from datetime import UTC, datetime

from app.models.crawl_domain import (
    ACTIVE_STATUSES,
    CONTROL_REQUEST_KEY,
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    CrawlStatus,
    TERMINAL_STATUSES,
    normalize_status,
    transition_status,
)

__all__ = [
    "ACTIVE_STATUSES",
    "CONTROL_REQUEST_KEY",
    "CONTROL_REQUEST_KILL",
    "CONTROL_REQUEST_PAUSE",
    "CrawlStatus",
    "TERMINAL_STATUSES",
    "normalize_status",
    "transition_status",
    "update_run_status",
    "get_control_request",
    "set_control_request",
]


def update_run_status(run, target: str | CrawlStatus) -> CrawlStatus:
    """Update run status and clear run-scoped progress counters on terminal transitions."""
    previous_status = str(run.status)
    next_status = transition_status(run.status, target)
    run.status = next_status.value
    if next_status in TERMINAL_STATUSES and (
        next_status.value != previous_status or run.completed_at is None
    ):
        run.completed_at = datetime.now(UTC)
        run_id = getattr(run, "id", None)
        if isinstance(run_id, int):
            from app.services.crawl_events import clear_url_progress_counter

            clear_url_progress_counter(run_id)

    return next_status


def get_control_request(run) -> str | None:
    value = run.get_summary(CONTROL_REQUEST_KEY)
    return str(value).strip().lower() if value else None


def set_control_request(run, request: str | None) -> None:
    if request:
        run.update_summary(**{CONTROL_REQUEST_KEY: request})
    else:
        run.remove_summary_keys(CONTROL_REQUEST_KEY)
