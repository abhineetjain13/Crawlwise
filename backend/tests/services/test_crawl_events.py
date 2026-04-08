from __future__ import annotations

import json

from app.core.telemetry import reset_correlation_id, set_correlation_id
from app.services import crawl_events


def test_prepare_log_event_adds_correlation_prefix(monkeypatch):
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_min_level", "info")
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_url_progress_sample_rate", 1)

    token = set_correlation_id("corr-test-123")
    try:
        level, message, should_persist = crawl_events.prepare_log_event(
            101, "info", "Pipeline started"
        )
    finally:
        reset_correlation_id(token)

    assert level == "info"
    assert message == "Pipeline started"
    assert should_persist is True


def test_prepare_log_event_samples_repetitive_progress_logs(monkeypatch):
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_min_level", "info")
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_url_progress_sample_rate", 3)

    crawl_events._url_progress_counters.clear()
    first = crawl_events.prepare_log_event(202, "info", "Processing URL 1/10: https://example.com/1")
    second = crawl_events.prepare_log_event(202, "info", "Processing URL 2/10: https://example.com/2")
    third = crawl_events.prepare_log_event(202, "info", "Processing URL 3/10: https://example.com/3")

    assert first[2] is True
    assert second[2] is False
    assert third[2] is False


def test_prepare_log_event_caps_db_row_volume_per_run(monkeypatch):
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_min_level", "info")
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_url_progress_sample_rate", 1)
    monkeypatch.setattr(crawl_events.settings, "crawl_log_db_max_rows_per_run", 2)

    crawl_events.clear_url_progress_counter(303)
    first = crawl_events.prepare_log_event(303, "info", "first")
    second = crawl_events.prepare_log_event(303, "info", "second")
    third = crawl_events.prepare_log_event(303, "info", "third")

    assert first[2] is True
    assert second[2] is True
    assert third[2] is False


def test_append_log_file_line_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl_events.settings, "crawl_log_file_enabled", True)
    monkeypatch.setattr(crawl_events.settings, "crawl_log_file_dir", tmp_path)

    crawl_events._append_log_file_line(
        run_id=404,
        level="info",
        message="hello",
        created_at=crawl_events.datetime(2026, 4, 8, 12, 0, 0),
    )
    path = tmp_path / "run_404.jsonl"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8").strip())
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
