from __future__ import annotations

from collections.abc import Mapping

VERDICT_SUCCESS: str = "success"
VERDICT_PARTIAL: str = "partial"
VERDICT_BLOCKED: str = "blocked"
VERDICT_LISTING_FAILED: str = "listing_detection_failed"
VERDICT_EMPTY: str = "empty"
VERDICT_ERROR: str = "error"


def compute_verdict(*, is_listing: bool, blocked: bool, record_count: int) -> str:
    if int(record_count) > 0:
        return VERDICT_PARTIAL if bool(blocked) else VERDICT_SUCCESS
    if bool(blocked):
        return VERDICT_BLOCKED
    return VERDICT_LISTING_FAILED if bool(is_listing) else VERDICT_EMPTY


def _aggregate_verdict(verdicts: list[str]) -> str:
    cleaned: list[str] = [
        str(value or "").strip() for value in verdicts if str(value or "").strip()
    ]
    if len(cleaned) == 0:
        return VERDICT_EMPTY
    verdict_set: set[str] = set(cleaned)
    if verdict_set.intersection({VERDICT_SUCCESS, VERDICT_PARTIAL}):
        return VERDICT_SUCCESS if verdict_set <= {VERDICT_SUCCESS} else VERDICT_PARTIAL
    for preferred in tuple([VERDICT_ERROR, VERDICT_BLOCKED, VERDICT_LISTING_FAILED]):
        if verdict_set.intersection({preferred}):
            return preferred
    return str(cleaned[-1])


def run_health_verdict(summary: dict[str, object] | object) -> dict[str, object]:
    from app.services.config.runtime_settings import crawler_runtime_settings

    payload = dict(summary) if isinstance(summary, Mapping) else {}
    raw_verdicts = payload.get("url_verdicts")
    verdicts = [
        str(value or "").strip()
        for value in list(raw_verdicts or [])
        if str(value or "").strip()
    ]
    try:
        url_count = int(payload.get("url_count") or 0)
    except (TypeError, ValueError):
        url_count = 0
    if isinstance(raw_verdicts, list):
        total = max(url_count, len(verdicts)) if verdicts else 0
    else:
        total = url_count
    failures = sum(
        1 for verdict in verdicts if verdict not in {VERDICT_SUCCESS, VERDICT_PARTIAL}
    )
    failure_rate = failures / total if total else 0.0
    status = "unknown"
    if total:
        if failure_rate >= crawler_runtime_settings.run_health_failed_error_rate:
            status = "failed"
        elif failure_rate >= crawler_runtime_settings.run_health_degraded_error_rate:
            status = "degraded"
        else:
            status = "healthy"
    elif isinstance(raw_verdicts, list):
        status = "healthy"
    return {
        "status": status,
        "url_count": total,
        "failure_count": failures,
        "failure_rate": round(failure_rate, 4),
        "degraded_error_rate": crawler_runtime_settings.run_health_degraded_error_rate,
        "failed_error_rate": crawler_runtime_settings.run_health_failed_error_rate,
    }
