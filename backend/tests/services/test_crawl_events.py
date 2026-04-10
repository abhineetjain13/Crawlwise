from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from app.core.telemetry import reset_correlation_id, set_correlation_id
from app.services import crawl_events


@pytest.mark.asyncio
async def test_prepare_log_event_adds_correlation_prefix(monkeypatch):
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_min_level", "info")
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_url_progress_sample_rate", 1)

    token = set_correlation_id("corr-test-123")
    try:
        level, message, should_persist = await crawl_events.prepare_log_event(
            101, "info", "Pipeline started"
        )
    finally:
        reset_correlation_id(token)

    assert level == "info"
    assert message == "Pipeline started"
    assert should_persist is True


@pytest.mark.asyncio
async def test_prepare_log_event_samples_repetitive_progress_logs(monkeypatch, fake_redis):
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_min_level", "info")
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_url_progress_sample_rate", 3)

    await fake_redis.delete("crawl:events:progress:202", "crawl:events:db:202")
    first = await crawl_events.prepare_log_event(202, "info", "Processing URL 1/10: https://example.com/1")
    second = await crawl_events.prepare_log_event(202, "info", "Processing URL 2/10: https://example.com/2")
    third = await crawl_events.prepare_log_event(202, "info", "Processing URL 3/10: https://example.com/3")

    assert first[2] is True
    assert second[2] is False
    assert third[2] is False


@pytest.mark.asyncio
async def test_prepare_log_event_caps_db_row_volume_per_run(monkeypatch, fake_redis):
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_min_level", "info")
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_url_progress_sample_rate", 1)
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_max_rows_per_run", 2)

    await crawl_events.clear_url_progress_counter_async(303)
    first = await crawl_events.prepare_log_event(303, "info", "first")
    second = await crawl_events.prepare_log_event(303, "info", "second")
    third = await crawl_events.prepare_log_event(303, "info", "third")

    assert first[2] is True
    assert second[2] is True
    assert third[2] is False


def test_append_log_file_line_emits_structured_log(monkeypatch):
    monkeypatch.setattr(crawl_events.settings, "crawl_log_file_enabled", True)
    info_mock = Mock()
    monkeypatch.setattr(crawl_events.logger, "info", info_mock)

    crawl_events._append_log_file_line(
        run_id=404,
        level="info",
        message="hello",
        created_at=crawl_events.datetime(2026, 4, 8, 12, 0, 0),
    )
    info_mock.assert_called_once()
    payload = json.loads(info_mock.call_args.args[1])
    assert payload["run_id"] == 404
    assert payload["level"] == "info"
    assert payload["message"] == "hello"


def test_merge_run_summary_patch_keeps_monotonic_progress_and_counts():
    current = {
        "progress": 80,
        "processed_urls": 8,
        "completed_urls": 8,
        "remaining_urls": 2,
        "verdict_counts": {"success": 8, "error": 0},
    }
    patch = {
        "progress": 60,
        "processed_urls": 6,
        "completed_urls": 6,
        "remaining_urls": 4,
        "verdict_counts": {"success": 6, "error": 1},
    }

    merged = crawl_events._merge_run_summary_patch(current, patch)

    assert merged["progress"] == 80
    assert merged["processed_urls"] == 8
    assert merged["completed_urls"] == 8
    assert merged["remaining_urls"] == 2
    assert merged["verdict_counts"] == {"success": 8, "error": 1}


def test_merge_run_summary_patch_merges_url_verdicts_positionally():
    current = {"url_verdicts": ["success", "", "blocked"]}
    patch = {"url_verdicts": ["", "error"]}

    merged = crawl_events._merge_run_summary_patch(current, patch)

    assert merged["url_verdicts"] == ["success", "error", "blocked"]
