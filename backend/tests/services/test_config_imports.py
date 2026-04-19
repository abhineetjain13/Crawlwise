from __future__ import annotations

import importlib


def test_static_config_exports_remain_import_stable() -> None:
    selectors = importlib.import_module("app.services.config.selectors")
    field_mappings = importlib.import_module("app.services.config.field_mappings")

    selectors_reloaded = importlib.reload(selectors)
    field_mappings_reloaded = importlib.reload(field_mappings)

    assert "CARD_SELECTORS" in selectors_reloaded.__all__
    assert selectors_reloaded.CARD_SELECTORS == selectors.CARD_SELECTORS
    assert selectors_reloaded.CARD_SELECTORS

    assert "CANONICAL_SCHEMAS" in field_mappings_reloaded.__all__
    assert field_mappings_reloaded.CANONICAL_SCHEMAS == field_mappings.CANONICAL_SCHEMAS
    assert "job_detail" in field_mappings_reloaded.CANONICAL_SCHEMAS
