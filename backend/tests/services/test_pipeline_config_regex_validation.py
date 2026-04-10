from __future__ import annotations

import importlib

import pytest


def test_pipeline_config_raises_descriptive_error_for_invalid_editorial_pattern(monkeypatch):
    import app.services.config.extraction_rules as extraction_rules
    import app.services.pipeline_config as pipeline_config

    mutated_rules = dict(extraction_rules.EXTRACTION_RULES)
    noise = dict(mutated_rules.get("listing_noise_filters", {}))
    noise["editorial_title_patterns"] = ["("]
    mutated_rules["listing_noise_filters"] = noise

    with monkeypatch.context() as patcher:
        patcher.setattr(extraction_rules, "EXTRACTION_RULES", mutated_rules)
        with pytest.raises(RuntimeError, match=r"editorial_title_patterns.*extraction_rules\.py"):
            importlib.reload(pipeline_config)

    importlib.reload(pipeline_config)
