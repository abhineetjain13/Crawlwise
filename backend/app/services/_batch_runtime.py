from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.models.crawl import CrawlRun
from app.services.crawl_state import (
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    TERMINAL_STATUSES,
    CrawlStatus,
    get_control_request,
    set_control_request,
    update_run_status,
)
from app.services.crawl_utils import normalize_target_url, parse_csv_urls
from app.services.domain_utils import normalize_domain
from app.services.pipeline.core import _mark_run_failed, _process_single_url
from app.services.pipeline.runtime_helpers import STAGE_FETCH, log_event, set_stage
from app.services.pipeline.types import URLProcessingConfig, URLProcessingResult
from app.services.publish import VERDICT_ERROR, _aggregate_verdict
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _ensure_url_processing_result(
    url_result: URLProcessingResult | tuple[object, object, object],
) -> URLProcessingResult:
    if isinstance(url_result, URLProcessingResult):
        return url_result
    if isinstance(url_result, tuple) and len(url_result) == 3:
        records, verdict, metrics = url_result
        return URLProcessingResult(
            records=list(records or []),
            verdict=str(verdict or ""),
            url_metrics=dict(metrics or {}),
        )
    raise TypeError(f"Unexpected URL result type: {type(url_result)!r}")


def _resolve_run_urls(run: CrawlRun, settings_view) -> list[str]:
    urls = settings_view.urls()
    if run.run_type == "batch" and urls:
        url_list = urls
    elif run.run_type == "csv" and settings_view.get("csv_content"):
        url_list = parse_csv_urls(settings_view.get("csv_content"))
    elif run.url:
        url_list = [run.url]
    else:
        raise ValueError("No URL provided")
    return [
        value for value in (normalize_target_url(item) for item in url_list) if value
    ]


def _current_duration_ms(run: CrawlRun) -> int:
    if not isinstance(run.created_at, datetime):
        return 0
    return max(0, int((datetime.now(UTC) - run.created_at).total_seconds() * 1000))


async def process_run(session: AsyncSession, run_id: int) -> None:
    try:
        run = await session.get(CrawlRun, run_id)
        if run is None or run.status_value in TERMINAL_STATUSES:
            return
        if run.status_value == CrawlStatus.PAUSED:
            return
        if run.status_value == CrawlStatus.PENDING:
            update_run_status(run, CrawlStatus.RUNNING)

        settings_view = run.settings_view
        url_list = _resolve_run_urls(run, settings_view)
        total_urls = len(url_list)
        if total_urls == 0:
            raise ValueError("No URL provided")

        proxy_list = settings_view.proxy_list()
        traversal_mode = settings_view.traversal_mode()
        max_pages = settings_view.max_pages()
        max_scrolls = settings_view.max_scrolls()
        max_records = settings_view.max_records()
        sleep_ms = settings_view.sleep_ms()

        run.update_summary(
            url_count=total_urls,
            record_count=int(run.get_summary("record_count", 0) or 0),
            progress=int(run.get_summary("progress", 0) or 0),
            current_stage=STAGE_FETCH,
            domain=normalize_domain(url_list[0]) if url_list else "",
            resolved_url_list=url_list,
        )
        await session.commit()

        verdicts: list[str] = []
        methods: dict[str, int] = {}
        record_count = int(run.get_summary("record_count", 0) or 0)

        for idx, url in enumerate(url_list, start=1):
            await session.refresh(run)
            control_request = get_control_request(run)
            if control_request == CONTROL_REQUEST_PAUSE:
                update_run_status(run, CrawlStatus.PAUSED)
                set_control_request(run, None)
                await log_event(session, run.id, "warning", "Run paused at checkpoint")
                await session.commit()
                return
            if control_request == CONTROL_REQUEST_KILL:
                update_run_status(run, CrawlStatus.KILLED)
                set_control_request(run, None)
                await log_event(session, run.id, "warning", "Run killed at checkpoint")
                await session.commit()
                return

            await log_event(session, run.id, "info", f"Processing URL {idx}/{total_urls}: {url}")
            await set_stage(
                session,
                run,
                STAGE_FETCH,
                current_url=url,
                current_url_index=idx,
                total_urls=total_urls,
            )
            remaining_records = max(max_records - record_count, 1)
            url_config = URLProcessingConfig(
                proxy_list=proxy_list,
                traversal_mode=traversal_mode,
                max_pages=max_pages,
                max_scrolls=max_scrolls,
                max_records=remaining_records,
                sleep_ms=sleep_ms,
                update_run_state=True,
                persist_logs=True,
            )
            try:
                url_result = _ensure_url_processing_result(
                    await _process_single_url(
                        session=session,
                        run=run,
                        url=url,
                        config=url_config,
                    )
                )
            except (RuntimeError, ValueError, TypeError, OSError) as exc:
                logger.warning("URL processing failed for run=%s url=%s", run.id, url, exc_info=True)
                url_result = URLProcessingResult(
                    records=[],
                    verdict=VERDICT_ERROR,
                    url_metrics={"error": f"{type(exc).__name__}: {exc}"},
                )

            verdicts.append(str(url_result.verdict or VERDICT_ERROR))
            record_count += len(url_result.records)
            method = str(url_result.url_metrics.get("method") or "").strip()
            if method:
                methods[method] = int(methods.get(method, 0) or 0) + 1
            run.update_summary(
                progress=int((idx / total_urls) * 100),
                record_count=record_count,
                completed_urls=idx,
                remaining_urls=max(total_urls - idx, 0),
                url_verdicts=verdicts,
                acquisition_summary={"methods": methods},
                duration_ms=_current_duration_ms(run),
            )
            await session.commit()

            if record_count >= max_records:
                await log_event(
                    session,
                    run.id,
                    "info",
                    f"Stopped after reaching max_records={max_records}",
                )
                await session.commit()
                break
            if sleep_ms > 0 and idx < total_urls:
                await asyncio.sleep(sleep_ms / 1000)

        await session.refresh(run)
        if run.status_value in TERMINAL_STATUSES:
            return
        aggregate_verdict = _aggregate_verdict(verdicts)
        update_run_status(run, CrawlStatus.COMPLETED)
        run.update_summary(
            progress=100,
            completed_urls=len(verdicts),
            remaining_urls=max(total_urls - len(verdicts), 0),
            extraction_verdict=aggregate_verdict,
            duration_ms=_current_duration_ms(run),
        )
        await log_event(
            session,
            run.id,
            "info",
            f"Pipeline finished. {record_count} records. verdict={aggregate_verdict}",
        )
        await session.commit()
    except (RuntimeError, ValueError, TypeError, OSError) as exc:
        await _mark_run_failed(session, run_id, f"{type(exc).__name__}: {exc}")
