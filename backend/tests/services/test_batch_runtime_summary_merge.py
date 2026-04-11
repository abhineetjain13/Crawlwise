from __future__ import annotations

from app.services.run_summary import merge_run_summary_patch as _merge_run_summary_patch


def test_merge_run_summary_patch_preserves_monotonic_progress_counters() -> None:
    current = {
        "url_count": 5,
        "record_count": 10,
        "progress": 60,
        "processed_urls": 3,
        "completed_urls": 3,
        "remaining_urls": 2,
    }
    patch = {
        "url_count": 4,
        "record_count": 9,
        "progress": 40,
        "processed_urls": 2,
        "completed_urls": 2,
        "remaining_urls": 3,
    }

    merged = _merge_run_summary_patch(current, patch)

    assert merged["url_count"] == 5
    assert merged["record_count"] == 10
    assert merged["progress"] == 60
    assert merged["processed_urls"] == 3
    assert merged["completed_urls"] == 3
    assert merged["remaining_urls"] == 2


def test_merge_run_summary_patch_merges_url_verdicts_by_position() -> None:
    current = {
        "url_verdicts": ["success", "", "blocked"],
    }
    patch = {
        "url_verdicts": ["", "partial"],
    }

    merged = _merge_run_summary_patch(current, patch)

    assert merged["url_verdicts"] == ["success", "partial", "blocked"]


def test_merge_run_summary_patch_merges_verdict_counts_monotonically() -> None:
    current = {
        "verdict_counts": {"success": 2, "blocked": 1},
    }
    patch = {
        "verdict_counts": {"success": 1, "blocked": 3, "partial": 1},
    }

    merged = _merge_run_summary_patch(current, patch)

    assert merged["verdict_counts"] == {"success": 2, "blocked": 3, "partial": 1}

