# Crawl run, record, log, and promotion models.
from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Mapping

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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
from app.services.run_summary import merge_run_summary_patch

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


class CrawlRecord(Base):
    __tablename__ = "crawl_records"

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
