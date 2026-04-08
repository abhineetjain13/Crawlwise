from __future__ import annotations

from pathlib import Path


def test_pipeline_helpers_no_longer_lazy_import_core() -> None:
    base = Path(__file__).resolve().parents[3] / "app" / "services" / "pipeline"
    llm_text = (base / "llm_integration.py").read_text(encoding="utf-8")
    trace_text = (base / "trace_builders.py").read_text(encoding="utf-8")

    assert "from .core import _merge_review_bucket_entries" not in llm_text
    assert "from .core import _should_surface_discovered_field" not in trace_text
