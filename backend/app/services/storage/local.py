from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


class LocalArtifactStorage:
    def __init__(self, *, root_dir: Path) -> None:
        self._root_dir = Path(root_dir)

    def persist_html_artifact(self, *, run_id: int, source_url: str, html: str) -> str:
        if not html:
            return ""
        artifact_path = self._artifact_base_path(
            run_id=run_id, source_url=source_url
        ).with_suffix(".html")
        artifact_path.write_text(str(html), encoding="utf-8")
        return str(artifact_path)

    def persist_json_artifact(
        self,
        *,
        run_id: int,
        source_url: str,
        suffix: str,
        payload: dict[str, Any],
    ) -> str:
        if not payload:
            return ""
        normalized_suffix = str(suffix or "").strip().lower()
        if not normalized_suffix:
            return ""
        base_path = self._artifact_base_path(run_id=run_id, source_url=source_url)
        artifact_path = base_path.with_name(f"{base_path.name}.{normalized_suffix}.json")
        artifact_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return str(artifact_path)

    def persist_png_artifact(
        self,
        *,
        run_id: int,
        source_url: str,
        suffix: str,
        content: bytes,
    ) -> str:
        if not content:
            return ""
        normalized_suffix = str(suffix or "").strip().lower()
        if not normalized_suffix:
            return ""
        base_path = self._artifact_base_path(run_id=run_id, source_url=source_url)
        artifact_path = base_path.with_name(f"{base_path.name}.{normalized_suffix}.png")
        artifact_path.write_bytes(bytes(content))
        return str(artifact_path)

    def persist_png_artifact_from_file(
        self,
        *,
        run_id: int,
        source_url: str,
        suffix: str,
        file_path: str | Path,
    ) -> str:
        source = Path(file_path)
        if not source.is_file():
            return ""
        normalized_suffix = str(suffix or "").strip().lower()
        if not normalized_suffix:
            return ""
        base_path = self._artifact_base_path(run_id=run_id, source_url=source_url)
        artifact_path = base_path.with_name(f"{base_path.name}.{normalized_suffix}.png")
        try:
            source.replace(artifact_path)
        except OSError:
            shutil.copyfile(source, artifact_path)
            source.unlink(missing_ok=True)
        return str(artifact_path)

    def _artifact_base_path(self, *, run_id: int, source_url: str) -> Path:
        safe_run_id = max(int(run_id or 0), 0)
        artifact_dir = self._root_dir / "runs" / str(safe_run_id) / "pages"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        url_hash = hashlib.sha256(str(source_url or "").encode("utf-8")).hexdigest()[:16]
        return artifact_dir / url_hash
