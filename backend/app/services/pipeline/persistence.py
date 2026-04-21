from __future__ import annotations

import asyncio
import hashlib

from app.models.crawl import CrawlRecord, CrawlRun
from app.services.db_utils import mapping_or_empty
from app.services.artifact_store import (
    persist_html_artifact,
    persist_json_artifact,
    persist_png_artifact,
    persist_png_artifact_from_file,
)
from app.services.publish.metadata import refresh_record_commit_metadata
from sqlalchemy.ext.asyncio import AsyncSession

def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _merge_browser_diagnostics(
    acquisition_result,
    diagnostics: dict[str, object],
) -> None:
    merged = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    merged.update(dict(diagnostics or {}))
    acquisition_result.browser_diagnostics = merged


def _record_identity_key(source_url: str) -> str | None:
    text = str(source_url or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_source_trace(acquisition_result, record: dict[str, object]) -> dict[str, object]:
    field_discovery = {}
    field_sources = mapping_or_empty(record.get("_field_sources"))
    for key, value in record.items():
        if str(key).startswith("_"):
            continue
        field_discovery[str(key)] = {
            "status": "found",
            "value": str(value),
            "sources": _string_list(
                field_sources.get(str(key), [str(record.get("_source") or "extraction")])
            ),
        }
    return {
        "acquisition": {
            "method": acquisition_result.method,
            "status_code": acquisition_result.status_code,
            "final_url": acquisition_result.final_url,
            "blocked": acquisition_result.blocked,
            "adapter_name": acquisition_result.adapter_name,
            "adapter_source_type": acquisition_result.adapter_source_type,
            "network_payload_count": len(list(acquisition_result.network_payloads or [])),
            "browser_diagnostics": mapping_or_empty(acquisition_result.browser_diagnostics),
        },
        "extraction": {
            "source": str(record.get("_source") or "extraction"),
            "confidence": mapping_or_empty(record.get("_confidence")),
            "self_heal": mapping_or_empty(record.get("_self_heal")),
            "manifest_trace": mapping_or_empty(record.get("_manifest_trace")),
            "review_bucket": list(record.get("_review_bucket") or [])
            if isinstance(record.get("_review_bucket"), list)
            else [],
            "semantic": mapping_or_empty(record.get("_semantic")),
        },
        "field_discovery": field_discovery,
    }


async def persist_acquisition_artifacts(
    *,
    run_id: int,
    acquisition_result,
    browser_attempted: bool,
    screenshot_required: bool,
) -> str:
    raw_html_path = await asyncio.to_thread(
        persist_html_artifact,
        run_id=run_id,
        source_url=acquisition_result.final_url,
        html=acquisition_result.html,
    )
    if not browser_attempted:
        return raw_html_path

    diagnostics = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    artifacts = mapping_or_empty(getattr(acquisition_result, "artifacts", {}))
    screenshot_path_source = str(artifacts.pop("browser_screenshot_path", "") or "").strip()
    screenshot_bytes = artifacts.pop("browser_screenshot_png", b"")
    screenshot_path = ""
    if screenshot_required:
        if screenshot_path_source:
            screenshot_path = await asyncio.to_thread(
                persist_png_artifact_from_file,
                run_id=run_id,
                source_url=acquisition_result.final_url,
                suffix="browser",
                file_path=screenshot_path_source,
            )
        elif isinstance(screenshot_bytes, (bytes, bytearray)):
            screenshot_path = await asyncio.to_thread(
                persist_png_artifact,
                run_id=run_id,
                source_url=acquisition_result.final_url,
                suffix="browser",
                content=screenshot_bytes,
            )

    diagnostics_payload = dict(diagnostics)
    diagnostics_payload["artifact_paths"] = {
        "html": raw_html_path or None,
        "screenshot": screenshot_path or None,
    }
    diagnostics_path = await asyncio.to_thread(
        persist_json_artifact,
        run_id=run_id,
        source_url=acquisition_result.final_url,
        suffix="browser",
        payload=diagnostics_payload,
    )
    _merge_browser_diagnostics(
        acquisition_result,
        {
            "artifact_paths": {
                "html": raw_html_path or None,
                "diagnostics": diagnostics_path or None,
                "screenshot": screenshot_path or None,
            }
        },
    )
    return raw_html_path


async def persist_extracted_records(
    session: AsyncSession,
    run: CrawlRun,
    records: list[dict[str, object]],
    *,
    acquisition_result,
    raw_html_path: str | None = None,
) -> int:
    persisted = 0
    seen_identities: set[str] = set()
    for record in records:
        data = {
            key: value
            for key, value in dict(record).items()
            if value not in (None, "", [], {}) and not str(key).startswith("_")
        }
        if not data:
            continue
        record_source_url = str(
            data.get("source_url") or acquisition_result.final_url
        )
        identity_source_url = str(data.get("url") or record_source_url)
        identity_key = _record_identity_key(identity_source_url)
        if identity_key and identity_key in seen_identities:
            continue
        if identity_key is not None:
            seen_identities.add(identity_key)
        raw_record = dict(record)
        page_markdown = str(getattr(acquisition_result, "page_markdown", "") or "").strip()
        record_url = str(data.get("url") or "").strip()
        if (
            page_markdown
            and not str(raw_record.get("page_markdown") or "").strip()
            and (not record_url or record_url == record_source_url)
        ):
            raw_record["page_markdown"] = page_markdown
        crawl_record = CrawlRecord(
            run_id=run.id,
            source_url=record_source_url,
            url_identity_key=identity_key,
            data=data,
            raw_data=raw_record,
            discovered_data={
                key: value
                for key, value in {
                    "confidence": mapping_or_empty(record.get("_confidence")),
                    "manifest_trace": mapping_or_empty(record.get("_manifest_trace")),
                    "semantic": mapping_or_empty(record.get("_semantic")),
                    "review_bucket": list(record.get("_review_bucket") or [])
                    if isinstance(record.get("_review_bucket"), list)
                    else [],
                }.items()
                if value not in (None, "", [], {})
            },
            source_trace=_build_source_trace(acquisition_result, record),
            raw_html_path=raw_html_path,
        )
        session.add(crawl_record)
        await session.flush()
        for field_name, value in data.items():
            refresh_record_commit_metadata(
                crawl_record,
                run=run,
                field_name=field_name,
                value=value,
                source_label=str(record.get("_source") or "extraction"),
                preserve_existing_sources=True,
            )
        persisted += 1
    return persisted
