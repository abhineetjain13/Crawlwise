from __future__ import annotations

VERDICT_SUCCESS = "success"
VERDICT_PARTIAL = "partial"
VERDICT_BLOCKED = "blocked"
VERDICT_SCHEMA_MISS = "schema_miss"
VERDICT_LISTING_FAILED = "listing_detection_failed"
VERDICT_EMPTY = "empty"
VERDICT_ERROR = "error"


def compute_verdict(*, is_listing: bool, blocked: bool, record_count: int) -> str:
    if record_count > 0:
        return VERDICT_PARTIAL if blocked else VERDICT_SUCCESS
    if blocked:
        return VERDICT_BLOCKED
    if is_listing:
        return VERDICT_LISTING_FAILED
    return VERDICT_EMPTY


def _aggregate_verdict(verdicts: list[str]) -> str:
    cleaned = [str(value or "").strip() for value in verdicts if str(value or "").strip()]
    if not cleaned:
        return VERDICT_EMPTY
    verdict_set = set(cleaned)
    if VERDICT_SUCCESS in verdict_set or VERDICT_PARTIAL in verdict_set:
        return VERDICT_SUCCESS if verdict_set <= {VERDICT_SUCCESS} else VERDICT_PARTIAL
    for preferred in (VERDICT_ERROR, VERDICT_BLOCKED, VERDICT_LISTING_FAILED):
        if preferred in verdict_set:
            return preferred
    return cleaned[-1]
