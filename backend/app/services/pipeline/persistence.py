from __future__ import annotations

import asyncio
import hashlib
import json

from app.models.crawl import CrawlRecord, CrawlRun
from app.services.db_utils import mapping_or_empty
from app.services.field_value_core import object_list as _object_list
from app.services.public_record_firewall import public_record_data_for_surface
from app.services.export.schema import build_source_trace
from app.services.artifact_store import (
    persist_html_artifact,
    persist_json_artifact,
    persist_png_artifact,
    persist_png_artifact_from_file,
)
from app.services.publish.metadata import refresh_record_commit_metadata
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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


def _record_content_fingerprint(
    data: dict[str, object],
    *,
    identity_source_url: str,
) -> str | None:
    identity_fields = ("gtin", "barcode", "sku", "mpn", "brand", "title")
    values = {
        field_name: _fingerprint_value(data.get(field_name))
        for field_name in identity_fields
        if _fingerprint_value(data.get(field_name)) not in (None, "", [], {})
    }
    if not values:
        values = {"url": _fingerprint_value(identity_source_url)}
    payload = json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fingerprint_value(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    if isinstance(value, list):
        return [
            item
            for item in (_fingerprint_value(item) for item in value)
            if item not in (None, "", [], {})
        ]
    if isinstance(value, dict):
        return {
            str(key): item
            for key, raw_item in sorted(value.items())
            if (item := _fingerprint_value(raw_item)) not in (None, "", [], {})
        }
    return value


def _stored_record_matches(
    row: CrawlRecord,
    *,
    source_url: str,
    data: dict[str, object],
    raw_data: dict[str, object],
    source_trace: dict[str, object],
    raw_html_path: str | None,
    content_fingerprint: str | None,
) -> bool:
    return (
        row.source_url == source_url
        and row.data == data
        and row.raw_data == raw_data
        and row.source_trace == source_trace
        and row.raw_html_path == raw_html_path
        and row.content_fingerprint == content_fingerprint
    )


def _update_stored_record(
    row: CrawlRecord,
    *,
    source_url: str,
    data: dict[str, object],
    raw_data: dict[str, object],
    discovered_data: dict[str, object],
    source_trace: dict[str, object],
    raw_html_path: str | None,
    content_fingerprint: str | None,
) -> None:
    row.source_url = source_url
    row.data = data
    row.raw_data = raw_data
    row.discovered_data = discovered_data
    row.source_trace = source_trace
    row.raw_html_path = raw_html_path
    row.content_fingerprint = content_fingerprint


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
    artifacts = dict(mapping_or_empty(getattr(acquisition_result, "artifacts", {})))
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
    candidate_identity_keys = {
        identity_key
        for record in records
        for identity_key in (
            _record_identity_key(
                str(
                    dict(record).get("url")
                    or dict(record).get("source_url")
                    or acquisition_result.final_url
                )
            ),
        )
        if identity_key
    }
    existing_records_by_identity: dict[str, CrawlRecord] = {}
    if candidate_identity_keys:
        existing_records_by_identity = {
            str(row.url_identity_key): row
            for row in (
                await session.scalars(
                    select(CrawlRecord).where(
                        CrawlRecord.run_id == run.id,
                        CrawlRecord.url_identity_key.in_(candidate_identity_keys),
                    )
                )
            )
            if row.url_identity_key
        }
    seen_identities: set[str] = set(existing_records_by_identity)
    for record in records:
        raw_record = dict(record)
        preliminary_source_url = str(
            raw_record.get("source_url") or acquisition_result.final_url
        )
        data, rejected_public_fields = public_record_data_for_surface(
            raw_record,
            surface=run.surface,
            page_url=preliminary_source_url,
            requested_fields=list(run.requested_fields or []),
        )
        if not data:
            continue
        if "listing" in str(run.surface or "") and not data.get("url"):
            continue
        record_source_url = str(
            data.get("source_url") or acquisition_result.final_url
        )
        identity_source_url = str(data.get("url") or record_source_url)
        identity_key = _record_identity_key(identity_source_url)
        if rejected_public_fields:
            raw_record["_rejected_public_fields"] = rejected_public_fields
        page_markdown = str(getattr(acquisition_result, "page_markdown", "") or "").strip()
        record_url = str(data.get("url") or "").strip()
        if (
            page_markdown
            and not str(raw_record.get("page_markdown") or "").strip()
            and (not record_url or record_url == record_source_url)
        ):
            raw_record["page_markdown"] = page_markdown
        content_fingerprint = _record_content_fingerprint(
            data,
            identity_source_url=identity_source_url,
        )
        discovered_data = {
            key: value
            for key, value in {
                "confidence": mapping_or_empty(record.get("_confidence")),
                "field_repair": mapping_or_empty(record.get("_field_repair")),
                "manifest_trace": mapping_or_empty(record.get("_manifest_trace")),
                "semantic": mapping_or_empty(record.get("_semantic")),
                "review_bucket": _object_list(record.get("_review_bucket")),
            }.items()
            if value not in (None, "", [], {})
        }
        source_trace = build_source_trace(
            acquisition_result,
            raw_record,
            data=data,
        )
        existing_record = existing_records_by_identity.get(identity_key or "")
        if identity_key and identity_key in seen_identities:
            if existing_record and not _stored_record_matches(
                existing_record,
                source_url=record_source_url,
                data=data,
                raw_data=raw_record,
                source_trace=source_trace,
                raw_html_path=raw_html_path,
                content_fingerprint=content_fingerprint,
            ):
                _update_stored_record(
                    existing_record,
                    source_url=record_source_url,
                    data=data,
                    raw_data=raw_record,
                    discovered_data=discovered_data,
                    source_trace=source_trace,
                    raw_html_path=raw_html_path,
                    content_fingerprint=content_fingerprint,
                )
                for field_name, value in data.items():
                    refresh_record_commit_metadata(
                        existing_record,
                        run=run,
                        field_name=field_name,
                        value=value,
                        source_label=str(record.get("_source") or "extraction"),
                        preserve_existing_sources=True,
                    )
                await session.flush()
                persisted += 1
            continue
        if identity_key is not None:
            seen_identities.add(identity_key)
        crawl_record = CrawlRecord(
            run_id=run.id,
            source_url=record_source_url,
            url_identity_key=identity_key,
            content_fingerprint=content_fingerprint,
            data=data,
            raw_data=raw_record,
            discovered_data=discovered_data,
            source_trace=source_trace,
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
