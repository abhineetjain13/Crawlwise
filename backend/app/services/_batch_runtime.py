from __future__ import annotations

import asyncio
from app.core.telemetry import (
    generate_correlation_id,
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.models.crawl import CrawlRecord, CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult, ProxyPoolExhausted
from app.services.crawl_metrics import (
    build_acquisition_profile,
    build_url_metrics,
    finalize_url_metrics,
)
from app.services.crawl_state import (
    TERMINAL_STATUSES,
    CrawlStatus,
    normalize_status,
    update_run_status,
)
from app.services.crawl_utils import normalize_target_url, parse_csv_urls, resolve_traversal_mode
from app.services.domain_utils import normalize_domain
from app.services.exceptions import RunControlError
from app.services.pipeline import (
    STAGE_FETCH,
    VERDICT_BLOCKED,
    VERDICT_EMPTY,
    VERDICT_LISTING_FAILED,
    VERDICT_PARTIAL,
    VERDICT_SCHEMA_MISS,
    VERDICT_SUCCESS,
    _aggregate_verdict,
    _log,
    _mark_run_failed,
    _process_single_url,
    _set_stage,
)
from app.services.pipeline_config import (
    DEFAULT_MAX_SCROLLS,
    MAX_URL_PROCESS_TIMEOUT_SECONDS,
    URL_PROCESS_TIMEOUT_SECONDS,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

class RunControlSignal(RunControlError):  # noqa: N818 - kept for compatibility with exception hierarchy tests.
    pass


async def _log_with_retry(
    session: AsyncSession,
    run_id: int,
    level: str,
    message: str,
) -> None:
    tagged_message = _with_correlation_tag(message)
    await _log(session, run_id, level, tagged_message)
    await session.commit()


def _with_correlation_tag(message: str) -> str:
    correlation_id = str(get_correlation_id() or "").strip()
    text = str(message or "")
    if not correlation_id:
        return text
    if text.startswith("[corr="):
        return text
    return f"[corr={correlation_id}] {text}"


async def _retry_run_update(
    session: AsyncSession,
    run_id: int,
    mutate,
) -> None:
    """Safely update a run using DB-level row locks (FOR UPDATE)."""
    result = await session.execute(
        select(CrawlRun)
        .where(CrawlRun.id == run_id)
        .with_for_update()
    )
    run = result.scalar_one_or_none()
    if run is None:
        return
    await mutate(session, run)
    await session.flush()
    await session.commit()


async def _cleanup_run_lock(run_id: int) -> None:
    # Intentionally left empty as the in-memory lock dict has been removed.
    # Kept to preserve the function signature used in the finally block.
    pass


async def _noop_checkpoint() -> None:
    return None


def _coerce_url_timeout_seconds(settings: dict) -> float:
    raw_value = settings.get("url_timeout_seconds", URL_PROCESS_TIMEOUT_SECONDS)
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return URL_PROCESS_TIMEOUT_SECONDS
    if value <= 0:
        return URL_PROCESS_TIMEOUT_SECONDS
    return min(value, MAX_URL_PROCESS_TIMEOUT_SECONDS)


async def process_run(session: AsyncSession, run_id: int) -> None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    current_status = normalize_status(run.status)
    if current_status in TERMINAL_STATUSES or current_status == CrawlStatus.PAUSED:
        return

    if current_status == CrawlStatus.PENDING:
        async def _start_mutation(retry_session: AsyncSession, retry_run: CrawlRun) -> None:
            update_run_status(retry_run, CrawlStatus.RUNNING)

        await _retry_run_update(session, run.id, _start_mutation)
        await _log_with_retry(session, run.id, "info", "Pipeline started")
        await session.refresh(run)
    else:
        async def _resume_mutation(retry_session: AsyncSession, retry_run: CrawlRun) -> None:
            return None

        await _retry_run_update(session, run.id, _resume_mutation)
        await _log_with_retry(session, run.id, "info", "Pipeline resumed")
        await session.refresh(run)

    persisted_summary = dict(run.result_summary or {})
    correlation_id = str(
        persisted_summary.get("correlation_id") or generate_correlation_id()
    ).strip()
    correlation_token = set_correlation_id(correlation_id)
    try:
        if str(persisted_summary.get("correlation_id") or "").strip() != correlation_id:
            async def _correlation_mutation(
                retry_session: AsyncSession, retry_run: CrawlRun
            ) -> None:
                retry_run.result_summary = _merge_run_summary_patch(
                    retry_run.result_summary,
                    {"correlation_id": correlation_id},
                )

            await _retry_run_update(session, run.id, _correlation_mutation)
            await session.refresh(run)

        settings = run.settings or {}
        urls = settings.get("urls", [])
        run_type = run.run_type

        if run_type == "batch" and urls:
            url_list = urls
        elif run_type == "csv" and settings.get("csv_content"):
            url_list = parse_csv_urls(settings["csv_content"])
        elif run.url:
            url_list = [run.url]
        else:
            raise ValueError("No URL provided")
        url_list = [normalize_target_url(value) for value in url_list]
        url_list = [value for value in url_list if value]

        proxy_list = settings.get("proxy_list", [])
        traversal_mode = settings.get("traversal_mode")
        max_pages = settings.get("max_pages", 5)
        max_scrolls = settings.get("max_scrolls", DEFAULT_MAX_SCROLLS)
        max_records = settings.get("max_records", 100)
        sleep_ms = settings.get("sleep_ms", 0)
        url_batch_concurrency = max(
            1,
            int(
                settings.get("url_batch_concurrency", URL_BATCH_CONCURRENCY)
                or URL_BATCH_CONCURRENCY
            ),
        )
        url_timeout_seconds = _coerce_url_timeout_seconds(settings)
        await _log_with_retry(
            session,
            run.id,
            "info",
            f"[traversal] mode={traversal_mode}, advanced={bool(settings.get('advanced_enabled'))}, url={url_list[0] if url_list else ''}",
        )

        total_urls = len(url_list)
        persisted_summary = dict(run.result_summary or {})
        start_index = min(
            int(persisted_summary.get("completed_urls", 0) or 0), total_urls
        )
        persisted_record_count = await _count_run_records(session, run.id)
        url_verdicts: list[str] = list(persisted_summary.get("url_verdicts") or [])[
            :start_index
        ]
        verdict_counts: dict[str, int] = dict(
            persisted_summary.get("verdict_counts") or {}
        )
        pending_items = list(enumerate(url_list[start_index:], start=start_index))
        completed_count = start_index
        acquisition_summary = (
            run.result_summary.get("acquisition_summary")
            if isinstance(run.result_summary, dict)
            else {}
        )

        async def _apply_url_result(
            idx: int,
            url: str,
            records_count: int,
            verdict: str,
            url_metrics: dict,
        ) -> None:
            nonlocal acquisition_summary, completed_count, persisted_record_count
            persisted_record_count += records_count
            completed_count += 1
            if idx < len(url_verdicts):
                url_verdicts[idx] = verdict
            else:
                url_verdicts.append(verdict)
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            acquisition_summary = _merge_run_acquisition_metrics(
                acquisition_summary, url_metrics
            )
            progress = int((completed_count / total_urls) * 100)
            async def _progress_mutation(
                retry_session: AsyncSession, retry_run: CrawlRun
            ) -> None:
                retry_run.result_summary = _merge_run_summary_patch(
                    retry_run.result_summary,
                    {
                        "url_count": total_urls,
                        "record_count": persisted_record_count,
                        "domain": _domain(url_list[0]) if url_list else "",
                        "progress": progress,
                        "processed_urls": completed_count,
                        "completed_urls": completed_count,
                        "remaining_urls": max(total_urls - completed_count, 0),
                        "url_verdicts": url_verdicts,
                        "verdict_counts": verdict_counts,
                        "acquisition_summary": acquisition_summary,
                        "current_url": url,
                        "current_url_index": idx + 1,
                    },
                )

            await _retry_run_update(session, run.id, _progress_mutation)
        for idx, url in pending_items:
            remaining_records = max(max_records - persisted_record_count, 0)
            if remaining_records <= 0:
                await _log(
                    session,
                    run.id,
                    "info",
                    f"Reached max_records ceiling ({max_records})",
                )
                break

            await _log(
                session,
                run.id,
                "info",
                f"Processing URL {idx + 1}/{total_urls}: {url}",
            )
            await _set_stage(
                session,
                run,
                STAGE_FETCH,
                current_url=url,
                current_url_index=idx + 1,
                total_urls=total_urls,
            )

            records, verdict, url_metrics = await asyncio.wait_for(
                _process_single_url(
                    session=session,
                    run=run,
                    url=url,
                    proxy_list=proxy_list,
                    traversal_mode=traversal_mode,
                    max_pages=max_pages,
                    max_scrolls=max_scrolls,
                    max_records=remaining_records,
                    sleep_ms=sleep_ms,
                    checkpoint=_noop_checkpoint,
                ),
                timeout=url_timeout_seconds,
            )
            await _apply_url_result(idx, url, len(records), verdict, url_metrics)
            if persisted_record_count >= max_records:
                await _log(
                    session,
                    run.id,
                    "info",
                    f"Stopped after reaching max_records={max_records}",
                )
                break

            if sleep_ms > 0 and idx < total_urls - 1:
                await _sleep_with_checkpoint(sleep_ms, _noop_checkpoint)

        aggregate_verdict = _aggregate_verdict(url_verdicts)
        async def _finalize_mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            current_status = normalize_status(retry_run.status)
            if current_status == CrawlStatus.RUNNING:
                if aggregate_verdict == VERDICT_SUCCESS:
                    update_run_status(retry_run, CrawlStatus.COMPLETED)
                elif aggregate_verdict in {
                    VERDICT_PARTIAL,
                    VERDICT_EMPTY,
                    VERDICT_BLOCKED,
                    VERDICT_SCHEMA_MISS,
                    VERDICT_LISTING_FAILED,
                }:
                    update_run_status(retry_run, CrawlStatus.FAILED)
            retry_run.result_summary = _merge_run_summary_patch(
                retry_run.result_summary,
                {
                    "url_count": total_urls,
                    "record_count": persisted_record_count,
                    "domain": _domain(url_list[0]) if url_list else "",
                    "progress": int((completed_count / total_urls) * 100)
                    if total_urls
                    else 100,
                    "extraction_verdict": aggregate_verdict,
                    "url_verdicts": url_verdicts,
                    "processed_urls": completed_count,
                    "completed_urls": completed_count,
                    "remaining_urls": max(total_urls - completed_count, 0),
                    "verdict_counts": verdict_counts,
                },
            )

        await _retry_run_update(session, run.id, _finalize_mutation)
        traversal_attempted = int(acquisition_summary.get("traversal_attempted", 0) or 0)
        traversal_succeeded = int(acquisition_summary.get("traversal_succeeded", 0) or 0)
        traversal_fell_back = int(acquisition_summary.get("traversal_fell_back", 0) or 0)
        traversal_modes_used = dict(acquisition_summary.get("traversal_modes_used") or {})
        await _log_with_retry(
            session,
            run.id,
            "info",
            "[traversal-summary] attempted="
            f"{traversal_attempted}, succeeded={traversal_succeeded}, "
            f"fell_back={traversal_fell_back}, modes={traversal_modes_used}",
        )
        await _log_with_retry(
            session,
            run.id,
            "info",
            f"Pipeline finished. {persisted_record_count} records. verdict={aggregate_verdict}",
        )

    except ProxyPoolExhausted as exc:
        await session.rollback()
        run = await session.get(CrawlRun, run_id)
        if run is None:
            return
        error_message = str(exc)
        async def _proxy_exhausted_mutation(
            retry_session: AsyncSession, retry_run: CrawlRun
        ) -> None:
            update_run_status(retry_run, CrawlStatus.PROXY_EXHAUSTED)
            retry_run.result_summary = _merge_run_summary_patch(
                retry_run.result_summary,
                {
                    "error": error_message,
                    "extraction_verdict": "proxy_exhausted",
                },
            )
            await _log(retry_session, retry_run.id, "error", error_message)

        await _retry_run_update(session, run.id, _proxy_exhausted_mutation)
    except TimeoutError:
        await _mark_run_failed(session, run_id, "URL processing timed out")
    except (
        RuntimeError,
        ValueError,
        TypeError,
        OSError,
    ) as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        await _mark_run_failed(session, run_id, error_msg)
    finally:
        reset_correlation_id(correlation_token)
        await _cleanup_run_lock(run_id)


async def _sleep_with_checkpoint(sleep_ms: int, checkpoint) -> None:
    remaining_ms = max(0, int(sleep_ms or 0))
    while remaining_ms > 0:
        await checkpoint()
        current_ms = min(remaining_ms, 250)
        await asyncio.sleep(current_ms / 1000)
        remaining_ms -= current_ms
    await checkpoint()

async def _count_run_records(session: AsyncSession, run_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(CrawlRecord)
                .where(CrawlRecord.run_id == run_id)
            )
        ).scalar()
        or 0
    )


def _collect_target_urls(payload: dict, settings: dict) -> list[str]:
    """Collect and deduplicate all target URLs from payload and settings."""
    from app.services.crawl_utils import collect_target_urls
    return collect_target_urls(payload, settings)


def _build_acquisition_profile(run_settings: dict | None) -> dict[str, object]:
    return build_acquisition_profile(run_settings)


def _resolve_traversal_mode(settings: dict | None) -> str | None:
    """Resolve and validate the traversal mode from settings."""
    return resolve_traversal_mode(settings)


def _build_url_metrics(
    acq: AcquisitionResult,
    *,
    requested_fields: list[str],
) -> dict[str, object]:
    return build_url_metrics(acq, requested_fields=requested_fields)


def _merge_run_summary_patch(current: object, patch: dict[str, object]) -> dict[str, object]:
    summary = dict(current or {}) if isinstance(current, dict) else {}
    merged = {**summary, **patch}

    for key in ("url_count", "record_count", "progress", "processed_urls", "completed_urls"):
        merged[key] = max(_as_int(summary.get(key)), _as_int(patch.get(key)))

    if "remaining_urls" in patch:
        prev_remaining = summary.get("remaining_urls")
        if prev_remaining is None:
            merged["remaining_urls"] = _as_int(patch.get("remaining_urls"))
        else:
            merged["remaining_urls"] = min(
                _as_int(prev_remaining),
                _as_int(patch.get("remaining_urls")),
            )

    if "url_verdicts" in patch or "url_verdicts" in summary:
        merged["url_verdicts"] = _merge_url_verdicts(
            summary.get("url_verdicts"),
            patch.get("url_verdicts"),
        )

    if "verdict_counts" in patch or "verdict_counts" in summary:
        merged["verdict_counts"] = _merge_verdict_counts(
            summary.get("verdict_counts"),
            patch.get("verdict_counts"),
        )

    return merged


def _merge_url_verdicts(
    current: object,
    patch: object,
) -> list[str]:
    current_list = list(current) if isinstance(current, list) else []
    patch_list = list(patch) if isinstance(patch, list) else []
    max_len = max(len(current_list), len(patch_list))
    merged: list[str] = []
    for idx in range(max_len):
        patch_value = str(patch_list[idx] or "").strip() if idx < len(patch_list) else ""
        current_value = str(current_list[idx] or "").strip() if idx < len(current_list) else ""
        merged.append(patch_value or current_value)
    return merged


def _merge_verdict_counts(current: object, patch: object) -> dict[str, int]:
    current_map = dict(current) if isinstance(current, dict) else {}
    patch_map = dict(patch) if isinstance(patch, dict) else {}
    keys = set(current_map) | set(patch_map)
    merged: dict[str, int] = {}
    for key in keys:
        merged[str(key)] = max(
            _as_int(current_map.get(key)),
            _as_int(patch_map.get(key)),
        )
    return merged


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _finalize_url_metrics(
    url_metrics: dict[str, object],
    *,
    records: list[dict],
    requested_fields: list[str],
) -> dict[str, object]:
    return finalize_url_metrics(
        url_metrics,
        records=records,
        requested_fields=requested_fields,
    )


def _merge_run_acquisition_metrics(
    existing: object, url_metrics: dict[str, object]
) -> dict[str, object]:
    current = dict(existing) if isinstance(existing, dict) else {}
    methods = dict(current.get("methods") or {})
    method = str(url_metrics.get("method") or "").strip()
    if method:
        methods[method] = int(methods.get(method, 0) or 0) + 1
    platform_families = dict(current.get("platform_families") or {})
    platform_family = str(url_metrics.get("platform_family") or "").strip()
    if platform_family:
        platform_families[platform_family] = (
            int(platform_families.get(platform_family, 0) or 0) + 1
        )
    requested_surfaces = dict(current.get("requested_surfaces") or {})
    requested_surface = str(url_metrics.get("requested_surface") or "").strip()
    if requested_surface:
        requested_surfaces[requested_surface] = int(
            requested_surfaces.get(requested_surface, 0) or 0
        ) + 1
    effective_surfaces = dict(current.get("effective_surfaces") or {})
    effective_surface = str(url_metrics.get("effective_surface") or "").strip()
    if effective_surface:
        effective_surfaces[effective_surface] = int(
            effective_surfaces.get(effective_surface, 0) or 0
        ) + 1

    summary = {
        "methods": methods,
        "platform_families": platform_families,
        "requested_surfaces": requested_surfaces,
        "effective_surfaces": effective_surfaces,
        "browser_attempted_urls": int(current.get("browser_attempted_urls", 0) or 0)
        + int(bool(url_metrics.get("browser_attempted"))),
        "browser_used_urls": int(current.get("browser_used_urls", 0) or 0)
        + int(bool(url_metrics.get("browser_used"))),
        "memory_browser_first_urls": int(
            current.get("memory_browser_first_urls", 0) or 0
        )
        + int(bool(url_metrics.get("memory_browser_first"))),
        "proxy_used_urls": int(current.get("proxy_used_urls", 0) or 0)
        + int(bool(url_metrics.get("proxy_used"))),
        "network_payloads_total": int(current.get("network_payloads_total", 0) or 0)
        + int(url_metrics.get("network_payloads", 0) or 0),
        "promoted_sources_total": int(current.get("promoted_sources_total", 0) or 0)
        + int(url_metrics.get("promoted_sources", 0) or 0),
        "frame_sources_total": int(current.get("frame_sources_total", 0) or 0)
        + int(url_metrics.get("frame_sources", 0) or 0),
        "host_wait_seconds_total": round(
            float(current.get("host_wait_seconds_total", 0.0) or 0.0)
            + float(url_metrics.get("host_wait_seconds", 0.0) or 0.0),
            3,
        ),
        "records_total": int(current.get("records_total", 0) or 0)
        + int(url_metrics.get("record_count", 0) or 0),
        "acquisition_ms_total": int(current.get("acquisition_ms_total", 0) or 0)
        + int(url_metrics.get("acquisition_ms", 0) or 0),
        "extraction_ms_total": int(current.get("extraction_ms_total", 0) or 0)
        + int(url_metrics.get("extraction_ms", 0) or 0),
        "curl_fetch_ms_total": int(current.get("curl_fetch_ms_total", 0) or 0)
        + int(url_metrics.get("curl_fetch_ms", 0) or 0),
        "browser_decision_ms_total": int(
            current.get("browser_decision_ms_total", 0) or 0
        )
        + int(url_metrics.get("browser_decision_ms", 0) or 0),
        "browser_launch_ms_total": int(current.get("browser_launch_ms_total", 0) or 0)
        + int(url_metrics.get("browser_launch_ms", 0) or 0),
        "browser_origin_warm_ms_total": int(
            current.get("browser_origin_warm_ms_total", 0) or 0
        )
        + int(url_metrics.get("browser_origin_warm_ms", 0) or 0),
        "browser_navigation_ms_total": int(
            current.get("browser_navigation_ms_total", 0) or 0
        )
        + int(url_metrics.get("browser_navigation_ms", 0) or 0),
        "browser_challenge_wait_ms_total": int(
            current.get("browser_challenge_wait_ms_total", 0) or 0
        )
        + int(url_metrics.get("browser_challenge_wait_ms", 0) or 0),
        "browser_listing_readiness_wait_ms_total": int(
            current.get("browser_listing_readiness_wait_ms_total", 0) or 0
        )
        + int(url_metrics.get("browser_listing_readiness_wait_ms", 0) or 0),
        "browser_traversal_ms_total": int(
            current.get("browser_traversal_ms_total", 0) or 0
        )
        + int(url_metrics.get("browser_traversal_ms", 0) or 0),
        "traversal_attempted": int(current.get("traversal_attempted", 0) or 0)
        + int(bool(url_metrics.get("traversal_attempted"))),
        "traversal_fell_back": int(current.get("traversal_fell_back", 0) or 0)
        + int(bool(url_metrics.get("traversal_fallback_used"))),
        "surface_remapped_urls": int(current.get("surface_remapped_urls", 0) or 0)
        + int(bool(url_metrics.get("surface_remapped"))),
    }
    traversal_succeeded_increment = int(
        bool(url_metrics.get("traversal_attempted"))
        and not bool(url_metrics.get("traversal_fallback_used"))
        and int(url_metrics.get("traversal_pages_collected", 0) or 0) > 0
    )
    summary["traversal_succeeded"] = int(current.get("traversal_succeeded", 0) or 0) + traversal_succeeded_increment
    traversal_modes_used = dict(current.get("traversal_modes_used") or {})
    mode_used = str(url_metrics.get("traversal_mode_used") or "").strip()
    if mode_used:
        traversal_modes_used[mode_used] = int(traversal_modes_used.get(mode_used, 0) or 0) + 1
    if traversal_modes_used:
        summary["traversal_modes_used"] = traversal_modes_used
    if "requested_fields_total" in url_metrics:
        summary["requested_fields_total"] = int(
            current.get("requested_fields_total", 0) or 0
        ) + int(url_metrics.get("requested_fields_total", 0) or 0)
        summary["requested_fields_found_best_total"] = int(
            current.get("requested_fields_found_best_total", 0) or 0
        ) + int(url_metrics.get("requested_fields_found_best", 0) or 0)
    return summary


_domain = normalize_domain
