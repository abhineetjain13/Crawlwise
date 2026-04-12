from __future__ import annotations

import importlib

import pytest


def _reload_adapter_runtime_module():
    return importlib.reload(
        importlib.import_module("app.services.config.adapter_runtime_settings")
    )


def test_adapter_runtime_settings_respect_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADAPTER_RUNTIME_SHOPIFY_CATALOG_LIMIT", "99")
    monkeypatch.setenv("ADAPTER_RUNTIME_ICIMS_PAGE_SIZE", "25")
    monkeypatch.setenv("ADAPTER_RUNTIME_ICIMS_MAX_OFFSET", "250")
    monkeypatch.setenv("ADAPTER_RUNTIME_ICIMS_PAGINATION_TIMEOUT_SECONDS", "11")

    try:
        adapter_runtime = _reload_adapter_runtime_module()

        assert adapter_runtime.SHOPIFY_CATALOG_LIMIT == 99
        assert adapter_runtime.ICIMS_PAGE_SIZE == 25
        assert adapter_runtime.ICIMS_MAX_OFFSET == 250
        assert adapter_runtime.ICIMS_PAGINATION_TIMEOUT_SECONDS == 11
    finally:
        monkeypatch.undo()
        _reload_adapter_runtime_module()


def test_adapter_runtime_settings_reject_invalid_icims_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADAPTER_RUNTIME_ICIMS_PAGE_SIZE", "100")
    monkeypatch.setenv("ADAPTER_RUNTIME_ICIMS_MAX_OFFSET", "50")

    try:
        with pytest.raises(
            ValueError, match="icims_max_offset must be >= icims_page_size"
        ):
            _reload_adapter_runtime_module()
    finally:
        monkeypatch.undo()
        _reload_adapter_runtime_module()
