from __future__ import annotations


from app.core.config import _normalize_sqlite_database_url, _resolve_project_path


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
