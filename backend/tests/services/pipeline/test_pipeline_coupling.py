from __future__ import annotations

from pathlib import Path


def test_pipeline_helpers_use_stage_owned_modules() -> None:
    base = Path(__file__).resolve().parents[3] / "app" / "services" / "pipeline"
    detail_text = (base / "detail_flow.py").read_text(encoding="utf-8")
    trace_text = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "services"
        / "publish"
        / "trace_builders.py"
    ).read_text(encoding="utf-8")

    assert "from app.services.extract.llm_cleanup import" in detail_text
    assert "from app.services.publish.review_shaping import" in detail_text
    assert "from .llm_integration import" not in detail_text
    assert "from .review_helpers import" not in detail_text
    assert "from .core import _should_surface_discovered_field" not in trace_text
    assert "from app.services.publish.review_shaping import _should_surface_discovered_field" in trace_text
