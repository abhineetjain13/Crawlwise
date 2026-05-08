from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.services.config.export_settings import ARTIFACT_STORAGE_BACKEND
from app.services.storage.base import ArtifactStorage
from app.services.storage.local import LocalArtifactStorage


def get_artifact_storage(*, root_dir: Path | None = None) -> ArtifactStorage:
    if ARTIFACT_STORAGE_BACKEND != "local":
        raise ValueError(f"unsupported artifact storage backend: {ARTIFACT_STORAGE_BACKEND}")
    return LocalArtifactStorage(root_dir=root_dir or settings.artifacts_dir)
