# Crawl run, record, log, and promotion models.
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DDL, event
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

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
            SELECT NULLIF(crawl_runs.settings->>'max_records', '')::integer
            INTO configured_max
            FROM crawl_runs
            WHERE crawl_runs.id = NEW.run_id;

            IF configured_max IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT COUNT(*)
            INTO current_count
            FROM crawl_records
            WHERE crawl_records.run_id = NEW.run_id;

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

            SELECT COUNT(*)
            INTO current_count
            FROM crawl_records
            WHERE crawl_records.run_id = NEW.id;

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
