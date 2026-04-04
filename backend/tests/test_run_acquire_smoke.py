# Tests for the acquire-only smoke runner report generation.
from __future__ import annotations

import json
import asyncio

from run_acquire_smoke import _build_summary, _run_batch, _write_report


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


async def _fake_run_one(run_id: int, name: str, url: str, timeout_seconds: int) -> dict:
    return {"ok": True, "run_id": run_id, "name": name, "url": url, "timeout_seconds": timeout_seconds}


def test_run_batch_uses_unique_start_run_ids(monkeypatch):
    monkeypatch.setattr("run_acquire_smoke._run_one", _fake_run_one)

    results = asyncio.run(_run_batch("api", 30, start_run_id=45000))

    assert results[0]["run_id"] == 45000
    assert results[-1]["run_id"] == 45003
