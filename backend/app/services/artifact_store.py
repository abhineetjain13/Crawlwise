from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.storage.factory import get_artifact_storage


def persist_html_artifact(*, run_id: int, source_url: str, html: str) -> str:
    return get_artifact_storage(root_dir=settings.artifacts_dir).persist_html_artifact(
        run_id=run_id, source_url=source_url, html=html
    )


def persist_json_artifact(
    *,
    run_id: int,
    source_url: str,
    suffix: str,
    payload: dict[str, Any],
) -> str:
    return get_artifact_storage(root_dir=settings.artifacts_dir).persist_json_artifact(
        run_id=run_id, source_url=source_url, suffix=suffix, payload=payload
    )


def persist_png_artifact(
    *,
    run_id: int,
    source_url: str,
    suffix: str,
    content: bytes,
) -> str:
    return get_artifact_storage(root_dir=settings.artifacts_dir).persist_png_artifact(
        run_id=run_id, source_url=source_url, suffix=suffix, content=content
    )


def persist_png_artifact_from_file(
    *,
    run_id: int,
    source_url: str,
    suffix: str,
    file_path: str | Path,
) -> str:
    return get_artifact_storage(root_dir=settings.artifacts_dir).persist_png_artifact_from_file(
        run_id=run_id, source_url=source_url, suffix=suffix, file_path=file_path
    )
