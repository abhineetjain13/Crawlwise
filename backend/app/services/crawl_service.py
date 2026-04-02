# Crawl orchestration service.
#
# Implements the single pipeline: ACQUIRE -> DISCOVER -> EXTRACT -> UNIFY -> PUBLISH
# Handles crawl, batch (multi-URL), and listing (category) crawls.
from __future__ import annotations

import csv
import io
import traceback
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlLog, CrawlRecord, CrawlRun
from app.models.selector import Selector
from app.services.acquisition.acquirer import acquire_html
from app.services.adapters.registry import run_adapter
from app.services.discover.service import DiscoveryManifest, discover_sources
from app.services.extract.listing_extractor import extract_listing_records
from app.services.extract.service import extract_candidates
from app.services.normalizers.field_normalizers import normalize_value


# ---------------------------------------------------------------------------
# Run CRUD helpers
# ---------------------------------------------------------------------------

async def create_crawl_run(session: AsyncSession, user_id: int, payload: dict) -> CrawlRun:
    urls = payload.get("urls") or []
    run = CrawlRun(
        user_id=user_id,
        run_type=payload["run_type"],
        url=payload.get("url") or (urls[0] if urls else ""),
        surface=payload["surface"],
        settings=payload.get("settings", {}),
        requested_fields=payload.get("additional_fields", []),
        result_summary={"url_count": max(1, len(urls) or 1), "progress": 0},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def list_runs(
    session: AsyncSession,
    page: int,
    limit: int,
    status: str = "",
    run_type: str = "",
    url_search: str = "",
) -> tuple[list[CrawlRun], int]:
    query = select(CrawlRun)
    count_query = select(func.count()).select_from(CrawlRun)
    if status:
        query = query.where(CrawlRun.status == status)
        count_query = count_query.where(CrawlRun.status == status)
    if run_type:
        query = query.where(CrawlRun.run_type == run_type)
        count_query = count_query.where(CrawlRun.run_type == run_type)
    if url_search:
        pattern = f"%{url_search.lower()}%"
        query = query.where(func.lower(CrawlRun.url).like(pattern))
        count_query = count_query.where(func.lower(CrawlRun.url).like(pattern))
    total = int((await session.execute(count_query)).scalar() or 0)
    result = await session.execute(
        query.order_by(CrawlRun.created_at.desc()).offset((page - 1) * limit).limit(limit)
    )
    return list(result.scalars().all()), total


async def get_run(session: AsyncSession, run_id: int) -> CrawlRun | None:
    return await session.get(CrawlRun, run_id)


async def get_run_records(
    session: AsyncSession, run_id: int, page: int, limit: int
) -> tuple[list[CrawlRecord], int]:
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(CrawlRecord).where(CrawlRecord.run_id == run_id)
            )
        ).scalar()
        or 0
    )
    result = await session.execute(
        select(CrawlRecord)
        .where(CrawlRecord.run_id == run_id)
        .order_by(CrawlRecord.created_at.asc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def get_run_logs(session: AsyncSession, run_id: int) -> list[CrawlLog]:
    result = await session.execute(
        select(CrawlLog).where(CrawlLog.run_id == run_id).order_by(CrawlLog.created_at.asc())
    )
    return list(result.scalars().all())


async def cancel_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    run.status = "cancelled"
    await session.commit()
    await session.refresh(run)
    return run


async def active_jobs(session: AsyncSession) -> list[dict]:
    result = await session.execute(
        select(CrawlRun)
        .where(CrawlRun.status.in_(["pending", "running"]))
        .order_by(CrawlRun.created_at.asc())
    )
    rows = []
    for run in result.scalars().all():
        rows.append({
            "run_id": run.id,
            "status": run.status,
            "progress": run.result_summary.get("progress", 0),
            "started_at": run.created_at,
            "url": run.url,
            "type": run.run_type,
        })
    return rows


# ---------------------------------------------------------------------------
# CSV parsing helper
# ---------------------------------------------------------------------------

def parse_csv_urls(csv_content: str) -> list[str]:
    """Parse URLs from CSV content (first column, skip header if present)."""
    urls: list[str] = []
    reader = csv.reader(io.StringIO(csv_content))
    for i, row in enumerate(reader):
        if not row:
            continue
        cell = row[0].strip()
        if i == 0 and not cell.startswith(("http://", "https://")):
            continue  # skip header
        if cell.startswith(("http://", "https://")):
            urls.append(cell)
    return urls


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def process_run(session: AsyncSession, run_id: int) -> None:
    """Execute the crawl pipeline for a run.

    Handles single-URL crawl, batch (multi-URL), and listing/category crawls.
    All errors are caught and the run is marked as failed with a message.
    """
    run = await session.get(CrawlRun, run_id)
    if run is None or run.status == "cancelled":
        return

    run.status = "running"
    await _log(session, run.id, "info", "Pipeline started")
    await session.commit()

    try:
        settings = run.settings or {}
        urls = settings.get("urls", [])
        run_type = run.run_type

        # Determine URL list
        if run_type == "batch" and urls:
            url_list = urls
        elif run_type == "csv" and settings.get("csv_content"):
            url_list = parse_csv_urls(settings["csv_content"])
        elif run.url:
            url_list = [run.url]
        else:
            raise ValueError("No URL provided")

        # Extract crawl settings
        proxy_list = settings.get("proxy_list", [])
        advanced_mode = settings.get("advanced_mode")  # None, "scroll", "paginate", "load_more", "auto"
        max_records = settings.get("max_records", 100)
        sleep_ms = settings.get("sleep_ms", 0)

        total_urls = len(url_list)
        all_records: list[dict] = []

        for idx, url in enumerate(url_list):
            # Check for cancellation between URLs
            await session.refresh(run)
            if run.status == "cancelled":
                await _log(session, run.id, "info", "Run cancelled by user")
                return

            await _log(session, run.id, "info", f"Processing URL {idx + 1}/{total_urls}: {url}")

            records = await _process_single_url(
                session=session,
                run=run,
                url=url,
                proxy_list=proxy_list,
                advanced_mode=advanced_mode,
                max_records=max_records,
            )
            all_records.extend(records)

            # Update progress
            progress = int(((idx + 1) / total_urls) * 100)
            run.result_summary = {
                "url_count": total_urls,
                "record_count": len(all_records),
                "domain": _domain(url),
                "progress": progress,
            }
            await session.commit()

            # Sleep between URLs if configured (for rate limiting)
            if sleep_ms > 0 and idx < total_urls - 1:
                import asyncio
                await asyncio.sleep(sleep_ms / 1000)

        # Finalize
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.result_summary = {
            "url_count": total_urls,
            "record_count": len(all_records),
            "domain": _domain(url_list[0]) if url_list else "",
            "progress": 100,
        }
        await _log(session, run.id, "info", f"Pipeline completed. {len(all_records)} records extracted.")
        await session.commit()

    except Exception as exc:
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        error_msg = f"{type(exc).__name__}: {exc}"
        run.result_summary = {
            **run.result_summary,
            "error": error_msg,
            "progress": run.result_summary.get("progress", 0),
        }
        await _log(session, run.id, "error", f"Pipeline failed: {error_msg}")
        await session.commit()


async def _process_single_url(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    proxy_list: list[str],
    advanced_mode: str | None,
    max_records: int,
) -> list[dict]:
    """Run the full 5-stage pipeline on a single URL.

    Returns list of normalized record dicts that were saved.
    """
    surface = run.surface
    additional_fields = run.requested_fields or []
    extraction_contract = (run.settings or {}).get("extraction_contract", [])

    # ── STAGE 1: ACQUIRE ──
    await _log(session, run.id, "info", f"[ACQUIRE] Fetching {url}")
    html, method, html_path, network_payloads = await acquire_html(
        run_id=run.id,
        url=url,
        proxy_list=proxy_list or None,
        advanced_mode=advanced_mode,
    )

    if not html or len(html.strip()) < 100:
        await _log(session, run.id, "warning", f"[ACQUIRE] Empty or blocked page: {url}")
        record = CrawlRecord(
            run_id=run.id,
            source_url=url,
            data={"_status": "blocked", "_message": "Page returned empty or blocked content"},
            raw_data={},
            discovered_data={},
            source_trace={"method": method},
            raw_html_path=html_path,
        )
        session.add(record)
        await session.flush()
        return []

    # ── STAGE 2: DISCOVER ──
    await _log(session, run.id, "info", f"[DISCOVER] Enumerating sources (method={method})")

    # Run platform adapter (rank 1 source)
    adapter_result = await run_adapter(url, html, surface)
    adapter_records = adapter_result.records if adapter_result else []

    manifest = discover_sources(
        html=html,
        network_payloads=network_payloads,
        adapter_records=adapter_records,
    )

    # ── STAGE 3: EXTRACT ──
    await _log(session, run.id, "info", "[EXTRACT] Extracting candidates")

    is_listing = surface in ("ecommerce_listing", "job_listing")

    if is_listing:
        # For listing pages, prefer adapter records if available
        if adapter_records:
            extracted_records = adapter_records
        else:
            # Use listing extractor to find repeating cards
            extracted_records = extract_listing_records(
                html=html,
                surface=surface,
                target_fields=set(additional_fields),
                page_url=url,
                max_records=max_records,
            )
            # Also extract detail-level candidates as a supplement
            candidates, source_trace = extract_candidates(
                url, surface, html, manifest, additional_fields, extraction_contract,
            )
    else:
        # For detail pages, use standard candidate extraction
        candidates, source_trace = extract_candidates(
            url, surface, html, manifest, additional_fields, extraction_contract,
        )
        # If adapter gave us records, use them; otherwise build from candidates
        if adapter_records:
            extracted_records = adapter_records
        else:
            extracted_records = []

    # ── STAGE 4: UNIFY ──
    await _log(session, run.id, "info", "[UNIFY] Merging and normalizing")

    saved_records: list[dict] = []

    if is_listing and extracted_records:
        # Save each listing record
        for raw_record in extracted_records[:max_records]:
            normalized = {k: normalize_value(k, v) for k, v in raw_record.items() if not k.startswith("_")}
            raw_data = {k: v for k, v in raw_record.items() if not k.startswith("_")}
            db_record = CrawlRecord(
                run_id=run.id,
                source_url=raw_record.get("url", url),
                data=normalized,
                raw_data=raw_data,
                discovered_data=manifest.as_dict(),
                source_trace={"type": "listing", "adapter": adapter_result.adapter_name if adapter_result else None},
                raw_html_path=html_path,
            )
            session.add(db_record)
            saved_records.append(normalized)
    elif extracted_records:
        # Detail page with adapter records
        for raw_record in extracted_records[:1]:  # detail = 1 record
            normalized = {k: normalize_value(k, v) for k, v in raw_record.items() if not k.startswith("_")}
            raw_data = {k: v for k, v in raw_record.items() if not k.startswith("_")}
            db_record = CrawlRecord(
                run_id=run.id,
                source_url=url,
                data=normalized,
                raw_data=raw_data,
                discovered_data=manifest.as_dict(),
                source_trace={"type": "detail", "adapter": adapter_result.adapter_name if adapter_result else None},
                raw_html_path=html_path,
            )
            session.add(db_record)
            saved_records.append(normalized)
    else:
        # Build record from candidates (detail page, no adapter)
        if candidates:
            normalized = {
                field: normalize_value(field, rows[0]["value"])
                for field, rows in candidates.items()
                if rows
            }
            raw_data = {
                field: rows[0]["value"]
                for field, rows in candidates.items()
                if rows
            }
            discovered_data = {
                key: value
                for key, value in {
                    **{field: rows for field, rows in candidates.items()},
                    "json_ld": manifest.json_ld or None,
                    "next_data": manifest.next_data,
                    "microdata": manifest.microdata or None,
                    "tables": manifest.tables or None,
                }.items()
                if value not in (None, "", [], {})
            }
            db_record = CrawlRecord(
                run_id=run.id,
                source_url=url,
                data=normalized,
                raw_data=raw_data,
                discovered_data=discovered_data,
                source_trace=source_trace,
                raw_html_path=html_path,
            )
            session.add(db_record)
            saved_records.append(normalized)

    # ── STAGE 5: PUBLISH ──
    await _log(session, run.id, "info", f"[PUBLISH] Saved {len(saved_records)} records")
    # Auto-save selectors for reuse
    if saved_records:
        await _upsert_selectors(session, url, saved_records[0])
    await session.flush()

    return saved_records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _log(session: AsyncSession, run_id: int, level: str, message: str) -> None:
    session.add(CrawlLog(run_id=run_id, level=level, message=message))
    await session.flush()


async def _upsert_selectors(session: AsyncSession, url: str, data: dict) -> None:
    domain = _domain(url)
    for field in data.keys():
        if field.startswith("_") or field not in {"title", "price", "description"}:
            continue
        result = await session.execute(
            select(Selector).where(Selector.domain == domain, Selector.field_name == field)
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            session.add(
                Selector(
                    domain=domain,
                    field_name=field,
                    selector=f"[data-field='{field}']",
                    selector_type="css",
                    source="deterministic",
                )
            )


def _domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or parsed.path.lower()
