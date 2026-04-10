# Crawl run, record, log, and promotion models.
from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Mapping

from sqlalchemy import DDL, event
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
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    last_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
        return dict(self.result_summary if isinstance(self.result_summary, Mapping) else {})

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
        merged = _merge_summary_patch(self.summary_dict(), dict(patch))
        self.result_summary = merged
        return merged


def _merge_summary_patch(current: object, patch: dict[str, object]) -> dict[str, object]:
    summary = dict(current) if isinstance(current, dict) else {}
    merged = {**summary, **patch}

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
        merged[str(key)] = max(_as_int(current_map.get(key)), _as_int(patch_map.get(key)))
    return merged


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class CrawlRecord(Base):
    __tablename__ = "crawl_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(CRAWL_RUN_FK, ondelete="CASCADE"), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    discovered_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_trace: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_html_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class CrawlLog(Base):
    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(CRAWL_RUN_FK, ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ReviewPromotion(Base):
    __tablename__ = "review_promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(CRAWL_RUN_FK, ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    surface: Mapped[str] = mapped_column(String(40))
    approved_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    field_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


event.listen(
    CrawlRecord.__table__,
    "after_create",
    DDL(
        """
        CREATE OR REPLACE FUNCTION enforce_crawl_run_max_records()
        RETURNS trigger AS $$
        DECLARE
            configured_max integer;
            current_count integer;
        BEGIN
            EXECUTE format(
                'SELECT NULLIF(settings->>''max_records'', '''')::integer FROM %%I.crawl_runs WHERE id = $1',
                TG_TABLE_SCHEMA
            )
            INTO configured_max
            USING NEW.run_id;

            IF configured_max IS NULL THEN
                RETURN NEW;
            END IF;

            EXECUTE format(
                'SELECT COUNT(*) FROM %%I.crawl_records WHERE run_id = $1',
                TG_TABLE_SCHEMA
            )
            INTO current_count
            USING NEW.run_id;

            IF current_count > configured_max THEN
                RAISE EXCEPTION 'max_records exceeded for run %%', NEW.run_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    CrawlRecord.__table__,
    "after_create",
    DDL(
        """
        CREATE CONSTRAINT TRIGGER trigger_enforce_crawl_run_max_records
        AFTER INSERT OR UPDATE OF run_id ON crawl_records
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW
        EXECUTE FUNCTION enforce_crawl_run_max_records();
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    CrawlRun.__table__,
    "after_create",
    DDL(
        """
        CREATE OR REPLACE FUNCTION enforce_crawl_run_max_records_on_settings()
        RETURNS trigger AS $$
        DECLARE
            configured_max integer;
            current_count integer;
        BEGIN
            configured_max := NULLIF(NEW.settings->>'max_records', '')::integer;
            IF configured_max IS NULL THEN
                RETURN NEW;
            END IF;

            EXECUTE format(
                'SELECT COUNT(*) FROM %%I.crawl_records WHERE run_id = $1',
                TG_TABLE_SCHEMA
            )
            INTO current_count
            USING NEW.id;

            IF current_count > configured_max THEN
                RAISE EXCEPTION 'max_records below existing record count for run %%', NEW.id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    CrawlRun.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER trigger_enforce_crawl_run_max_records_on_settings
        BEFORE INSERT OR UPDATE OF settings ON crawl_runs
        FOR EACH ROW
        EXECUTE FUNCTION enforce_crawl_run_max_records_on_settings();
        """
    ).execute_if(dialect="postgresql"),
)
