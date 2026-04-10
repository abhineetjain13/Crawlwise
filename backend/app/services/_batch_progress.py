from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.models.crawl import CrawlRun
from sqlalchemy.ext.asyncio import AsyncSession

RetryRunUpdate = Callable[
    [AsyncSession, int, Callable[[AsyncSession, CrawlRun], Awaitable[None]]],
    Awaitable[None],
]


@dataclass(slots=True)
class BatchRunProgressState:
    total_urls: int
    url_domain: str = ""
    url_verdicts: list[str] = field(default_factory=list)
    verdict_counts: dict[str, int] = field(default_factory=dict)
    acquisition_summary: dict[str, object] = field(default_factory=dict)
    persisted_record_count: int = 0
    completed_count: int = 0

    @classmethod
    def from_summary(
        cls,
        current_summary: object,
        *,
        total_urls: int,
        url_domain: str,
        persisted_record_count: int,
    ) -> "BatchRunProgressState":
        summary = dict(current_summary) if isinstance(current_summary, dict) else {}
        completed_count = min(_as_int(summary.get("completed_urls", 0)), total_urls)
        return cls(
            total_urls=total_urls,
            url_domain=str(url_domain or ""),
            url_verdicts=list(summary.get("url_verdicts") or [])[:completed_count],
            verdict_counts=dict(summary.get("verdict_counts") or {}),
            acquisition_summary=dict(summary.get("acquisition_summary") or {}),
            persisted_record_count=max(0, _as_int(persisted_record_count)),
            completed_count=completed_count,
        )

    def record_url_result(
        self,
        *,
        idx: int,
        records_count: int,
        verdict: str,
        url_metrics: dict[str, object],
    ) -> None:
        self.persisted_record_count += max(0, _as_int(records_count))
        self.completed_count += 1
        if idx >= len(self.url_verdicts):
            self.url_verdicts.extend([""] * (idx + 1 - len(self.url_verdicts)))
        self.url_verdicts[idx] = verdict
        self.verdict_counts[verdict] = int(self.verdict_counts.get(verdict, 0) or 0) + 1
        self.acquisition_summary = _merge_run_acquisition_metrics(
            self.acquisition_summary,
            url_metrics,
        )

    def build_progress_patch(
        self,
        *,
        current_url: str,
        current_url_index: int,
    ) -> dict[str, object]:
        return {
            "url_count": self.total_urls,
            "record_count": self.persisted_record_count,
            "domain": self.url_domain,
            "progress": self._progress_percent(),
            "processed_urls": self.completed_count,
            "completed_urls": self.completed_count,
            "remaining_urls": max(self.total_urls - self.completed_count, 0),
            "url_verdicts": self.url_verdicts,
            "verdict_counts": self.verdict_counts,
            "acquisition_summary": self.acquisition_summary,
            "current_url": current_url,
            "current_url_index": current_url_index,
        }

    def build_final_patch(self, aggregate_verdict: str) -> dict[str, object]:
        return {
            "url_count": self.total_urls,
            "record_count": self.persisted_record_count,
            "domain": self.url_domain,
            "progress": self._progress_percent(final=True),
            "extraction_verdict": aggregate_verdict,
            "url_verdicts": self.url_verdicts,
            "processed_urls": self.completed_count,
            "completed_urls": self.completed_count,
            "remaining_urls": max(self.total_urls - self.completed_count, 0),
            "verdict_counts": self.verdict_counts,
        }

    async def persist_patch(
        self,
        *,
        session: AsyncSession,
        run_id: int,
        retry_run_update: RetryRunUpdate,
        patch: dict[str, object],
    ) -> None:
        async def _mutation(retry_session: AsyncSession, retry_run: CrawlRun) -> None:
            retry_run.merge_summary_patch(patch)

        await retry_run_update(session, run_id, _mutation)

    async def persist_url_result(
        self,
        *,
        session: AsyncSession,
        run_id: int,
        retry_run_update: RetryRunUpdate,
        idx: int,
        url: str,
        records_count: int,
        verdict: str,
        url_metrics: dict[str, object],
    ) -> None:
        self.record_url_result(
            idx=idx,
            records_count=records_count,
            verdict=verdict,
            url_metrics=url_metrics,
        )
        await self.persist_patch(
            session=session,
            run_id=run_id,
            retry_run_update=retry_run_update,
            patch=self.build_progress_patch(
                current_url=url,
                current_url_index=idx + 1,
            ),
        )

    async def persist_final_summary(
        self,
        *,
        session: AsyncSession,
        run_id: int,
        retry_run_update: RetryRunUpdate,
        aggregate_verdict: str,
    ) -> None:
        await self.persist_patch(
            session=session,
            run_id=run_id,
            retry_run_update=retry_run_update,
            patch=self.build_final_patch(aggregate_verdict),
        )

    def _progress_percent(self, *, final: bool = False) -> int:
        if self.total_urls <= 0:
            return 100 if final else 0
        return int((self.completed_count / self.total_urls) * 100)


def _merge_run_summary_patch(current: object, patch: dict[str, object]) -> dict[str, object]:
    summary = dict(current) if isinstance(current, dict) else {}
    merged = {**summary, **patch}

    # Preserve monotonic counters/progress when late/stale writes race in.
    for key in ("url_count", "record_count", "progress", "processed_urls", "completed_urls"):
        if key in summary or key in patch:
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


def _merge_url_verdicts(current: object, patch: object) -> list[str]:
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


def _as_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _merge_run_acquisition_metrics(
    existing: object,
    url_metrics: dict[str, object],
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
            _as_float(current.get("host_wait_seconds_total", 0.0))
            + _as_float(url_metrics.get("host_wait_seconds", 0.0)),
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
        "browser_total_ms_total": int(current.get("browser_total_ms_total", 0) or 0)
        + int(url_metrics.get("browser_total_ms", 0) or 0),
        "request_wait_ms_total": int(current.get("request_wait_ms_total", 0) or 0)
        + int(url_metrics.get("request_wait_ms", 0) or 0),
        "host_fetch_ms_total": int(current.get("host_fetch_ms_total", 0) or 0)
        + int(url_metrics.get("host_fetch_ms", 0) or 0),
        "host_browser_first_ms_total": int(
            current.get("host_browser_first_ms_total", 0) or 0
        )
        + int(url_metrics.get("host_browser_first_ms", 0) or 0),
        "host_total_ms_total": int(current.get("host_total_ms_total", 0) or 0)
        + int(url_metrics.get("host_total_ms", 0) or 0),
        "pages_collected_total": int(current.get("pages_collected_total", 0) or 0)
        + int(url_metrics.get("pages_collected", 0) or 0),
        "scroll_iterations_total": int(current.get("scroll_iterations_total", 0) or 0)
        + int(url_metrics.get("scroll_iterations", 0) or 0),
        "pages_scrolled_total": int(current.get("pages_scrolled_total", 0) or 0)
        + int(url_metrics.get("pages_scrolled", 0) or 0),
        "traversal_attempted": int(current.get("traversal_attempted", 0) or 0)
        + int(bool(url_metrics.get("traversal_attempted"))),
        "traversal_succeeded": int(current.get("traversal_succeeded", 0) or 0)
        + int(bool(url_metrics.get("traversal_succeeded"))),
        "traversal_fell_back": int(current.get("traversal_fell_back", 0) or 0)
        + int(bool(url_metrics.get("traversal_fell_back"))),
    }
    traversal_mode = str(url_metrics.get("traversal_mode_used") or "").strip()
    if traversal_mode:
        summary["traversal_modes_used"] = {
            **dict(current.get("traversal_modes_used") or {}),
            traversal_mode: int(
                dict(current.get("traversal_modes_used") or {}).get(traversal_mode, 0) or 0
            )
            + 1,
        }
    elif current.get("traversal_modes_used"):
        summary["traversal_modes_used"] = dict(current.get("traversal_modes_used") or {})

    return summary
