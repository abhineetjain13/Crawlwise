from __future__ import annotations

from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES_ROOT = Path(__file__).resolve().parent


def read_optional_artifact_text(
    path: str,
    *,
    fixture_subdir: str | None = None,
) -> str:
    artifact_path = Path(path)
    candidates: list[Path] = []
    if fixture_subdir:
        candidates.append(_FIXTURES_ROOT / fixture_subdir / artifact_path.name)
    candidates.extend((artifact_path, _BACKEND_ROOT / artifact_path))
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="ignore")
    pytest.skip(f"artifact fixture missing: {candidates[0] if candidates else artifact_path}")
