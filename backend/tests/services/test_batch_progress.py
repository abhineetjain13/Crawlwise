from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services._batch_progress import (
    BatchRunProgressState,
    persist_batch_url_result,
)


def test_batch_run_progress_state_builds_progress_patch() -> None:
    state = BatchRunProgressState.from_summary(
        {
            "completed_urls": 1,
            "url_verdicts": ["success"],
            "verdict_counts": {"success": 1},
            "acquisition_summary": {"methods": {"curl_cffi": 1}},
            "quality_summary": {
                "level": "medium",
                "score": 0.6,
                "scored_urls": 1,
                "level_counts": {"medium": 1},
            },
        },
        total_urls=3,
        url_domain="example.com",
        persisted_record_count=5,
    )

    state.record_url_result(
        idx=1,
        records_count=2,
        verdict="partial",
        url_metrics={
            "method": "browser",
            "browser_used": True,
            "record_count": 2,
            "quality_summary": {
                "level": "high",
                "score": 0.9,
                "listing_completeness": {"applicable": True, "complete": False},
            },
        },
    )

    patch = state.build_progress_patch(
        current_url="https://example.com/items/2",
        current_url_index=2,
    )

    assert patch["url_count"] == 3
    assert patch["record_count"] == 7
    assert patch["progress"] == 66
    assert patch["completed_urls"] == 2
    assert patch["remaining_urls"] == 1
    assert patch["url_verdicts"] == ["success", "partial"]
    assert patch["verdict_counts"] == {"success": 1, "partial": 1}
    assert patch["acquisition_summary"]["methods"] == {"curl_cffi": 1, "browser": 1}
    assert patch["quality_summary"]["scored_urls"] == 2
    assert patch["quality_summary"]["level"] == "medium"
    assert patch["quality_summary"]["listing_incomplete_urls"] == 1
    assert patch["current_url"] == "https://example.com/items/2"
    assert patch["current_url_index"] == 2


def test_batch_run_progress_state_aligns_out_of_order_verdict_indices() -> None:
    state = BatchRunProgressState.from_summary(
        {
            "completed_urls": 1,
            "url_verdicts": ["success"],
        },
        total_urls=4,
        url_domain="example.com",
        persisted_record_count=0,
    )

    state.record_url_result(
        idx=3,
        records_count=0,
        verdict="blocked",
        url_metrics={},
    )

    assert state.url_verdicts == ["success", "", "", "blocked"]


def test_batch_run_progress_state_reconstructs_out_of_order_verdicts_without_truncation() -> None:
    state = BatchRunProgressState.from_summary(
        {
            "completed_urls": 3,
            "url_verdicts": ["success", "", "blocked"],
            "verdict_counts": {"success": 1, "blocked": 1},
        },
        total_urls=4,
        url_domain="example.com",
        persisted_record_count=0,
    )

    assert state.completed_count == 1
    assert state.url_verdicts == ["success", "", "blocked"]


def test_batch_run_progress_state_final_patch_includes_quality_and_acquisition_summary() -> None:
    state = BatchRunProgressState.from_summary(
        {
            "completed_urls": 0,
            "url_verdicts": [],
            "verdict_counts": {},
        },
        total_urls=1,
        url_domain="example.com",
        persisted_record_count=0,
    )

    state.record_url_result(
        idx=0,
        records_count=3,
        verdict="partial",
        url_metrics={
            "method": "curl_cffi",
            "record_count": 3,
            "quality_summary": {
                "level": "low",
                "score": 0.45,
                "variant_completeness": {"applicable": True, "complete": False},
            },
        },
    )

    patch = state.build_final_patch("partial")

    assert patch["extraction_verdict"] == "partial"
    assert patch["acquisition_summary"]["methods"] == {"curl_cffi": 1}
    assert patch["quality_summary"]["level"] == "low"
    assert patch["quality_summary"]["variant_incomplete_urls"] == 1


@pytest.mark.asyncio
async def test_batch_run_progress_state_persists_url_result() -> None:
    state = BatchRunProgressState.from_summary(
        {
            "progress": 10,
            "completed_urls": 0,
            "url_verdicts": [],
            "verdict_counts": {},
        },
        total_urls=2,
        url_domain="example.com",
        persisted_record_count=0,
    )

    captured: dict[str, object] = {}

    async def fake_retry_run_update(session, run_id, mutate) -> None:
        run = SimpleNamespace()
        run.result_summary = {
            "progress": 10,
            "completed_urls": 0,
            "url_verdicts": [],
            "verdict_counts": {},
        }
        run.merge_summary_patch = lambda patch: run.result_summary.update(patch)
        await mutate(session, run)
        captured["run_id"] = run_id
        captured["summary"] = run.result_summary

    await persist_batch_url_result(
        state=state,
        session=None,
        run_id=7,
        retry_run_update=fake_retry_run_update,
        idx=0,
        url="https://example.com/items/1",
        records_count=1,
        verdict="success",
        url_metrics={
            "method": "browser",
            "browser_used": True,
            "record_count": 1,
            "quality_summary": {
                "level": "high",
                "score": 0.92,
            },
        },
    )

    summary = captured["summary"]
    assert captured["run_id"] == 7
    assert summary["progress"] == 50
    assert summary["completed_urls"] == 1
    assert summary["record_count"] == 1
    assert summary["current_url"] == "https://example.com/items/1"
    assert summary["current_url_index"] == 1
    assert summary["url_verdicts"] == ["success"]
    assert summary["verdict_counts"] == {"success": 1}
    assert summary["acquisition_summary"]["methods"] == {"browser": 1}
    assert summary["quality_summary"]["level"] == "high"
