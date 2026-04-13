from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.services.acquisition.blocked_detector import detect_blocked_page
from app.services.config.crawl_runtime import (
    ACQUISITION_ARTIFACT_CLEANUP_INTERVAL_SECONDS,
    ACQUISITION_ARTIFACT_TTL_SECONDS,
)

logger = logging.getLogger(__name__)
_ARTIFACT_CLEANUP_LOCK = threading.Lock()
_LAST_ARTIFACT_CLEANUP_STARTED_AT = 0.0
_ARTIFACT_SUBDIRECTORIES = ("html", "network", "diagnostics")


@dataclass(frozen=True, slots=True)
class AcquisitionArtifactPaths:
    artifact_path: Path
    diagnostics_path: Path
    network_payload_path: Path


def artifact_paths(run_id: int, url: str) -> AcquisitionArtifactPaths:
    return AcquisitionArtifactPaths(
        artifact_path=settings.artifacts_dir / "html" / f"{_artifact_basename(run_id, url)}.html",
        diagnostics_path=settings.artifacts_dir
        / "diagnostics"
        / f"{_artifact_basename(run_id, url)}.json",
        network_payload_path=settings.artifacts_dir
        / "network"
        / f"{_artifact_basename(run_id, url)}.json",
    )


async def persist_failure_artifacts(
    run_id: int,
    url: str,
    *,
    error_detail: str,
) -> str:
    await asyncio.to_thread(prune_expired_acquisition_artifacts)
    paths = artifact_paths(run_id, url)
    await asyncio.to_thread(
        _write_failed_diagnostics,
        run_id,
        url,
        paths.diagnostics_path,
        error_detail=error_detail,
    )
    return str(paths.diagnostics_path)


async def persist_acquisition_artifacts(
    run_id: int,
    url: str,
    result,
    *,
    scrub_payload,
    scrub_html,
    scrub_text,
) -> tuple[str, str]:
    await asyncio.to_thread(prune_expired_acquisition_artifacts)
    paths = artifact_paths(run_id, url)
    artifact_path = await asyncio.to_thread(
        _write_artifact_file,
        paths.artifact_path,
        result,
        scrub_payload=scrub_payload,
        scrub_html=scrub_html,
        scrub_text=scrub_text,
    )
    await asyncio.to_thread(
        _write_network_payloads,
        paths.network_payload_path,
        result.network_payloads,
        scrub_payload=scrub_payload,
    )
    await asyncio.to_thread(
        _write_diagnostics,
        run_id,
        url,
        result,
        artifact_path,
        paths.diagnostics_path,
        paths.network_payload_path,
        scrub_payload=scrub_payload,
    )
    return str(artifact_path), str(paths.diagnostics_path)


def prune_expired_acquisition_artifacts() -> None:
    global _LAST_ARTIFACT_CLEANUP_STARTED_AT
    ttl_seconds = max(0, int(ACQUISITION_ARTIFACT_TTL_SECONDS or 0))
    if ttl_seconds <= 0:
        return
    now = time.time()
    cleanup_interval_seconds = max(
        0, int(ACQUISITION_ARTIFACT_CLEANUP_INTERVAL_SECONDS or 0)
    )
    if (
        cleanup_interval_seconds > 0
        and now - _LAST_ARTIFACT_CLEANUP_STARTED_AT < cleanup_interval_seconds
    ):
        return
    if not _ARTIFACT_CLEANUP_LOCK.acquire(blocking=False):
        return
    try:
        if (
            cleanup_interval_seconds > 0
            and now - _LAST_ARTIFACT_CLEANUP_STARTED_AT < cleanup_interval_seconds
        ):
            return
        _LAST_ARTIFACT_CLEANUP_STARTED_AT = now
        cutoff_timestamp = now - ttl_seconds
        for subdirectory in _ARTIFACT_SUBDIRECTORIES:
            directory = settings.artifacts_dir / subdirectory
            if not directory.exists():
                continue
            for path in directory.iterdir():
                if not path.is_file():
                    continue
                try:
                    if path.stat().st_mtime <= cutoff_timestamp:
                        path.unlink(missing_ok=True)
                except FileNotFoundError:
                    continue
                except OSError:
                    logger.warning(
                        "Failed to prune expired acquisition artifact %s",
                        path,
                        exc_info=True,
                    )
    finally:
        _ARTIFACT_CLEANUP_LOCK.release()


def _artifact_basename(run_id: int, url: str) -> str:
    import hashlib

    return f"{run_id}_{hashlib.md5(url.encode()).hexdigest()}"


def _write_artifact_file(
    artifact_path: Path,
    result,
    *,
    scrub_payload,
    scrub_html,
    scrub_text,
) -> Path:
    path = artifact_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if result.content_type == "json" and result.json_data is not None:
        path = path.with_suffix(".json")
        path.write_text(
            json.dumps(scrub_payload(result.json_data), indent=2, default=str),
            encoding="utf-8",
        )
        return path
    if result.content_type == "json":
        path = path.with_suffix(".json")
        path.write_text(scrub_text(result.html or ""), encoding="utf-8")
        return path
    path.write_text(scrub_html(result.html or ""), encoding="utf-8")
    return path


def _write_network_payloads(
    network_payload_path: Path,
    payloads: list[dict],
    *,
    scrub_payload,
) -> None:
    if not payloads:
        return
    network_payload_path.parent.mkdir(parents=True, exist_ok=True)
    network_payload_path.write_text(
        json.dumps(scrub_payload(payloads), indent=2),
        encoding="utf-8",
    )


def _write_failed_diagnostics(
    run_id: int,
    url: str,
    diagnostics_path: Path,
    *,
    error_detail: str,
) -> None:
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "url": url,
        "status": "failed",
        "artifact_path": None,
        "network_payload_path": None,
        "html_length": 0,
        "json_kind": None,
        "network_payloads": 0,
        "blocked": None,
        "diagnostics": {
            "error_code": "acquisition_failed",
            "error_detail": error_detail,
        },
    }
    diagnostics_path.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )


def _write_diagnostics(
    run_id: int,
    url: str,
    result,
    artifact_path: Path,
    diagnostics_path: Path,
    network_payload_path: Path,
    *,
    scrub_payload,
) -> None:
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    blocked = (
        detect_blocked_page(result.html).as_dict()
        if result.content_type == "html"
        else None
    )
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "url": url,
        "status": "completed",
        "method": result.method,
        "content_type": result.content_type,
        "artifact_path": str(artifact_path),
        "network_payload_path": str(network_payload_path)
        if result.network_payloads
        else None,
        "html_length": len(result.html or ""),
        "json_kind": type(result.json_data).__name__
        if result.json_data is not None
        else None,
        "network_payloads": len(result.network_payloads or []),
        "blocked": blocked,
        "diagnostics": scrub_payload(result.diagnostics),
    }
    diagnostics_path.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
