from __future__ import annotations

import importlib
from pathlib import Path

from app.core.config import _normalize_sqlite_database_url, _resolve_project_path
from app.services.pipeline_config import COOKIE_CONSENT_SELECTORS


def test_normalize_sqlite_database_url_resolves_relative_path_to_backend_dir(tmp_path):
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()

    normalized = _normalize_sqlite_database_url(
        "sqlite+aiosqlite:///./crawlerai.db",
        sqlite_anchor=backend_dir,
    )

    assert normalized == f"sqlite+aiosqlite:///{(backend_dir / 'crawlerai.db').resolve().as_posix()}"


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


def test_pipeline_config_allows_missing_cookie_consent_selector_file(monkeypatch):
    import app.services.pipeline_config as pipeline_config

    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if path.name == "consent_selectors.json":
            return False
        return original_exists(path)

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "exists", fake_exists)
        reloaded = importlib.reload(pipeline_config)
        assert reloaded.COOKIE_CONSENT_SELECTORS == []

    restored = importlib.reload(pipeline_config)
    assert restored.COOKIE_CONSENT_SELECTORS != []
