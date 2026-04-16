# Crawl run, record, log, and promotion models.
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_domain import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    CrawlStatus,
    normalize_status,
    transition_status,
)
from app.models.crawl_settings import CrawlRunSettings
from app.services.run_summary import as_int, merge_run_summary_patch

CRAWL_RUN_FK = "crawl_runs.id"


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    run_type: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    surface: Mapped[str] = mapped_column(String(40))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    requested_fields: Mapped[list] = mapped_column(JSONB, default=list)
    result_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    queue_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    last_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def status_value(self) -> CrawlStatus:
        return normalize_status(self.status)

    @property
    def settings_view(self) -> CrawlRunSettings:
        return CrawlRunSettings.from_value(self.settings)

    def is_active(self) -> bool:
        return self.status_value in ACTIVE_STATUSES

    def is_terminal(self) -> bool:
        return self.status_value in TERMINAL_STATUSES

    def can_transition_to(self, target: str | CrawlStatus) -> bool:
        try:
            transition_status(self.status, target)
        except ValueError:
            return False
        return True

    def set_status(self, target: str | CrawlStatus) -> CrawlStatus:
        next_status = transition_status(self.status, target)
        self.status = next_status.value
        return next_status

    def get_setting(self, key: str, default: object = None) -> object:
        settings = self.settings if isinstance(self.settings, Mapping) else {}
        return settings.get(key, default)

    def update_settings(self, **updates: object) -> dict[str, object]:
        merged = dict(self.settings if isinstance(self.settings, dict) else {})
        merged.update(updates)
        self.settings = merged
        return merged

    def summary_dict(self) -> dict[str, object]:
        return dict(
            self.result_summary if isinstance(self.result_summary, Mapping) else {}
        )

    def get_summary(self, key: str, default: object = None) -> object:
        return self.summary_dict().get(key, default)

    def update_summary(self, **updates: object) -> dict[str, object]:
        merged = self.summary_dict()
        merged.update(updates)
        self.result_summary = merged
        return merged

    def remove_summary_keys(self, *keys: str) -> dict[str, object]:
        merged = self.summary_dict()
        for key in keys:
            merged.pop(key, None)
        self.result_summary = merged
        return merged

    def merge_summary_patch(self, patch: Mapping[str, object]) -> dict[str, object]:
        merged = merge_run_summary_patch(self.summary_dict(), dict(patch))
        self.result_summary = merged
        return merged

    def apply_batch_progress_patch(self, patch: Mapping[str, object]) -> dict[str, object]:
        return self.merge_summary_patch(patch)

    def build_batch_progress_state(
        self,
        *,
        total_urls: int,
        url_domain: str,
        persisted_record_count: int,
    ) -> "BatchRunProgressState":
        return BatchRunProgressState.from_run(
            self,
            total_urls=total_urls,
            url_domain=url_domain,
            persisted_record_count=persisted_record_count,
        )


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
    def from_run(
        cls,
        run: CrawlRun,
        *,
        total_urls: int,
        url_domain: str,
        persisted_record_count: int,
    ) -> "BatchRunProgressState":
        return cls.from_summary(
            run.summary_dict(),
            total_urls=total_urls,
            url_domain=url_domain,
            persisted_record_count=persisted_record_count,
        )

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
        raw_verdicts = [
            str(item or "").strip() for item in list(summary.get("url_verdicts") or [])
        ][:total_urls]
        completed_count = min(as_int(summary.get("completed_urls", 0)), total_urls)
        if raw_verdicts:
            completed_count = 0
            for verdict in raw_verdicts:
                if not verdict:
                    break
                completed_count += 1
        return cls(
            total_urls=total_urls,
            url_domain=str(url_domain or ""),
            url_verdicts=raw_verdicts,
            verdict_counts=dict(summary.get("verdict_counts") or {}),
            acquisition_summary=dict(summary.get("acquisition_summary") or {}),
            persisted_record_count=max(0, as_int(persisted_record_count)),
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
        self.persisted_record_count += max(0, as_int(records_count))
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
        error_message: str | None = None,
    ) -> dict[str, object]:
        patch = {
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
        if error_message:
            patch["error"] = error_message
        return patch

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

    def _progress_percent(self, *, final: bool = False) -> int:
        if self.total_urls <= 0:
            return 100 if final else 0
        return int((self.completed_count / self.total_urls) * 100)


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

    summary = {
        "methods": methods,
        "platform_families": platform_families,
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
        traversal_modes_used = dict(current.get("traversal_modes_used") or {})
        summary["traversal_modes_used"] = {
            **traversal_modes_used,
            traversal_mode: int(traversal_modes_used.get(traversal_mode, 0) or 0) + 1,
        }
    elif current.get("traversal_modes_used"):
        summary["traversal_modes_used"] = dict(current.get("traversal_modes_used") or {})

    return summary


class CrawlRecord(Base):
    __tablename__ = "crawl_records"
    __table_args__ = (
        Index(
            "uq_crawl_records_run_identity",
            "run_id",
            "url_identity_key",
            unique=True,
            postgresql_where=text("url_identity_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete="CASCADE"), index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    url_identity_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    discovered_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_trace: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_html_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CrawlLog(Base):
    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete="CASCADE"), index=True
    )
    level: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ReviewPromotion(Base):
    __tablename__ = "review_promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete="CASCADE"), index=True
    )
    domain: Mapped[str] = mapped_column(String(255), index=True)
    surface: Mapped[str] = mapped_column(String(40))
    approved_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    field_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
