# Tests for the acquire-only smoke runner report generation.
from __future__ import annotations

import json

from run_acquire_smoke import _build_summary, _write_report


def test_build_summary_counts_successes_and_failures():
    overall = {
        "api": [
            {"ok": True, "url": "https://example.com/a"},
            {"ok": False, "url": "https://example.com/b"},
        ],
        "commerce": [
            {"ok": True, "url": "https://example.com/c"},
        ],
    }

    summary = _build_summary(overall)

    assert summary == {
        "api": {"ok": 1, "failed": 1, "total": 2},
        "commerce": {"ok": 1, "failed": 0, "total": 1},
    }


def test_write_report_persists_timestamped_json(tmp_path, monkeypatch):
    overall = {
        "api": [
            {
                "ok": True,
                "url": "https://example.com/a",
                "method": "curl_cffi",
                "diagnostics_path": str(tmp_path / "diag.json"),
            }
        ]
    }
    monkeypatch.setattr("run_acquire_smoke.settings.artifacts_dir", tmp_path)

    report_path = _write_report(overall, ["api"], 30)

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_path.parent == tmp_path / "acquisition_smoke"
    assert payload["batches"] == ["api"]
    assert payload["timeout_seconds"] == 30
    assert payload["summary"]["api"] == {"ok": 1, "failed": 0, "total": 1}
    assert payload["results"]["api"][0]["diagnostics_path"].endswith("diag.json")
