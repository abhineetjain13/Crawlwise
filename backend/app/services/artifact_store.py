from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.config import settings


def persist_html_artifact(*, run_id: int, source_url: str, html: str) -> str:
    if not html:
        return ""
    artifact_path = _artifact_base_path(run_id=run_id, source_url=source_url).with_suffix(
        ".html"
    )
    artifact_path.write_text(str(html), encoding="utf-8")
    return str(artifact_path)


def persist_json_artifact(
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
    artifact_path = _artifact_base_path(run_id=run_id, source_url=source_url).with_name(
        f"{_artifact_base_path(run_id=run_id, source_url=source_url).name}.{normalized_suffix}.json"
    )
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return str(artifact_path)


def persist_png_artifact(
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
    artifact_path = _artifact_base_path(run_id=run_id, source_url=source_url).with_name(
        f"{_artifact_base_path(run_id=run_id, source_url=source_url).name}.{normalized_suffix}.png"
    )
    artifact_path.write_bytes(bytes(content))
    return str(artifact_path)


def _artifact_base_path(*, run_id: int, source_url: str) -> Path:
    safe_run_id = max(int(run_id or 0), 0)
    artifact_dir = Path(settings.artifacts_dir) / "runs" / str(safe_run_id) / "pages"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.sha256(str(source_url or "").encode("utf-8")).hexdigest()[:16]
    return artifact_dir / url_hash
