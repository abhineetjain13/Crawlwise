from __future__ import annotations

import importlib
import pytest

from app.core.config import (
    Settings,
    _check_secret_defaults,
    _resolve_project_path,
    settings,
)
from app.services.config.crawl_runtime import DEFAULT_MAX_PAGES as MODULE_DEFAULT_MAX_PAGES
from app.services.config.selectors import CONSENT_SELECTORS as MODULE_COOKIE_CONSENT_SELECTORS
from app.services.config.selectors import COOKIE_CONSENT_SELECTORS
from app.services.config.crawl_runtime import DEFAULT_MAX_PAGES


def test_database_url_defaults_to_postgres_asyncpg(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert (
        Settings(_env_file=None).database_url
        == "postgresql+asyncpg://postgres:postgres@localhost:5432/crawl_db"
    )


def test_resolve_project_path_keeps_absolute_paths(tmp_path):
    absolute = (tmp_path / "backend" / "artifacts").resolve()
    absolute.mkdir(parents=True)

    assert _resolve_project_path(absolute, anchor=tmp_path) == absolute


def test_resolve_project_path_resolves_relative_paths_from_project_root(tmp_path):
    resolved = _resolve_project_path("./backend/artifacts", anchor=tmp_path)

    assert resolved == (tmp_path / "backend" / "artifacts").resolve()


def test_cookie_consent_selectors_avoid_overbroad_accept_matches():
    assert ".cookie-banner button" not in COOKIE_CONSENT_SELECTORS
    assert "button:has-text('Accept')" not in COOKIE_CONSENT_SELECTORS
    assert "button:has-text('Accept All')" in COOKIE_CONSENT_SELECTORS


def test_selector_and_runtime_modules_export_expected_values():
    selectors = importlib.reload(importlib.import_module("app.services.config.selectors"))
    crawl_runtime = importlib.reload(
        importlib.import_module("app.services.config.crawl_runtime")
    )

    assert selectors.COOKIE_CONSENT_SELECTORS == list(MODULE_COOKIE_CONSENT_SELECTORS)
    assert crawl_runtime.DEFAULT_MAX_PAGES == MODULE_DEFAULT_MAX_PAGES == DEFAULT_MAX_PAGES
    restored = importlib.reload(selectors)
    assert restored.COOKIE_CONSENT_SELECTORS != []


def test_crawl_runtime_reads_env_overrides(monkeypatch):
    monkeypatch.setenv("CRAWLER_RUNTIME_DEFAULT_MAX_PAGES", "9")

    import app.services.config.runtime_settings as runtime_settings
    import app.services.config.crawl_runtime as crawl_runtime

    importlib.reload(runtime_settings)
    reloaded_crawl_runtime = importlib.reload(crawl_runtime)

    assert reloaded_crawl_runtime.DEFAULT_MAX_PAGES == 9

    monkeypatch.undo()
    importlib.reload(runtime_settings)
    importlib.reload(crawl_runtime)


def test_llm_runtime_reads_env_overrides(monkeypatch):
    monkeypatch.setenv("CRAWLER_LLM_GROQ_MAX_TOKENS", "4321")

    import app.services.config.runtime_settings as runtime_settings
    import app.services.config.llm_runtime as llm_runtime

    importlib.reload(runtime_settings)
    reloaded_llm_runtime = importlib.reload(llm_runtime)

    assert reloaded_llm_runtime.LLM_GROQ_MAX_TOKENS == 4321

    monkeypatch.undo()
    importlib.reload(runtime_settings)
    importlib.reload(llm_runtime)


def test_check_secret_defaults_warns_in_dev_for_insecure_defaults(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(settings, "jwt_secret_key", "change-me")
    monkeypatch.setattr(settings, "encryption_key", "change-me-32-bytes-minimum-change-me")
    monkeypatch.setattr(settings, "bootstrap_admin_once", False)
    monkeypatch.setattr(settings, "default_admin_email", "admin@example.invalid")
    monkeypatch.setattr(settings, "default_admin_password", None)

    _check_secret_defaults()

    assert "SECURITY WARNING" in caplog.text


def test_check_secret_defaults_raises_outside_dev_for_insecure_defaults(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setattr(settings, "jwt_secret_key", "change-me")
    monkeypatch.setattr(settings, "encryption_key", "change-me-32-bytes-minimum-change-me")
    monkeypatch.setattr(settings, "bootstrap_admin_once", False)
    monkeypatch.setattr(settings, "default_admin_email", "admin@example.invalid")
    monkeypatch.setattr(settings, "default_admin_password", None)

    with pytest.raises(RuntimeError, match="SECURITY WARNING"):
        _check_secret_defaults()


def test_check_secret_defaults_raises_for_bootstrap_placeholder_email(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(settings, "jwt_secret_key", "secure-jwt-secret")
    monkeypatch.setattr(settings, "encryption_key", "secure-encryption-key-32-bytes-min")
    monkeypatch.setattr(settings, "bootstrap_admin_once", True)
    monkeypatch.setattr(settings, "default_admin_email", "admin@example.invalid")
    monkeypatch.setattr(settings, "default_admin_password", "StrongerAdmin#123")

    with pytest.raises(RuntimeError, match="non-default default_admin_email"):
        _check_secret_defaults()
