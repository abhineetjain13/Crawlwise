from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ArtifactStorage(Protocol):
    def persist_html_artifact(self, *, run_id: int, source_url: str, html: str) -> str: ...

    def persist_json_artifact(
        self,
        *,
        run_id: int,
        source_url: str,
        suffix: str,
        payload: dict[str, Any],
    ) -> str: ...

    def persist_png_artifact(
        self,
        *,
        run_id: int,
        source_url: str,
        suffix: str,
        content: bytes,
    ) -> str: ...

    def persist_png_artifact_from_file(
        self,
        *,
        run_id: int,
        source_url: str,
        suffix: str,
        file_path: str | Path,
    ) -> str: ...
