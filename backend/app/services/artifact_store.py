from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.config import settings


def persist_html_artifact(*, run_id: int, source_url: str, html: str) -> str:
    if not html:
        return ""
    safe_run_id = max(int(run_id or 0), 0)
    artifact_dir = Path(settings.artifacts_dir) / "runs" / str(safe_run_id) / "pages"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.sha256(str(source_url or "").encode("utf-8")).hexdigest()[:16]
    artifact_path = artifact_dir / f"{url_hash}.html"
    artifact_path.write_text(str(html), encoding="utf-8")
    return str(artifact_path)
