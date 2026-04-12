from __future__ import annotations

import importlib


def _reload_extraction_audit_module():
    return importlib.reload(
        importlib.import_module("app.services.config.extraction_audit_settings")
    )


def test_extraction_audit_settings_respect_listing_card_overrides(monkeypatch):
    monkeypatch.setenv("CRAWLER_EXTRACTION_LISTING_CARD_JOB_TITLE_MIN_CHARS", "6")
    monkeypatch.setenv("CRAWLER_EXTRACTION_LISTING_CARD_LISTING_TITLE_MIN_CHARS", "5")
    monkeypatch.setenv("CRAWLER_EXTRACTION_LISTING_CARD_JOB_PARTIAL_SIGNAL_SCORE", "0.75")
    monkeypatch.setenv(
        "CRAWLER_EXTRACTION_LISTING_CARD_GENERIC_TEXT_SIGNAL_SCORE", "0.25"
    )

    extraction_settings = _reload_extraction_audit_module()

    assert extraction_settings.LISTING_CARD_JOB_TITLE_MIN_CHARS == 6
    assert extraction_settings.LISTING_CARD_LISTING_TITLE_MIN_CHARS == 5
    assert extraction_settings.LISTING_CARD_JOB_PARTIAL_SIGNAL_SCORE == 0.75
    assert extraction_settings.LISTING_CARD_GENERIC_TEXT_SIGNAL_SCORE == 0.25
