from __future__ import annotations

import importlib

from app.core.config import Settings, _resolve_project_path
from app.services.config.selectors import CONSENT_SELECTORS as MODULE_COOKIE_CONSENT_SELECTORS
from app.services.pipeline_config import COOKIE_CONSENT_SELECTORS


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


def test_pipeline_config_uses_python_selector_module():
    import app.services.pipeline_config as pipeline_config

    reloaded = importlib.reload(pipeline_config)
    assert reloaded.COOKIE_CONSENT_SELECTORS == list(MODULE_COOKIE_CONSENT_SELECTORS)
    restored = importlib.reload(pipeline_config)
    assert restored.COOKIE_CONSENT_SELECTORS != []
